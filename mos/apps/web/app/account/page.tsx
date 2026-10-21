import { redirect } from "next/navigation";

// 账户中心入口：账户设置统一收口在 Account security（/account 之前无 index，直达 404）
export default function AccountIndex() {
  redirect("/account/security");
}
