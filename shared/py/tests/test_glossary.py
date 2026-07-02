"""glossary 测试：
- 单元（假 Supabase 桩，无网络）：_norm 归一化、lookup 命中/未命中/domain、load_map 分页取全(>1000)、
  lookup_batch 分块(>200)+去重。
- 集成（真实 Supabase，缺 .env/网络则跳过）：load_map/lookup 一致。
"""
import pytest

from glossary import GlossaryClient
from glossary.client import _norm


# ---------------- 假 Supabase 桩（模仿 PostgREST 查询链） ----------------
class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self._filters = {}
        self._in = None
        self._range = None
        self._limit = None
        self._order = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._in = (col, list(vals))
        return self

    def order(self, col, **k):
        self._order = col
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters.items())]
        if self._in:
            col, vals = self._in
            s = set(vals)
            rows = [r for r in rows if r.get(col) in s]
        if self._order:
            rows = sorted(rows, key=lambda r: r.get(self._order, ""))
        if self._range:
            a, b = self._range
            rows = rows[a : b + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Result(rows)


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _Query(list(self._rows))


def _rows(*triples):
    """(source_term, target_term, domain) → glossary 行（ja→zh）。"""
    return [
        {
            "id": f"id{i}",
            "source_lang": "ja",
            "target_lang": "zh",
            "source_term": st,
            "target_term": tt,
            "domain": dm,
        }
        for i, (st, tt, dm) in enumerate(triples)
    ]


# ---------------- _norm ----------------
def test_norm():
    assert _norm("  壁面 ") == "壁面"
    assert _norm(None) == ""
    # NFC：分解形 が(か+ ゙) 归一到合成形
    assert _norm("が") == _norm("が")


# ---------------- lookup ----------------
def test_lookup_hit_miss_and_domain():
    sb = _FakeSupabase(_rows(("壁面", "墙面", ""), ("床", "地板", "材料")))
    g = GlossaryClient(sb)

    hit = g.lookup("  壁面 ", "ja", "zh")  # 带空白 → _norm 后命中
    assert hit is not None and hit.target_term == "墙面"

    assert g.lookup("天井", "ja", "zh") is None  # 未命中
    assert g.lookup("床", "ja", "zh", domain="材料").target_term == "地板"  # domain 过滤命中
    assert g.lookup("床", "ja", "zh", domain="金物") is None  # domain 不符 → 未命中


# ---------------- load_map 分页 ----------------
def test_load_map_paginates_over_1000():
    triples = [(f"term{i:05d}", f"译{i}", "") for i in range(1500)]
    g = GlossaryClient(_FakeSupabase(_rows(*triples)))
    m = g.load_map("ja", "zh")
    assert len(m) == 1500  # 证明翻过了 1000 行上限（多页取全）
    assert m["term00042"] == "译42"


def test_load_map_empty():
    assert GlossaryClient(_FakeSupabase([])).load_map("ja", "zh") == {}


# ---------------- lookup_batch 分块 + 去重 ----------------
def test_lookup_batch_chunk_and_dedup():
    # 250 条（>200 触发分块）+ 一个重复 source_term 不同 domain（应去重取一条）
    triples = [(f"t{i:04d}", f"v{i}", "") for i in range(250)]
    triples.append(("t0000", "v0-alt", "材料"))  # 与 t0000 撞键
    g = GlossaryClient(_FakeSupabase(_rows(*triples)))

    want = [f"t{i:04d}" for i in range(250)] + ["缺失项"]
    hits = g.lookup_batch(want, "ja", "zh")
    assert len(hits) == 250  # 250 命中；"缺失项"不在结果里
    assert "缺失项" not in hits
    assert hits["t0000"].source_term == "t0000"  # 撞键只保留一条


def test_lookup_batch_empty_input():
    assert GlossaryClient(_FakeSupabase(_rows(("壁面", "墙面", "")))).lookup_batch([], "ja", "zh") == {}


# ---------------- 集成（真实 Supabase）----------------
def test_integration_load_map_lookup_consistent():
    pytest.importorskip("supabase")
    try:
        from settings import Settings
        from supabase_client import make_service_client

        s = Settings.from_env()
    except Exception as e:
        pytest.skip(f"缺少配置: {e}")
    g = GlossaryClient(make_service_client(s.supabase_url, s.supabase_service_role_key))
    try:
        m = g.load_map("ja", "zh")
    except Exception as e:
        pytest.skip(f"Supabase 连接不可用: {e}")
    assert len(m) > 100
    term = next(iter(m))
    assert g.lookup(term, "ja", "zh").target_term == m[term]
