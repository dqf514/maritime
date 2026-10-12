// IMOS A5 双重 UI 归并 — 旧路径 → 规范入口 深链对照表。
// 各旧路径在 app/ 下保留同名 stub 页面执行实际跳转；本表作文档/校验单一来源。

export const REDIRECTS: Record<string, string> = {
  // 1. 航次详情唯一入口 = workspace（Phase 2 面板式工作台）
  "/operations/voyages/{id}": "/operations/voyages/{id}/workspace",
  // 2. 组织架构唯一入口 = /admin/org
  "/admin/organization": "/admin/org",
  // 4. 租约列表唯一入口 = /charters（?type=tc|coa 页签切换）
  "/charters/tc": "/charters?type=tc",
  "/charters/coa": "/charters?type=coa",
};
