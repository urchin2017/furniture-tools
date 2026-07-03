"""Step 2「定外形尺寸」：skill 的交互式看图协议改成服务端调 claude_client.complete_vision。

每页一次视觉调用：整页图 + 四象限放大图 + 骨架记录（measured/text_dims/qty_hint）+
文字层 + 术语表命中 → Claude 按铁律返回该页全部品番的
W/D/H/qty/dim_source/dim_evidence/日中品名材质备考，再合并回 products.json 记录。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .prompts import SYSTEM_PROMPT, build_user_text

# 视觉渲染 DPI：整页图超过 API 长边上限(约1568px)会被服务端等比缩小，
# 所以整页不必高于 160；细小尺寸数字靠四象限放大图（render_pages 里是 dpi+60）。
VISION_DPI = 160


def _norm_code(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").strip()).upper()


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抠出 JSON 对象（容忍 ```json 围栏/前后解释文字）。"""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"模型输出里找不到 JSON 对象：{t[:200]!r}")
    return json.loads(t[start : end + 1])


def _coerce_int(v: Any) -> int | None:
    if v in (None, "", "null"):
        return None
    try:
        return int(round(float(str(v).replace(",", ""))))
    except (TypeError, ValueError):
        return None


def _clean_product(p: dict[str, Any]) -> dict[str, Any]:
    """把模型返回的一条产品收敛成 products.json 字段口径。"""
    src = str(p.get("dim_source") or "PENDING")
    if src not in ("visual", "geometry", "PENDING"):
        src = "PENDING"
    mat_jp = [str(x) for x in (p.get("mat_jp") or []) if str(x).strip()]
    mat_cn = [str(x) for x in (p.get("mat_cn") or []) if str(x).strip()]
    return {
        "row_code": _norm_code(str(p.get("row_code") or "")),
        "name_jp": str(p.get("name_jp") or "").strip(),
        "name_cn": str(p.get("name_cn") or "").strip(),
        "mat_jp": mat_jp,
        "mat_cn": mat_cn,
        "W": _coerce_int(p.get("W")),
        "D": _coerce_int(p.get("D")),
        "H": _coerce_int(p.get("H")),
        "qty": _coerce_int(p.get("qty")),
        "dim_source": src,
        "dim_evidence": str(p.get("dim_evidence") or "").strip(),
        "note_jp": str(p.get("note_jp") or "").strip(),
        "note_cn": str(p.get("note_cn") or "").strip(),
    }


def render_vision_images(doc, pageno: int, out_dir: str) -> tuple[list[bytes], list[str]]:
    """整页 + 四象限放大（复用 skill 的 render_pages），返回 (PNG bytes 列表, 图例)。"""
    from skills.drawing_to_quotation.render_pages import render_page

    os.makedirs(out_dir, exist_ok=True)
    render_page(doc, pageno - 1, out_dir, dpi=VISION_DPI, zoom_quadrants=True)
    names = [
        (f"full_page_{pageno:02d}.png", "图1=整页"),
        (f"full_page_{pageno:02d}_tl.png", "图2=左上象限放大"),
        (f"full_page_{pageno:02d}_tr.png", "图3=右上象限放大"),
        (f"full_page_{pageno:02d}_bl.png", "图4=左下象限放大"),
        (f"full_page_{pageno:02d}_br.png", "图5=右下象限放大"),
    ]
    images, legend = [], []
    for fname, label in names:
        path = os.path.join(out_dir, fname)
        if os.path.exists(path):
            with open(path, "rb") as f:
                images.append(f.read())
            legend.append(label)
    return images, legend


def glossary_hits_for_text(text: str, maps: dict[str, dict[str, str]], limit: int = 40) -> list[str]:
    """在页面文字层里扫术语表命中（子串匹配），输出「原文 → 译文」提示行。"""
    text = unicodedata.normalize("NFC", text or "")
    lines: list[str] = []
    for direction, mp in maps.items():
        for src, dst in mp.items():
            if len(src) >= 2 and src in text:
                lines.append(f"[{direction}] {src} → {dst}")
                if len(lines) >= limit:
                    return lines
    return lines


@dataclass
class PageDecision:
    products: list[dict[str, Any]]
    cost_usd: float
    warnings: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    model: str = ""


def decide_page(
    claude,
    *,
    pageno: int,
    records: list[dict[str, Any]],
    page_text: str,
    images_png: list[bytes],
    image_legend: list[str],
    glossary_lines: list[str],
) -> PageDecision:
    """对一页图纸跑视觉判断，返回该页全部品番的确认结果。"""
    user_text = build_user_text(pageno, records, page_text, glossary_lines, image_legend)
    result = claude.complete_vision(
        system=SYSTEM_PROMPT, user_text=user_text, images_png=images_png, max_tokens=8000
    )
    data = extract_json(result.text)
    raw = data.get("products")
    if not isinstance(raw, list):
        raise ValueError(f"第 {pageno} 页模型输出缺少 products 数组")
    products = [_clean_product(p) for p in raw if isinstance(p, dict)]
    warnings = [
        f"第 {pageno} 页 {p['row_code'] or '(空品番)'}：dim_source={p['dim_source']}，未确认"
        for p in products
        if p["dim_source"] == "PENDING"
    ]
    return PageDecision(
        products=products,
        cost_usd=result.usage.cost_usd(),
        warnings=warnings,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cache_read_input_tokens=result.usage.cache_read_input_tokens,
        cache_creation_input_tokens=result.usage.cache_creation_input_tokens,
        model=result.model,
    )


def merge_page_decision(
    scaffold_records: list[dict[str, Any]], decision: PageDecision
) -> list[dict[str, Any]]:
    """把视觉结果合并回该页骨架记录（骨架的 page/page_image/measured/text_dims 保留）。

    - 品番对上 → 更新尺寸/数量/双语文案；
    - 视觉补出的新品番（骨架漏拆的变体）→ 以本页第一条骨架为底新建记录；
    - 骨架里的空品番占位（无文本层页）在视觉给出品番后剔除；
    - 视觉漏答的骨架品番保持 PENDING（fill_quote 会标 ⚠）。
    """
    by_code = {_norm_code(r.get("row_code", "")): r for r in scaffold_records}
    base = scaffold_records[0]
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in decision.products:
        code = p["row_code"]
        if not code or code in seen:
            continue
        seen.add(code)
        if code in by_code:
            rec = dict(by_code[code])
        elif "" in by_code:
            rec = dict(by_code.pop(""))  # 空品番占位（无文本层页）被本条认领，不再复用
        else:
            rec = dict(base)             # 骨架漏拆的变体：以本页第一条为底新建
        rec.update(p)
        merged.append(rec)
    for code, rec in by_code.items():
        if code and code not in seen:
            merged.append(rec)  # 视觉漏答 → 保持 PENDING，出⚠行
    if not merged:               # 视觉一条没给（异常保守兜底）：保留骨架，全部走⚠
        return scaffold_records
    return merged
