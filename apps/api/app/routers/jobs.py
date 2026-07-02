"""jobs 表基础 CRUD 骨架（创建/查询）。

异步执行 + 进度写入见 T10 的 `tasks/runner.py`（尚未实现）：本骨架里创建的任务会
停在 `status='queued'`，等 T10 接上真正的后台执行。service_role 客户端绕过 RLS，
所以这里必须显式按 user_id 过滤（admin 除外）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from app.deps import CurrentUser, get_current_user, get_supabase

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
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    if body.feature not in _FEATURES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知 feature：{body.feature}")
    rows = (
        supabase.table("jobs")
        .insert({"user_id": user.id, "feature": body.feature, "params": body.params or {}})
        .execute()
        .data
    )
    return rows[0]


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
