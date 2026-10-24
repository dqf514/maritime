"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { StateView } from "@/components/StateView";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Msg = {
  id: string;
  subject: string | null;
  from_email: string | null;
  parse_status: string;
  parse_confidence: number | null;
  parse_result: Record<string, unknown>;
};

type Account = {
  id: string;
  email: string;
  provider: string;
  display_name: string | null;
  status: string;
};

type ReplyDraft = {
  to: string;
  subject: string;
  body: string;
  template: string;
};

/** AI 动作推荐（/ai/assist/recommend/email）—— 只建议，执行仍由人工确认 */
type Recommend = {
  message_id: string;
  email_type: string;
  recommendation: "apply" | "reply" | "review";
  confidence: number;
  reason: string;
  reply_template: string;
  already_applied: boolean;
  source: string;
};

const REPLY_TEMPLATES = ["ack_recap", "counter_offer", "nor_ack", "laytime_query", "general"] as const;
type ReplyTemplate = (typeof REPLY_TEMPLATES)[number];

/** 解析结果 → 结构化字段 chips（替代原始 JSON 预览） */
function parseFields(r: Msg): { etype: string; pairs: Array<[string, unknown]> } {
  const p = (r.parse_result || {}) as Record<string, unknown>;
  const cls = (p.classification || {}) as Record<string, unknown>;
  const etype = String(p.email_type || cls.type || "");
  const sub = ((p.fixture_recap || p.nor || p.laytime) as Record<string, unknown>) || p;
  const pairs: Array<[string, unknown]> = [];
  const pick = (src: Record<string, unknown>, keys: string[]) => {
    for (const k of keys) {
      if (src[k] !== undefined && src[k] !== null && src[k] !== "") pairs.push([k, src[k]]);
    }
  };
  if (etype === "fixture_recap" || etype === "recap") {
    pick(sub, ["vessel", "vessel_name", "cargo", "laycan", "load_port", "discharge_port", "freight_rate", "demurrage_rate"]);
  } else if (etype === "nor") {
    pick(sub, ["vessel", "port", "date_time", "draft"]);
  } else if (etype === "laytime_statement") {
    if (Array.isArray(sub.events)) pairs.push(["events", sub.events.length]);
    pick(sub, ["allowed_days"]);
  } else {
    pick(sub, ["vessel", "vessel_name"]);
  }
  const matched = (p.matched || {}) as Record<string, unknown>;
  if (matched.counterparty_name) pairs.push(["counterparty", matched.counterparty_name]);
  return { etype, pairs };
}

