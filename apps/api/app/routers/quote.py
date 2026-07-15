"""报价模块的轻量同步端点。

/analyze —— 生成前的「判断」步骤：把已上传的图纸 PDF 快速分页判定位图/矢量，
返回处理计划（哪些页本地零 AI、哪些页需 AI 看图），供前端在真正建生成任务前展示给用户。
只做几何量取 + 光栅判定，秒级返回、不调 AI；文件必须在本人 uploads 目录下。
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from app.config import get_settings  # noqa: F401  (触发 shared/py 加入 sys.path)
from app.deps import CurrentUser, get_current_user, get_supabase

from netretry import with_retry

router = APIRouter(dependencies=[Depends(get_current_user)])


class AnalyzeIn(BaseModel):
    pdf_path: str
    skip_pages: list[int] | None = None
    vision_mode: str = "auto"


@router.post("/analyze")
def analyze(
    body: AnalyzeIn,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    # 延迟 import：analyze 依赖 fitz/skills，放函数内避免拖慢无关端点的冷启动。
    from app.modules.quote.analyze import analyze_pdf

    if not str(body.pdf_path).startswith(f"{user.id}/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "非法文件路径：必须位于本人 uploads 目录下")

    tmp = tempfile.NamedTemporaryFile(prefix="quote_analyze_", suffix=".pdf", delete=False)
    tmp.close()
    try:
        data = with_retry(
            lambda: supabase.storage.from_("uploads").download(body.pdf_path),
            desc="下载图纸",
        )
        with open(tmp.name, "wb") as f:
            f.write(data)
        skip = body.skip_pages if body.skip_pages is not None else [1]
        try:
            return analyze_pdf(tmp.name, skip, body.vision_mode)
        except Exception as exc:  # noqa: BLE001 — 坏 PDF 等返回 400 而非 500
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"图纸分析失败：{exc}") from exc
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
