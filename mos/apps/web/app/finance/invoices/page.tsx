// 发票列表唯一入口 = /finance 的「Invoices」标签页（列表页是壳，标签自取数）。
// /finance/invoices 保留为永久重定向，防止书签与外链失效。

import { redirect } from "next/navigation";

export default function InvoicesAlias() {
  redirect("/finance?tab=invoices");
}
