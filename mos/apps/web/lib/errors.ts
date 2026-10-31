// D4 错误消息字典：后端稳定 code → 人话（IMOS FAQ 错误字典同构）。
// api 层统一走 apiError()，页面 toast.error(err.message) 即得可读文案；
// 未入典的 code 保留后端 message，兜底按 HTTP 状态翻译。语言跟随 marios_locale。

type Msg = { en: string; zh: string };

const DICT: Record<string, Msg> = {
  // 状态机 / 授权
  INVALID_STATE: {
    en: "This action is not allowed in the record's current status.",
    zh: "当前单据状态下不允许该操作。",
  },
  MODULE_NOT_LICENSED: {
    en: "This module is not licensed for your tenant — contact your administrator.",
    zh: "该模块未获授权，请联系管理员开通。",
  },
  FORBIDDEN: { en: "You don't have permission for this action.", zh: "没有执行该操作的权限。" },
  PERMISSION_DENIED: { en: "You don't have permission for this action.", zh: "没有执行该操作的权限。" },
  NOT_FOUND: { en: "Record not found.", zh: "记录不存在。" },
  UNAUTHORIZED: { en: "Session expired — please sign in again.", zh: "登录已过期，请重新登录。" },
  // 校验 / 并发
  VALIDATION_ERROR: { en: "Please check the highlighted fields.", zh: "请检查填写的内容。" },
  STALE_WRITE: {
    en: "This record was modified by someone else — refresh and retry.",
    zh: "记录已被他人修改，请刷新后重试。",
  },
  CONFLICT: { en: "The record changed — refresh and retry.", zh: "记录状态已变化，请刷新后重试。" },
  // 财务链
  APPROVAL_LIMIT: { en: "Amount exceeds your approval limit.", zh: "金额超出您的审批额度。" },
  PERIOD_CLOSED: { en: "This accounting period is closed.", zh: "该会计期间已关账。" },
  MACR_LOCKED: {
    en: "Posted accruals cannot be deleted — reverse or rebuild instead.",
    zh: "已过账计提不可删除，请冲销或重建。",
  },
  // 限流 / 平台
  RATE_LIMITED: { en: "Too many requests — try again shortly.", zh: "请求过于频繁，请稍后再试。" },
  TENANT_MISMATCH: { en: "Record belongs to another tenant.", zh: "记录属于其他租户。" },
  TENANT_NOT_FOUND: { en: "Target tenant not found.", zh: "目标租户不存在。" },
  // 运营链
  REPORT_SEQUENCE: {
    en: "Report out of sequence — a later stage was already submitted for this port call.",
    zh: "报文顺序错误：该挂靠已提交更晚阶段的报告。",
  },
  ALERT_BLOCKED: {
    en: "A blocking alert must be resolved before saving.",
    zh: "存在阻断级预警，处理后才能保存。",
  },
  INVALID_PORT_FUNCTION: { en: "Unknown port function code.", zh: "未知的港口功能代码。" },
  // 平台 / 集成
  INVALID_SCHEDULE_TYPE: { en: "Unsupported schedule type.", zh: "不支持的调度类型。" },
  INVALID_OUTPUT_FORMAT: { en: "Unsupported output format.", zh: "不支持的输出格式。" },
  EXPORT_FORMAT_UNSUPPORTED: { en: "Unsupported export format.", zh: "不支持的导出格式。" },
  BATCH_NOT_FOUND: { en: "Payment batch not found.", zh: "付款批次不存在。" },
  FIELD_NOT_PERMITTED: { en: "One or more fields are read-only for your role.", zh: "部分字段对当前角色只读。" },
  FIELD_PERM_EXISTS: { en: "This field permission already exists.", zh: "该字段权限规则已存在。" },
  UDF_EXISTS: { en: "This user field already exists for the entity.", zh: "该实体下已存在同名用户字段。" },
  UNKNOWN_ENTITY: { en: "Unknown entity for user fields.", zh: "未知的用户字段实体。" },
  // 镜像发票
  MIRROR_READONLY: {
    en: "Mirror invoices follow their source and cannot be edited directly.",
    zh: "镜像发票跟随源发票，不可直接编辑。",
  },
  MIRROR_EXISTS: { en: "A mirror invoice already exists.", zh: "镜像发票已存在。" },
  INTERCOMPANY_DISABLED: {
    en: "Intercompany mirroring is disabled (config flag).",
    zh: "公司间镜像功能未启用（配置标志）。",
  },
  NOT_MIRRORABLE: { en: "This invoice cannot be mirrored.", zh: "该发票不可镜像。" },
  // 任务中心（动作绑定 / 任务字段）
  UNKNOWN_ACTION: { en: "Unknown system action.", zh: "未知的系统动作。" },
  ACTION_ENTITY_REQUIRED: {
    en: "Pick the record this action belongs to.",
    zh: "请选择该动作对应的单据。",
  },
  ACTION_ENTITY_MISMATCH: {
    en: "This action applies to a different kind of record.",
    zh: "该动作适用于其他类型的单据。",
  },
  ACTION_ALREADY_DONE: {
    en: "That action is already finished on this record — there is nothing left to track.",
    zh: "该单据上的此动作已经完成，无需再跟踪。",
  },
  INVALID_ASSIGNEE: {
    en: "The assignee is not an active user of this tenant.",
    zh: "负责人不是本租户的有效用户。",
  },
  INVALID_PARENT: { en: "The parent record is invalid.", zh: "上级记录无效。" },
  INVALID_PRIORITY: { en: "Invalid priority.", zh: "优先级取值无效。" },
  INVALID_STATUS: { en: "Invalid status.", zh: "状态取值无效。" },
  INVALID_WEIGHT: { en: "Weight must be greater than zero.", zh: "权重必须大于零。" },
  INVALID_CODE: { en: "Code is required.", zh: "编码不能为空。" },
  DUPLICATE_CODE: { en: "This code is already in use.", zh: "该编码已被占用。" },
  EMPTY_COMMENT: { en: "Write something before posting.", zh: "请先填写内容再发送。" },
  ROLE_REQUIRED: {
    en: "Your role does not allow this action.",
    zh: "当前角色不允许该操作。",
  },
  UNKNOWN_TAB: { en: "Unknown view.", zh: "未知的视图。" },
  UNKNOWN_ENTITY_TYPE: {
    en: "This record type cannot be linked.",
    zh: "该记录类型不可关联。",
  },
  // 积分 / 会员
  INVALID_POINTS: { en: "Points must be a positive number.", zh: "积分必须为正数。" },
  // 连接器 / 集成
  UNKNOWN_CONNECTOR: { en: "Unknown connector type.", zh: "未知的连接器类型。" },
  CONNECTOR_UNHEALTHY: {
    en: "The connector health check did not pass.",
    zh: "连接器健康检查未通过。",
  },
  // 报表 / 设计器
  INVALID_QUERY_SPEC: { en: "The query specification is invalid.", zh: "查询规格无效。" },
  REPORT_NOT_FOUND: { en: "Report not found.", zh: "报表不存在。" },
  // 迁移 / 数据运维
  MIGRATION_FAILED: { en: "The migration job failed.", zh: "迁移任务失败。" },
  BACKUP_FAILED: { en: "The backup could not be created.", zh: "备份创建失败。" },
  // 凭据 / 密钥
  INVALID_SECRET: { en: "The secret reference is invalid.", zh: "密钥引用无效。" },
};

