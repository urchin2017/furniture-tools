"""jobs 表 CRUD + 异步执行触发。

创建任务后用 `BackgroundTasks` 扔给 `tasks/runner.run_job` 在后台跑，前端轮询
`GET /api/jobs/{id}` 看 status/progress。具体 feature 的业务逻辑由各模块
session 注册进 `runner.HANDLERS`；没注册的 feature 会在后台任务里直接标
`status='error'`，不会静默卡在 `queued`。service_role 客户端绕过 RLS，所以
这里必须显式按 user_id 过滤（admin 除外）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from app.deps import CurrentUser, get_current_user, get_supabase
from app.tasks.runner import run_job

router = APIRouter(dependencies=[Depends(get_current_user)])

_FEATURES = {
    "quote_generate",
    "quote_compare",
    "drawing_translate",
    "drawing_revision_diff",
    "shipping_marks",
}


class JobCreate(BaseModel):
    feature: str
    params: dict[str, Any] | None = None


class JobOut(BaseModel):
    id: str
    user_id: str
    feature: str
    status: str
    progress: int
    params: dict[str, Any] | None = None
    output_files: Any = None
    error: str | None = None


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobCreate,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    if body.feature not in _FEATURES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知 feature：{body.feature}")
    params = body.params or {}
    rows = (
        supabase.table("jobs")
        .insert({"user_id": user.id, "feature": body.feature, "params": params})
        .execute()
        .data
    )
    job = rows[0]
    background_tasks.add_task(run_job, supabase, job["id"], body.feature, params)
    return job


@router.get("", response_model=list[JobOut])
def list_jobs(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> list[dict[str, Any]]:
    q = supabase.table("jobs").select("*").order("created_at", desc=True)
    if user.role != "admin":
        q = q.eq("user_id", user.id)
    return q.execute().data or []


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    rows = supabase.table("jobs").select("*").eq("id", job_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    job = rows[0]
    if job["user_id"] != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """把 status 置 cancelled；后台任务在页与页之间读到后即刻停下（见 runner.JobContext）。
    已结束（done/error/cancelled）的任务直接返回，不改。"""
    rows = supabase.table("jobs").select("*").eq("id", job_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    job = rows[0]
    if job["user_id"] != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if job["status"] in ("queued", "running"):
        supabase.table("jobs").update({"status": "cancelled"}).eq("id", job_id).execute()
        job["status"] = "cancelled"
    return job
