"""导入后「判断」步骤：快速classify PDF 每页是**位图**还是**矢量**，给出处理计划。

在真正生成之前跑（同步、秒级）：只做几何量取 + 光栅判定，不渲染大图、不调 AI。
让用户先看到「哪些页矢量→本地零 AI、哪些页位图→需 AI 看图、预计几次 AI 调用」，
再决定是否开始生成。分流依据与 generate.py 完全一致（dims.page_kind / route_for_kind）。
"""
from __future__ import annotations

from typing import Any

import fitz

from skills.drawing_to_quotation.extract_scaffold import detect_raster, find_codes
from skills.drawing_to_quotation.measure_dims import vector_ok_probe

from . import dims

# 单页看图的粗略成本上限（美元）：仅用于生成前的「预计花费」提示与花钱确认闸，
# 不是精确账单——真实成本按 token 在生成结果里逐页给出。默认按 Sonnet-5 一页整页+四象限
# 图 + 思考/输出的经验上限估。宁可略高，避免低估让用户误花钱。
EST_USD_PER_VISION_PAGE = 0.15


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
                vok = vector_ok_probe(page)  # 轻量探测：只判有没有可用矢量线，不量尺寸
            except Exception:  # noqa: BLE001 — 探测异常按无矢量处理
                vok = False
            measured = {"vector_ok": vok}
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

    ai_pages = [p["page"] for p in pages if p["path"] == "vision"]
    summary = {
        "total": len(pages),
        "vision_mode": vmode,
        "vector_pages": [p["page"] for p in pages if p["kind"] == "vector"],
        "bitmap_pages": [p["page"] for p in pages if p["kind"] == "bitmap"],
        "ai_pages": ai_pages,
        "local_pages": [p["page"] for p in pages if p["path"] == "local"],
        # 生成前的粗略预计花费（美元），供前端花钱确认闸用；本地零 AI 时为 0。
        "est_cost_usd": round(len(ai_pages) * EST_USD_PER_VISION_PAGE, 2),
    }
    return {"pages": pages, "summary": summary}
