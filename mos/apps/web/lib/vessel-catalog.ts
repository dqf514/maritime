// 船舶主数据的受控词表 —— IMOS Vessel Detail 口径。
// 纯数据模块（不依赖 i18n）：渲染处用 t(`page.vessels.xxx.${code}`, code) 解析标签。

// IMOS 对齐的业务分组（母船队 / 船管 / 拖驳 / 灵便重吊）
export const FLEET_GROUPS = [
  "mother_vessel",
  "ship_management",
  "tugs_barges",
  "flf",
  "other",
] as const;

// IMOS Vessel Detail 的 Ownership（TC / Own / Not Specified）；空串 = 未指定
export const OWNERSHIP_OPTIONS = ["", "tc", "own", "not_specified"] as const;

// 常用航线区（datalist 建议值，可自由输入 —— 与 IMOS 的自由文本口径一致）
export const TRADE_AREAS = ["ASIA", "EURO", "USEC", "USG", "USWC", "TRANSATL", "ME", "AFR", "GLOBAL"];

// 常用船级社
export const CLASS_SOCIETIES = ["ABS", "DNV", "LR", "BV", "NK", "RINA", "CCS", "KR", "GL"];
