"""tasks/runner 单元测试：假 Supabase 桩（模仿 update().eq().execute() 链），无网络。"""
from __future__ import annotations

import pytest

from app.tasks.runner import HANDLERS, JobContext, run_job


@pytest.fixture(autouse=True)
def _clear_handlers():
    # HANDLERS 现在启动时就有真实注册（quote_generate），测完必须还原而不是清空，
    # 否则后跑的测试文件看到的是被掏空的注册表。
    saved = dict(HANDLERS)
    HANDLERS.clear()
    yield
    HANDLERS.clear()
    HANDLERS.update(saved)


def test_run_job_success_writes_running_then_done(fake_supabase):
    seen_mid_run_progress = []

    def handler(ctx: JobContext) -> dict:
        ctx.report_progress(50)
        seen_mid_run_progress.append(
            fake_supabase._tables["jobs"][0]["progress"]  # 确认 report_progress 是同步立刻写库的
        )
        return {"ok": True}

    HANDLERS["quote_generate"] = handler
    fake_supabase.table("jobs").insert({"id": "job-1", "user_id": "u1", "feature": "quote_generate"}).execute()

    run_job(fake_supabase, "job-1", "quote_generate", {"a": 1})

    assert seen_mid_run_progress == [50]
    row = fake_supabase._tables["jobs"][0]
    assert row["status"] == "done"
    assert row["progress"] == 100
    assert row["output_files"] == {"ok": True}


def test_run_job_handler_exception_writes_error(fake_supabase):
    def handler(ctx: JobContext) -> dict:
        raise ValueError("坏参数")

    HANDLERS["quote_generate"] = handler
    fake_supabase.table("jobs").insert({"id": "job-2", "user_id": "u1", "feature": "quote_generate"}).execute()

    run_job(fake_supabase, "job-2", "quote_generate", {})

    row = fake_supabase._tables["jobs"][0]
    assert row["status"] == "error"
    assert "坏参数" in row["error"]


def test_run_job_unregistered_feature_writes_error_without_running(fake_supabase):
    fake_supabase.table("jobs").insert({"id": "job-3", "user_id": "u1", "feature": "shipping_marks"}).execute()

    run_job(fake_supabase, "job-3", "shipping_marks", {})

    row = fake_supabase._tables["jobs"][0]
    assert row["status"] == "error"
    assert "尚未实现" in row["error"]
