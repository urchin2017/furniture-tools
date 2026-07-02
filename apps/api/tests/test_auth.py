"""auth.py 单元测试：verify_token / fetch_role，假 Supabase 桩（无网络）。

边界情况：get_user 抛 AuthError、get_user 返回 user=None（防御性分支）、
fetch_role 查不到 profile 行时的默认值。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from supabase import AuthError

from app.auth import fetch_role, verify_token


def _fake_auth(valid_token="good-token", user_id="u1", email="a@b.com"):
    def get_user(token):
        if token != valid_token:
            raise AuthError("invalid token", None)
        return SimpleNamespace(user=SimpleNamespace(id=user_id, email=email))

    return SimpleNamespace(get_user=get_user)


def test_verify_token_success(fake_supabase):
    fake_supabase.auth = _fake_auth()
    user_id, email = verify_token(fake_supabase, "good-token")
    assert user_id == "u1"
    assert email == "a@b.com"


def test_verify_token_invalid_raises_401(fake_supabase):
    fake_supabase.auth = _fake_auth()
    with pytest.raises(HTTPException) as exc:
        verify_token(fake_supabase, "garbage")
    assert exc.value.status_code == 401


def test_verify_token_empty_token_raises_401(fake_supabase):
    fake_supabase.auth = _fake_auth()
    with pytest.raises(HTTPException) as exc:
        verify_token(fake_supabase, "")
    assert exc.value.status_code == 401


def test_verify_token_none_user_raises_401(fake_supabase):
    """防御性分支：get_user 没抛异常但返回了没有 user 的响应。"""
    fake_supabase.auth = SimpleNamespace(get_user=lambda token: SimpleNamespace(user=None))
    with pytest.raises(HTTPException) as exc:
        verify_token(fake_supabase, "whatever")
    assert exc.value.status_code == 401


def test_fetch_role_found(fake_supabase):
    fake_supabase.table("profiles").insert({"id": "u1", "role": "admin"}).execute()
    assert fetch_role(fake_supabase, "u1") == "admin"


def test_fetch_role_missing_defaults_to_sales(fake_supabase):
    assert fetch_role(fake_supabase, "no-such-user") == "sales"
