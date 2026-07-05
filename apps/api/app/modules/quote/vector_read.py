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


_CY_TOL = 8   # 同一条尺寸线的文字坐标容差（px）——把 670│30 这类共线分段归到一条线


def _h_totals(vw):
    """横向尺寸线：按 cy 把文字归组求段和。**只保留至少含一个真横向 token 的线**——
    这样把 670│30（含被误判成竖向的 30）算进来，却排除「两个竖向标注恰好同高」（如 L-01 的两个 2700）。
    返回 [(段和, token数)…]。"""
    lines: list[list] = []
    for p in sorted(vw, key=lambda q: q[2]):
        for ln in lines:
            if abs(ln[0][2] - p[2]) <= _CY_TOL:
                ln.append(p)
                break
        else:
            lines.append([p])
    return [(sum(x[0] for x in ln), len(ln)) for ln in lines
            if any(x[3] == "h" for x in ln)]


def _is_front_view(vw, w_mm):
    """正面/平面主视图：含一条 ≈ 整体宽 W 的横向尺寸线（其内部分段不能当深度）。"""
    return any(tot >= 0.9 * w_mm for tot, _ in _h_totals(vw))


def _depth_from_side_view(page, w_mm, h_mm, strong_only=False):
    """几何法读深度，按「最外侧尺寸线才算外形」分档（依次尝试，先命中先返回）：
      T1 **平面图竖向深度**：正面图正上方那张「竖向主导」的平面/俯视图，其竖向外形即深度
         （书桌类：深度 400 画在俯视图上、方向是竖的）。
      T2 **窄侧视链**：某簇一条干净的横向尺寸链（最外≈各段和）、且深度 < 0.25·W —— 真正的窄侧视
         （挂衣套装 20+150=170、标识牌 60）。避开大尺寸的内部链与零件详图。
      T3 **重复外形线**：同一深度值出现在 ≥2 条横线上（端视图上下各标一次，如 1300），取最大 ——
         多体产品（大长桌+标识）取最外体的进深。
      T4 **最外线段和**：非正面视图里最外那条横线的分段之和（返却台 670+30=700）。
    T1–T3 为「强档」（信号明确，可盖过同族借用）；T4 为「弱档」（同族借用更可信时让位）。
    `strong_only=True` 只跑 T1–T3。均无果返回 None（留空标黄、绝不臆造）。"""
    try:
        h_lines, v_lines = _segments(page.get_drawings())
        toks = _dim_tokens(page.get_text("words"))
    except Exception:  # noqa: BLE001
        return None
    if not toks or not h_mm or not w_mm:
        return None
    pts = [(v, cx, cy, _orient(cx, cy, h_lines, v_lines)) for (v, cx, cy) in toks]
    views_pts = _cluster(pts)
    fronts = [vw for vw in views_pts if _is_front_view(vw, w_mm)]

    # T1) 平面图竖向深度：整簇位于正面图之上、竖向外形主导（按 token 真实朝向判断）、且 < 0.7H。
    front_top = min((p[2] for vw in fronts for p in vw), default=None)
    if front_top is not None:
        planv = []
        for vw in views_pts:
            if vw in fronts or max(p[2] for p in vw) > front_top:
                continue
            mv = max((p[0] for p in vw if p[3] == "v"), default=0)
            mh = max((p[0] for p in vw if p[3] == "h"), default=0)
            if mv and mv < 0.7 * h_mm and mv > 1.5 * max(mh, 1):
                planv.append(mv)
        if planv:
            return max(planv)

    # T2) 窄侧视链：干净链且 < 0.25W。
    narrow = []
    for vw in views_pts:
        if vw in fronts:
            continue
        hs = [p[0] for p in vw if p[3] == "h" and p[0] < 0.9 * w_mm]
        c = _is_chain(hs)
        if c is not None and c < 0.25 * w_mm:
            narrow.append(c)
    if narrow:
        return max(narrow)

    # T3) 重复外形线：同一深度值出现在 ≥2 条横线上（跨所有簇），取最大。
    all_totals = [int(round(tot)) for vw in views_pts for tot, _n in _h_totals(vw)
                  if 40 <= tot < 0.9 * w_mm]
    repeated = [v for v in set(all_totals) if all_totals.count(v) >= 2]
    if repeated:
        return max(repeated)

    if strong_only:                 # 弱档（T4）让位于同族借用
        return None
    # T4) 最外线段和（只在非正面视图里，避开正面图内部分段）。
    nonfront = [int(round(tot)) for vw in views_pts if vw not in fronts
                for tot, _n in _h_totals(vw) if 40 <= tot < 0.9 * w_mm]
    return max(nonfront) if nonfront else None


_WDIFF_RE = re.compile(r"[（(]\s*[WwＷ]\s*([-+－＋])\s*(\d{2,4})\s*[)）]")


def read_width_diff(page):
    """读图上「尺寸差」修正注记（如「…のサイズ違い（W-100）」）→ 返回宽度增量（-100）。
    这是图纸自带的机器可读修正（同款变体常只标一句 W±N），据此把整体宽改对，仍是「依据图纸」。
    无此注记返回 0。"""
    try:
        m = _WDIFF_RE.search(page.get_text())
    except Exception:  # noqa: BLE001
        return 0
    if not m:
        return 0
    sign = -1 if m.group(1) in "-－" else 1
    return sign * int(m.group(2))


def read_depth_prefix(page, w_mm=None):
    """只取显式「D 前缀」深度注记（最可靠）。读不出返回 None。"""
    try:
        return _prefixed_depth(page.get_text("words"), w_mm)
    except Exception:  # noqa: BLE001
        return None


def read_depth_geometry(page, w_mm=None, h_mm=None, strong_only=False):
    """几何法读深度。strong_only=True 只跑强档 T1–T3（信号明确，跑在同族借用之前、可盖过借用）；
    默认跑全部（含弱档 T4，跑在同族借用之后兜底）。读不出返回 None。"""
    return _depth_from_side_view(page, w_mm, h_mm, strong_only=strong_only)


def read_depth_mm(page, w_mm=None, h_mm=None):
    """确定性读取「深度 D」(mm)：先取显式「D 前缀」注记，再退回侧视图几何法。
    读不出返回 None（宁留空标黄、不臆造，绝不参考外部 Excel）。"""
    d = read_depth_prefix(page, w_mm)
    if d is not None:
        return d
    return _depth_from_side_view(page, w_mm, h_mm)
