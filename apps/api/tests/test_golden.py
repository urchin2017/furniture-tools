"""黄金文件/快照对比：API 路由表是确定性输出，改动若意外增删/改了路由会被这里抓到。

重新生成黄金文件：`UPDATE_GOLDEN=1 pytest tests/test_golden.py`
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

GOLDEN = pathlib.Path(__file__).parent / "golden"
_UPDATE = bool(os.environ.get("UPDATE_GOLDEN"))


def _load(name):
    p = GOLDEN / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _save(name, obj):
    GOLDEN.mkdir(exist_ok=True)
    (GOLDEN / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_route_surface_golden():
    from app.main import app

    routes = sorted(
        f"{method} {route.path}"
        for route in app.routes
        for method in (getattr(route, "methods", None) or [])
    )
    if _UPDATE:
        _save("routes.json", routes)
        pytest.skip("已更新 routes.json")
    golden = _load("routes.json")
    assert golden is not None, "缺 golden/routes.json —— 先跑 UPDATE_GOLDEN=1 生成"
    assert routes == golden, "API 路由表变了——如果是有意为之，UPDATE_GOLDEN=1 重新生成"
