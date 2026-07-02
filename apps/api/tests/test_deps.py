"""deps.py 单元测试：get_current_user 的鉴权头解析边界 + require_admin 角色分支，无网络。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from supabase import AuthError

from app.deps import CurrentUser, get_current_user, require_admin


def _wire_auth(fake_supabase, role="sales", user_id="u1", email="a@b.com", valid_token="good-token"):
    fake_supabase.table("profiles").insert({"id": user_id, "role": role}).execute()

    def get_user(token):
        if token != valid_token:
            raise AuthError("invalid token", None)
        return SimpleNamespace(user=SimpleNamespace(id=user_id, email=email))

    fake_supabase.auth = SimpleNamespace(get_user=get_user)
    return fake_supabase


def test_missing_authorization_header_401(fake_supabase):
    _wire_auth(fake_supabase)
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization=None, supabase=fake_supabase)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("header", ["good-token", "Basic good-token", "bearer", ""])
def test_malformed_authorization_header_401(fake_supabase, header):
    """缺 "Bearer " 前缀 / 用了别的 scheme / 空字符串，都必须 401，不能崩其它异常。"""
    _wire_auth(fake_supabase)
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization=header, supabase=fake_supabase)
    assert exc.value.status_code == 401


def test_valid_bearer_token_returns_current_user(fake_supabase):
    _wire_auth(fake_supabase, role="admin")
    user = get_current_user(authorization="Bearer good-token", supabase=fake_supabase)
    assert user == CurrentUser(id="u1", email="a@b.com", role="admin")


def test_require_admin_rejects_non_admin():
    with pytest.raises(HTTPException) as exc:
        require_admin(user=CurrentUser(id="u1", email=None, role="sales"))
    assert exc.value.status_code == 403


def test_require_admin_allows_admin():
    admin = CurrentUser(id="u1", email=None, role="admin")
    assert require_admin(user=admin) == admin
