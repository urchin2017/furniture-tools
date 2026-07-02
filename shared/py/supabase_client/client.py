"""Supabase service_role 客户端（后端用）。

⚠️ service_role **绕过 RLS**。后端读写私有数据（jobs / storage 对象）时**必须**用
校验出的 user_id 显式过滤/写入 —— 数据隔离靠代码纪律，RLS 是前端直连的兜底。
service_role key 只存 .env，永不进前端。

命名说明：本包故意叫 `supabase_client` 而非 `supabase`，避免与 pip 包 `supabase`
同名互相遮蔽（否则 `from supabase import create_client` 会指向本包自身）。
"""
from __future__ import annotations

from supabase import Client, create_client


def make_service_client(url: str, service_role_key: str) -> Client:
    """用 service_role key 建 Supabase 客户端（绕过 RLS）。"""
    return create_client(url, service_role_key)


def service_client_from_env() -> Client:
    """从 .env 读 URL + service_role key 建客户端。"""
    from settings import Settings

    s = Settings.from_env()
    return make_service_client(s.supabase_url, s.supabase_service_role_key)
