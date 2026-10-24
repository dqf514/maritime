"""安全响应头中间件（P2 · 安全与部署组）。

审计发现：整套系统**一个安全响应头都没下发** —— 没有 CSP、没有 nosniff、
没有 Referrer-Policy，HSTS 也只在反代层偶尔手写一条。

这里补齐，但必须避免两件事：

1. **不能把 CSP 一刀切地套到所有响应上**。FastAPI 自带的 ``/docs``（Swagger UI）
   与 ``/redoc`` 要从 jsDelivr 取 JS/CSS；文档引擎的 HTML 预览是**租户可编辑
   的内容**，必须禁止脚本（存储型 XSS 的最后一道闸）。
2. **HSTS 只能在 HTTPS 响应上下发**。在明文 HTTP 上发 HSTS 会让浏览器把该
   域名的后续访问强制升级成 HTTPS —— 本地开发（http://localhost:8000）会直接
   变成"连不上"。

所以规则按**响应类型**和**协议**分别决定：

- 全部响应：``X-Content-Type-Options`` · ``Referrer-Policy`` ·
  ``X-Frame-Options`` · ``Permissions-Policy``
- HTML 响应（文档预览 / Swagger UI）：按路径区分 CSP
- JSON 响应：``default-src 'none'``（JSON 本来就不是文档，等于零成本）
- 仅当本次请求确实是 HTTPS（或 ``X-Forwarded-Proto: https``）时才发 HSTS
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: JSON / 通用响应：不允许加载任何资源，也不允许被嵌套进 frame
_CSP_NON_DOC = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

#: 文档引擎的 HTML 预览：租户可编辑 → 彻底禁脚本，但保留内联样式与图片
_CSP_DOC_PREVIEW = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; "
    "font-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
    "script-src 'none'; object-src 'none'"
)

#: Swagger UI / ReDoc：需要 jsDelivr 的 CSS + JS
_CSP_SWAGGER = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' data: https://cdn.jsdelivr.net; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class SecurityHeadersMiddleware:
    """给每个响应补上安全响应头。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""
        is_https = scope.get("scheme") == "https"
        if not is_https:
            # 反代后面：uvicorn 开了 --proxy-headers 时 scheme 已是 https；
            # 没开的话这里退回到 X-Forwarded-Proto 判定。
            for key, value in scope.get("headers", []):
                if key.lower() == b"x-forwarded-proto" and value.lower() == b"https":
                    is_https = True
                    break

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                content_type = ""
                for key, value in headers:
                    if key.lower() == b"content-type":
                        content_type = value.decode("latin-1").lower()
                        break

                def add(name: bytes, value: bytes) -> None:
                    if name.lower() not in existing:
                        headers.append((name, value))

                add(b"x-content-type-options", b"nosniff")
                add(b"referrer-policy", b"strict-origin-when-cross-origin")
                add(b"x-frame-options", b"SAMEORIGIN")
                add(b"permissions-policy", _PERMISSIONS_POLICY.encode())

                if is_https:
                    # 只在真正的 HTTPS 上发 —— 明文下发会把浏览器锁死在 HTTPS
                    add(
                        b"strict-transport-security",
                        b"max-age=31536000; includeSubDomains",
                    )

                if content_type.startswith("text/html"):
                    if path.startswith("/docs") or path.startswith("/redoc"):
                        csp = _CSP_SWAGGER
                    else:
                        csp = _CSP_DOC_PREVIEW
                else:
                    csp = _CSP_NON_DOC
                add(b"content-security-policy", csp.encode())

                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
