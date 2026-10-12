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
};

const BY_STATUS: Record<number, Msg> = {
  401: { en: "Session expired — please sign in again.", zh: "登录已过期，请重新登录。" },
  403: { en: "Access denied for your role or module license.", zh: "当前角色或许可无权访问。" },
  404: { en: "Not found.", zh: "未找到对应记录。" },
  409: { en: "The record changed — refresh and retry.", zh: "记录状态已变化，请刷新后重试。" },
  422: { en: "Validation failed — check the form.", zh: "校验失败，请检查表单。" },
  429: { en: "Too many requests — try again shortly.", zh: "请求过于频繁，请稍后再试。" },
  500: { en: "Server error — try again or contact support.", zh: "服务器错误，请重试或联系支持。" },
};

function currentLocale(): string {
  if (typeof window === "undefined") return "en";
  try {
    return localStorage.getItem("marios_locale") || "en";
  } catch {
    return "en";
  }
}

function pick(msg: Msg): string {
  return currentLocale().startsWith("zh") ? msg.zh : msg.en;
}

/** 后端 detail（string 或 {code,message}）→ 本地化人话；查不到原样返回。 */
export function humanizeDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object") {
    const d = detail as { code?: string; message?: string };
    if (d.code && DICT[d.code]) return pick(DICT[d.code]);
    if (d.message) return d.message;
    if (d.code && d.code.startsWith("HTTP_")) {
      const n = Number(d.code.slice(5));
      if (BY_STATUS[n]) return pick(BY_STATUS[n]);
    }
  }
  return null;
}

/**
 * 统一构造 API 错误：err.message 为人话，err.code / err.status / err.detail 保留原始信息。
 * 用法：`throw apiError(method, path, res.status, body)`
 */
export function apiError(method: string, path: string, status: number, body: unknown): Error {
  const detail = (body as { detail?: unknown } | null)?.detail;
  const code =
    detail && typeof detail === "object" ? (detail as { code?: string }).code : undefined;
  const message = humanizeDetail(detail) ?? pick(BY_STATUS[status]) ?? `${method} ${path} failed`;
  const err: any = new Error(message);
  err.status = status;
  err.code = code ?? (BY_STATUS[status] ? `HTTP_${status}` : undefined);
  err.detail = detail;
  return err;
}
