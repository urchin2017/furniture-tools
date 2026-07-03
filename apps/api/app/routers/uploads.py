"""大文件中转上传。

浏览器直传 Supabase storage 在本机慢上行 + TLS 抖动的网络下会中途断
（实测 17MB 从浏览器传必挂、从服务端传 28s 能过），所以改成：
浏览器 → 本地 API（内网，秒传）→ 服务端带重试传 storage uploads 桶。
key 固定 `<user_id>/<purpose>/<随机>/<ASCII文件名>`，与 storage RLS 的
user 前缀策略一致；返回 key 给前端拿去建 job params。
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from supabase import Client

from app.deps import CurrentUser, get_current_user, get_supabase

router = APIRouter(dependencies=[Depends(get_current_user)])

_MAX_MB = 50  # Supabase 存储桶单文件上限
_RETRIES = 3


def _safe_name(name: str, fallback: str) -> str:
    """storage key 只用 ASCII（中日文件名在 storage key 里不可靠）；扩展名单独保底，
    否则纯 CJK 文件名（如「図面.pdf」）清洗后连 .pdf 都会被剥掉。"""
    import os.path

    stem, ext = os.path.splitext(name or "")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or fallback.rsplit(".", 1)[0]
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", ext or ""):
        ext = ""
    return stem + ext.lower()


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    purpose: str = Form("quote"),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", purpose):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "非法 purpose")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "空文件")
    if len(data) > _MAX_MB * 1024 * 1024:
        raise HTTPException(
            413, f"文件 {len(data) / 1024 / 1024:.1f}MB 超过存储上限 {_MAX_MB}MB，请先压缩"
        )

    key = f"{user.id}/{purpose}/{uuid.uuid4().hex[:12]}/{_safe_name(file.filename or '', 'file.bin')}"
    content_type = file.content_type or "application/octet-stream"
    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            supabase.storage.from_("uploads").upload(
                key, data, file_options={"content-type": content_type, "upsert": "true"}
            )
            return {"path": key, "size": len(data), "content_type": content_type}
        except Exception as exc:  # noqa: BLE001 — 本机网络抖动，重试是常态
            last_exc = exc
            if attempt < _RETRIES - 1:
                time.sleep(2 * (attempt + 1))
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY, f"上传 storage 失败（已重试 {_RETRIES} 次）：{last_exc}"
    )
