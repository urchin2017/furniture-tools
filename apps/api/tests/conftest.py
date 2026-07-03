import os
import pathlib
import sys
import uuid

# 把 apps/api 加入 sys.path，好 `import app.xxx`（app/config.py 会再把 shared/py 接上）。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
# shared/py 在 sys.path 上才能 import settings.load_env（app.config 也靠它）。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "shared" / "py"))

# 离线单测在 import app 时会触发 get_settings()，需要这几个环境变量存在（值不必真实——
# Supabase/Claude 都被假桩/依赖覆盖替掉了）。本地开发若仓库根有真 .env 则真实值优先，
# 云端/CI 没有 .env 时用占位值兜底，让纯离线套件无需任何密钥即可跑通。
from settings import load_env as _load_env  # noqa: E402

_load_env()  # 真 .env 若存在，其值先进 os.environ，下面的占位不会覆盖
for _k, _v in {
    "NEXT_PUBLIC_SUPABASE_URL": "https://placeholder.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_placeholder",
    "ANTHROPIC_API_KEY": "sk-ant-placeholder",
}.items():
    os.environ.setdefault(_k, _v)

import pytest


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """假 Supabase 查询链：够用来测 jobs 表的 insert/select/update + eq/order/limit。"""

    def __init__(self, table_rows: list[dict]):
        self._rows = table_rows
        self._op = None
        self._payload = None
        self._filters: dict = {}
        self._order = None
        self._limit = None

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def select(self, *_a, **_k):
        self._op = self._op or "select"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._op == "insert":
            row = {
                "id": str(uuid.uuid4()),
                "status": "queued",
                "progress": 0,
                "output_files": None,
                "error": None,
                "created_at": "2026-07-02T00:00:00Z",
                **self._payload,
            }
            self._rows.append(row)
            return _Result([row])

        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters.items())]
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
            return _Result(matched)

        if self._order:
            col, desc = self._order
            matched = sorted(matched, key=lambda r: r.get(col, ""), reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        return _Result(matched)


class FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict]] = {}

    def table(self, name):
        return _Query(self._tables.setdefault(name, []))


@pytest.fixture
def fake_supabase():
    return FakeSupabase()


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """auth.authenticate 有 5 分钟 token 缓存——不清会让同名 token 跨测试串角色。"""
    from app.auth import _token_cache

    _token_cache.clear()
    yield
    _token_cache.clear()
