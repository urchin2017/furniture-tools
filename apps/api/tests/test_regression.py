"""回归测试：把这次开发踩过的坑/关键设计决策锁死，未来改动若破坏它们会立即失败。无网络。"""
from __future__ import annotations

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.deps import CurrentUser
from app.routers.jobs import JobCreate, create_job, get_job, list_jobs
from app.tasks.runner import HANDLERS, run_job


def test_openapi_schema_builds_without_error():
    """回归：本机 python3.9 下 FastAPI/pydantic 曾没法对 `from __future__ import
    annotations` 产生的 `X | None` 求值，会在路由注册阶段直接抛 TypeError（見
    eval-type-backport 相关坑）。这里生成一次 OpenAPI schema，确保所有 router 的类型
    标注都能正常解析——这是最容易被以后新增路由不小心破坏的地方。
    """
    from app.main import app

    schema = app.openapi()
    assert schema["paths"], "OpenAPI schema 里应该至少有已注册的路由"


def test_unregistered_feature_job_never_stuck_in_queued(fake_supabase):
    """回归：feature 没注册 handler 时，job 必须显式落到 status='error'，
    不能像最初设计那样悄悄停在 'queued' 让人误以为还在排队。
    """
    saved_handlers = dict(HANDLERS)  # HANDLERS 现在有真实注册（quote_generate），测完还原
    HANDLERS.clear()
    try:
        fake_supabase.table("jobs").insert(
            {"id": "job-x", "user_id": "u1", "feature": "shipping_marks"}
        ).execute()

        run_job(fake_supabase, "job-x", "shipping_marks", {})

        row = fake_supabase._tables["jobs"][0]
        assert row["status"] != "queued"
        assert row["status"] == "error"
    finally:
        HANDLERS.update(saved_handlers)


def test_service_role_bypass_still_isolates_jobs_by_user(fake_supabase):
    """回归：service_role 客户端绕过 RLS，jobs 的用户隔离完全靠 routers/jobs.py 里
    显式的 `.eq('user_id', ...)` 过滤——这里锁死这个行为，防止以后重构 routers/jobs.py
    时手滑漏掉隔离条件，导致销售之间能互相看到彼此的任务。
    """
    alice = CurrentUser(id="alice", email=None, role="sales")
    bob = CurrentUser(id="bob", email=None, role="sales")
    admin = CurrentUser(id="root", email=None, role="admin")

    create_job(
        JobCreate(feature="quote_generate", params={}),
        BackgroundTasks(),
        user=alice,
        supabase=fake_supabase,
    )

    assert list_jobs(user=bob, supabase=fake_supabase) == []  # bob 看不到 alice 的任务
    assert len(list_jobs(user=admin, supabase=fake_supabase)) == 1  # admin 能看到全部

    job_id = fake_supabase._tables["jobs"][0]["id"]
    with pytest.raises(HTTPException) as exc:
        get_job(job_id, user=bob, supabase=fake_supabase)
    assert exc.value.status_code == 404  # 故意 404 而非 403，不向 bob 暴露"这个 id 存在"

    assert get_job(job_id, user=alice, supabase=fake_supabase)["id"] == job_id
    assert get_job(job_id, user=admin, supabase=fake_supabase)["id"] == job_id
