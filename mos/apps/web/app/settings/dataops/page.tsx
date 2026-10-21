import { redirect } from "next/navigation";

// 数据运维入口：index 缺失时直达 /settings/dataops 会 404 —— 默认落到备份页
export default function DataOpsIndex() {
  redirect("/settings/dataops/backup");
}
