// 组织架构唯一入口 = /admin/org（269 行完整版）。
// 本旧路径保留为永久重定向，防止书签与外链失效。

import { redirect } from "next/navigation";

export default function OrgAliasPage() {
  redirect("/admin/org");
}
