"""uploads 中转路由测试：TestClient + 假 storage + dependency override（无网络）。

背景：浏览器直传 Supabase 大文件在本机慢上行/TLS 抖动下会断（实测 17MB 必挂），
改走 浏览器→本地API→服务端重试传 storage。这里锁死该路由的关键行为。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.deps import CurrentUser, get_current_user, get_supabase
from app.main import app


class _FakeStorage:
    def __init__(self, fail_times: int = 0):
        self.files: dict[str, bytes] = {}
        self.fail_times = fail_times  # 跨 from_() 句柄共享：前 N 次 upload 抛网络错

    def from_(self, bucket):
        return _FakeBucket(self)


class _FakeBucket:
    def __init__(self, storage: _FakeStorage):
        self._s = storage

    def upload(self, key, data, file_options=None):
        if self._s.fail_times > 0:
            self._s.fail_times -= 1
            raise ConnectionError("SSL flake")
        self._s.files[key] = data


class _FakeSupabase:
    def __init__(self, fail_times: int = 0):
        self.storage = _FakeStorage(fail_times)


def _client(fake):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="user-1", email="a@b.com", role="sales"
    )
    app.dependency_overrides[get_supabase] = lambda: fake
    return TestClient(app)


def _cleanup():
    app.dependency_overrides.clear()


def test_upload_success_key_under_user_prefix():
    fake = _FakeSupabase()
    try:
        resp = _client(fake).post(
            "/api/uploads",
            files={"file": ("図面（中文） .pdf", b"%PDF-fake", "application/pdf")},
            data={"purpose": "quote"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["path"].startswith("user-1/quote/"), "key 必须落在本人前缀下（RLS 口径）"
        assert body["path"].endswith(".pdf") and body["size"] == len(b"%PDF-fake")
        # 非 ASCII 文件名被清洗，key 仍合法
        assert all(ord(c) < 128 for c in body["path"])
        assert body["path"] in fake.storage.files
    finally:
        _cleanup()


def test_upload_rejects_oversize_and_empty_and_bad_purpose():
    fake = _FakeSupabase()
    try:
        c = _client(fake)
        big = b"x" * (50 * 1024 * 1024 + 1)
        assert c.post("/api/uploads", files={"file": ("a.pdf", big, "application/pdf")}).status_code == 413
        assert c.post("/api/uploads", files={"file": ("a.pdf", b"", "application/pdf")}).status_code == 400
        assert (
            c.post(
                "/api/uploads",
                files={"file": ("a.pdf", b"x", "application/pdf")},
                data={"purpose": "../evil"},
            ).status_code
            == 400
        )
    finally:
        _cleanup()


def test_upload_retries_transient_storage_failures(monkeypatch):
    import app.routers.uploads as uploads_mod

    monkeypatch.setattr(uploads_mod.time, "sleep", lambda *_: None)  # 不真等
    fake = _FakeSupabase(fail_times=2)  # 前两次挂、第三次成功 → 重试要兜住
    try:
        resp = _client(fake).post(
            "/api/uploads", files={"file": ("a.pdf", b"x", "application/pdf")}
        )
        assert resp.status_code == 201
    finally:
        _cleanup()


def test_upload_requires_auth():
    # 不 override get_current_user：缺 Authorization 头必须 401
    app.dependency_overrides.clear()
    resp = TestClient(app).post(
        "/api/uploads", files={"file": ("a.pdf", b"x", "application/pdf")}
    )
    assert resp.status_code == 401
