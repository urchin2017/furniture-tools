"""netretry 单元测试：网络层错误重试、逻辑错误直抛、重试耗尽报错。"""
from __future__ import annotations

import httpx
import pytest

import netretry
from netretry import with_retry


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(netretry.time, "sleep", lambda *_: None)


def test_retries_transport_errors_until_success():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("[SSL: WRONG_VERSION_NUMBER] wrong version number")
        return "ok"

    assert with_retry(flaky) == "ok"
    assert len(calls) == 3


def test_non_network_errors_raise_immediately():
    calls = []

    def logical_error():
        calls.append(1)
        raise ValueError("RLS 拒绝之类的逻辑错误")

    with pytest.raises(ValueError):
        with_retry(logical_error)
    assert len(calls) == 1, "逻辑错误不该重试"


def test_exhausted_retries_raise_runtime_error_with_desc():
    def always_flaky():
        raise ConnectionError("flake")

    with pytest.raises(RuntimeError, match="更新 jobs"):
        with_retry(always_flaky, attempts=2, desc="更新 jobs job-1")
