"""claude_client 测试：
- 纯单元（无网络）：Usage.cost_usd 组合、from_response 缺字段兜底、_text_of 过滤。
- 单元（假 Anthropic 桩，无网络）：complete / complete_vision / stream_complete 的请求构造 + 响应解析 + 图片 base64。
- 集成（真实 API，缺 anthropic/.env/网络则跳过）：complete 返回 pong。
"""
import base64

import pytest

from claude_client import ClaudeClient, LLMResult, Usage


# ---------------- Usage（纯单元）----------------
def test_cost_usd_combinations():
    assert Usage().cost_usd() == 0.0
    assert abs(Usage(input_tokens=1_000_000, output_tokens=1_000_000).cost_usd() - 30.0) < 1e-6
    # cache_read ~0.1x input($0.5/M)，cache_write ~1.25x($6.25/M)
    assert abs(Usage(cache_read_input_tokens=1_000_000).cost_usd() - 0.5) < 1e-6
    assert abs(Usage(cache_creation_input_tokens=1_000_000).cost_usd() - 6.25) < 1e-6


def test_cost_usd_follows_model():
    """计价跟随实际模型，不再写死 Opus 价；未知/空模型回退默认（Opus，不低估）。"""
    toks = dict(input_tokens=1_000_000, output_tokens=1_000_000)
    opus = Usage(**toks, model="claude-opus-4-8").cost_usd()
    assert opus == 30.0  # 5 + 25
    assert Usage(**toks, model="claude-sonnet-5").cost_usd() == 18.0  # 3 + 15 = 0.6x Opus
    assert Usage(**toks, model="claude-haiku-4-5").cost_usd() == 6.0  # 1 + 5
    # 带 -日期 后缀也能前缀匹配
    assert Usage(**toks, model="claude-sonnet-4-5-20250929").cost_usd() == 18.0
    # 未知/空模型 → 回退默认 Opus 价
    assert Usage(**toks, model="").cost_usd() == opus
    assert Usage(**toks, model="claude-brand-new-9").cost_usd() == opus


def test_usage_from_response_missing_fields():
    class U:  # 只有部分字段（模仿 SDK usage 对象缺 cache 字段）
        input_tokens = 10
        output_tokens = 5

    u = Usage.from_response(U())
    assert u.input_tokens == 10 and u.output_tokens == 5
    assert u.cache_read_input_tokens == 0 and u.cache_creation_input_tokens == 0

    class U2:  # 字段为 None
        input_tokens = None

    assert Usage.from_response(U2()).input_tokens == 0


# ---------------- 假 Anthropic 桩 ----------------
class _Blk:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _U:
    input_tokens = 12
    output_tokens = 7
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Msg:
    def __init__(self):
        self.content = [_Blk("thinking", None), _Blk("text", "pong"), _Blk("text", "!")]
        self.usage = _U()
        self.stop_reason = "end_turn"
        self.model = "claude-opus-4-8"


class _Stream:
    def __init__(self, msg):
        self._msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._msg


class _Messages:
    def __init__(self, msg):
        self.calls = []
        self._msg = msg

    def create(self, **kw):
        self.calls.append(("create", kw))
        return self._msg

    def stream(self, **kw):
        self.calls.append(("stream", kw))
        return _Stream(self._msg)


class _FakeAnthropic:
    def __init__(self):
        self.messages = _Messages(_Msg())


def _client_with_fake():
    pytest.importorskip("anthropic")  # 构造真实 client 需要包（不联网）
    c = ClaudeClient("dummy-key")
    fake = _FakeAnthropic()
    c._c = fake
    return c, fake


def test_text_of_filters_thinking():
    c, _ = _client_with_fake()
    assert c._text_of(_Msg()) == "pong!"  # thinking 块被过滤，text 块拼接


def test_complete_request_and_parse():
    c, fake = _client_with_fake()
    r = c.complete(system="SYS", user_text="hi", max_tokens=123)
    assert isinstance(r, LLMResult)
    assert r.text == "pong!" and r.stop_reason == "end_turn" and r.model == "claude-opus-4-8"
    assert r.usage.cost_usd() > 0
    _, kw = fake.messages.calls[-1]
    assert kw["model"] == "claude-opus-4-8"
    assert kw["thinking"] == {"type": "adaptive"}  # 无 budget_tokens
    assert "budget_tokens" not in kw.get("thinking", {})
    assert kw["system"] == "SYS" and kw["max_tokens"] == 123
    assert kw["messages"] == [{"role": "user", "content": "hi"}]


def test_complete_vision_encodes_images():
    c, fake = _client_with_fake()
    img = b"\x89PNG\r\n\x1a\nFAKEBYTES"
    r = c.complete_vision(system="S", user_text="看图", images_png=[img])
    assert r.text == "pong!"
    _, kw = fake.messages.calls[-1]
    content = kw["messages"][0]["content"]
    # 图片块在前、文本块在最后
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(content[0]["source"]["data"]) == img  # base64 可还原
    assert content[-1] == {"type": "text", "text": "看图"}
    assert kw["thinking"] == {"type": "adaptive"}


def test_stream_complete_uses_stream():
    c, fake = _client_with_fake()
    r = c.stream_complete(system="S", user_text="长输出", max_tokens=64000)
    assert r.text == "pong!"
    kind, kw = fake.messages.calls[-1]
    assert kind == "stream"  # 走流式而非 create
    assert kw["max_tokens"] == 64000 and kw["thinking"] == {"type": "adaptive"}


# ---------------- 集成（真实 API）----------------
def test_integration_complete_ping():
    pytest.importorskip("anthropic")
    try:
        c = ClaudeClient.from_env()
    except Exception as e:
        pytest.skip(f"缺少配置: {e}")
    try:
        r = c.complete(
            system="You are terse. Reply with exactly one lowercase word, no punctuation.",
            user_text="Reply with the single word: pong",
            max_tokens=64,
        )
    except Exception as e:
        pytest.skip(f"Anthropic API 不可用: {e}")
    assert "pong" in r.text.lower()
    assert r.usage.cost_usd() > 0
    # 断言响应模型跟随配置（CLAUDE_MODEL），不写死具体版本——换模型时这条不该失败。
    assert r.model.startswith(c._model)
