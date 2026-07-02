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

# Claude Opus 4.8 定价（USD / 1M tokens）
_IN_PER_M = 5.0
_OUT_PER_M = 25.0
_CACHE_READ_PER_M = 0.5  # ~0.1x input
_CACHE_WRITE_PER_M = 6.25  # ~1.25x input（5m TTL）


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def cost_usd(self) -> float:
        return round(
            self.input_tokens / 1e6 * _IN_PER_M
            + self.output_tokens / 1e6 * _OUT_PER_M
            + self.cache_read_input_tokens / 1e6 * _CACHE_READ_PER_M
            + self.cache_creation_input_tokens / 1e6 * _CACHE_WRITE_PER_M,
            6,
        )

    @classmethod
    def from_response(cls, u) -> "Usage":
        def g(name: str) -> int:
            return int(getattr(u, name, 0) or 0)

        return cls(
            input_tokens=g("input_tokens"),
            output_tokens=g("output_tokens"),
            cache_read_input_tokens=g("cache_read_input_tokens"),
            cache_creation_input_tokens=g("cache_creation_input_tokens"),
        )


@dataclass
class LLMResult:
    text: str
    usage: Usage
    stop_reason: str
    model: str


class ClaudeClient:
    def __init__(self, api_key: str, *, model: str = "claude-opus-4-8", max_retries: int = 2):
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
            usage=Usage.from_response(message.usage),
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
            system=system,
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
