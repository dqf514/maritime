"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { PageGuide } from "@/components/PageGuide";
import { RecordModal } from "@/components/RecordModal";
import { StateView } from "@/components/StateView";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { AiExtractFill, type ExtractedValues } from "@/components/ai/AiExtractFill";
import { apiGet, apiPost } from "@/lib/api";
import { handled, msgOf } from "@/lib/errors";
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

/** 逐类型落单按钮文案（Request XIV：油/使费/发票/索赔等新分支各有具名按钮） */
const APPLY_LABEL_KEYS: Record<string, [string, string]> = {
  fixture_recap: ["page.email.apply_recap", "Create estimate & charter drafts"],
  recap: ["page.email.apply_recap", "Create estimate & charter drafts"],
  nor: ["page.email.apply_nor", "Stamp NOR time"],
  laytime_statement: ["page.email.apply_laytime", "Create laytime calc"],
  bunker_offer: ["page.email.apply_bunker_order", "Create bunker order"],
  port_disbursement: ["page.email.apply_pda", "Create PDA draft"],
  invoice: ["page.email.apply_invoice", "Create invoice draft"],
  claim: ["page.email.apply_claim", "Create claim record"],
};

/** 存档目标实体 → 列表端点 + 选项文案（列表端点形状不一，统一防御式取值） */
const ARCHIVE_SOURCES: Record<string, { url: string; label: (e: Record<string, unknown>) => string }> = {
  voyage: { url: "/api/v1/voyages", label: (e) => String(e.voyage_no || e.name || e.id || "") },
  port_disbursement: { url: "/api/v1/port-disbursements", label: (e) => String(e.port || e.voyage_no || e.id || "") },
  bunker_order: { url: "/api/v1/bunker-orders", label: (e) => String(e.order_no || e.id || "") },
  claim: { url: "/api/v1/claims", label: (e) => String(e.claim_no || e.id || "") },
  invoice: { url: "/api/v1/invoices", label: (e) => String(e.invoice_no || e.id || "") },
  charter: { url: "/api/v1/charters", label: (e) => String(e.charter_no || e.id || "") },
  estimate: { url: "/api/v1/estimates", label: (e) => String(e.title || e.id || "") },
  laytime: { url: "/api/v1/laytimes", label: (e) => String(e.voyage_no || e.port || e.id || "") },
};

function msgEmailType(m: { parse_result?: Record<string, unknown> }): string {
  const p = (m.parse_result || {}) as Record<string, unknown>;
  const cls = (p.classification || {}) as Record<string, unknown>;
  return String(p.email_type || cls.type || "");
}

/** 进复核队列的业务类型 —— 只有这些才值得 AI 复核（B：其余不烧 token） */
const BUSINESS_TYPES = new Set([
  "fixture_recap",
  "recap",
  "nor",
  "laytime_statement",
  "bunker_offer",
  "port_disbursement",
  "invoice",
  "claim",
]);

/** 可疑判定：业务类型 +（低置信 或 关键字段缺失）→ 打开详情时后台跑一次 AI 识别 */
function needsAiSuggest(m: { parse_confidence: number | null; parse_result?: Record<string, unknown> }): boolean {
  const etype = msgEmailType(m);
  if (!BUSINESS_TYPES.has(etype)) return false;
  if (m.parse_confidence == null || m.parse_confidence < 0.8) return true;
  const p = (m.parse_result || {}) as Record<string, unknown>;
  const raw = p[etype];
  const sub = (raw && typeof raw === "object" ? raw : p) as Record<string, unknown>;
  if (etype === "nor") return !sub.date_time;
  if (etype === "fixture_recap" || etype === "recap") return !sub.vessel && !sub.vessel_name;
  if (etype === "laytime_statement") return !Array.isArray(sub.events) || sub.events.length === 0;
  return false;
}

const DAY_OPTIONS = [7, 14, 30] as const;
const COUNT_OPTIONS = [200, 500, 1000] as const;
/** 切文件夹自动同步的冷却时间 —— 5 分钟内不重复自动拉（手动同步同样重置计时） */
const AUTO_SYNC_COOLDOWN_MS = 5 * 60 * 1000;
const FALLBACK_FOLDERS: FolderInfo[] = [
  { key: "inbox", display_name: "Inbox", well_known: "inbox", parent_key: null },
  { key: "sentitems", display_name: "Sent Items", well_known: "sentitems", parent_key: null },
];
type StatusFilter = "" | "review" | "parsed" | "pending" | "ignored";

/** 同步偏好（天数/条数/文件夹）持久化 —— 刷新不丢勾选；值非法时回退默认 */
const SYNC_PREFS_KEY = "marios_email_sync_prefs";
type SyncPrefs = {
  days: (typeof DAY_OPTIONS)[number];
  count: (typeof COUNT_OPTIONS)[number];
  folders: string[];
};
const SYNC_PREFS_DEFAULT: SyncPrefs = { days: 7, count: 200, folders: ["inbox", "sentitems"] };

