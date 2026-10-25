"""HTML → 纯文本转换（stdlib only）。

Graph API 的 body.content 通常是 HTML 片段（Outlook 会带 mso 样式垃圾）。
入库前统一转纯文本，classify / 规则解析器就不至于把标签吞进字段里。
纯文本输入必须幂等返回 —— 回填迁移会对历史行重复执行。
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "li", "main", "nav", "ol", "p",
    "pre", "section", "table", "tr", "ul",
}
_BR_HR = {"br", "hr"}
#: 块级起始标签的占位符：相邻块（<p>a</p><p>b</p>）不该挤出空行，
#: 起始只放占位符、结束才真正换行，收尾时把占位符清掉。
_MARK = "\x00"
_CELL_TAGS = {"td", "th"}
_SKIP_TAGS = {"style", "script", "head", "title"}
_TAG = re.compile(r"</?[a-zA-Z][^<>]*>")
_BLANK_RUN = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: N802
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _BR_HR:
            self._out.append("\n")
        elif tag in _BLOCK_TAGS:
            self._out.append(_MARK)
        elif tag in _CELL_TAGS:
            self._out.append("\t")

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: N802
        # <br/> <hr/> 等自闭合形式
        if tag in _SKIP_TAGS or self._skip_depth:
            return
        if tag in _BR_HR or tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_endtag(self, tag: str) -> None:  # noqa: N802
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:  # noqa: N802
        if self._skip_depth:
            return
        self._out.append(data)

    def text(self) -> str:
        return "".join(self._out)


def html_to_text(raw: str | None) -> str:
    """把 HTML 片段转成干净的纯文本；纯文本/None 幂等返回。

    - 先 unescape 一次，处理 `&lt;span&gt;` 这种双重转义的输入；
    - 含标签才走 HTMLParser；块级标签（p/div/br/tr/td…）产出换行/制表符；
    - style/script 内容丢弃；链接 <a href> 只留文字；
    - 收尾规范化：行尾空白、连续空行（>2 个换行折叠为 1 个空行）。
    """
    if not raw:
        return ""
    text = html.unescape(raw)
    if "<" not in text:
        # 纯文本（可能含 &amp; 等实体，已还原）——只做收尾规范化
        return _normalize(text)
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
        out = parser.text().replace(_MARK, "")
    except Exception:  # pragma: no cover - 解析器兜底：极端畸形 HTML 直接剥标签
        out = _TAG.sub("\n", text)
    return _normalize(out)


def _normalize(s: str) -> str:
    lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out = "\n".join(lines)
    out = _BLANK_RUN.sub("\n\n", out)
    return out.strip()
