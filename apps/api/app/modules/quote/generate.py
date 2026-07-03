"""quote_generate 的 JobHandler：图纸 PDF + Excel 模板 → 御見積書。

编排 skill v5 四步管线（机械脚本在 shared/py/skills/drawing_to_quotation）：
  ① build_scaffold（骨架+光栅判定） ② 视觉定外形尺寸（dims.py → complete_vision）
  ③ fill_quote_build（填模板） ④ render_xlsx（LibreOffice 渲染目视验证图）

输入 params（前端建任务时给）：
  pdf_path / template_path —— uploads 桶内 key，必须以 "<user_id>/" 开头
  project(str) / skip_pages(list[int], 默认[1]=封面) / start_row(18) / last_row(50)
  require_visual(bool, 默认 False=允许出带⚠草稿)

输出 output_files（写回 jobs 表）：outputs 桶文件清单 + 尺寸摘要 + 成本。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from typing import Any

import fitz

from app.config import get_settings  # noqa: F401  (触发 shared/py 加入 sys.path，须在下面 import 之前)

from claude_client import ClaudeClient
from glossary import GlossaryClient
from netretry import with_retry
from skills.drawing_to_quotation import build_scaffold, fill_quote_build, render_xlsx

from . import dims

_CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".json": "application/json",
    ".pdf": "application/pdf",
}


def _content_type(path: str) -> str:
    return _CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def _safe_ascii(name: str, fallback: str) -> str:
    """storage 对象 key 只用 ASCII（非 ASCII key 在 Supabase storage 上不可靠）。"""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return s or fallback


def _get_user_id(ctx) -> str:
    rows = with_retry(
        lambda: ctx.supabase.table("jobs").select("user_id").eq("id", ctx.job_id).limit(1).execute().data,
        desc="查任务归属",
    )
    if not rows:
        raise RuntimeError(f"jobs 表里找不到任务 {ctx.job_id}")
    return rows[0]["user_id"]


def _download(ctx, bucket: str, key: str, dest: str) -> str:
    data = with_retry(lambda: ctx.supabase.storage.from_(bucket).download(key), desc=f"下载 {key}")
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def _upload(ctx, bucket: str, key: str, local_path: str) -> dict[str, Any]:
    with open(local_path, "rb") as f:
        data = f.read()
    with_retry(
        lambda: ctx.supabase.storage.from_(bucket).upload(
            key, data, file_options={"content-type": _content_type(local_path), "upsert": "true"}
        ),
        desc=f"上传 {key}",
    )
    return {
        "bucket": bucket,
        "path": key,
        "name": os.path.basename(local_path),
        "content_type": _content_type(local_path),
        "size": len(data),
    }


def _load_glossary_maps(ctx) -> tuple[dict[str, dict[str, str]], list[str]]:
    """报价用双向术语提示（日⇄中）。术语表挂了不阻塞管线，只记 warning。"""
    warnings: list[str] = []
    maps: dict[str, dict[str, str]] = {}
    try:
        g = GlossaryClient(ctx.supabase)
        maps["ja→zh"] = with_retry(lambda: g.load_map("ja", "zh"), desc="载入术语表 ja→zh")
        maps["zh→ja"] = with_retry(lambda: g.load_map("zh", "ja"), desc="载入术语表 zh→ja")
    except Exception as exc:  # noqa: BLE001 — 术语表不可用只降级，不让任务失败
        warnings.append(f"术语表加载失败（翻译无术语提示）：{exc}")
        maps = {}
    return maps, warnings


def _mark_duplicate_codes(products: list[dict[str, Any]]) -> None:
    """同一品番出现在多页（如 F09 既是 Counter 又是 Shelf-02）→ 两行都保留＋备考报警。"""
    counts = Counter(p.get("row_code") for p in products if p.get("row_code"))
    for p in products:
        code = p.get("row_code")
        if code and counts[code] > 1 and "重複" not in (p.get("note_jp") or ""):
            p["note_jp"] = ((p.get("note_jp") or "") + f"\n品番{code}重複使用・要確認").strip()
            p["note_cn"] = ((p.get("note_cn") or "") + f"\n品番{code}重复使用·待确认").strip()


def run(ctx) -> dict[str, Any]:
    params = ctx.params or {}
    pdf_key = params.get("pdf_path") or ""
    template_key = params.get("template_path") or ""
    project = str(params.get("project") or "")
    raw_skip = params.get("skip_pages")
    skip_pages = [int(x) for x in raw_skip] if raw_skip is not None else [1]  # 默认跳封面页
    start_row = int(params.get("start_row") or 18)
    last_row = int(params.get("last_row") or 50)
    require_visual = bool(params.get("require_visual"))

    if not pdf_key or not template_key:
        raise ValueError("params 缺少 pdf_path / template_path")
    user_id = _get_user_id(ctx)
    for key in (pdf_key, template_key):
        if not str(key).startswith(f"{user_id}/"):
            raise ValueError("非法文件路径：必须位于本人 uploads 目录下")

    workdir = tempfile.mkdtemp(prefix="quote_generate_")
    try:
        pdf_local = _download(ctx, "uploads", pdf_key, os.path.join(workdir, "drawing.pdf"))
        template_local = _download(ctx, "uploads", template_key, os.path.join(workdir, "template.xlsx"))
        ctx.report_progress(8)

        # ① 骨架 + 光栅判定 + 整页图
        json_path = os.path.join(workdir, "products.json")
        payload = build_scaffold(
            pdf_local, json_path, img_dir=os.path.join(workdir, "pages"),
            dpi=150, skip_pages=skip_pages, project=project,
        )
        products: list[dict[str, Any]] = payload["products"]
        raster_pages: list[int] = payload.get("raster_pages", [])
        ctx.report_progress(15)

        # ② 定外形尺寸（判断步骤 → complete_vision，铁律见 prompts.SYSTEM_PROMPT）
        maps, warnings = _load_glossary_maps(ctx)
        claude = ClaudeClient.from_env()
        doc = fitz.open(pdf_local)
        pages = sorted({p["page"] for p in products})
        cost_usd = 0.0
        merged_all: list[dict[str, Any]] = []
        vision_dir = os.path.join(workdir, "vision")
        for i, pageno in enumerate(pages):
            page_records = [p for p in products if p["page"] == pageno]
            page_text = doc[pageno - 1].get_text()
            images, legend = dims.render_vision_images(doc, pageno, vision_dir)
            gl_lines = dims.glossary_hits_for_text(page_text, maps)
            decision = dims.decide_page(
                claude, pageno=pageno, records=page_records, page_text=page_text,
                images_png=images, image_legend=legend, glossary_lines=gl_lines,
            )
            cost_usd += decision.cost_usd
            warnings.extend(decision.warnings)
            merged_all.extend(dims.merge_page_decision(page_records, decision))
            ctx.report_progress(15 + int(60 * (i + 1) / len(pages)))

        products = merged_all
        _mark_duplicate_codes(products)
        payload["products"] = products
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        ctx.report_progress(78)

        # ③ 填 Excel 模板（视觉确认闸门在 fill_quote 里）
        today = datetime.date.today().isoformat()
        display_name = f"御見積書_{project or '報価'}_v1_{today}.xlsx"
        out_xlsx = os.path.join(workdir, display_name)
        fill_summary = fill_quote_build(
            pdf_local, template_local, json_path, out_xlsx, project,
            start_row, last_row, require_visual,
        )
        ctx.report_progress(86)

        # ④ 渲染目视验证（需 LibreOffice；本机没有 soffice 时降级跳过）
        check_pngs: list[str] = []
        try:
            check_pngs = render_xlsx(out_xlsx, os.path.join(workdir, "check"),
                                     area=f"A1:N{last_row + 3}")
        except Exception as exc:  # noqa: BLE001 — 渲染验证是加分项，失败不吞掉成品
            warnings.append(f"渲染验证跳过（LibreOffice 不可用或转换失败）：{exc}")
        ctx.report_progress(93)

        # 上传 outputs 桶（key 用 ASCII，中文名放 display_name 由前端下载时还原）
        prefix = f"{user_id}/{ctx.job_id}"
        files = [_upload(ctx, "outputs", f"{prefix}/{_safe_ascii(display_name, 'quote.xlsx')}", out_xlsx)]
        files[0]["display_name"] = display_name
        for png in check_pngs:
            files.append(_upload(ctx, "outputs", f"{prefix}/check/{os.path.basename(png)}", png))
        files.append(_upload(ctx, "outputs", f"{prefix}/products.json", json_path))

        return {
            "files": files,
            "summary": {
                "project": project,
                "rows": fill_summary["rows"],
                "raster_pages": raster_pages,
                "unconfirmed": fill_summary["unconfirmed"],
                "missing": fill_summary["missing"],
                "cost_usd": round(cost_usd, 4),
                "warnings": warnings,
                "products": [
                    {k: p.get(k) for k in ("row_code", "page", "W", "D", "H", "qty", "dim_source")}
                    for p in products
                ],
            },
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
