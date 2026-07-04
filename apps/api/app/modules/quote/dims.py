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

from .prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_TEXT, build_user_text

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
    # 逐维待确认高亮（任务3）：清洗成 W/D/H 子集，缺省 []。透传给 fill_quote 单格标黄。
    confirm_dims = [d for d in (p.get("confirm_dims") or []) if d in ("W", "D", "H")]
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
        "confirm_dims": confirm_dims,
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
    # max_tokens 给足：adaptive thinking 会先花一段"思考"额度，复杂/大页（如 47MB 高清扫描页）
    # 若额度太小，会在思考阶段就被截断、来不及吐 JSON → 空输出。16000 给思考+JSON 留足空间。
    result = claude.complete_vision(
        system=SYSTEM_PROMPT, user_text=user_text, images_png=images_png, max_tokens=16000
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


def page_needs_vision(records: list[dict[str, Any]], raster_pages, pageno: int) -> bool:
    """分流判定：这一页要不要送**视觉**（贵）？还是几何+文字就够（廉价文字路）？

    成本控制铁律：矢量高置信页 W/H 几何已可靠量出 → 不必再送图给 AI「看」，走纯文字调用即可。
    仅以下情形才需视觉：光栅/扫描页、无矢量层、几何低置信、或 W/H 任一轴局部疑似/超界。
    """
    if pageno in (raster_pages or []):
        return True
    m = (records[0].get("measured") or {}) if records else {}
    if not m.get("vector_ok") or m.get("confidence") != "high":
        return True
    for axis in ("W", "H"):
        a = m.get(axis) or {}
        if a.get("overall_value") is None or a.get("suspect_local") or not a.get("extent_ok"):
            return True
    return False  # 矢量 + 高置信 + W/H 干净 → 走廉价文字路，不发图


def decide_page_text(
    claude,
    *,
    pageno: int,
    records: list[dict[str, Any]],
    page_text: str,
    glossary_lines: list[str],
) -> PageDecision:
    """廉价文字路：矢量高置信页不发图，仅凭几何量取 + 文字层 + 术语表跑一次**纯文字**判断。

    与 decide_page 同口径返回，但用 complete（无图）→ 输入 token 只有几千（视觉路要 ~1.6万+），
    单页成本降约 5~8 倍，且几乎不上传大图（顺带不吃上行带宽、不卡网络）。
    """
    user_text = build_user_text(pageno, records, page_text, glossary_lines, image_legend=[])
    result = claude.complete(system=SYSTEM_PROMPT_TEXT, user_text=user_text, max_tokens=16000)
    data = extract_json(result.text)
    raw = data.get("products")
    if not isinstance(raw, list):
        raise ValueError(f"第 {pageno} 页（文字路）模型输出缺少 products 数组")
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


# ============ 纯本地零 AI 提取（不调 Anthropic）============
# 品名/材質关键字锚定（通用尽力版；拿到真实样图后按其模板精修）。
_NAME_RE = re.compile(r"(?:品名|名称|品名称)\s*[:：]?\s*([^\n\r]{1,40})")
_MAT_RE = re.compile(r"(?:材質|材质|材料|仕様)\s*[:：]?\s*([^\n\r]{1,60})")


def glossary_translate(term: str, maps: dict[str, dict[str, str]]) -> str:
    """脚本侧术语表翻译：先精确命中，再子串命中；都没有返回 ""（调用方保留原文 + ⚠）。"""
    t = (term or "").strip()
    if not t:
        return ""
    for mp in maps.values():
        if t in mp:
            return mp[t]
    for mp in maps.values():
        for src, dst in mp.items():
            if len(src) >= 2 and src in t:
                return dst
    return ""


def _local_axis(measured: dict, text_dims: dict, axis: str) -> tuple[int | None, str, bool]:
    """一根轴的本地取值：几何高置信优先（并与文字注记交叉核对），否则退文字注记。
    返回 (值, 来源'geometry'/'text'/'none', 是否需人工复核)。"""
    a = (measured.get(axis) or {}) if isinstance(measured, dict) else {}
    tv = _coerce_int(text_dims.get(axis)) if isinstance(text_dims, dict) else None
    geom_ok = (
        measured.get("vector_ok")
        and measured.get("confidence") == "high"
        and a.get("overall_value") is not None
        and a.get("extent_ok")
        and not a.get("suspect_local")
    )
    if geom_ok:
        gv = int(round(a["overall_value"]))
        # 几何 ✕ 文字交叉核对：差得多 → 疑似"局部尺寸陷阱"，标⚠（这一步替 AI 做掉大部分陷阱检测）
        mismatch = tv is not None and abs(gv - tv) > max(5, int(0.05 * gv))
        return gv, "geometry", mismatch
    if tv is not None:
        return tv, "text", True  # 纯靠文字注记 → 一律复核（可能是分割/局部寸法）
    return None, "none", True


def decide_page_local(
    records: list[dict[str, Any]],
    page_text: str,
    maps: dict[str, dict[str, str]],
) -> PageDecision:
    """纯本地零 AI 提取一页：几何量取 W/H + 文字层 D/品名/材質/数量 + 术语表翻译。
    **不调 Anthropic，成本/tokens 恒为 0。** 拿不准的维/未命中术语表的名称一律标⚠待人工。"""
    name_jp = ""
    m = _NAME_RE.search(page_text or "")
    if m:
        name_jp = m.group(1).strip()
    mat_jp: list[str] = []
    mm = _MAT_RE.search(page_text or "")
    if mm and mm.group(1).strip():
        mat_jp = [mm.group(1).strip()]

    products: list[dict[str, Any]] = []
    warnings: list[str] = []
    for r in records:
        code = _norm_code(str(r.get("row_code") or ""))
        measured = r.get("measured") or {}
        text_dims = r.get("text_dims") or {}
        W, ws, wflag = _local_axis(measured, text_dims, "W")
        H, hs, hflag = _local_axis(measured, text_dims, "H")
        D = _coerce_int(text_dims.get("D")) if isinstance(text_dims, dict) else None
        confirm = []
        if W is not None and wflag:
            confirm.append("W")
        if D is not None:
            confirm.append("D")  # D 永远只有文字来源 → 一律复核
        if H is not None and hflag:
            confirm.append("H")
        src = "geometry" if (ws == "geometry" and hs == "geometry") else "PENDING"
        nm_jp = name_jp or str(r.get("name_jp") or "")
        nm_cn = glossary_translate(nm_jp, maps)
        mats_jp = mat_jp or [str(x) for x in (r.get("mat_jp") or []) if str(x).strip()]
        mats_cn = [c for c in (glossary_translate(x, maps) for x in mats_jp) if c]
        note = "本地提取（几何+文字+术语表，未经 AI 看图），尺寸/品名务必人工核对。"
        if nm_jp and not nm_cn:
            note += "（品名未命中术语表，保留日文待译/补词条）"
        products.append(_clean_product({
            "row_code": code,
            "name_jp": nm_jp,
            "name_cn": nm_cn or nm_jp,
            "mat_jp": mats_jp,
            "mat_cn": mats_cn,
            "W": W, "D": D, "H": H,
            "qty": _coerce_int(r.get("qty_hint")),
            "dim_source": src,
            "dim_evidence": "本地几何量取/文字注记提取",
            "confirm_dims": confirm,
            "note_jp": "", "note_cn": note,
        }))
        if src == "PENDING" or confirm:
            flag = "/".join(confirm) or "尺寸"
            warnings.append(f"第 {r.get('page')} 页 {code or '(空品番)'}：本地提取，{flag} 需人工核对")
    return PageDecision(products=products, cost_usd=0.0, warnings=warnings, model="local-script")


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