const BY_STATUS: Record<number, Msg> = {
  400: { en: "The request was rejected — check the values you entered.", zh: "请求被拒绝，请检查填写的内容。" },
  401: { en: "Session expired — please sign in again.", zh: "登录已过期，请重新登录。" },
  402: { en: "Payment is required for this action.", zh: "该操作需要先完成付款。" },
  403: { en: "Access denied for your role or module license.", zh: "当前角色或许可无权访问。" },
  404: { en: "Not found.", zh: "未找到对应记录。" },
  405: { en: "This action is not allowed here.", zh: "此处不允许该操作。" },
  406: { en: "The requested format is not acceptable.", zh: "不支持请求的数据格式。" },
  408: { en: "The request timed out — try again.", zh: "请求超时，请重试。" },
  409: { en: "The record changed — refresh and retry.", zh: "记录状态已变化，请刷新后重试。" },
  410: { en: "This record has been removed.", zh: "该记录已被删除。" },
  412: { en: "A precondition failed — refresh and retry.", zh: "前置条件不满足，请刷新后重试。" },
  413: { en: "The uploaded file is too large.", zh: "上传的文件过大。" },
  415: { en: "Unsupported file type.", zh: "不支持的文件类型。" },
  422: { en: "Validation failed — check the form.", zh: "校验失败，请检查表单。" },
  429: { en: "Too many requests — try again shortly.", zh: "请求过于频繁，请稍后再试。" },
  500: { en: "Server error — try again or contact support.", zh: "服务器错误，请重试或联系支持。" },
  501: { en: "This operation is not implemented yet.", zh: "该功能尚未实现。" },
  502: { en: "Upstream service error — try again shortly.", zh: "上游服务异常，请稍后重试。" },
  503: { en: "Service temporarily unavailable — try again shortly.", zh: "服务暂时不可用，请稍后重试。" },
  504: { en: "The server took too long to respond — try again.", zh: "服务器响应超时，请重试。" },
};

