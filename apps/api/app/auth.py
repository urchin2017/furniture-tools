"""校验 Supabase JWT → user_id / email / role。

不用本地 JWT secret 验签，而是拿前端传来的 access token 直接问 Supabase Auth
（`auth.get_user(token)`）：token 无效/过期会抛 `AuthError`。这样不用管新旧 key
格式（sb_publishable_/sb_secret_）对应的签名算法，也不用在 .env 里再存一份
JWT secret。
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from supabase import AuthError, Client


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    role: str


def verify_token(supabase: Client, token: str) -> tuple[str, str | None]:
    """向 Supabase Auth 校验 access token，返回 (user_id, email)。无效则抛 401。"""
    try:
        resp = supabase.auth.get_user(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的登录凭证"
        ) from exc
    if resp is None or resp.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的登录凭证"
        )
    return resp.user.id, resp.user.email


def fetch_role(supabase: Client, user_id: str) -> str:
    """查 profiles.role；查不到时默认 sales（新用户触发器建 profile 有极短延迟窗口）。"""
    rows = (
        supabase.table("profiles").select("role").eq("id", user_id).limit(1).execute().data
    )
    return rows[0]["role"] if rows else "sales"
