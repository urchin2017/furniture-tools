"""FastAPI 依赖：service_role 客户端单例 + current_user 注入。"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status
from supabase import Client

from app.auth import CurrentUser, authenticate
from app.config import get_settings  # noqa: F401  (触发 shared/py 加入 sys.path)

from supabase_client import service_client_from_env


@lru_cache
def get_supabase() -> Client:
    """service_role 客户端（绕过 RLS）。路由层必须显式按 user_id 过滤/写入。"""
    return service_client_from_env()


def get_current_user(
    authorization: str | None = Header(default=None),
    supabase: Client = Depends(get_supabase),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少登录凭证")
    token = authorization.split(" ", 1)[1].strip()
    # authenticate = verify_token + fetch_role，带 5 分钟 token 缓存 + 网络重试
    # （鉴权是每个请求都要过的出网调用，本机 TLS 抖动下必须这样兜）
    return authenticate(supabase, token)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user
