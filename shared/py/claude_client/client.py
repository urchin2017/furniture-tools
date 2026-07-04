"""服务端 Claude 封装。

- 统一服务端 key（销售无 key，全走这把）。
- model=`claude-opus-4-8`，**adaptive thinking**（`thinking={"type":"adaptive"}`，不要 `budget_tokens`）。
- system prompt 来自各 skill 的 SKILL.md prose。
- 三个入口：
    complete        —— 纯文本判断步骤（翻译未命中词条、报价定尺寸的文字判断）
    complete_vision —— 视觉兜底（扫描页、低置信尺寸、图纸对比核对）；最贵，仅在分流判必要时调
    stream_complete —— 长输出（整套翻译/报告），流式避免 HTTP 超时
- 每次调用返回 LLMResult，含 usage；调用方把 `result.usage.cost_usd()` 累加写进 jobs 行。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

# 默认/Opus 4.8 定价（USD / 1M tokens）；未知模型回退到这组（偏保守，不低估）。
# _IN_PER_M / _OUT_PER_M 保留为默认单价（回归测试锁定）。
_IN_PER_M = 5.0
_OUT_PER_M = 25.0
_CACHE_READ_PER_M = 0.5  # ~0.1x input（历史常量；实际按输入价 0.1x 派生）
_CACHE_WRITE_PER_M = 6.25  # ~1.25x input（5m TTL）

# 各模型 (输入, 输出) 单价（USD / 1M tokens）。缓存读=0.1×输入、写=1.25×输入 由此派生。
# 引入期优惠（如 Sonnet 5 $2/$10 至 2026-08-31）不入表，按标准价估算（偏保守）。
_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def _rates_for(model: str) -> tuple[float, float]:
    """按模型 id 前缀查 (输入, 输出) 单价（容忍 -日期 后缀）；未知模型回退默认（Opus）价，不低估。"""
    for prefix, rates in _MODEL_PRICES.items():
        if model.startswith(prefix):
            return rates
    return (_IN_PER_M, _OUT_PER_M)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    model: str = ""  # 计价按此模型；空 → 回退默认（Opus）价

    def cost_usd(self) -> float:
        in_m, out_m = _rates_for(self.model)
        return round(
            self.input_tokens / 1e6 * in_m
            + self.output_tokens / 1e6 * out_m
            + self.cache_read_input_tokens / 1e6 * (in_m * 0.1)
            + self.cache_creation_input_tokens / 1e6 * (in_m * 1.25),
            6,
        )

    @classmethod
    def from_response(cls, u, model: str = "") -> "Usage":
        def g(name: str) -> int:
            return int(getattr(u, name, 0) or 0)

        return cls(
            input_tokens=g("input_tokens"),
            output_tokens=g("output_tokens"),
            cache_read_input_tokens=g("cache_read_input_tokens"),
            cache_creation_input_tokens=g("cache_creation_input_tokens"),
            model=model or "",
        )


@dataclass
class LLMResult:
    text: str
    usage: Usage
    stop_reason: str
    model: str


class ClaudeClient:
    # max_retries 默认 4：本机 TLS 抖动（SSL WRONG_VERSION_NUMBER），SDK 自带的
    # 指数退避重试要多给几次机会，否则长管线里一次抖动就废掉整个任务。
    def __init__(self, api_key: str, *, model: str = "claude-opus-4-8", max_retries: int = 4):
        import anthropic

        self._c = anthropic.Anthropic(api_key=api_key, max_retries=max_retries)
        self._model = model

    @staticmethod
    def _text_of(message) -> str:
        return "".join(
            b.text for b in message.content if getattr(b, "type", None) == "text"
        )

    def _result(self, message) -> LLMResult:
        return LLMResult(
            text=self._text_of(message),
            usage=Usage.from_response(message.usage, message.model),
            stop_reason=message.stop_reason or "",
            model=message.model,
        )

    def complete(self, *, system: str, user_text: str, max_tokens: int = 16000) -> LLMResult:
        msg = self._c.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user_text}],
        )
        return self._result(msg)

    def complete_vision(
        self,
        *,
        system: str,
        user_text: str,
        images_png: list[bytes],
        max_tokens: int = 16000,
        media_type: str = "image/png",
    ) -> LLMResult:
        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(img).decode("ascii"),
                },
            }
            for img in images_png
        ]
        content.append({"type": "text", "text": user_text})
        msg = self._c.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            # system（五条铁律+看图协议，长）在多页看图里逐页复用 → 打 ephemeral 缓存：
            # 首页写缓存、后续页命中读（5min TTL），省重复输入 token（cache_read≈0.1×输入）。
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        )
        return self._result(msg)

    def stream_complete(self, *, system: str, user_text: str, max_tokens: int = 64000) -> LLMResult:
        with self._c.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            msg = stream.get_final_message()
        return self._result(msg)

    @classmethod
    def from_env(cls) -> "ClaudeClient":
        from settings import Settings

        s = Settings.from_env()
        return cls(s.anthropic_api_key, model=s.claude_model)