function loadSyncPrefs(): SyncPrefs {
  if (typeof window === "undefined") return SYNC_PREFS_DEFAULT;
  try {
    const raw = window.localStorage.getItem(SYNC_PREFS_KEY);
    if (!raw) return SYNC_PREFS_DEFAULT;
    const p = JSON.parse(raw) as Partial<SyncPrefs>;
    return {
      days: DAY_OPTIONS.includes(p.days as never) ? (p.days as SyncPrefs["days"]) : SYNC_PREFS_DEFAULT.days,
      count: COUNT_OPTIONS.includes(p.count as never) ? (p.count as SyncPrefs["count"]) : SYNC_PREFS_DEFAULT.count,
      folders:
        Array.isArray(p.folders) && p.folders.length
          ? p.folders.filter((f): f is string => typeof f === "string" && f.length > 0).slice(0, 10)
          : SYNC_PREFS_DEFAULT.folders,
    };
  } catch {
    return SYNC_PREFS_DEFAULT;
  }
}

function saveSyncPrefs(next: SyncPrefs) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SYNC_PREFS_KEY, JSON.stringify(next));
  } catch {
    /* 隐私模式/存储满 → 不持久化，不影响本次会话 */
  }
}

/** 解析结果 → 结构化字段 chips（替代原始 JSON 预览） */
function parseFields(r: { parse_result: Record<string, unknown> }): {
  etype: string;
  pairs: Array<[string, unknown]>;
} {
  const p = (r.parse_result || {}) as Record<string, unknown>;
  const cls = (p.classification || {}) as Record<string, unknown>;
  const etype = String(p.email_type || cls.type || "");
  const sub =
    ((p.fixture_recap || p.nor || p.laytime || p.bunker_offer || p.port_disbursement || p.invoice ||
      p.claim) as Record<string, unknown>) || p;
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
  } else if (etype === "bunker_offer") {
    pick(sub, ["port", "grade", "unit_price", "qty_ordered", "supplier", "currency"]);
  } else if (etype === "port_disbursement") {
    pick(sub, ["port", "pda_amount", "fda_amount", "agent", "currency"]);
  } else if (etype === "invoice") {
    pick(sub, ["invoice_no_ref", "amount", "currency", "due_date"]);
  } else if (etype === "claim") {
    pick(sub, ["claim_type", "amount", "currency", "time_bar"]);
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
  // 邮件时间按租户默认时区展示（lestarigroup = Asia/Singapore，UTC+8）；
  // 未取到时回退 UTC，避免不同浏览器本地时区造成同屏不一致。
  const [tz, setTz] = useState<string>("UTC");
  /** 主列表加载失败 —— 绝不能与「没有邮件」混淆 */
  const [err, setErr] = useState<string | null>(null);
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
  /** 文件夹勾选弹窗（原 details 弹层会在工具栏里挤出上下滚动条 —— 改 modal） */
  const [foldersOpen, setFoldersOpen] = useState(false);
  /** 文件夹弹窗草稿：勾选只改草稿，点「保存」才写回 syncFolders，「取消」丢弃 */
  const [foldersDraft, setFoldersDraft] = useState<string[]>([]);
  const [activeFolder, setActiveFolder] = useState("inbox");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("review");
  const [sortKey, setSortKey] = useState<string>("sent_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  // 详情
  const [detailFor, setDetailFor] = useState<Msg | null>(null);
  const [detail, setDetail] = useState<MsgDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  /** 处理建议区：邮件先出；可疑业务邮件 pending → AI 识别 → 对应动作（Request XIX-B） */
  const [sug, setSug] = useState<{ phase: "idle" | "pending" | "done" | "error"; rec: Recommend | null }>({
    phase: "idle",
    rec: null,
  });
  const sugReqRef = useRef(0);
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
  /** 忽略并记住 —— 弹窗带「记住」勾选（默认勾上，用户的诉求就是「别再犯」） */
  const [ignoreFor, setIgnoreFor] = useState<Msg | null>(null);
  const [ignoreRemember, setIgnoreRemember] = useState(true);
  /** 邮件存档弹窗：选目标项目 → 正文作为附件（带版本）挂上去 */
  const [archiveFor, setArchiveFor] = useState<Msg | null>(null);
  const [archiveType, setArchiveType] = useState<string>("voyage");
  const [archiveEntityId, setArchiveEntityId] = useState("");
  const [archiveOptions, setArchiveOptions] = useState<Array<{ id: string; label: string }>>([]);
  const [archiveErr, setArchiveErr] = useState<string | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);
  // AI 推荐
  const [recFor, setRecFor] = useState<Msg | null>(null);
  const [rec, setRec] = useState<Recommend | null>(null);
  const [recBusy, setRecBusy] = useState(false);
  /** 同步并发守卫 + 自动同步冷却计时（切文件夹触发的自动拉取 5 分钟内不重复） */
  const syncingRef = useRef(false);
  const lastSyncAtRef = useRef(0);
  /** 同步状态的页面级呈现 —— 只靠转瞬即逝的 toast，用户会盯着旧邮件问「怎么都是老邮件？」 */
  const [syncUi, setSyncUi] = useState<{
    phase: "idle" | "running" | "done" | "error";
    startedAt?: number;
    synced?: number;
    folders?: string[];
    error?: string;
  }>({ phase: "idle" });
  /** 「上次同步 x 前」+ 同步已用时的公共时钟 */
  const [clock, setClock] = useState(() => Date.now());
  /** 上次同步时间 —— localStorage 持久化，刷新后仍能判断列表有多新 */
  const [lastSyncedAt, setLastSyncedAt] = useState<number>(() => {
    try {
      return Number(window.localStorage.getItem("marios_email_last_sync") || 0) || 0;
    } catch {
      return 0;
    }
  });
  /** 本次同步新拉到的邮件 id —— 行高亮 12s，让「列表哪里变了」肉眼可见 */
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  /** 同步前的行快照（手动同步才快照；切文件夹的自动同步整表都是新的，不逐行高亮） */
  const preSyncIdsRef = useRef<Set<string> | null>(null);
  const doneTimerRef = useRef<number | null>(null);
  const newIdsTimerRef = useRef<number | null>(null);

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
    let fresh: Msg[] | null = null;
    if (msgsR.status === "fulfilled") {
      fresh = msgsR.value as Msg[];
      setRows(fresh);
      setErr(null);
    } else {
      setRows([]);
      setErr(msgOf(msgsR.reason));
    }
    // 账户列表仅供同步按钮 ensure 用；加载失败时置空，由 ensureSyncAccount 重建
    setAccounts(accR.status === "fulfilled" ? (accR.value as Account[]) : []);
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
    return fresh; // sync() 用它 diff 出「本次新拉到的」行做高亮
  }, [activeFolder, syncDays, syncCount]);

  // sync 完成后的刷新要用「最新」的 load —— 否则切文件夹触发的自动同步
  // 会用旧 activeFolder 的闭包把新文件夹的列表覆写掉
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  // 「上次同步 x 前」/ 同步已用时的时钟：同步中每秒走一格，空闲 30 秒走一格
  useEffect(() => {
    const iv = window.setInterval(() => setClock(Date.now()), syncUi.phase === "running" ? 1000 : 30000);
    return () => window.clearInterval(iv);
  }, [syncUi.phase]);

  // 卸载时清掉挂着的定时器
  useEffect(
    () => () => {
      if (doneTimerRef.current) window.clearTimeout(doneTimerRef.current);
      if (newIdsTimerRef.current) window.clearTimeout(newIdsTimerRef.current);
    },
    [],
  );

  // 租户默认时区（Asia/Singapore 等）—— 邮件时间按它格式化。
  useEffect(() => {
    apiGet("/api/v1/me")
      .then((me) => {
        const t = (me as { tenant?: { default_timezone?: string } } | null)?.tenant?.default_timezone;
        if (t) setTz(t);
      })
      .catch(handled); // 时区取不到回退 UTC（tz state 默认值），无需打扰用户
  }, []);

  // 挂载时恢复上次的同步偏好（天数/条数/文件夹勾选）—— 刷新不丢
  useEffect(() => {
    const p = loadSyncPrefs();
    setSyncDays(p.days);
    setSyncCount(p.count);
    setSyncFolders(p.folders);
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

  async function sync(opts?: { folders?: string[]; auto?: boolean }) {
    const auto = Boolean(opts?.auto);
    const folders = (opts?.folders?.length ? opts.folders : syncFolders).slice(0, 10);
    // 并发守卫 + 自动同步 5 分钟冷却（手动同步同样重置计时 —— 刚拉过就不再自动拉）
    if (syncingRef.current) return;
    if (auto && Date.now() - lastSyncAtRef.current < AUTO_SYNC_COOLDOWN_MS) return;
    syncingRef.current = true;
    // 页面级状态：进入 running（手动同步快照当前行 id —— 完成后 diff 出「新邮件」高亮；
    // 切文件夹的自动同步整表都是新文件夹的行，不做逐行高亮，芯片提示就够）
    if (doneTimerRef.current) window.clearTimeout(doneTimerRef.current);
    preSyncIdsRef.current = auto ? null : new Set(rows.map((r) => r.id));
    setSyncUi({ phase: "running", startedAt: Date.now(), folders });
    try {
      if (!auto) {
        toast.success(
          m365
            ? t("page.email.syncing_m365", "正在从 Microsoft 365 同步邮件…")
            : t("page.email.syncing", "Syncing demo mailbox…"),
        );
      }
      const acc = await ensureSyncAccount();
      const qs = new URLSearchParams({
        days: String(syncDays),
        count: String(syncCount),
        folders: folders.join(",") || "inbox",
      });
      const result = (await apiPost(`/api/v1/email/accounts/${acc.id}/sync?${qs.toString()}`)) as {
        synced?: number;
        capped?: boolean;
        folders?: Record<string, number>;
      };
      lastSyncAtRef.current = Date.now();
      const fresh = await loadRef.current(); // 用最新 load —— 自动同步横跨文件夹切换
      // 新邮件高亮：本次拉到的、快照里没有的 id（12s 后自动熄灭）
      const before = preSyncIdsRef.current;
      if (before && fresh) {
        setNewIds(new Set(fresh.filter((m) => !before.has(m.id)).map((m) => m.id)));
        if (newIdsTimerRef.current) window.clearTimeout(newIdsTimerRef.current);
        newIdsTimerRef.current = window.setTimeout(() => setNewIds(new Set()), 12000);
      }
      // 「上次同步」持久化 —— 刷新页面也能看到列表有多新
      const now = Date.now();
      setLastSyncedAt(now);
      try {
        window.localStorage.setItem("marios_email_last_sync", String(now));
      } catch {
        // localStorage 不可用（隐私模式等）只丢展示，不影响同步
      }
      // 各文件夹拉取条数 —— 按勾选逐项显示（去重后 0 条也显示），让用户确认勾选的文件夹确实被同步了
      const folderMap = result.folders && typeof result.folders === "object" ? result.folders : {};
      const perFolder = folders
        .map((f) => `${f} ${folderMap[f] ?? 0}`)
        .join(" · ");
      // 芯片常驻 10s：0 条也明示「同步完成」，避免用户以为没动静
      setSyncUi({ phase: "done", synced: result.synced ?? 0, folders });
      doneTimerRef.current = window.setTimeout(
        () => setSyncUi((s) => (s.phase === "done" ? { phase: "idle" } : s)),
        10000,
      );
      // toast 只作为补充提示（自动同步 0 条保持安静，芯片已说明）
      if (!auto || (result.synced ?? 0) > 0) {
        toast.success(
          t("page.email.synced", "Synced {n} message(s).", { n: result.synced ?? 1 }) + (perFolder ? ` (${perFolder})` : ""),
        );
      }
      if (result.capped) {
        toast.error(
          t("page.email.sync_capped", "达到单次同步总量上限（2000 条），部分邮件未拉取 — 可缩小天数/条数再同步。"),
        );
      }
    } catch (ex) {
      setSyncUi({ phase: "error", error: msgOf(ex, t("page.email.sync_fail", "Sync failed")) });
      throw ex;
    } finally {
      syncingRef.current = false;
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
        const more =
          created.length > 1
            ? ` ${t("page.email.created_more", "+{n} more draft(s) created", { n: created.length - 1 })}`
            : "";
        toast.success(
          t("page.email.apply_done", "Draft created: {kind} — {title}", {
            kind: c.entity,
            title: c.title || c.voyage_no || c.id,
          }) + more,
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

  /** 忽略并记住：出复核队列 + 记发件人规则（可选），同源同类型后续不再识别 */
  async function ignoreMsg(m: Msg, remember: boolean) {
    try {
      await apiPost(`/api/v1/email/review/${m.id}/ignore`, { remember });
      toast.success(
        remember
          ? t("page.email.ignore_ok", "Ignored — rule saved for this sender")
          : t("page.email.ignored", "Ignored"),
      );
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("page.email.ignore_fail", "Ignore failed")));
    }
  }

  /** 存档目标清单：按实体类型取前 200 条（各端点形状不一，统一成 {id,label}） */
  const loadArchiveOptions = useCallback(
    async (etype: string) => {
      const src = ARCHIVE_SOURCES[etype];
      if (!src) {
        setArchiveOptions([]);
        return;
      }
      setArchiveBusy(true);
      setArchiveErr(null);
      try {
        // 列表端点两种形状：裸数组（bunker/PDA/charters/estimates）或分页信封 {items}
        const raw = (await apiGet(`${src.url}?limit=200`)) as
          | Array<Record<string, unknown>>
          | { items?: Array<Record<string, unknown>> };
        const list = Array.isArray(raw) ? raw : Array.isArray(raw?.items) ? raw.items : [];
        setArchiveOptions(
          list.map((e) => ({
            id: String(e.id),
            label: src.label(e),
          })),
        );
      } catch (ex) {
        setArchiveOptions([]);
        setArchiveErr(msgOf(ex, t("page.email.archive_load_fail", "Could not load the entity list")));
      } finally {
        setArchiveBusy(false);
      }
    },
    [t],
  );

  /** 打开存档弹窗：默认 voyage，首次进入即拉清单 */
  const openArchive = useCallback(
    (m: Msg) => {
      setArchiveFor(m);
      setArchiveType("voyage");
      setArchiveEntityId("");
      void loadArchiveOptions("voyage");
    },
    [loadArchiveOptions],
  );

  async function saveArchive() {
    if (!archiveFor || !archiveEntityId) return;
    try {
      const res = (await apiPost(`/api/v1/email/messages/${archiveFor.id}/archive`, {
        entity_type: archiveType,
        entity_id: archiveEntityId,
      })) as { version_no?: number };
      const opt = archiveOptions.find((o) => o.id === archiveEntityId);
      toast.success(
        t("page.email.archive_done", "Archived to {title} (v{n})", {
          title: opt?.label || archiveEntityId,
          n: res?.version_no ?? 1,
        }),
      );
      setArchiveFor(null);
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("page.email.archive_fail", "Archive failed")));
    }
  }

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

  /** 处理建议区 —— 可疑业务邮件打开即后台 AI 识别；错误不打扰阅读，落区里降级为规则建议 */
  const runSuggest = useCallback(async (m: MsgDetail) => {
    const req = ++sugReqRef.current;
    setSug({ phase: "pending", rec: null });
    try {
      const r = (await apiPost(`/api/v1/ai/assist/recommend/email/${m.id}`, {})) as Recommend;
      if (sugReqRef.current === req) setSug({ phase: "done", rec: r });
    } catch {
      if (sugReqRef.current === req) setSug({ phase: "error", rec: null });
    }
  }, []);

  // 详情加载完成 → 评估是否触发 AI（B：低置信/关键字段缺失才烧 token；否则规则动作直接出）
  useEffect(() => {
    sugReqRef.current += 1; // 关闭/切换详情时使在途 AI 请求失效
    if (!detail) {
      setSug({ phase: "idle", rec: null });
      return;
    }
    if (needsAiSuggest(detail)) void runSuggest(detail);
    else setSug({ phase: "idle", rec: null });
  }, [detail, runSuggest]);

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

  const menuItems = (m: Msg): ContextMenuItem[] => {
    const etype = msgEmailType(m);
    const applyLabel = APPLY_LABEL_KEYS[etype];
    return [
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
              label: applyLabel ? t(applyLabel[0], applyLabel[1]) : t("page.email.apply_btn", "Create draft"),
              onClick: () => requestApply(m),
            },
            {
              key: "ignore",
              label: t("page.email.ignore_btn", "忽略"),
              onClick: () => {
                setIgnoreRemember(true);
                setIgnoreFor(m);
              },
            },
            {
              key: "confirm",
              label: t("page.email.confirm_btn", "确认解析"),
              onClick: () => requestConfirm(m),
            },
          ]
        : []),
      {
        key: "archive",
        label: t("page.email.archive_btn", "存档"),
        onClick: () => openArchive(m),
      },
      {
        key: "reply",
        label: t("page.email.reply_btn", "Reply"),
        onClick: () => void openReply(m),
      },
      { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyMsgId(m) },
      { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportMsgs([m]) },
    ];
  };

  // ── 前端状态筛选 + 客户端排序（finance/pnl 模式：useMemo 比较器） ──────
  const statusFiltered = useMemo(() => {
    if (!statusFilter) return rows;
    // 忽略过的邮件 parse_status 已置 parsed —— 「已忽略」芯片按 ignored_at 判
    if (statusFilter === "ignored") {
      return rows.filter((m) => Boolean((m.parse_result || {}).ignored_at));
    }
    return rows.filter((m) => m.parse_status === statusFilter && !(m.parse_result || {}).ignored_at);
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

  /** Tab 切换：inbox 默认复核队列，其他文件夹看全量；顺手自动同步该文件夹（5 分钟冷却） */
  const changeFolder = useCallback(
    (key: string) => {
      setActiveFolder(key);
      setStatusFilter(key === "inbox" ? "review" : "");
      // 换文件夹后旧行高亮/旧芯片都失去意义（进行中的同步除外）
      setNewIds(new Set());
      setSyncUi((s) => (s.phase === "running" ? s : { phase: "idle" }));
      // 切到哪个文件夹就补拉哪个（只拉当前 Tab，不按勾选全拉）；
      // 未连邮箱账户且非 M365 时不自动建账户 —— 首次仍走手动同步按钮
      if (m365 || accounts.length) {
        void sync({ folders: [key], auto: true }).catch((ex) =>
          toast.error(msgOf(ex, t("page.email.sync_fail", "Sync failed"))),
        );
      }
    },
    [accounts.length, m365, sync, t, toast],
  );

  const folderTabs = useMemo<TabItem[]>(
    () =>
      folderList.map((f) => ({
        key: f.key,
        label: f.parent_key ? `└ ${f.display_name}` : f.display_name,
        title: f.key,
      })),
    [folderList],
  );

  const columns = useMemo<ColumnDef<Msg>[]>(
    () => [
      {
        key: "subject",
        title: t("page.email.subject", "Subject"),
        width: 360,
        minWidth: 200,
        sortable: true,
        // truncate=true：长主题截断显示（td title 提示全文），不再把后面的列挤出视口
        truncate: true,
        value: (r) => r.subject || "",
        render: (_v, r) => r.subject || t("page.email.no_subject", "(no subject)"),
      },
      {
        key: "from_email",
        title: t("page.email.from", "From"),
        width: 160,
        sortable: true,
        truncate: true,
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
        render: (_v, r) => (r.sent_at ? formatInTz(r.sent_at, tz) : "—"),
      },
      {
        key: "parse_status",
        title: t("common.status", "Status"),
        width: 100,
        sortable: true,
        value: (r) => r.parse_status,
        render: (_v, r) =>
          (r.parse_result || {}).ignored_at ? (
            <span className="badge">{t("page.email.ignored", "已忽略")}</span>
          ) : (
            r.parse_status
          ),
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
        width: 320,
        minWidth: 260,
        // block 截断：限宽换行（行高随内容），解析字段再长也顶不宽列
        truncate: "block",
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
        width: 90,
        // 行内只留「查看详情」：AI 建议 / 回复 / 生成业务草稿 / 确认解析都收进详情弹窗，
        // 快捷操作走右键菜单 —— 一排 5 个按钮看不过来，且「确认」脱离上下文没人看得懂
        render: (_v, r) => (
          <span className="row-actions" onClick={(e) => e.stopPropagation()}>
            <button className="btn btn-sm" type="button" onClick={() => void openDetail(r)}>
              {t("page.email.detail_btn", "查看详情")}
            </button>
          </span>
        ),
      },
    ],
    [t, openDetail, tz],
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

  // 同步芯片文案 —— clock 驱动定时重算（running 每秒 / idle 30s）
  const elapsedSec =
    syncUi.phase === "running" && syncUi.startedAt ? Math.max(1, Math.floor((clock - syncUi.startedAt) / 1000)) : 0;
  const agoLabel = !lastSyncedAt
    ? ""
    : (() => {
        const diff = Math.max(0, clock - lastSyncedAt);
        if (diff < 60000) return t("page.email.just_now", "just now");
        if (diff < 3600000) return t("page.email.ago_min", "{n} 分钟前", { n: Math.floor(diff / 60000) });
        return t("page.email.ago_hour", "{n} 小时前", { n: Math.floor(diff / 3600000) });
      })();

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.email", "Email Review") }]}
        title={t("page.email.title", "Email Review")}
        subtitle={t("page.email.sub", "AI-parsed recaps awaiting confirmation.")}
        actions={<PageGuide pageKey="email_review" />}
      />
      <Toolbar
        right={
          <span className="email-toolbar-right">
            {syncUi.phase === "running" ? (
              <span className="sync-chip sync-chip-busy" role="status">
                <span className="sync-chip-spin" aria-hidden />
                {t("page.email.syncing_chip", "Syncing {folders}… {s}s", {
                  folders: (syncUi.folders || []).join("/"),
                  s: elapsedSec,
                })}
              </span>
            ) : syncUi.phase === "done" ? (
              <span className="sync-chip sync-chip-ok" role="status">
                {(syncUi.synced ?? 0) > 0
                  ? t("page.email.synced_chip", "Synced — {n} new", { n: syncUi.synced ?? 0 })
                  : t("page.email.synced_none", "Synced — no new mail")}
              </span>
            ) : syncUi.phase === "error" ? (
              <span className="sync-chip sync-chip-err" role="alert">
                {t("page.email.sync_error_chip", "Sync failed")}: {syncUi.error}
              </span>
            ) : agoLabel ? (
              <span className="sync-chip" role="status">
                {t("page.email.last_synced", "Last sync {when}", { when: agoLabel })}
              </span>
            ) : null}
            <span className="hint">
              {t("page.email.count", "{n} messages", { n: sorted.length })}
              {rows.length !== sorted.length ? ` / ${rows.length}` : ""}
            </span>
          </span>
        }
      >
        <button
          className="btn btn-primary"
          type="button"
          disabled={syncUi.phase === "running"}
          onClick={() => sync().catch((ex) => toast.error(msgOf(ex, t("page.email.sync_fail", "Sync failed"))))}
        >
          {syncUi.phase === "running"
            ? t("page.email.sync_btn_busy", "同步中…")
            : m365
              ? t("page.email.sync_btn_m365", "同步 Microsoft 365 邮件")
              : t("page.email.sync_btn", "Sync demo inbox")}
        </button>
        <label className="email-sync-opt">
          {t("page.email.days", "天数")}
          <select
            value={syncDays}
            onChange={(e) => {
              const days = Number(e.target.value) as 7 | 14 | 30;
              setSyncDays(days);
              saveSyncPrefs({ days, count: syncCount, folders: syncFolders });
            }}
          >
            {DAY_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {t("page.email.days_opt", "{n} 天", { n: d })}
              </option>
            ))}
          </select>
        </label>
        <label className="email-sync-opt">
          {t("page.email.limit", "条数")}
          <select
            value={syncCount}
            onChange={(e) => {
              const count = Number(e.target.value) as 200 | 500 | 1000;
              setSyncCount(count);
              saveSyncPrefs({ days: syncDays, count, folders: syncFolders });
            }}
          >
            {COUNT_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => {
            setFoldersDraft(syncFolders);
            setFoldersOpen(true);
          }}
        >
          {t("page.email.folders_btn", "文件夹")} ({syncFolders.length})
        </button>
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
        {statusChip("ignored", t("page.email.filter_ignored", "已忽略"))}
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
      {/* 置信度说明与邮箱账户面板已移除（用户反馈占高度无用）；
          账户由同步按钮自动 ensure 创建，无需常驻展示 */}
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
            rowClassName={(r) => (newIds.has(r.id) ? "grid-row-new" : undefined)}
            onRowClick={(r) => void openDetail(r)}
            onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
            onSortChange={onSortChange}
            storageKey="email_review_grid"
            // 客户端分页：邮件一屏放不下（48+ 行），按页浏览；换 Tab/筛选自动回第一页
            pageSize={25}
            emptyText={t("page.email.empty_folder", "No messages in this folder.")}
          />
        </StateView>
        <ContextMenu controller={rowCtx} items={menuItems} />
      </div>

      {/* 同步文件夹勾选 —— 原工具栏 details 弹层改 modal：弹层挂在 overflow-x:auto 的
          工具栏里会把 overflow-y 也顶成 auto，右缘冒出上下滚动条、滚动才看到弹层 */}
      <RecordModal
        open={foldersOpen}
        title={t("page.email.folders_btn", "文件夹")}
        onClose={() => setFoldersOpen(false)}
        canDelete={false}
        onSave={() => {
          setSyncFolders(foldersDraft);
          saveSyncPrefs({ days: syncDays, count: syncCount, folders: foldersDraft });
          setFoldersOpen(false);
        }}
      >
        <div className="email-folders-list">
          {folderList.map((f) => (
            // check-row：复用站内复选行样式（压过 .record-modal-body label 的纵向 grid 布局）
            <label key={f.key} className="check-row">
              <input
                type="checkbox"
                checked={foldersDraft.includes(f.key)}
                onChange={(e) =>
                  setFoldersDraft((prev) =>
                    e.target.checked ? [...prev, f.key] : prev.filter((k) => k !== f.key),
                  )
                }
              />
              {f.parent_key ? `└ ${f.display_name}` : f.display_name}
            </label>
          ))}
        </div>
        {/* 草稿式：勾选只改 foldersDraft，页脚「保存」才写回同步参数，「取消」丢弃
            （RecordModal 的 U5 未保存守卫会先弹「有未保存的修改」确认） */}
        <p className="row-actions">
          <button
            className="btn btn-sm"
            type="button"
            onClick={() => setFoldersDraft(folderList.map((f) => f.key))}
          >
            {t("common.select_all", "全选")}
          </button>
          <button className="btn btn-sm" type="button" onClick={() => setFoldersDraft([])}>
            {t("common.clear", "清空")}
          </button>
        </p>
      </RecordModal>

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
                <strong>{detail.sent_at ? formatInTz(detail.sent_at, tz) : "—"}</strong>
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
            {/* 处理建议区（Request XIX-B）：邮件先出；可疑业务邮件 pending → AI 识别 → 对应动作 */}
            {(() => {
              const storedType = msgEmailType(detail);
              const sugRec = sug.phase === "done" ? sug.rec : null;
              const aiType = sugRec ? sugRec.email_type || storedType : storedType;
              // AI 结论驱动：仅 recommendation=apply 给落单动作 —— review/reply 收起，防错类型落单
              const showApply = sugRec ? sugRec.recommendation === "apply" && !sugRec.already_applied : true;
              const isReview = detail.parse_status === "review";
              const applyLabel = APPLY_LABEL_KEYS[aiType];
              return (
                <div className="email-sug">
                  <div className="email-sug-head">
                    <h4>{t("page.email.sug_title", "处理建议")}</h4>
                    {sug.phase === "pending" ? (
                      <span className="badge badge-info" role="status">
                        <span className="sug-spin" aria-hidden="true" />
                        {t("page.email.sug_pending", "AI 正在识别这封邮件…")}
                      </span>
                    ) : sug.phase === "error" ? (
                      <span className="badge badge-fail" role="alert">
                        {t("page.email.sug_fail", "AI 识别失败 — 以下为规则建议")}
                      </span>
                    ) : sugRec && sugRec.source === "llm" ? (
                      <span className="badge badge-pass">{t("page.email.sug_ai", "AI 识别")}</span>
                    ) : (
                      <span className="badge">{t("page.email.sug_rule", "规则建议")}</span>
                    )}
                    {sug.phase !== "pending" ? (
                      <button
                        className="btn btn-sm"
                        type="button"
                        title={t("page.email.ai_rec_hint", "让 AI 根据这封邮件推荐下一步操作（落单 / 回复），仅建议不自动执行")}
                        onClick={() => void runSuggest(detail)}
                      >
                        ✦ {t("page.email.sug_rerun", "重新识别")}
                      </button>
                    ) : null}
                    {sug.phase === "error" ? (
                      <button
                        className="btn btn-sm"
                        type="button"
                        onClick={() => void runSuggest(detail)}
                      >
                        {t("page.email.sug_retry", "重试")}
                      </button>
                    ) : null}
                  </div>
                  {sug.phase === "pending" ? (
                    <p className="muted sug-pending-line">
                      {t("page.email.sug_pending_hint", "正在识别类型与下一步动作 — 邮件内容可先阅读…")}
                    </p>
                  ) : null}
                  {sugRec ? (
                    <p className="sug-reason">
                      {sugRec.email_type && sugRec.email_type !== storedType
                        ? `${t("page.email.sug_type_diff", "AI 识别为 {ai}（规则：{rule}）", {
                            ai: sugRec.email_type,
                            rule: storedType || "—",
                          })} · `
                        : ""}
                      {t("page.email.sug_reason", "推荐理由：{reason}", { reason: sugRec.reason })}
                      {sugRec.already_applied
                        ? ` · ${t("page.email.sug_applied", "已生成业务草稿 — 建议回复确认。")}`
                        : ""}
                    </p>
                  ) : null}
                  {/* 识别中不给动作按钮 —— 处理结束后才显示对应动作（用户规格） */}
                  {sug.phase !== "pending" ? (
                  <p className="row-actions">
                    {showApply && ["fixture_recap", "recap", "nor"].includes(aiType) ? (
                      <button className="btn btn-primary btn-sm" type="button" onClick={applyToEstimate}>
                        {t("page.email.fill_estimate", "填入航次计算")}
                      </button>
                    ) : null}
                    {showApply && isReview ? (
                      <button
                        className="btn btn-sm btn-primary"
                        type="button"
                        title={t(
                          "page.email.apply_hint",
                          "用解析字段一键生成业务草稿（估算 / 装卸时间 / NOR 停租时间等），会创建真实记录",
                        )}
                        onClick={() => {
                          const m = detail;
                          setDetailFor(null);
                          setDetail(null);
                          requestApply(m);
                        }}
                      >
                        {applyLabel
                          ? t(applyLabel[0], applyLabel[1])
                          : t("page.email.apply_btn", "Create draft")}
                      </button>
                    ) : null}
                    {isReview ? (
                      <>
                        <button
                          className="btn btn-sm"
                          type="button"
                          title={t(
                            "page.email.ignore_hint",
                            "忽略本次建议；勾选记住后，同一发件人不会再被识别为此类型。",
                          )}
                          onClick={() => {
                            const m = detail;
                            setDetailFor(null);
                            setDetail(null);
                            setIgnoreRemember(true);
                            setIgnoreFor(m);
                          }}
                        >
                          {t("page.email.ignore_btn", "忽略")}
                        </button>
                        <button
                          className="btn btn-sm"
                          type="button"
                          title={t("page.email.confirm_hint", "采纳解析结果，该邮件移出复核队列")}
                          onClick={() => {
                            const id = detail.id;
                            setDetailFor(null);
                            setDetail(null);
                            void confirm(id).catch((ex) => toast.error(msgOf(ex, t("page.email.confirm_fail", "Confirm failed"))));
                          }}
                        >
                          {t("page.email.confirm_btn", "确认解析")}
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
                  ) : null}
                </div>
              );
            })()}
            <p className="row-actions">
              <button
                className="btn btn-sm"
                type="button"
                title={t("page.email.archive_entity_hint", "邮件正文将作为附件（带版本）挂到所选记录下。")}
                onClick={() => {
                  const m = detail;
                  setDetailFor(null);
                  setDetail(null);
                  openArchive(m);
                }}
              >
                {t("page.email.archive_btn", "存档")}
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

      {/* 忽略并记住 —— 出复核队列；勾选记住则同源同类型后续降级为普通邮件 */}
      <RecordModal
        open={Boolean(ignoreFor)}
        title={t("page.email.ignore_title", "忽略建议")}
        onClose={() => setIgnoreFor(null)}
        onSave={() => {
          const m = ignoreFor;
          const remember = ignoreRemember;
          setIgnoreFor(null);
          if (m) void ignoreMsg(m, remember);
        }}
        canDelete={false}
        size="md"
      >
        <p>{t("page.email.ignore_hint", "忽略本次建议；勾选记住后，同一发件人不会再被识别为此类型。")}</p>
        <p className="muted">{ignoreFor?.subject || ignoreFor?.from_email || ""}</p>
        <label className="check-row">
          <input
            type="checkbox"
            checked={ignoreRemember}
            onChange={(e) => setIgnoreRemember(e.target.checked)}
          />
          {t("page.email.ignore_remember", "记住这次误判")}
        </label>
      </RecordModal>

      {/* 存档 —— 邮件正文作为附件（带版本）挂到所选业务记录 */}
      <RecordModal
        open={Boolean(archiveFor)}
        title={t("page.email.archive_title", "存档邮件到项目")}
        onClose={() => {
          setArchiveFor(null);
          setArchiveEntityId("");
        }}
        onSave={() => void saveArchive()}
        saving={archiveBusy}
        canDelete={false}
        size="md"
      >
        <p className="muted">{archiveFor?.subject || archiveFor?.from_email || ""}</p>
        <p className="hint">{t("page.email.archive_entity_hint", "邮件正文将作为附件（带版本）挂到所选记录下。")}</p>
        <div className="form-row">
          <label>
            {t("page.email.archive_entity", "目标项目")}
            <select
              value={archiveType}
              onChange={(e) => {
                setArchiveType(e.target.value);
                setArchiveEntityId("");
                void loadArchiveOptions(e.target.value);
              }}
            >
              {Object.keys(ARCHIVE_SOURCES).map((k) => (
                <option key={k} value={k}>
                  {t(`email.type.${k}`, k)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="form-row">
          <label>
            {t("page.email.archive_pick", "选择项目")}
            {archiveErr ? (
              <span className="state-view-error" role="alert">
                {archiveErr}
              </span>
            ) : (
              <select
                value={archiveEntityId}
                onChange={(e) => setArchiveEntityId(e.target.value)}
                disabled={archiveBusy || !archiveOptions.length}
              >
                <option value="">{t("page.email.archive_placeholder", "请选择…")}</option>
                {archiveOptions.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            )}
          </label>
        </div>
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
