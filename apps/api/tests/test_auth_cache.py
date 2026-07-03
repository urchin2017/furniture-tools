"""auth.authenticate 的缓存与网络容错测试（无网络，假桩 + monkeypatch）。

背景：鉴权是每个请求都要走的出网调用，本机 TLS 抖动下曾把它抖成
无 CORS 头的 500（浏览器显示 Failed to fetch）。对策=重试+短期缓存+503。
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

import netretry
from app.auth import authenticate


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(netretry.time, "sleep", lambda *_: None)


def _wire(fake_supabase, fail_times=0):
    fake_supabase.table("profiles").insert({"id": "u1", "role": "sales"}).execute()
    calls = {"n": 0}

    def get_user(token):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise httpx.ConnectTimeout("_ssl.c:1112: The handshake operation timed out")
        return SimpleNamespace(user=SimpleNamespace(id="u1", email="a@b.com"))

    fake_supabase.auth = SimpleNamespace(get_user=get_user)
    return calls


def test_second_call_hits_cache_not_network(fake_supabase):
    calls = _wire(fake_supabase)
    u1 = authenticate(fake_supabase, "tok-1")
    u2 = authenticate(fake_supabase, "tok-1")
    assert u1 == u2 and u1.id == "u1"
    assert calls["n"] == 1, "第二次应走缓存，不再出网"


def test_transient_tls_flake_is_retried(fake_supabase):
    calls = _wire(fake_supabase, fail_times=2)  # 前两次握手超时，第三次成功
    user = authenticate(fake_supabase, "tok-2")
    assert user.id == "u1"
    assert calls["n"] == 3


def test_persistent_network_failure_returns_503_not_crash(fake_supabase):
    _wire(fake_supabase, fail_times=99)
    with pytest.raises(HTTPException) as exc:
        authenticate(fake_supabase, "tok-3")
    assert exc.value.status_code == 503, "网络耗尽必须是带 CORS 的 503，不能裸异常变 Failed to fetch"
