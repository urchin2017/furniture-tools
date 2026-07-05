"""矢量图纸「确定性读取」——不靠 AI 看图，直接从 PDF 的线条坐标 + 文字坐标查尺寸。

思路（用户提供的 drawing_probe 思路）：
- `page.get_drawings()` 拿到每条线的精确坐标；`page.get_text("words")` 拿到每个尺寸数字的包围框；
- 尺寸数字贴在横线上=宽度方向、贴在竖线上=高度方向（同一坐标系，空间关联可判定）；
- 按位置把数字聚成「视图」（立面/侧视/平面各一簇），每簇的最大横/纵向数字=该视图外形；
- **深度 D** = 侧视/平面视图里那条「非整体宽、非整体高」的外形尺寸（跨视图出现的第三个尺寸）。

已知边界（写进逻辑）：整体高的判定在多视图图纸上不稳（内部竖向尺寸可能比外形高还大），
所以本模块**只负责补「深度 D」**——W/H 仍由 measure_dims 几何引擎给；D 补不出时返回 None（留空标黄，
绝不臆造）。全部可回溯到坐标、可复现、可做 golden 测试。
"""
from __future__ import annotations

import re

_DIM_RE = re.compile(r"^[WHDwhdØφ]?\s*[=＝]?\s*(\d{2,5})(?:\.\d+)?\s*(?:mm|MM|㎜)?$")
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


def read_depth_mm(page, w_mm=None, h_mm=None):
    """确定性读取「深度 D」(mm)：视图聚类后取那条既非整体宽、又非整体高的外形跨尺寸。
    读不出返回 None（宁留空标黄，不臆造）。w_mm/h_mm 若给出用于排除 W/H 本身。"""
    try:
        h_lines, v_lines = _segments(page.get_drawings())
        toks = _dim_tokens(page.get_text("words"))
    except Exception:  # noqa: BLE001
        return None
    if not toks or (not h_lines and not v_lines):
        return None
    pts = [(v, cx, cy, _orient(cx, cy, h_lines, v_lines)) for (v, cx, cy) in toks]
    W = w_mm or max((p[0] for p in pts if p[3] == "h"), default=0)
    H = h_mm or max((p[0] for p in pts if p[3] == "v"), default=0)
    if not W or not H:
        return None
    # 各视图里「小于整体宽的最大横向」或「小于整体高的最大纵向」都是深度候选；取其最大。
    cand = []
    for view in _cluster(pts):
        hs = [p[0] for p in view if p[3] == "h"]
        vs = [p[0] for p in view if p[3] == "v"]
        if hs:
            mh = max(hs)
            if mh < W * 0.98:
                cand.append(mh)
        if vs:
            mv = max(vs)
            if mv < H * 0.98:
                cand.append(mv)
    return max(cand) if cand else None
