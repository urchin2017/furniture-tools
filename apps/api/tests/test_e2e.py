"""端到端：不 override 任何依赖，走真实 FastAPI app + 真实 Supabase Auth 网络请求。

只自动化测"无效凭证被真实 Supabase Auth 正确拒绝"这条链路——这是能安全塞进自动化
测试的最大范围。完整的"真实登录态"端到端（含合法 token）需要真账号密码，属于人工/
浏览器验证的范畴（本次开发已在真实 Chrome + Docker 容器里人工验证过登录/术语表 CRUD，
见 HANDOFF.md）。

缺 .env/网络则跳过。
"""
from __future__ import annotations

import pytest


def test_invalid_bearer_token_rejected_by_real_supabase_auth():
    pytest.importorskip("supabase")
    from app.config import get_settings  # 顺带把 shared/py 接上 sys.path

    try:
        get_settings()
    except Exception as e:
        pytest.skip(f"缺少配置: {e}")

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    try:
        resp = client.get(
            "/api/jobs", headers={"Authorization": "Bearer definitely-not-a-real-token"}
        )
    except Exception as e:
        pytest.skip(f"Supabase 网络不可用: {e}")
    assert resp.status_code == 401
