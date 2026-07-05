"""矢量图纸「确定性读取」——不靠 AI 看图，直接从 PDF 的文字/线条坐标查「深度 D」。

思路（用户提供的 drawing_probe 思路 + 「最外侧尺寸线才算外形」原则）：
- `page.get_text("words")` 拿到每个尺寸数字的包围框、`page.get_drawings()` 拿到每条线的坐标；
- 尺寸数字贴在横线上=宽度方向、贴在竖线上=高度方向（同一坐标系，空间关联可判定）；
- 按位置把数字聚成「视图」（立面/侧视/平面各一簇），每簇的最大横/纵向数字=该视图外形。

深度 D 的两级确定性读取（越靠前越可靠）：
  1) **显式 D 前缀注记**（D500 / D580 / D30…）——SEKI 图在图内直接把深度写成「D+数值」，
     这是最可靠的深度来源，直接取用（多个取最外/最大）。
  2) **侧视图法**（几何）：深度 = 那张「侧视/断面视图」的整体横向尺寸——它与正面图**同高**
     （竖向外形 ≈ 整体高 H），但横向比整体宽 W 窄。正是「最外侧尺寸线才算外形」：
     取该视图最外层横向链，避开内部尺寸链/半块详图/引出注记（R30、20 这类小簇会被排除）。

已知边界：整体高 H、整体宽 W 仍由 measure_dims 几何引擎给；D 补不出时返回 None
（宁留空标黄、绝不臆造，也绝不参考外部 Excel）。全部可回溯到坐标、可复现、可做 golden 测试。
"""
from __future__ import annotations

import re

_DIM_RE = re.compile(r"^[WHDwhdØφ]?\s*[=＝]?\s*(\d{2,5})(?:\.\d+)?\s*(?:mm|MM|㎜)?$")
# 显式深度注记：D500 / D=580 / ｄ30（全/半角 D，可带 = ＝）。
_DEPTH_PREFIX_RE = re.compile(r"^[Dd]\s*[=＝]?\s*(\d{2,5})(?:\.\d+)?$")
_FLAT_TOL = 1.5
_NEAR_TOL = 25
_MIN_MM, _MAX_MM = 20, 8000


def _segments(drawings):
    h, v = [], []
    for path in drawings:
        for item in path["items"]:
            if item[0] == "l":
                a, b = item[1], item[2]
                dx, dy = abs(b.x - a.x), abs(b.y - a.y)
                if dy <= _FLAT_TOL and dx > _FLAT_TOL:
                    h.append((a.x, a.y, b.x, b.y))
                elif dx <= _FLAT_TOL and dy > _FLAT_TOL:
                    v.append((a.x, a.y, b.x, b.y))
    return h, v


def _dim_tokens(words):
    out = []
    for (x0, y0, x1, y1, text, *_rest) in words:
        m = _DIM_RE.match((text or "").strip())
        if m:
            val = int(m.group(1))
            if _MIN_MM <= val <= _MAX_MM:
                out.append((val, (x0 + x1) / 2, (y0 + y1) / 2))
    return out


def _prefixed_depth(words, w_mm=None):
    """取显式「D+数值」深度注记（最可靠）。多个取最外/最大；返回 None 表示图上没写。"""
    vals = []
    for (x0, y0, x1, y1, text, *_rest) in words:
        m = _DEPTH_PREFIX_RE.match((text or "").strip())
        if m:
            v = int(m.group(1))
            if _MIN_MM <= v <= _MAX_MM:
                vals.append(v)
    if not vals:
        return None
    # 同页多张视图可能各写一次 D（如连续页），取最外层=最大值。
    return max(vals)


def _orient(cx, cy, h_lines, v_lines):
    """判定数字贴的是横线(h=宽度方向)还是竖线(v=高度方向)。"""
    bh = bv = 1e9
    for (x0, y0, x1, y1) in h_lines:
        if min(x0, x1) - _NEAR_TOL <= cx <= max(x0, x1) + _NEAR_TOL:
            bh = min(bh, abs(cy - y0))
    for (x0, y0, x1, y1) in v_lines:
        if min(y0, y1) - _NEAR_TOL <= cy <= max(y0, y1) + _NEAR_TOL:
            bv = min(bv, abs(cx - x0))
    if bh <= _NEAR_TOL and bh <= bv:
        return "h"
    if bv <= _NEAR_TOL:
        return "v"
    return "?"