function currentLocale(): string {
  if (typeof window === "undefined") return "en";
  try {
    return localStorage.getItem("marios_locale") || "en";
  } catch {
    return "en";
  }
}

function pick(msg?: Msg): string | undefined {
  if (!msg) return undefined;
  return currentLocale().startsWith("zh") ? msg.zh : msg.en;
}

/** 后端 detail（string 或 {code,message}）→ 本地化人话；查不到原样返回。 */
export function humanizeDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object") {
    const d = detail as { code?: string; message?: string };
    if (d.code && DICT[d.code]) return pick(DICT[d.code]) ?? null;
    if (d.message) return d.message;
    if (d.code && d.code.startsWith("HTTP_")) {
      const n = Number(d.code.slice(5));
      if (BY_STATUS[n]) return pick(BY_STATUS[n]) ?? null;
    }
  }
  return null;
}

/** 未入典状态的兜底文案（不再把 "POST /api/v1/xxx failed" 抛给用户）。 */
const GENERIC: Msg = {
  en: "The operation failed — try again or contact support.",
  zh: "操作失败，请重试或联系支持。",
};

/**
 * 统一构造 API 错误：err.message 为人话，err.code / err.status / err.detail 保留原始信息。
 * 用法：`throw apiError(method, path, res.status, body)`
 */
export function apiError(method: string, path: string, status: number, body: unknown): Error {
  const detail = (body as { detail?: unknown } | null)?.detail;
  const code =
    detail && typeof detail === "object" ? (detail as { code?: string }).code : undefined;
  const message = humanizeDetail(detail) ?? pick(BY_STATUS[status]) ?? pick(GENERIC) ?? "Request failed.";
  const err: any = new Error(message);
  err.status = status;
  err.code = code ?? (BY_STATUS[status] ? `HTTP_${status}` : undefined);
  err.detail = detail;
  return err;
}

/**
 * 取错误的人话文案。
 *
 * 页面里请一律用 `toast.error(msgOf(err))`，**不要**用 `String(err)` ——
 * 后者会把 "Error: " 前缀和 "HTTP 500" 之类的原始串直接显示给用户。
 */
export function msgOf(err: unknown, fallback?: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err.trim()) return err;
  if (typeof err === "object" && err !== null) {
    const e = err as { message?: unknown; detail?: unknown };
    if (typeof e.message === "string" && e.message) return e.message;
    const d = humanizeDetail(e.detail);
    if (d) return d;
  }
  return fallback ?? pick(GENERIC) ?? "The operation failed — try again.";
}

/**
 * 「这个错误已经在别处处理过了」的**显式**标记（审计 P1-4 · 一致性门禁）。
 *
 * 以前到处写 `loadList().catch(() => undefined)` —— 看代码的人分不清
 * 两种情况：
 *
 *   a) `loadList()` 内部已经 `setErr(msgOf(ex))`，外面这层只是防止
 *      unhandled rejection；
 *   b) 错误被**真的吞掉**了，界面上一片"暂无数据"，用户完全不知道
 *      刚才那次取数失败了。
 *
 * (b) 正是 P1-4 的病灶。现在这种"已处理"必须写成 `.catch(handled)`，
 * 一眼可辨；而 `scripts/lint-consistency.mjs` 的 `silent-catch` 规则会
 * 把 `catch(() => …)` / `catch(() => undefined)` 全部判为违规 —— 新代码
 * 只能二选一：`.catch(handled)`（错误已在别处处理）或
 * `.catch((ex) => toast.error(msgOf(ex)))`（就地报错）。
 */
export const handled = (): undefined => undefined;
