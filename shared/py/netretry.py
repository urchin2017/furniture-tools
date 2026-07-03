"""网络重试小工具。

本机网络有历史性 TLS 抖动（httpx.ConnectError: SSL WRONG_VERSION_NUMBER /
SSLEOFError，curl 也要 --retry），长任务里几十次 Supabase/Claude 请求只要一次
抖动就会整体失败——所有出网调用都应包上 with_retry。

只重试网络层错误（httpx 传输错误/OSError 系），不重试 API 逻辑错误
（4xx/RLS 拒绝重试也不会变对，白等几秒还掩盖真错误）。
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")

# ConnectError/SSL错误/超时/断流都在 httpx.TransportError 下；OSError 覆盖裸 socket/ssl 报错
RETRYABLE = (httpx.TransportError, OSError, ConnectionError, TimeoutError)


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 2.0,
    desc: str = "",
) -> T:
    """跑 fn()，网络层错误按线性退避重试（2s/4s/6s…），其余异常原样抛。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except RETRYABLE as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(base_delay * (i + 1))
    raise RuntimeError(f"网络重试 {attempts} 次仍失败{('：' + desc) if desc else ''}") from last