def _cluster(pts, gap=130):
    """按 2D 位置把点单链聚类成「视图」。"""
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if abs(pts[i][1] - pts[j][1]) < gap and abs(pts[i][2] - pts[j][2]) < gap:
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i, p in enumerate(pts):
        groups.setdefault(find(i), []).append(p)
    return list(groups.values())


def _is_chain(hs, tol_mm=3, tol_pct=0.02):
    """一簇横向尺寸是否构成「尺寸链」：最外层 ≈ 其余各段之和（如 20+150=170）。
    是则最外层就是该视图的外形横向尺寸（最外侧尺寸线才算外形）；返回该外形值，否则 None。"""
    if len(hs) < 2:
        return None
    top = max(hs)
    rest = sum(hs) - top
    if abs(top - rest) <= max(tol_mm, top * tol_pct):
        return top
    return None


def _depth_from_side_view(page, w_mm, h_mm):
    """侧视图法（几何）读深度，两条互补的「最外侧尺寸线才算外形」判据：
      A) **同高侧视**：某视图竖向外形≈整体高 H、横向比整体宽 W 窄 → 该视图整体横向=深度
         （侧视图=正面图转 90°，同高）。要求 ≥2 条横向尺寸，避开孤立小注记（如缝隙 20）。
      B) **横向尺寸链**：某簇最外层横向 ≈ 其余各段之和（如 20+150=170）、且 < 0.9·W →
         这是一条真正的外形横向链（避开 R 角、单点注记）。取最外层。
    A 优先（更强），A 无果用 B。多候选取最外层（最大）。读不出返回 None。"""
    try:
        h_lines, v_lines = _segments(page.get_drawings())
        toks = _dim_tokens(page.get_text("words"))
    except Exception:  # noqa: BLE001
        return None
    if not toks or not h_mm or not w_mm:
        return None
    pts = [(v, cx, cy, _orient(cx, cy, h_lines, v_lines)) for (v, cx, cy) in toks]
    views = [([p[0] for p in vw if p[3] == "h"], [p[0] for p in vw if p[3] == "v"])
             for vw in _cluster(pts)]
    # A) 同高侧视：竖向≈H、横向<0.9W、且≥2 条横向（排除孤立注记）。
    matchH = []
    for hs, vs in views:
        if len(hs) >= 2 and vs:
            h_overall, v_overall = max(hs), max(vs)
            if 0.8 * h_mm <= v_overall <= 1.03 * h_mm and h_overall < 0.9 * w_mm:
                matchH.append(h_overall)
    if matchH:
        return max(matchH)
    # B) 横向尺寸链：最外层≈其余之和、<0.9W。
    chains = []
    for hs, _vs in views:
        c = _is_chain([x for x in hs if x < 0.9 * w_mm] or hs)
        if c is not None and c < 0.9 * w_mm:
            chains.append(c)
    return max(chains) if chains else None


def read_depth_prefix(page, w_mm=None):
    """只取显式「D 前缀」深度注记（最可靠）。读不出返回 None。"""
    try:
        return _prefixed_depth(page.get_text("words"), w_mm)
    except Exception:  # noqa: BLE001
        return None


def read_depth_geometry(page, w_mm=None, h_mm=None):
    """只用侧视图几何法读深度（在 D 前缀、同族借用都无果后的最后一档）。读不出返回 None。"""
    return _depth_from_side_view(page, w_mm, h_mm)


def read_depth_mm(page, w_mm=None, h_mm=None):
    """确定性读取「深度 D」(mm)：先取显式「D 前缀」注记，再退回侧视图几何法。
    读不出返回 None（宁留空标黄、不臆造，绝不参考外部 Excel）。"""
    d = read_depth_prefix(page, w_mm)
    if d is not None:
        return d
    return _depth_from_side_view(page, w_mm, h_mm)
