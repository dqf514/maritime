"""PDF 引擎的线程亲和性回归测试。

背景：Playwright 的 **sync API 绑定 greenlet** —— 浏览器在哪个线程启动，就只能在那条
线程里调用。FastAPI 的同步路由跑在 anyio 线程池里、线程会轮换，早期实现把浏览器单例
直接放在模块级全局，跨线程复用会抛 ``Cannot switch to a different thread``，表现为
「导出 PDF」约一半概率 503 PDF_ENGINE_UNAVAILABLE。

修复：所有 PDF 渲染集中到一条专属线程（``marios-pdf``），浏览器也只在那里创建/关闭。

这些用例用假浏览器复现 greenlet 的跨线程报错，不需要真的装 Chromium。
"""

from __future__ import annotations

import threading

from app.services import doc_engine


class _FakePage:
    def set_content(self, html, wait_until=None):  # noqa: ANN001, D102
        return None

    def wait_for_timeout(self, ms):  # noqa: ANN001, D102
        return None

    def pdf(self, **kwargs):  # noqa: ANN003, D102
        return b"%PDF-1.4 fake"

    def close(self):  # noqa: D102
        return None


class _FakeBrowser:
    def new_page(self):  # noqa: D102
        return _FakePage()

    def is_connected(self):  # noqa: D102
        return True

    def close(self):  # noqa: D102
        return None


def _install_fake_browser(monkeypatch):
    """装一个「跨线程即报错」的假浏览器 —— 复刻 playwright greenlet 的行为。"""
    owner: dict[str, str] = {}

    def fake_get_browser():
        name = threading.current_thread().name
        if owner.get("thread") and owner["thread"] != name:
            raise RuntimeError(
                f"Cannot switch to a different thread\n\tCurrent: {owner['thread']}\n\tTarget: {name}"
            )
        owner["thread"] = name
        return _FakeBrowser()

    monkeypatch.setattr(doc_engine, "_get_browser", fake_get_browser)
    return owner


def test_pdf_render_runs_on_the_dedicated_worker_thread(monkeypatch):
    """渲染必须离开调用方线程，落到专属的 PDF 线程上。"""
    owner = _install_fake_browser(monkeypatch)

    doc_engine.html_to_pdf("<html><body>x</body></html>", wait_ms=0)

    assert owner["thread"].startswith("marios-pdf"), owner
    assert owner["thread"] != threading.current_thread().name


def test_concurrent_pdf_renders_do_not_fail(monkeypatch):
    """并发导出 PDF 不得出现跨线程失败（回归：约一半 503）。"""
    owner = _install_fake_browser(monkeypatch)
    results: list[object] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            out = doc_engine.html_to_pdf("<html><body>x</body></html>", wait_ms=0)
        except Exception as exc:  # noqa: BLE001
            out = exc
        with lock:
            results.append(out)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, failures
    assert len(results) == 12
    assert all(r == b"%PDF-1.4 fake" for r in results)
    # 所有渲染都在同一条线程上 —— 浏览器单例因此始终可用
    assert owner["thread"].startswith("marios-pdf")


def test_html_to_pdf_wraps_engine_failures(monkeypatch):
    """渲染失败时统一抛 PDFEngineUnavailable（上层回落 HTML），不把底层异常漏给调用方。"""

    def boom(*args, **kwargs):  # noqa: ANN002, ANN003, D102
        raise RuntimeError("chromium exploded")

    monkeypatch.setattr(doc_engine, "_render_pdf", boom)
    try:
        doc_engine.html_to_pdf("<html></html>", wait_ms=0)
    except doc_engine.PDFEngineUnavailable as exc:
        assert "chromium exploded" in str(exc)
    else:
        raise AssertionError("expected PDFEngineUnavailable")
