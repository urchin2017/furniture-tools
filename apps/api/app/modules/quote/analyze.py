"""导入后「判断」步骤：快速classify PDF 每页是**位图**还是**矢量**，给出处理计划。

在真正生成之前跑（同步、秒级）：只做几何量取 + 光栅判定，不渲染大图、不调 AI。
让用户先看到「哪些页矢量→本地零 AI、哪些页位图→需 AI 看图、预计几次 AI 调用」，
再决定是否开始生成。分流依据与 generate.py 完全一致（dims.page_kind / route_for_kind）。
"""
from __future__ import annotations

from typing import Any

import fitz

from skills.drawing_to_quotation.extract_scaffold import detect_raster, find_codes
from skills.drawing_to_quotation.measure_dims import measure_page

from . import dims


def analyze_pdf(pdf_path: str, skip_pages, vision_mode: str = "auto") -> dict[str, Any]:
    """分析一份图纸 PDF，返回逐页位图/矢量判定与处理计划。

    返回 {"pages": [...], "summary": {...}}：
      pages[i] = {page, kind: "bitmap"|"vector", path: "local"|"vision", codes, vector_ok}
      summary  = {total, vision_mode, vector_pages, bitmap_pages, ai_pages, local_pages}
    """
    skip = {int(x) for x in (skip_pages or [])}
    vmode = str(vision_mode or "auto").lower()
    doc = fitz.open(pdf_path)
    try:
        pages: list[dict[str, Any]] = []
        for pi in range(doc.page_count):
            pageno = pi + 1
            if pageno in skip:
                continue
            page = doc[pi]
            text = page.get_text()
            codes = [c for c in find_codes(text) if c]
            try:
                measured = measure_page(page)
            except Exception:  # noqa: BLE001 — 量取异常按无矢量处理
                measured = {"vector_ok": False}
            kind = "bitmap" if detect_raster(page, measured) else "vector"
            path = dims.route_for_kind(kind, vmode)
            pages.append({
                "page": pageno,
                "kind": kind,
                "path": path,
                "codes": codes,
                "vector_ok": bool(measured.get("vector_ok")),
            })
    finally:
        doc.close()

    summary = {
        "total": len(pages),
        "vision_mode": vmode,
        "vector_pages": [p["page"] for p in pages if p["kind"] == "vector"],
        "bitmap_pages": [p["page"] for p in pages if p["kind"] == "bitmap"],
        "ai_pages": [p["page"] for p in pages if p["path"] == "vision"],
        "local_pages": [p["page"] for p in pages if p["path"] == "local"],
    }
    return {"pages": pages, "summary": summary}
