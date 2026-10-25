"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { StateView } from "@/components/StateView";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { AiExtractFill, type ExtractedValues } from "@/components/ai/AiExtractFill";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { downloadCsv } from "@/lib/csv";
import { formatInTz, parseUtc } from "@/lib/datetime";
import { htmlToText } from "@/lib/htmlText";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Msg = {
  id: string;
  subject: string | null;
  from_email: string | null;
  parse_status: string;
  parse_confidence: number | null;
  parse_result: Record<string, unknown>;
  sent_at: string | null;
  folder: string;
  direction: string;
};

type MsgDetail = Msg & {
  message_id: string;
  body_text: string;
};

type Account = {
  id: string;
  email: string;
  provider: string;
  display_name: string | null;
  status: string;
};

type FolderInfo = {
  key: string;
  display_name: string;
  well_known: string | null;
  parent_key: string | null;
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

const DAY_OPTIONS = [7, 14, 30] as const;
const COUNT_OPTIONS = [200, 500, 1000] as const;
const FALLBACK_FOLDERS: FolderInfo[] = [
  { key: "inbox", display_name: "Inbox", well_known: "inbox", parent_key: null },
  { key: "sentitems", display_name: "Sent Items", well_known: "sentitems", parent_key: null },
];
type StatusFilter = "" | "review" | "parsed" | "pending";

/** 解析结果 → 结构化字段 chips（替代原始 JSON 预览） */
function parseFields(r: { parse_result: Record<string, unknown> }): {
  etype: string;
  pairs: Array<[string, unknown]>;
} {
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
  } else if (etype === "outbound") {
    pick(sub, ["to_recipients"]);
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
  const router = useRouter();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [rows, setRows] = useState<Msg[]>([]);
  const [m365, setM365] = useState(false);
  const [loading, setLoading] = useState(true);
  /** 主列表加载失败 —— 绝不能与「没有邮件」混淆 */
  const [err, setErr] = useState<string | null>(null);
  /** 邮箱账号面板（次级列表）加载失败 —— 局部提示，不影响主列表 */
  const [accErr, setAccErr] = useState<string | null>(null);
  /** M365 连接状态（参考数据）加载失败 —— 只影响徽标 */
  const [officeErr, setOfficeErr] = useState<string | null>(null);
  /** 文件夹清单加载失败 —— 降级静态双 Tab */
  const [foldersErr, setFoldersErr] = useState<string | null>(null);
  const rowCtx = useContextMenu<Msg>();
  // 同步参数（天数 + 条数双控；服务端硬上限 30 天 / 1000 条）
  const [syncDays, setSyncDays] = useState<(typeof DAY_OPTIONS)[number]>(7);
  const [syncCount, setSyncCount] = useState<(typeof COUNT_OPTIONS)[number]>(200);
  const [syncFolders, setSyncFolders] = useState<string[]>(["inbox", "sentitems"]);
  const [folderList, setFolderList] = useState<FolderInfo[]>(FALLBACK_FOLDERS);
  const [activeFolder, setActiveFolder] = useState("inbox");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("review");
  const [sortKey, setSortKey] = useState<string>("sent_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  // 详情
  const [detailFor, setDetailFor] = useState<Msg | null>(null);
  const [detail, setDetail] = useState<MsgDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  // 详情 → 填入航次计算
  const [extractOpen, setExtractOpen] = useState(false);
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
   * 取数：四个来源彼此独立（allSettled），主列表失败走错误态，参考数据失败只做局部提示。
   * 主列表 = 当前文件夹 + 时间窗 + 条数上限（全状态；状态筛选在前端做，
   * 以便「N 封被状态筛选隐藏」提示能算出来）。
   */
  const load = useCallback(async () => {
    setLoading(true);
    const qs = new URLSearchParams({
      folder: activeFolder,
      days: String(syncDays),
      limit: String(syncCount),
    });
    const [accR, msgsR, foldersR, officeR] = await Promise.allSettled([
      apiGet("/api/v1/email/accounts"),
      apiGet(`/api/v1/email/messages?${qs.toString()}`),
      apiGet("/api/v1/email/folders"),
      apiGet("/api/v1/office/status"),
    ]);
    if (msgsR.status === "fulfilled") {
      setRows(msgsR.value as Msg[]);
      setErr(null);
    } else {
      setRows([]);
      setErr(msgOf(msgsR.reason));
    }
    if (accR.status === "fulfilled") {
      setAccounts(accR.value as Account[]);
      setAccErr(null);
    } else {
      setAccounts([]);
      setAccErr(msgOf(accR.reason));
    }
    if (foldersR.status === "fulfilled") {
      const fl = (foldersR.value as { folders?: FolderInfo[] } | null)?.folders || [];
      // inbox / sentitems 永远并入（Graph 权限不给全时至少有双 Tab 可看）
      const keys = new Set(fl.map((f) => f.key.toLowerCase()));
      const merged = [...fl];
      for (const fb of FALLBACK_FOLDERS) {
        if (!keys.has(fb.key)) merged.unshift(fb);
      }
      setFolderList(merged);
      setFoldersErr(null);
    } else {
      setFolderList(FALLBACK_FOLDERS);
      setFoldersErr(msgOf(foldersR.reason));
    }
    if (officeR.status === "fulfilled") {
      setM365(Boolean((officeR.value as { connected?: boolean } | null)?.connected));
      setOfficeErr(null);
    } else {
      setM365(false);
      setOfficeErr(msgOf(officeR.reason));
    }
    setLoading(false);
  }, [activeFolder, syncDays, syncCount]);

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
        ? t("page.email.syncing_m365", "正在从 Microsoft 365 同步邮件…")
        : t("page.email.syncing", "Syncing demo mailbox…"),
    );
    const acc = await ensureSyncAccount();
    const qs = new URLSearchParams({
      days: String(syncDays),
      count: String(syncCount),
      folders: syncFolders.join(",") || "inbox",
    });
    const result = (await apiPost(`/api/v1/email/accounts/${acc.id}/sync?${qs.toString()}`)) as {
      synced?: number;
      capped?: boolean;
    };
    await load();
    toast.success(t("page.email.synced", "Synced {n} message(s).", { n: result.synced ?? 1 }));
    if (result.capped) {
      toast.error(
        t("page.email.sync_capped", "达到单次同步总量上限（2000 条），部分邮件未拉取 — 可缩小天数/条数再同步。"),
      );
    }
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

  /** 行点击 → 详情（正文 + 解析字段；DataGrid 行 onClick 不阻止冒泡，行内按钮需 stopPropagation） */
  const openDetail = useCallback(
    async (m: Msg) => {
      setDetailFor(m);
      setDetail(null);
      setDetailErr(null);
      setDetailBusy(true);
      try {
        const d = (await apiGet(`/api/v1/email/messages/${m.id}`)) as MsgDetail;
        setDetail(d);
      } catch (ex) {
        setDetailErr(msgOf(ex, t("page.email.detail_fail", "加载邮件详情失败")));
      } finally {
        setDetailBusy(false);
      }
    },
    [t],
  );

  /** 详情 → 填入航次计算：现成 parse_result 预填 AiExtractFill 预览，确认后转 estimates 页 */
  function applyToEstimate() {
    if (!detail) return;
    setExtractOpen(true);
  }

  const onExtractApply = useCallback(
    (values: ExtractedValues) => {
      const payload = {
        ...values,
        source_email: detail
          ? { id: detail.id, subject: detail.subject, from_email: detail.from_email }
          : undefined,
      };
      try {
        sessionStorage.setItem("marios_estimate_prefill", JSON.stringify(payload));
      } catch {
        /* 隐私模式等场景 sessionStorage 不可用 — 直接提示 */
        toast.error(t("page.email.prefill_fail", "无法写入浏览器缓存 — 请在估算页手动填写。"));
        return;
      }
      setExtractOpen(false);
      setDetailFor(null);
      toast.success(t("page.email.prefill_ok", "已带入估算页 — 请复核后保存。"));
      router.push("/estimates");
    },
    [detail, router, t, toast],
  );

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
      ["id", "subject", "from_email", "sent_at", "folder", "direction", "parse_status", "parse_confidence"],
      list.map((m) => [
        m.id,
        m.subject ?? "",
        m.from_email ?? "",
        m.sent_at ?? "",
        m.folder || "inbox",
        m.direction || "inbound",
        m.parse_status,
        m.parse_confidence ?? "",
      ]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const menuItems = (m: Msg): ContextMenuItem[] => [
    {
      key: "detail",
      label: t("page.email.detail_btn", "查看详情"),
      onClick: () => void openDetail(m),
    },
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

  // ── 前端状态筛选 + 客户端排序（finance/pnl 模式：useMemo 比较器） ──────
  const statusFiltered = useMemo(() => {
    if (!statusFilter) return rows;
    return rows.filter((m) => m.parse_status === statusFilter);
  }, [rows, statusFilter]);

  const sorted = useMemo(() => {
    const arr = [...statusFiltered];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      let av: string | number | null;
      let bv: string | number | null;
      switch (sortKey) {
        case "subject":
          av = a.subject || "";
          bv = b.subject || "";
          break;
        case "from_email":
          av = a.from_email || "";
          bv = b.from_email || "";
          break;
        case "parse_status":
          av = a.parse_status;
          bv = b.parse_status;
          break;
        case "parse_confidence":
          av = a.parse_confidence;
          bv = b.parse_confidence;
          break;
        case "sent_at":
        default:
          av = a.sent_at ? parseUtc(a.sent_at)?.getTime() ?? null : null;
          bv = b.sent_at ? parseUtc(b.sent_at)?.getTime() ?? null : null;
          break;
      }
      // null 恒最后（不随升降序翻转）
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * ((av as number) - (bv as number));
    });
    return arr;
  }, [statusFiltered, sortKey, sortDir]);

  const onSortChange = useCallback((key: string, dir: "asc" | "desc" | null) => {
    setSortKey(key);
    setSortDir(dir === "asc" ? "asc" : "desc");
  }, []);

  /** Tab 切换：inbox 默认复核队列，其他文件夹看全量 */
  const changeFolder = useCallback((key: string) => {
    setActiveFolder(key);
    setStatusFilter(key === "inbox" ? "review" : "");
  }, []);

  const folderTabs = useMemo<TabItem[]>(
    () =>
      folderList.map((f) => ({
        key: f.key,
        label: f.parent_key ? `└ ${f.display_name}` : f.display_name,
        title: f.key,
      })),
    [folderList],
  );

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
        minWidth: 200,
        sortable: true,
        value: (r) => r.subject || "",
        render: (_v, r) => r.subject || t("page.email.no_subject", "(no subject)"),
      },
      {
        key: "from_email",
        title: t("page.email.from", "From"),
        width: 160,
        sortable: true,
        value: (r) => r.from_email || "",
        render: (_v, r) => {
          if ((r.direction || "inbound") === "outbound") {
            const to = ((r.parse_result || {}) as { to_recipients?: string[] }).to_recipients;
            return `→ ${to?.[0] || "—"}`;
          }
          return r.from_email || "—";
        },
      },
      {
        key: "sent_at",
        title: t("page.email.time", "Time"),
        width: 150,
        sortable: true,
        value: (r) => (r.sent_at ? parseUtc(r.sent_at)?.getTime() ?? null : null),
        render: (_v, r) => (r.sent_at ? formatInTz(r.sent_at) : "—"),
      },
      {
        key: "parse_status",
        title: t("common.status", "Status"),
        width: 100,
        sortable: true,
        value: (r) => r.parse_status,
      },
      {
        key: "parse_confidence",
        title: t("page.email.confidence", "Confidence"),
        width: 100,
        align: "right",
        sortable: true,
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
                // 两列 dl：标签走 email.parse.* 词表，未知键回落原键；值过 htmlToText 兜底
                <dl className="parse-kv">
                  {pairs.map(([k, val]) => (
                    <div key={k}>
                      <dt>{t(`email.parse.${k}`, k)}</dt>
                      <dd>{k === "to_recipients" && Array.isArray(val) ? val.join(", ") : htmlToText(val)}</dd>
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
          <span className="row-actions" onClick={(e) => e.stopPropagation()}>
            <button className="btn btn-sm" type="button" onClick={() => void openDetail(r)}>
              {t("page.email.detail_btn", "查看详情")}
            </button>
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
    [t, openDetail, openRecommend, openReply, requestApply, requestConfirm],
  );

  /** 状态筛选芯片把行全筛没了、但未筛时有行 → 提示被隐藏的数量 */
  const hiddenByFilter = statusFilter ? rows.length - statusFiltered.length : 0;

  const statusChip = (key: StatusFilter, label: string) => (
    <button
      key={key || "all"}
      type="button"
      className={`btn btn-sm${statusFilter === key ? " btn-primary" : ""}`}
      onClick={() => setStatusFilter(key)}
    >
      {label}
    </button>
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.email", "Email Review") }]}
        title={t("page.email.title", "Email Review")}
        subtitle={t("page.email.sub", "AI-parsed recaps awaiting confirmation.")}
      />
      <Toolbar
        right={
          <span className="hint">
            {t("page.email.count", "{n} messages", { n: sorted.length })}
            {rows.length !== sorted.length ? ` / ${rows.length}` : ""}
          </span>
        }
      >
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => sync().catch((ex) => toast.error(msgOf(ex, t("page.email.sync_fail", "Sync failed"))))}
        >
          {m365
            ? t("page.email.sync_btn_m365", "同步 Microsoft 365 邮件")
            : t("page.email.sync_btn", "Sync demo inbox")}
        </button>
        <label className="email-sync-opt">
          {t("page.email.days", "天数")}
          <select value={syncDays} onChange={(e) => setSyncDays(Number(e.target.value) as 7 | 14 | 30)}>
            {DAY_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {t("page.email.days_opt", "{n} 天", { n: d })}
              </option>
            ))}
          </select>
        </label>
        <label className="email-sync-opt">
          {t("page.email.limit", "条数")}
          <select value={syncCount} onChange={(e) => setSyncCount(Number(e.target.value) as 200 | 500 | 1000)}>
            {COUNT_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <details className="email-folders-pop">
          <summary className="btn btn-sm">
            {t("page.email.folders_btn", "文件夹")} ({syncFolders.length})
          </summary>
          <div className="email-folders-pop-body">
            {folderList.map((f) => (
              <label key={f.key} className="email-folders-pop-item">
                <input
                  type="checkbox"
                  checked={syncFolders.includes(f.key)}
                  onChange={(e) =>
                    setSyncFolders((prev) =>
                      e.target.checked ? [...prev, f.key] : prev.filter((k) => k !== f.key),
                    )
                  }
                />
                {f.parent_key ? `└ ${f.display_name}` : f.display_name}
              </label>
            ))}
          </div>
        </details>
        {m365 ? <span className="badge badge-pass">{t("page.email.m365_connected", "Microsoft 365 已连接")}</span> : null}
        {officeErr ? (
          <span className="badge badge-warn" title={officeErr}>
            {t("page.email.office_status_fail", "M365 status unavailable")}
          </span>
        ) : null}
        {foldersErr ? (
          <span className="badge badge-warn" title={foldersErr}>
            {t("page.email.folders_fail", "文件夹清单不可用，已降级双 Tab")}
          </span>
        ) : null}
      </Toolbar>
      <Tabs
        items={folderTabs}
        value={activeFolder}
        onChange={changeFolder}
        variant="pill"
        panelIdPrefix="email-folders"
      />
      <div className="row-actions">
        {statusChip("", t("page.email.filter_all", "全部"))}
        {statusChip("review", t("page.email.filter_review", "待复核"))}
        {statusChip("parsed", t("page.email.filter_parsed", "已解析"))}
        {statusChip("pending", t("page.email.filter_pending", "待处理"))}
      </div>
      {hiddenByFilter > 0 && statusFiltered.length === 0 ? (
        <p className="hint">
          {t("page.email.hidden_by_filter", "{n} 封被状态筛选隐藏。", { n: hiddenByFilter })}{" "}
          <button className="btn btn-sm" type="button" onClick={() => setStatusFilter("")}>
            {t("page.email.filter_show_all", "显示全部")}
          </button>
        </p>
      ) : null}
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
          empty={!loading && !err && sorted.length === 0}
          emptyText={t("page.email.empty_folder", "No messages in this folder.")}
          onRetry={() => void load()}
        >
          <DataGrid<Msg>
            columns={columns}
            data={sorted}
            rowKey={(r) => r.id}
            onRowClick={(r) => void openDetail(r)}
            onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
            onSortChange={onSortChange}
            storageKey="email_review_grid"
            emptyText={t("page.email.empty_folder", "No messages in this folder.")}
          />
        </StateView>
        <ContextMenu controller={rowCtx} items={menuItems} />
      </div>

      {/* 邮件详情 —— 纯文本正文 + 干净解析字段 + 填入航次计算入口 */}
      <RecordModal
        open={Boolean(detailFor)}
        title={detail?.subject || detailFor?.subject || t("page.email.detail_title", "邮件详情")}
        onClose={() => {
          setDetailFor(null);
          setDetail(null);
        }}
        canEdit={false}
        canDelete={false}
        size="lg"
      >
        {detailBusy ? (
          <p className="muted">{t("page.email.detail_loading", "加载中…")}</p>
        ) : detailErr ? (
          <p className="state-view-error" role="alert">
            {detailErr}
          </p>
        ) : detail ? (
          <>
            <div className="ws-kv-grid">
              <div className="ws-kv">
                <span>{(detail.direction || "inbound") === "outbound" ? t("page.email.to", "收件人") : t("page.email.from", "From")}</span>
                <strong>
                  {(detail.direction || "inbound") === "outbound"
                    ? ((detail.parse_result as { to_recipients?: string[] })?.to_recipients?.join(", ") || "—")
                    : detail.from_email || "—"}
                </strong>
              </div>
              <div className="ws-kv">
                <span>{t("page.email.time", "Time")}</span>
                <strong>{detail.sent_at ? formatInTz(detail.sent_at) : "—"}</strong>
              </div>
              <div className="ws-kv">
                <span>{t("page.email.folder", "文件夹")}</span>
                <strong>{detail.folder || "inbox"}</strong>
              </div>
              <div className="ws-kv">
                <span>{t("common.status", "Status")}</span>
                <strong>{detail.parse_status}</strong>
              </div>
              <div className="ws-kv">
                <span>{t("page.email.confidence", "Confidence")}</span>
                <strong>
                  {detail.parse_confidence != null ? (
                    <><Num v={detail.parse_confidence * 100} digits={0} />%</>
                  ) : (
                    "—"
                  )}
                </strong>
              </div>
            </div>
            <h4>{t("page.email.body", "正文")}</h4>
            <pre className="email-detail-body">{htmlToText(detail.body_text)}</pre>
            {(() => {
              const { etype, pairs } = parseFields(detail);
              if (!pairs.length) return null;
              return (
                <>
                  <h4>
                    {t("page.email.parsed_title", "解析字段")}
                    {etype ? <span className="badge badge-info">{t(`email.type.${etype}`, etype)}</span> : null}
                  </h4>
                  <dl className="parse-kv">
                    {pairs.map(([k, val]) => (
                      <div key={k}>
                        <dt>{t(`email.parse.${k}`, k)}</dt>
                        <dd>{k === "to_recipients" && Array.isArray(val) ? val.join(", ") : htmlToText(val)}</dd>
                      </div>
                    ))}
                  </dl>
                </>
              );
            })()}
            <p className="row-actions">
              {["fixture_recap", "recap", "nor"].includes(
                String((detail.parse_result || {}).email_type || ""),
              ) ? (
                <button className="btn btn-primary btn-sm" type="button" onClick={applyToEstimate}>
                  {t("page.email.fill_estimate", "填入航次计算")}
                </button>
              ) : null}
              {detail.parse_status === "review" ? (
                <>
                  <button
                    className="btn btn-sm btn-primary"
                    type="button"
                    onClick={() => {
                      const m = detail;
                      setDetailFor(null);
                      setDetail(null);
                      requestApply(m);
                    }}
                  >
                    {t("page.email.apply_btn", "Create draft")}
                  </button>
                  <button
                    className="btn btn-sm"
                    type="button"
                    onClick={() => {
                      const id = detail.id;
                      setDetailFor(null);
                      setDetail(null);
                      void confirm(id).catch((ex) => toast.error(msgOf(ex, t("page.email.confirm_fail", "Confirm failed"))));
                    }}
                  >
                    {t("common.confirm", "Confirm")}
                  </button>
                </>
              ) : null}
              <button
                className="btn btn-sm"
                type="button"
                onClick={() => {
                  const m = detail;
                  setDetailFor(null);
                  setDetail(null);
                  void openReply(m);
                }}
              >
                {t("page.email.reply_btn", "Reply")}
              </button>
            </p>
            <p className="hint">
              {t("page.email.message_id", "Message-ID")}：<code>{detail.message_id}</code>
            </p>
          </>
        ) : null}
      </RecordModal>

      {/* 详情 → 填入航次计算：现成解析字段预填预览，确认后跳估算页 */}
      <AiExtractFill
        open={extractOpen}
        onClose={() => setExtractOpen(false)}
        initialFields={detail?.parse_result}
        initialKind={String((detail?.parse_result || {})?.email_type || "")}
        onApply={onExtractApply}
      />

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
            ? t("page.email.confirm_apply_ask", 'Create a real business draft from "{subject}"? This cannot be undone automatically.', {
                subject: pending?.msg.subject || pending?.msg.from_email || pending?.msg.id || "",
              })
            : t("page.email.confirm_parse_ask", 'Confirm the parse result of "{subject}"? It will leave the review queue.', {
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
