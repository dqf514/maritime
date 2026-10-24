// 预览 HTML 防御性净化 —— 后端渲染单据模板时 autoescape=False（后端修复中），
// 前端这一层做「去掉可执行内容」的兜底：即便模板正文或主数据里混入
// <script> / on*= / javascript:，也不进 iframe。
//
// 注意：这**不是**通用 HTML 消毒器（不解析 DOM、不修复畸形标记），
// 只是把常见的可执行载荷剔除掉；真正的隔离靠 iframe 的 sandbox 属性。

/** 移除 <script>/<style>…</style> 之外的主动内容标签及其正文。 */
const BLOCK_TAGS = ["script", "iframe", "object", "embed", "link", "meta", "base", "form"];

function stripTagBlocks(html: string): string {
  let out = html;
  for (const tag of BLOCK_TAGS) {
    const re = new RegExp(`<${tag}\\b[^>]*>[\\s\\S]*?<\\/${tag}\\s*>`, "gi");
    out = out.replace(re, "");
    // 自闭合写法
    out = out.replace(new RegExp(`<${tag}\\b[^>]*\\/?>`, "gi"), "");
  }
  return out;
}

/** 去掉行内事件处理器（onclick=… / onerror=… / …）。 */
function stripEventHandlers(html: string): string {
  return html.replace(/\son[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, "");
}

/** 去掉 javascript: / vbscript: / data:text/html 之类的可执行 URL。 */
function stripScriptUrls(html: string): string {
  return html.replace(
    /(href|src|action|formaction|xlink:href)\s*=\s*(?:"\s*(?:javascript|vbscript|data:text\/html)[^"]*"|'\s*(?:javascript|vbscript|data:text\/html)[^']*'|(?:javascript|vbscript|data:text\/html)[^\s>]*)/gi,
    "$1=\"#\"",
  );
}

/**
 * 把预览 HTML 净化成「只显示、不执行」的片段。
 * 保留版式所需的 <style>/CSS 与普通标签，剔除一切主动内容。
 */
export function stripActiveContent(html: string): string {
  if (!html) return "";
  let out = stripTagBlocks(html);
  out = stripEventHandlers(out);
  out = stripScriptUrls(out);
  return out;
}