export default function EmailReviewPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [rows, setRows] = useState<Msg[]>([]);
  const [m365, setM365] = useState(false);
  const [loading, setLoading] = useState(true);
  /** 主列表（待复核邮件）加载失败 —— 绝不能与「没有邮件」混淆 */
  const [err, setErr] = useState<string | null>(null);
  /** 邮箱账号面板（次级列表）加载失败 —— 局部提示，不影响主列表 */
  const [accErr, setAccErr] = useState<string | null>(null);
  /** M365 连接状态（参考数据）加载失败 —— 只影响徽标 */
  const [officeErr, setOfficeErr] = useState<string | null>(null);
  const rowCtx = useContextMenu<Msg>();
  // 回复对话框状态
  const [replyFor, setReplyFor] = useState<Msg | null>(null);
  const [replyTemplate, setReplyTemplate] = useState<ReplyTemplate>("ack_recap");
  const [replyBody, setReplyBody] = useState("");
  const [replySending, setReplySending] = useState(false);
  /** 待确认的破坏性动作：落单（创建真实记录）/ 确认解析（出队）/ 发信 */
  const [pending, setPending] = useState<{ kind: "apply" | "confirm"; msg: Msg } | null>(null);
  const [pendingSend, setPendingSend] = useState(false);
  // AI 推荐
  const [recFor, setRecFor] = useState<Msg | null>(null);
  const [rec, setRec] = useState<Recommend | null>(null);
  const [recBusy, setRecBusy] = useState(false);

  /**
   * 取数：三个来源彼此独立（allSettled），主列表失败走错误态，参考数据失败只做局部提示。
   */
  const load = useCallback(async () => {
    setLoading(true);
    const [accR, reviewR, officeR] = await Promise.allSettled([
      apiGet("/api/v1/email/accounts"),
      apiGet("/api/v1/email/review"),
      apiGet("/api/v1/office/status"),
    ]);
    if (reviewR.status === "fulfilled") {
      setRows(reviewR.value as Msg[]);
      setErr(null);
    } else {
      setRows([]);
      setErr(msgOf(reviewR.reason));
    }
    if (accR.status === "fulfilled") {
      setAccounts(accR.value as Account[]);
      setAccErr(null);
    } else {
      setAccounts([]);
      setAccErr(msgOf(accR.reason));
    }
    if (officeR.status === "fulfilled") {
      setM365(Boolean((officeR.value as { connected?: boolean } | null)?.connected));
      setOfficeErr(null);
    } else {
      setM365(false);
      setOfficeErr(msgOf(officeR.reason));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function ensureSyncAccount() {
    if (accounts.length) return accounts[0];
    // Microsoft 365 connected → real mailbox (address resolved server-side from /me)
    if (m365) {
      return apiPost("/api/v1/email/accounts", {
        provider: "microsoft",
        display_name: "Microsoft 365 Inbox",
        config: {},
      });
    }
    return apiPost("/api/v1/email/accounts", {
      provider: "demo",
      email: "ops@demo.marios",
      display_name: "Ops Inbox",
      config: {},
    });
  }

  async function sync() {
    toast.success(
      m365
        ? t("page.email.syncing_m365", "正在从 Microsoft 365 同步收件箱…")
        : t("page.email.syncing", "Syncing demo mailbox…"),
    );
    const acc = await ensureSyncAccount();
    const result = await apiPost(`/api/v1/email/accounts/${acc.id}/sync`);
    await load();
    toast.success(t("page.email.synced", "Synced {n} message(s).", { n: result.synced ?? 1 }));
  }

  async function confirm(id: string) {
    await apiPost(`/api/v1/email/review/${id}/confirm`, {});
    toast.success(t("page.email.confirmed", "Parse result confirmed."));
    await load();
  }

  /** 解析结果一键落单：recap→估算草稿 / NOR→盖 nor_at / SOF→装卸时间草稿 */
  async function applyDraft(m: Msg) {
    try {
      const res = await apiPost(`/api/v1/email/review/${m.id}/apply`, {});
      const created = res.created || [];
      const hints: string[] = res.hints || [];
      if (created.length) {
        const c = created[0];
        toast.success(
          t("page.email.apply_done", "Draft created: {kind} — {title}", {
            kind: c.entity,
            title: c.title || c.voyage_no || c.id,
          }),
        );
      } else if (hints.length) {
        toast.error(hints.join(", "));
      } else {
        toast.error(t("page.email.apply_none", "This email type has no auto-draft yet."));
      }
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("page.email.apply_fail", "Create draft failed")));
    }
  }

  /** 破坏性入口：落单会真实创建业务记录 —— 先确认。 */
  const requestApply = useCallback((m: Msg) => {
    setPending({ kind: "apply", msg: m });
  }, []);

  /** 确认解析结果会把该邮件移出待办队列 —— 先确认。 */
  const requestConfirm = useCallback((m: Msg) => {
    setPending({ kind: "confirm", msg: m });
  }, []);

  const openReply = useCallback(
    async (m: Msg) => {
      setReplyFor(m);
      setReplyTemplate("ack_recap");
      setReplyBody("");
      try {
        const rendered: ReplyDraft = await apiPost(`/api/v1/email/messages/${m.id}/reply`, {
          template: "ack_recap",
          preview: true,
        });
        setReplyBody(rendered.body);
      } catch (ex) {
        toast.error(msgOf(ex, t("page.email.reply_preview_fail", "Preview failed")));
      }
    },
    [t, toast],
  );

  async function changeReplyTemplate(tpl: ReplyTemplate) {
    setReplyTemplate(tpl);
    if (!replyFor) return;
    try {
      const rendered: ReplyDraft = await apiPost(`/api/v1/email/messages/${replyFor.id}/reply`, {
        template: tpl,
        preview: true,
      });
      setReplyBody(rendered.body);
    } catch {
      /* 保留当前正文，用户可手改 */
    }
  }

  async function sendReply() {
    if (!replyFor) return;
    setReplySending(true);
    try {
      const res = await apiPost(`/api/v1/email/messages/${replyFor.id}/reply`, {
        template: replyTemplate,
        extra: { body_override: replyBody },
      });
      toast.success(t("page.email.reply_sent", "Reply sent via {channel}", { channel: res.channel }));
      setReplyFor(null);
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("page.email.reply_fail", "Reply failed")));
    } finally {
      setReplySending(false);
    }
  }

  /** AI 推荐下一步动作（apply/reply/review）—— 建议，不落库 */
  const openRecommend = useCallback(
    async (m: Msg) => {
      setRecFor(m);
      setRec(null);
      setRecBusy(true);
      try {
        const r: Recommend = await apiPost(`/api/v1/ai/assist/recommend/email/${m.id}`, {});
        setRec(r);
      } catch (ex) {
        toast.error(msgOf(ex, t("page.email.rec_fail", "AI 推荐失败")));
        setRecFor(null);
      } finally {
        setRecBusy(false);
      }
    },
    [t, toast],
  );

  /** 按 AI 推荐执行 —— 仍走既有的人工确认端点 */
  async function actOnRecommend() {
    if (!recFor || !rec) return;
    if (rec.recommendation === "apply") {
      const target = recFor;
      setRecFor(null);
      // 落单会真实建记录 —— 走二次确认
      setPending({ kind: "apply", msg: target });
      return;
    }
    if (rec.recommendation === "reply") {
      const target = recFor;
      const tpl = (rec.reply_template || "ack_recap") as ReplyTemplate;
      setRecFor(null);
      await openReply(target);
      if (tpl !== "ack_recap") await changeReplyTemplate(tpl);
    }
    // "review" → 保持人工复核，无需自动动作
  }

  async function onAccountCellSave(rowId: string, colKey: string, value: unknown, row: Account) {
    const src = row as unknown as Record<string, unknown>;
    if ((src[colKey] ?? "") === (value ?? "")) return;
    try {
      // config only replaced when explicitly sent — never include it here
      await apiPatch(`/api/v1/email/accounts/${rowId}`, { [colKey]: value === "" ? null : value });
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  const deleteAccount = useCallback(
    async (id: string) => {
      try {
        await apiDelete(`/api/v1/email/accounts/${id}`);
        toast.success(t("common.recycled", "Moved to recycle bin"));
        await load();
      } catch (ex: any) {
        toast.error(msgOf(ex));
      }
    },
    [t, toast, load],
  );

  function copyMsgId(m: Msg) {
    void navigator.clipboard.writeText(m.id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  function exportMsgs(list: Msg[]) {
    downloadCsv(
      "email_review",
      ["id", "subject", "from_email", "parse_status", "parse_confidence"],
      list.map((m) => [m.id, m.subject ?? "", m.from_email ?? "", m.parse_status, m.parse_confidence ?? ""]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const menuItems = (m: Msg): ContextMenuItem[] => [
    {
      key: "ai",
      label: t("page.email.ai_rec", "AI 建议"),
      onClick: () => void openRecommend(m),
    },
    ...(m.parse_status === "review"
      ? [
          {
            key: "apply",
            label: t("page.email.apply_btn", "Create draft"),
            onClick: () => requestApply(m),
          },
          {
            key: "confirm",
            label: t("common.confirm", "Confirm"),
            onClick: () => requestConfirm(m),
          },
        ]
      : []),
    {
      key: "reply",
      label: t("page.email.reply_btn", "Reply"),
      onClick: () => void openReply(m),
    },
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyMsgId(m) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportMsgs([m]) },
  ];

  const accountColumns = useMemo<ColumnDef<Account>[]>(
    () => [
      {
        key: "email",
        title: t("common.email", "Email"),
        minWidth: 180,
        value: (r) => r.email,
        editor: { type: "text" },
      },
      {
        key: "display_name",
        title: t("page.email.display_name", "Display name"),
        minWidth: 140,
        value: (r) => r.display_name || "",
        editor: { type: "text" },
        render: (v) => (v ? String(v) : "—"),
      },
      {
        key: "provider",
        title: t("page.email.provider", "Provider"),
        width: 120,
        value: (r) => r.provider,
        editor: { type: "text" },
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 110,
        value: (r) => r.status,
        editor: {
          type: "select",
          options: [
            { value: "active", label: t("page.email.status_active", "Active") },
            { value: "paused", label: t("page.email.status_paused", "Paused") },
          ],
        },
      },
      {
        key: "_actions",
        title: "",
        width: 70,
        align: "right",
        render: (_v, a) => <RowActions label={a.email} onDelete={() => deleteAccount(a.id)} />,
      },
    ],
    [t, deleteAccount],
  );

  const columns = useMemo<ColumnDef<Msg>[]>(
    () => [
      {
        key: "subject",
        title: t("page.email.subject", "Subject"),
        minWidth: 180,
        value: (r) => r.subject || "",
        render: (_v, r) => r.subject || t("page.email.no_subject", "(no subject)"),
      },
      {
        key: "from_email",
        title: t("page.email.from", "From"),
        width: 160,
        value: (r) => r.from_email || "",
        render: (_v, r) => r.from_email || "—",
      },
      { key: "parse_status", title: t("common.status", "Status"), width: 110, value: (r) => r.parse_status },
      {
        key: "parse_confidence",
        title: t("page.email.confidence", "Confidence"),
        width: 110,
        align: "right",
        value: (r) => r.parse_confidence ?? null,
        render: (_v, r) => (r.parse_confidence != null ? <><Num v={r.parse_confidence * 100} digits={0} />%</> : "—"),
      },
      {
        key: "parse_preview",
        title: t("page.email.parse_fields", "Parsed fields"),
        minWidth: 260,
        value: (r) => JSON.stringify(r.parse_result),
        render: (_v, r) => {
          const { etype, pairs } = parseFields(r);
          return (
            <span className="parse-fields">
              {etype ? <span className="badge badge-info">{t(`email.type.${etype}`, etype)}</span> : null}
              {pairs.length ? (
                // 两列 dl：标签走 email.parse.* 词表，未知键回落原键；值原样展示
                <dl className="parse-kv">
                  {pairs.map(([k, val]) => (
                    <div key={k}>
                      <dt>{t(`email.parse.${k}`, k)}</dt>
                      <dd>{String(val)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <code>{JSON.stringify(r.parse_result).slice(0, 120)}</code>
              )}
            </span>
          );
        },
      },
      {
        key: "actions",
        title: "",
        width: 250,
        render: (_v, r) => (
          <span className="row-actions">
            <button className="btn btn-sm" type="button" onClick={() => void openRecommend(r)}>
              ✦ {t("page.email.ai_rec", "AI 建议")}
            </button>
            <button className="btn btn-sm" type="button" onClick={() => void openReply(r)}>
              {t("page.email.reply_btn", "Reply")}
            </button>
            {r.parse_status === "review" ? (
              <>
                <button
                  className="btn btn-sm btn-primary"
                  type="button"
                  onClick={() => requestApply(r)}
                >
                  {t("page.email.apply_btn", "Create draft")}
                </button>
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={() => requestConfirm(r)}
                >
                  {t("common.confirm", "Confirm")}
                </button>
              </>
            ) : null}
          </span>
        ),
      },
    ],
    [t, openRecommend, openReply, requestApply, requestConfirm],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.email", "Email Review") }]}
        title={t("page.email.title", "Email Review")}
        subtitle={t("page.email.sub", "AI-parsed recaps awaiting confirmation.")}
      />
      <Toolbar right={<span className="hint">{t("page.email.count", "{n} messages", { n: rows.length })}</span>}>
        <button className="btn btn-primary" type="button" onClick={() => sync().catch((ex) => toast.error(msgOf(ex, t("page.email.sync_fail", "Sync failed"))))}>
          {m365 ? t("page.email.sync_btn_m365", "同步 Microsoft 365 收件箱") : t("page.email.sync_btn", "Sync demo inbox")}
        </button>
        {m365 ? <span className="badge badge-pass">{t("page.email.m365_connected", "Microsoft 365 已连接")}</span> : null}
        {officeErr ? (
          <span className="badge badge-warn" title={officeErr}>
            {t("page.email.office_status_fail", "M365 status unavailable")}
          </span>
        ) : null}
      </Toolbar>
      <StatusLegend statuses={["pending", "review", "parsed", "failed"]} />
      <div className="panel">
        <h3>{t("page.email.accounts", "Mailbox accounts")}</h3>
        {accErr ? (
          <p className="state-view-error" role="alert">
            {t("page.email.accounts_fail", "Mailbox accounts could not be loaded: {err}", { err: accErr })}
          </p>
        ) : null}
        <DataGrid<Account>
          columns={accountColumns}
          data={accounts}
          rowKey={(a) => a.id}
          editable
          onCellSave={onAccountCellSave}
          storageKey="email_accounts_grid"
          emptyText={t("page.email.no_accounts", "No mailbox accounts")}
        />
      </div>
      <div className="panel">
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!loading && !err && rows.length === 0}
          emptyText={t("page.email.empty", "No messages pending review.")}
          onRetry={() => void load()}
        >
          <DataGrid<Msg>
            columns={columns}
            data={rows}
            rowKey={(r) => r.id}
            onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
            storageKey="email_review_grid"
            emptyText={t("page.email.empty", "No messages pending review.")}
          />
        </StateView>
        <ContextMenu controller={rowCtx} items={menuItems} />
      </div>
      <RecordModal
        open={Boolean(replyFor)}
        title={t("page.email.reply_title", "Reply to sender")}
        onClose={() => setReplyFor(null)}
        onSave={() => setPendingSend(true)}
        saving={replySending}
        canDelete={false}
        size="lg"
      >
        <div className="form-row">
          <label>
            {t("page.email.reply_template", "Template")}
            <select value={replyTemplate} onChange={(e) => changeReplyTemplate(e.target.value as ReplyTemplate)}>
              {REPLY_TEMPLATES.map((tpl) => (
                <option key={tpl} value={tpl}>
                  {tpl === "ack_recap"
                    ? t("page.email.tpl_ack_recap", "Confirm recap")
                    : tpl === "counter_offer"
                      ? t("page.email.tpl_counter_offer", "Counter offer")
                      : tpl === "nor_ack"
                        ? t("page.email.tpl_nor_ack", "Acknowledge NOR")
                        : tpl === "laytime_query"
                          ? t("page.email.tpl_laytime_query", "Laytime query")
                          : t("page.email.tpl_general", "General reply")}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">→ {replyFor?.from_email || "—"} · {replyFor?.subject}</p>
        <label>
          {t("page.email.reply_body", "Body (editable)")}
          <textarea rows={14} value={replyBody} onChange={(e) => setReplyBody(e.target.value)} />
        </label>
      </RecordModal>

      {/* AI 推荐 —— 建议在此确认，执行才落到业务端点 */}
      <RecordModal
        open={Boolean(recFor)}
        title={t("page.email.rec_title", "AI 建议的下一步")}
        onClose={() => setRecFor(null)}
        canEdit={false}
        canDelete={false}
        size="md"
      >
        {recBusy ? (
          <p className="muted">{t("page.email.rec_loading", "正在分析…")}</p>
        ) : rec ? (
          <>
            <div className="form-row">
              <span className="ai-rec">
                {rec.recommendation === "apply"
                  ? t("page.email.rec_apply", "生成业务草稿")
                  : rec.recommendation === "reply"
                    ? t("page.email.rec_reply", "回复发件人")
                    : t("page.email.rec_review", "人工复核")}
                <span className="ai-rec-conf">
                  <Num v={rec.confidence * 100} digits={0} />%
                </span>
                <span className="badge">{rec.source === "llm" ? "AI" : "rules"}</span>
              </span>
            </div>
            <p>{rec.reason}</p>
            {rec.source && rec.source !== "llm" ? (
              <p className="ai-rec-note">
                {t(
                  "page.email.rec_rules_hint",
                  "AI 模型未配置或暂不可用 — 本推荐由内置规则生成。",
                )}
              </p>
            ) : null}
            <p className="muted">
              {t("page.email.rec_type", "识别类型")}：{rec.email_type || "—"}
              {rec.reply_template ? ` · ${t("page.email.rec_tpl", "回复模板")}：${rec.reply_template}` : ""}
              {rec.already_applied ? ` · ${t("page.email.rec_applied", "草稿已生成")}` : ""}
            </p>
            {rec.recommendation !== "review" ? (
              <p className="row-actions">
                <button className="btn btn-primary" type="button" onClick={() => void actOnRecommend()}>
                  {t("page.email.rec_act", "按建议执行")}
                </button>
              </p>
            ) : (
              <p className="hint">{t("page.email.rec_review_hint", "无法自动处理，请人工复核该邮件。")}</p>
            )}
            {!rec.already_applied && rec.recommendation === "reply" ? (
              <p className="hint">{t("page.email.rec_reply_hint", "执行后会打开回复草稿，发送前可编辑正文。")}</p>
            ) : null}
          </>
        ) : (
          <p className="muted">{t("page.email.rec_none", "无推荐")}</p>
        )}
      </RecordModal>

      {/* 落单 / 确认解析 —— 都会改变真实数据，先二次确认 */}
      <ConfirmDialog
        open={pending !== null}
        title={
          pending?.kind === "apply"
            ? t("page.email.confirm_apply_title", "Create business draft")
            : t("page.email.confirm_parse_title", "Confirm parse result")
        }
        message={
          pending?.kind === "apply"
            ? t("page.email.confirm_apply_msg", 'Create a real business draft from "{subject}"? This cannot be undone automatically.', {
                subject: pending?.msg.subject || pending?.msg.from_email || pending?.msg.id || "",
              })
            : t("page.email.confirm_parse_msg", 'Confirm the parse result of "{subject}"? It will leave the review queue.', {
                subject: pending?.msg.subject || pending?.msg.from_email || pending?.msg.id || "",
              })
        }
        confirmLabel={
          pending?.kind === "apply" ? t("page.email.apply_btn", "Create draft") : t("common.confirm", "Confirm")
        }
        danger={pending?.kind === "apply"}
        onConfirm={() => {
          const p = pending;
          setPending(null);
          if (!p) return;
          if (p.kind === "apply") void applyDraft(p.msg);
          else void confirm(p.msg.id).catch((ex) => toast.error(msgOf(ex, t("page.email.confirm_fail", "Confirm failed"))));
        }}
        onCancel={() => setPending(null)}
      />

      {/* 发信不可撤回 —— 二次确认 */}
      <ConfirmDialog
        open={pendingSend}
        title={t("page.email.confirm_send_title", "Send reply")}
        message={t("page.email.confirm_send_msg", 'Send this reply to {to}? The message will be delivered immediately.', {
          to: replyFor?.from_email || "—",
        })}
        confirmLabel={t("page.email.send_btn", "Send")}
        danger
        onConfirm={() => {
          setPendingSend(false);
          void sendReply();
        }}
        onCancel={() => setPendingSend(false)}
      />
    </AppShell>
  );
}
