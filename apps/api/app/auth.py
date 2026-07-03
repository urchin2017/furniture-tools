"""校验 Supabase JWT → user_id / email / role。

不用本地 JWT secret 验签，而是拿前端传来的 access token 直接问 Supabase Auth
（`auth.get_user(token)`）：token 无效/过期会抛 `AuthError`。这样不用管新旧 key
格式（sb_publishable_/sb_secret_）对应的签名算法，也不用在 .env 里再存一份
JWT secret。

⚠ 这一步是**每个请求都要走的出网调用**，在本机 TLS 抖动的网络下是高频故障点
（实测 ConnectTimeout 会让浏览器看到无 CORS 头的 500 → 显示为 Failed to fetch）。
对策：① 网络层错误走 netretry 重试；② 校验通过的 token 短期缓存（5 分钟，远短于
token 有效期 1 小时），把轮询等高频请求的出网次数降到近零；③ 重试仍失败时抛
503 HTTPException（走正常响应路径，带 CORS 头，前端能看到有意义的报错）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException, status
from supabase import AuthError, Client

from app.config import get_settings  # noqa: F401  (触发 shared/py 加入 sys.path，须在 netretry 之前)

from netretry import with_retry

_CACHE_TTL = 300.0  # 秒。token 本身有效期约 1h，缓存 5min 安全
_CACHE_MAX = 512
# token -> (过期时刻, user_id, email, role)
_token_cache: dict[str, tuple[float, str, str | None, str]] = {}


def _cache_get(token: str) -> tuple[str, str | None, str] | None:
    hit = _token_cache.get(token)
    if hit and hit[0] > time.monotonic():
        return hit[1], hit[2], hit[3]
    _token_cache.pop(token, None)
    return None


def _cache_put(token: str, user_id: str, email: str | None, role: str) -> None:
    if len(_token_cache) >= _CACHE_MAX:  # 简单防涨：满了整体清掉重来
        _token_cache.clear()
    _token_cache[token] = (time.monotonic() + _CACHE_TTL, user_id, email, role)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    role: str


def verify_token(supabase: Client, token: str) -> tuple[str, str | None]:
    """向 Supabase Auth 校验 access token，返回 (user_id, email)。无效则抛 401。"""
    try:
        resp = with_retry(lambda: supabase.auth.get_user(token), desc="Supabase Auth 校验登录态")
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的登录凭证"
        ) from exc
    except RuntimeError as exc:  # netretry 重试耗尽（网络抖动）
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="鉴权服务暂时不可达（网络抖动），请稍后重试",
        ) from exc
    if resp is None or resp.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的登录凭证"
        )
    return resp.user.id, resp.user.email


def fetch_role(supabase: Client, user_id: str) -> str:
    """查 profiles.role；查不到时默认 sales（新用户触发器建 profile 有极短延迟窗口）。"""
    try:
        rows = with_retry(
            lambda: supabase.table("profiles").select("role").eq("id", user_id).limit(1).execute().data,
            desc="查 profiles.role",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="鉴权服务暂时不可达（网络抖动），请稍后重试",
        ) from exc
    return rows[0]["role"] if rows else "sales"


def authenticate(supabase: Client, token: str) -> CurrentUser:
    """verify_token + fetch_role，带 5 分钟结果缓存（高频轮询不再每次出网）。"""
    cached = _cache_get(token)
    if cached:
        return CurrentUser(id=cached[0], email=cached[1], role=cached[2])
    user_id, email = verify_token(supabase, token)
    role = fetch_role(supabase, user_id)
    _cache_put(token, user_id, email, role)
    return CurrentUser(id=user_id, email=email, role=role)
