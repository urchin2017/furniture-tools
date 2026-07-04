"""jobs 异步执行骨架：FastAPI `BackgroundTasks` 调这里的 `run_job`，跑完把
status/progress/output_files/error 写回 `jobs` 表，前端轮询 `GET /api/jobs/{id}`。

真正的业务逻辑（报价生成、图纸翻译……）留给各自模块的 session 实现，写好
handler 后注册进 `HANDLERS` 就能被这里调度；没注册的 feature 直接标 error，
不会静默卡在 `queued`。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from supabase import Client

from netretry import with_retry


class JobCancelled(Exception):
    """用户中途取消任务（前端 POST /api/jobs/{id}/cancel 把 status 置 cancelled）。"""


def _update_job(supabase: Client, job_id: str, payload: dict[str, Any]) -> None:
    """写 jobs 表带重试——本机 TLS 抖动，状态写入失败会让任务假死在 running。"""
    with_retry(
        lambda: supabase.table("jobs").update(payload).eq("id", job_id).execute(),
        desc=f"更新 jobs {job_id}",
    )


@dataclass
class JobContext:
    """传给 handler 的执行上下文：读 params、汇报进度、查是否被取消。"""

    supabase: Client
    job_id: str
    params: dict[str, Any]
    _last_cancel_check: float = field(default=0.0, repr=False)
    _cancelled: bool = field(default=False, repr=False)

    def report_progress(self, progress: int) -> None:
        try:
            _update_job(self.supabase, self.job_id, {"progress": progress})
        except Exception:  # noqa: BLE001 — 进度是尽力而为，绝不因它杀掉任务本体
            pass

    def is_cancelled(self) -> bool:
        """任务是否被用户取消（读 jobs.status=='cancelled'）。节流：最多每 2s 查一次库，
        供长任务在页与页之间调用，命中后即刻停下。查询失败保守当未取消。"""
        if self._cancelled:
            return True
        now = time.time()
        if now - self._last_cancel_check < 2.0:
            return False
        self._last_cancel_check = now
        try:
            rows = (
                self.supabase.table("jobs").select("status").eq("id", self.job_id).limit(1).execute().data
            )
            if rows and rows[0].get("status") == "cancelled":
                self._cancelled = True
        except Exception:  # noqa: BLE001
            pass
        return self._cancelled


JobHandler = Callable[[JobContext], dict[str, Any]]


def _quote_generate(ctx: JobContext) -> dict[str, Any]:
    """懒 import：模块拉着 fitz/numpy/openpyxl/anthropic 一大串重依赖，
    放函数体里 API 启动（和离线测试收集）就不用背着它们。"""
    from app.modules.quote.generate import run

    return run(ctx)


# feature -> handler。模块实现后在这里注册。
HANDLERS: dict[str, JobHandler] = {
    "quote_generate": _quote_generate,
}


def run_job(supabase: Client, job_id: str, feature: str, params: dict[str, Any]) -> None:
    """后台任务入口：跑 handler，把结果/异常写回 jobs 表（全部写入带重试）。"""
    handler = HANDLERS.get(feature)
    if handler is None:
        _update_job(supabase, job_id, {"status": "error", "error": f"功能模块 {feature} 尚未实现"})
        return

    _update_job(supabase, job_id, {"status": "running", "progress": 0})
    ctx = JobContext(supabase=supabase, job_id=job_id, params=params)
    try:
        result = handler(ctx)
    except JobCancelled:
        # 用户取消：保持 cancelled 状态，不写 error/done（前端已停轮询、回到可重来的状态）。
        _update_job(supabase, job_id, {"status": "cancelled"})
        return
    except Exception as exc:  # noqa: BLE001 — 后台任务必须兜底，否则异常被吞掉、job 卡在 running
        _update_job(supabase, job_id, {"status": "error", "error": str(exc)})
        return

    _update_job(supabase, job_id, {"status": "done", "progress": 100, "output_files": result})
