"""/api/quote/analyze 路由测试：TestClient + 假 storage + dependency override（无网络）。

覆盖「判断」步骤的路由行为：下载图纸→分页判位图/矢量→返回处理计划；
含鉴权、越权路径、坏 PDF、跳过全部页等边界/异常。
"""
from __future__ import annotations

import fitz
from fastapi.testclient import TestClient

from app.deps import CurrentUser, get_current_user, get_supabase
from app.main import app


# ---------- 造图纸：矢量页（画线）vs 位图页（嵌大图）----------

def _vector_pdf(pages: int = 1) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        p = doc.new_page(width=842, height=595)
        p.draw_rect(fitz.Rect(100, 100, 500, 300))
        p.insert_text((550, 400), f"款号：V{i + 1:02d}\nW1200 D850 H725", fontsize=7)
    return doc.tobytes()


def _bitmap_pdf() -> bytes:
    """一页：嵌一张 600×600 位图（无矢量线）→ detect_raster 判为光栅/位图页。"""
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 600))
    pix.set_rect(pix.irect, (240, 240, 240))
    page.insert_image(fitz.Rect(40, 40, 700, 540), stream=pix.tobytes("png"))
    page.insert_text((60, 560), "款号：R01", fontsize=8)
    return doc.tobytes()


class _FakeBucket:
    def __init__(self, files):
        self._files = files

    def download(self, key):
        return self._files[key]


class _FakeStorage:
    def __init__(self, files):
        self._files = files

    def from_(self, bucket):
        return _FakeBucket(self._files)


class _FakeSupabase:
    def __init__(self, files):
        self.storage = _FakeStorage(files)


def _client(files):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="user-1", email="a@b.com", role="sales"
    )
    app.dependency_overrides[get_supabase] = lambda: _FakeSupabase(files)
    return TestClient(app)


def _post(client, pdf_path="user-1/quote/x/d.pdf", **body):
    return client.post("/api/quote/analyze", json={"pdf_path": pdf_path, **body})


def test_analyze_vector_page_plans_local():
    files = {"user-1/quote/x/d.pdf": _vector_pdf(1)}
    try:
        r = _post(_client(files), skip_pages=[], vision_mode="auto")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["total"] == 1
        pg = body["pages"][0]
        assert pg["kind"] == "vector" and pg["path"] == "local"
        assert body["summary"]["ai_pages"] == [] and body["summary"]["local_pages"] == [1]
        assert pg["codes"] == ["V01"]
    finally:
        app.dependency_overrides.clear()


def test_analyze_bitmap_page_plans_vision():
    files = {"user-1/quote/x/d.pdf": _bitmap_pdf()}
    try:
        r = _post(_client(files), skip_pages=[], vision_mode="auto")
        assert r.status_code == 200, r.text
        body = r.json()
        pg = body["pages"][0]
        assert pg["kind"] == "bitmap" and pg["path"] == "vision", "位图页→AI 看图"
        assert body["summary"]["ai_pages"] == [1] and body["summary"]["bitmap_pages"] == [1]
    finally:
        app.dependency_overrides.clear()


def test_analyze_always_mode_forces_vision_even_on_vector():
    files = {"user-1/quote/x/d.pdf": _vector_pdf(1)}
    try:
        r = _post(_client(files), skip_pages=[], vision_mode="always")
        assert r.json()["pages"][0]["path"] == "vision"
    finally:
        app.dependency_overrides.clear()


def test_analyze_skip_all_pages_boundary():
    files = {"user-1/quote/x/d.pdf": _vector_pdf(2)}
    try:
        r = _post(_client(files), skip_pages=[1, 2], vision_mode="auto")
        assert r.status_code == 200
        assert r.json()["summary"]["total"] == 0 and r.json()["pages"] == []
    finally:
        app.dependency_overrides.clear()


def test_analyze_rejects_foreign_path():
    files = {"user-2/quote/x/d.pdf": _vector_pdf(1)}
    try:
        r = _post(_client(files), pdf_path="user-2/quote/x/d.pdf")
        assert r.status_code == 400 and "本人" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_analyze_corrupt_pdf_returns_400():
    files = {"user-1/quote/x/d.pdf": b"not a pdf at all"}
    try:
        r = _post(_client(files), skip_pages=[])
        assert r.status_code == 400 and "分析失败" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_analyze_requires_auth():
    app.dependency_overrides.clear()
    r = TestClient(app).post("/api/quote/analyze", json={"pdf_path": "user-1/quote/x/d.pdf"})
    assert r.status_code == 401
