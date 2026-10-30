// 对手方主数据的受控词表 —— 类型走 reference dataset（counterparty_types），
// 这里只放写死的集合与历史值归一。纯数据模块（不依赖 i18n）：
// 渲染处用参照表标签或 t(`page.parties.xxx.${code}`, code) 解析。

// 生命周期（Active/Inactive，与 sanctions_status 正交）
export const PARTY_STATUS = ["active", "inactive"] as const;

export const SANCTIONS_STATUS = ["clear", "review", "blocked"] as const;

/**
 * 历史「多角色」取值（复数角色名）→ 现行类型码（counterparty_types 参照表）。
 *
 * 对手方的多角色（同时是船东 + 经纪人）现在统一存放在类型字段里，代码取自
 * counterparty_types 参照表（charterer / owner / broker / agent / shipper /
 * consignee / supplier / operator / other）。早期版本另存了一份复数角色码，
 * 读出来时按本表归一，避免同一家公司在列表页和详情页显示成两套取值。
 */
export const LEGACY_TYPE_ALIASES: Record<string, string> = {
  agents: "agent",
  brokers: "broker",
  charterers: "charterer",
  owners: "owner",
  company_info: "other",
  misc: "other",
};

/** 把历史多角色码归一到现行类型码；无法归一的原样保留（不丢数据）。 */
export function normalizePartyTypes(codes: readonly (string | null | undefined)[] | null | undefined): string[] {
  const out: string[] = [];
  for (const raw of codes ?? []) {
    const code = String(raw ?? "").trim();
    if (!code) continue;
    const mapped = LEGACY_TYPE_ALIASES[code] ?? code;
    if (!out.includes(mapped)) out.push(mapped);
  }
  return out;
}
