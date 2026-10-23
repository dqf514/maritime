// 对手方主数据的受控词表 —— IMOS Counterparty 口径。
// 纯数据模块（不依赖 i18n）：渲染处用 t(`page.parties.xxx.${code}`, code) 解析标签。
// type 走 reference dataset（counterparty_types），这里只放写死的集合。

// IMOS Address Type：一家公司常同时是 Agents + Brokers + Charterers + Owners + Company Info + Misc
export const PARTY_ROLES = [
  "agents",
  "brokers",
  "charterers",
  "owners",
  "company_info",
  "misc",
] as const;

// IMOS lifecycle（Active/Inactive，与 sanctions_status 正交）
export const PARTY_STATUS = ["active", "inactive"] as const;

export const SANCTIONS_STATUS = ["clear", "review", "blocked"] as const;
