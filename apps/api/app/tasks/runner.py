"""jobs 异步执行骨架：FastAPI `BackgroundTasks` 调这里的 `run_job`，跑完把
status/progress/output_files/error 写回 `jobs` 表，前端轮询 `GET /api/jobs/{id}`。

真正的业务逻辑（报价生成、图纸翻译……）留给各自模块的 session 实现，写好
handler 后注册进 `HANDLERS` 就能被这里调度；没注册的 feature 直接标 error，
不会静默卡在 `queued`。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from supabase import Client


@dataclass
class JobContext:
    """传给 handler 的执行上下文：读 params、汇报进度。"""

    supabase: Client
    job_id: str
    params: dict[str, Any]

    def report_progress(self, progress: int) -> None:
        self.supabase.table("jobs").update({"progress": progress}).eq("id", self.job_id).execute()


JobHandler = Callable[[JobContext], dict[str, Any]]

# feature -> handler。模块实现后在这里注册，例如：
#   from app.modules.quote.generate import run as quote_generate_run
#   HANDLERS["quote_generate"] = quote_generate_run
HANDLERS: dict[str, JobHandler] = {}


def run_job(supabase: Client, job_id: str, feature: str, params: dict[str, Any]) -> None:
    """后台任务入口：跑 handler，把结果/异常写回 jobs 表。"""
    handler = HANDLERS.get(feature)
    if handler is None:
        supabase.table("jobs").update(
            {"status": "error", "error": f"功能模块 {feature} 尚未实现"}
        ).eq("id", job_id).execute()
        return

    supabase.table("jobs").update({"status": "running", "progress": 0}).eq("id", job_id).execute()
    ctx = JobContext(supabase=supabase, job_id=job_id, params=params)
    try:
        result = handler(ctx)
    except Exception as exc:  # noqa: BLE001 — 后台任务必须兜底，否则异常被吞掉、job 卡在 running
        supabase.table("jobs").update({"status": "error", "error": str(exc)}).eq("id", job_id).execute()
        return

    supabase.table("jobs").update(
        {"status": "done", "progress": 100, "output_files": result}
    ).eq("id", job_id).execute()
