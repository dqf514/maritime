"""html_to_text —— HTML 邮件正文转纯文本的单测。"""
from __future__ import annotations

from app.services.html_to_text import html_to_text


def test_none_and_empty():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_plain_text_idempotent():
    s = "MV DEMO WAVE / SGSIN to NLRTM\nLaycan 10-15 Nov 2026"
    assert html_to_text(s) == s
    # 幂等：二次转换结果不变
    assert html_to_text(html_to_text(s)) == s


def test_block_tags_become_newlines():
    out = html_to_text("<p>Vessel: MV DEMO</p><p>Port: SGSIN</p>")
    assert out == "Vessel: MV DEMO\nPort: SGSIN"
    assert "<" not in out


def test_br_and_div():
    out = html_to_text("<div>line1<br>line2</div>")
    assert "line1" in out and "line2" in out
    assert out.index("line1") < out.index("line2")


def test_mso_outlook_garbage_stripped():
    raw = (
        '<html><head><style>.MsoNormal{mso-style-unhide:no;}</style></head>'
        '<body lang=EN-US><div class=MsoNormal><span style=\'font-size:11.0pt\'>'
        "Firm offer MV DEMO WAVE</span></div></body></html>"
    )
    out = html_to_text(raw)
    assert out == "Firm offer MV DEMO WAVE"
    assert "mso" not in out.lower()
    assert "font-size" not in out


def test_double_escaped_tags():
    # &lt;span&gt;Firm offer&lt;/span&gt; —— unescape 后应按标签处理
    out = html_to_text("&lt;span&gt;Firm offer&lt;/span&gt;")
    assert out == "Firm offer"


def test_entities_decoded():
    assert html_to_text("AT&amp;T &amp; cargo") == "AT&T & cargo"
    assert html_to_text("rate&nbsp;is 12.5") == "rate\xa0is 12.5"


def test_table_cells_tabs():
    out = html_to_text("<table><tr><td>Vessel</td><td>MV DEMO</td></tr></table>")
    assert "Vessel" in out and "MV DEMO" in out


def test_anchor_keeps_text_only():
    out = html_to_text('<p>See <a href="https://example.com/x">the recap</a> please</p>')
    assert out == "See the recap please"
    assert "https://example.com" not in out


def test_blank_lines_collapsed():
    out = html_to_text("<p>a</p><div></div><div></div><div></div><p>b</p>")
    assert "\n\n\n" not in out


def test_inline_span_keeps_text():
    out = html_to_text("<p>NOR tendered at <b>08:00</b> LT</p>")
    assert out == "NOR tendered at 08:00 LT"


def test_script_dropped():
    out = html_to_text("<p>hello</p><script>alert(1)</script><p>world</p>")
    assert "alert" not in out
    assert out == "hello\nworld"


def test_table_rows_newline():
    out = html_to_text("<table><tr><td>a</td></tr><tr><td>b</td></tr></table>")
    assert "a" in out and "b" in out
