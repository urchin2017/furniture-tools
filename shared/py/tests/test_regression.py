"""回归测试：把踩过的坑/关键决策锁死，未来改动若破坏它们会立即失败。无网络。"""
import pytest


def test_supabase_package_not_shadowed():
    """本地包故意叫 supabase_client，绝不能遮蔽 pip 包 supabase。

    坑：若本地包叫 `supabase`，模块内 `from supabase import create_client` 会指向自己 → 崩。
    """
    import supabase  # 真实 pip 包

    assert hasattr(supabase, "create_client")
    import supabase_client

    assert supabase_client is not supabase
    from supabase_client.client import make_service_client

    assert callable(make_service_client)


def test_opus_48_pricing_constants_pinned():
    """Opus 4.8 定价常量锁死（$5/$25 per 1M；cache_read 0.1x、cache_write 1.25x）。"""
    from claude_client import client as cc

    assert cc._IN_PER_M == 5.0
    assert cc._OUT_PER_M == 25.0
    assert cc._CACHE_READ_PER_M == 0.5
    assert cc._CACHE_WRITE_PER_M == 6.25


def test_load_map_pagination_boundary():
    """PostgREST 单次 1000 行上限：恰好 1000 / 1001 行都必须取全（回归 前端曾漏 243 条的同类坑）。"""
    from glossary import GlossaryClient
    from test_glossary import _FakeSupabase, _rows  # 复用假桩（pytest 按 basename 导入）

    for n in (999, 1000, 1001, 2001):
        triples = [(f"t{i:05d}", f"v{i}", "") for i in range(n)]
        m = GlossaryClient(_FakeSupabase(_rows(*triples))).load_map("ja", "zh")
        assert len(m) == n, f"{n} 行应全取回，实得 {len(m)}"


def test_adaptive_thinking_never_sends_budget_tokens():
    """三个入口都必须发 adaptive thinking、绝不带 budget_tokens（Opus 4.8 会 400）。"""
    pytest.importorskip("anthropic")
    from claude_client import ClaudeClient

    class _Blk:
        type = "text"
        text = "ok"

    class _U:
        input_tokens = output_tokens = cache_read_input_tokens = cache_creation_input_tokens = 0

    class _Msg:
        content = [_Blk()]
        usage = _U()
        stop_reason = "end_turn"
        model = "claude-opus-4-8"

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return _Msg()

    class _Msgs:
        def __init__(self):
            self.kws = []

        def create(self, **kw):
            self.kws.append(kw)
            return _Msg()

        def stream(self, **kw):
            self.kws.append(kw)
            return _Ctx()

    class _Fake:
        def __init__(self):
            self.messages = _Msgs()

    c = ClaudeClient("dummy")
    c._c = _Fake()
    c.complete(system="s", user_text="u")
    c.complete_vision(system="s", user_text="u", images_png=[b"x"])
    c.stream_complete(system="s", user_text="u")

    assert len(c._c.messages.kws) == 3
    for kw in c._c.messages.kws:
        assert kw["thinking"] == {"type": "adaptive"}
        assert "budget_tokens" not in kw["thinking"]
        assert kw["model"] == "claude-opus-4-8"
