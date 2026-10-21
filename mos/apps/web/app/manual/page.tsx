import { headers } from "next/headers";
import { redirect } from "next/navigation";

// 手册正文是静态文件：中文 public/manual/index.html、英文 public/manual/en.html。
// Next（trailingSlash:false）对目录不会自动补 index：裸 /manual 会先被 308 归一再落 404 ——
// 这里用路由把干净 URL /manual 转发到静态文件，并按 Accept-Language 自动选语言
// （两版顶部导航也有手动 中文 | English 切换）。
export default async function ManualPage() {
  const al = ((await headers()).get("accept-language") || "").toLowerCase();
  const zhIdx = al.indexOf("zh");
  const enIdx = al.indexOf("en");
  const zh = zhIdx >= 0 && (enIdx < 0 || zhIdx <= enIdx);
  redirect(zh ? "/manual/index.html" : "/manual/en.html");
}
