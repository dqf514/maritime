"""XML 解析安全（XXE / billion laughs）回归。

**背景**：``POST /api/v1/forms/submit`` 直接用标准库 ``xml.etree.ElementTree``
解析**客户端提交**的表单 XML。标准库的 expat 会展开 DTD 里的内部实体，
因此一份 ``<!DOCTYPE>`` + ``<!ENTITY>`` 的载荷可以做：

- **实体膨胀（billion laughs）**：几百字节的输入展开成 GB 级内存 → 进程 OOM；
- **外部实体（XXE）**：在允许外部实体解析的部署里读取本地文件 / 探测内网。

修法：改用 ``defusedxml``（``forbid_dtd=True``），DTD 与实体一律拒绝。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# 经典 billion laughs：9 层实体，每层 10 个引用 → 10^9 个字符。
_BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
 <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
 <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
 <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
 <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
 <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<Form formType="noon_report"><Field name="x">&lol9;</Field></Form>"""

# 外部实体：读取本地文件（经典 XXE）
_XXE_FILE = """<?xml version="1.0"?>
<!DOCTYPE data [
 <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<Form formType="noon_report"><Field name="x">&xxe;</Field></Form>"""

# 外部实体 + SYSTEM 协议指向内网（SSRF 变体）
_XXE_HTTP = """<?xml version="1.0"?>
<!DOCTYPE data [
 <!ENTITY xxe SYSTEM "http://169.254.169.254/latest/meta-data/">
]>
<Form formType="noon_report"><Field name="x">&xxe;</Field></Form>"""


def _post(client: TestClient, auth_headers: dict, xml: str):
    return client.post("/api/v1/forms/submit", json={"xml": xml}, headers=auth_headers)


def test_forms_submit_rejects_billion_laughs(client: TestClient, auth_headers: dict):
    """实体膨胀载荷必须被 400 拒掉，且**不能**把内存打爆。"""
    r = _post(client, auth_headers, _BILLION_LAUGHS)
    assert r.status_code == 400, r.text
    assert "FORM_XML_UNSAFE" in r.text or "FORM_XML_PARSE" in r.text


def test_forms_submit_rejects_xxe_file_entity(client: TestClient, auth_headers: dict):
    """外部实体（读本地文件）必须被 400 拒掉。"""
    r = _post(client, auth_headers, _XXE_FILE)
    assert r.status_code == 400, r.text
    assert "FORM_XML_UNSAFE" in r.text or "FORM_XML_PARSE" in r.text


def test_forms_submit_rejects_xxe_http_entity(client: TestClient, auth_headers: dict):
    """外部实体指向内网元数据服务必须被 400 拒掉（不会发起任何出网请求）。"""
    r = _post(client, auth_headers, _XXE_HTTP)
    assert r.status_code == 400, r.text
    assert "FORM_XML_UNSAFE" in r.text or "FORM_XML_PARSE" in r.text


def test_forms_submit_still_accepts_plain_xml(client: TestClient, auth_headers: dict):
    """正常表单 XML 不受影响 —— 走到业务校验（缺 formType / 未知表单），不是 400 解析错。"""
    plain = '<Form formType="noon_report"><Field name="mt_per_day">12.5</Field></Form>'
    r = _post(client, auth_headers, plain)
    # 合法 XML → 不会命中 FORM_XML_PARSE / FORM_XML_UNSAFE
    assert "FORM_XML_PARSE" not in r.text
    assert "FORM_XML_UNSAFE" not in r.text


def test_forms_submit_still_rejects_malformed_xml(client: TestClient, auth_headers: dict):
    """坏 XML 仍然是 400 + FORM_XML_PARSE（不能因为换了库把解析错变成 500）。"""
    r = _post(client, auth_headers, "<Form><unclosed></Form>")
    assert r.status_code == 400, r.text
    assert "FORM_XML_PARSE" in r.text
