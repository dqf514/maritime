import { redirect } from "next/navigation";

// 手册正文是静态文件 public/manual/index.html。Next（trailingSlash:false）
// 对目录不会自动补 index：裸 /manual 会先被 308 归一再落 404 ——
// 这里用路由把干净 URL /manual 转发到静态文件，同时保留 /manual/index.html 直链。
export default function ManualPage() {
  redirect("/manual/index.html");
}
