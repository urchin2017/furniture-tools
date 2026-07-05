"""矢量图「确定性读尺寸」vector_read 全面测试。

覆盖六类：单元 / 集成 / 回归 / 边界·异常 / 端到端 / 黄金快照。
全部用**合成 PDF 页**复现真实图纸的标注模式（不落任何客户机密图纸），
每个场景对应 D 级联的一档或一个已修复的 bug，可复现、可回归。
"""
from __future__ import annotations

import fitz
import pytest

from app.modules.quote import vector_read as vr


# ── 合成图纸小工具：造一页，画线 + 写尺寸数字 ─────────────────────────────
def _page(width=1200, height=842):
    doc = fitz.open()
    return doc, doc.new_page(width=width, height=height)


def _hdim(pg, x0, x1, y, label):
    """一条横向尺寸线 + 数字（贴线上方）。"""
    pg.draw_line(fitz.Point(x0, y), fitz.Point(x1, y))
    pg.insert_text(((x0 + x1) / 2 - 6, y - 8), str(label), fontsize=8)


def _vdim(pg, y0, y1, x, label):
    """一条竖向尺寸线 + 数字（贴线左侧）。"""
    pg.draw_line(fitz.Point(x, y0), fitz.Point(x, y1))
    pg.insert_text((x - 18, (y0 + y1) / 2), str(label), fontsize=8)


# ══════════════════════════════ 一、单元测试 ══════════════════════════════
def test_dim_regex_accepts_prefixes_units_and_range():
    words = [(0, 0, 9, 9, t) for t in ("W1000", "D=500", "745mm", "φ30", "1316")]
    vals = sorted(v for (v, _cx, _cy) in vr._dim_tokens(words))
    assert vals == [30, 500, 745, 1000, 1316]


def test_dim_regex_rejects_nonnumbers_and_out_of_range():
    words = [(0, 0, 9, 9, t) for t in ("abc", "R", "5", "99999", "CIY_B-01", "")]
    assert vr._dim_tokens(words) == []


def test_prefixed_depth_takes_outermost_max():
    words = [(0, 0, 9, 9, t) for t in ("D500", "D=520", "d80")]
    assert vr._prefixed_depth(words) == 520          # 多个 D 取最外/最大


def test_prefixed_depth_none_when_absent():
    words = [(0, 0, 9, 9, t) for t in ("W1000", "H745", "500")]
    assert vr._prefixed_depth(words) is None          # 无 D 前缀 → None（不误取裸数）


def test_prefixed_depth_ignores_out_of_range():
    words = [(0, 0, 9, 9, t) for t in ("D5", "D9999")]
    assert vr._prefixed_depth(words) is None


def test_is_chain_detects_segment_sum():
    assert vr._is_chain([20, 150, 170]) == 170        # 170 = 20+150
    assert vr._is_chain([60, 60]) == 60               # 两段相等（同尺寸重复标注）
    assert vr._is_chain([180, 400, 635, 670]) is None  # 670 ≠ 180+400+635
    assert vr._is_chain([500]) is None                # 单段不成链


def test_cluster_splits_views_by_position():
    pts = [(100, 100, 100, "h"), (110, 120, 110, "h"),   # 左视图
           (200, 900, 100, "h"), (210, 920, 110, "h")]   # 右视图（相距远）
    groups = vr._cluster(pts)
    assert len(groups) == 2


# ══════════════════════════════ 二、集成：D 四级级联优先级 ═══════════════════
def test_prefix_beats_geometry_in_cascade():
    """read_depth_mm：显式 D 前缀优先于几何法。"""
    doc, pg = _page()
    pg.insert_text((300, 400), "D500", fontsize=8)     # 前缀 → 500
    _hdim(pg, 800, 940, 200, 670)                       # 侧视也有个 670，但应被前缀压过
    _hdim(pg, 800, 948, 200, 30)
    assert vr.read_depth_mm(doc[0], w_mm=1800, h_mm=1360) == 500


def test_geometry_matchH_side_view():
    """几何 A 档：与整体高同高的侧视图，横向即深度。"""
    doc, pg = _page()
    _hdim(pg, 60, 400, 300, 1800)      # 正面宽 W=1800
    _vdim(pg, 120, 300, 55, 1360)      # 正面高 H
    _hdim(pg, 800, 900, 200, 500)      # 侧视横向 500（<0.9W）
    _hdim(pg, 800, 880, 230, 300)      # 侧视第二条横向（满足≥2条）
    _vdim(pg, 200, 500, 790, 1360)     # 侧视竖向 ≈ H → 判为侧视
    assert vr.read_depth_geometry(doc[0], w_mm=1800, h_mm=1360) == 500


def test_geometry_chain_when_no_matchH():
    """几何 B 档：无同高侧视，但有横向尺寸链 20+150=170。"""
    doc, pg = _page()
    _hdim(pg, 800, 820, 200, 20)
    _hdim(pg, 820, 970, 200, 150)
    _hdim(pg, 800, 970, 180, 170)
    assert vr.read_depth_geometry(doc[0], w_mm=886, h_mm=1316) == 170


def test_geometry_segment_sum_outermost_line():
    """几何 C 档：最外线被分段 670│30（无显式合计）→ 段和 700，正面≈W 那条跳过。"""
    doc, pg = _page()
    _hdim(pg, 60, 400, 300, 1800)      # 正面整体宽线（跳过）
    _vdim(pg, 120, 300, 55, 1360)
    pg.draw_line(fitz.Point(800, 200), fitz.Point(940, 200))
    pg.insert_text((850, 192), "670", fontsize=8)
    pg.draw_line(fitz.Point(940, 200), fitz.Point(948, 200))
    pg.insert_text((944, 192), "30", fontsize=8)       # 与 670 共线（同 cy）
    _hdim(pg, 805, 940, 500, 635)                       # 底座单段 635（<700）
    assert vr.read_depth_geometry(doc[0], w_mm=1800, h_mm=1360) == 700


def test_geometry_plan_view_vertical_depth():
    """T1 平面图竖向深度：正面图正上方那张俯视图，深度画成竖向（书桌 400）。"""
    doc, pg = _page()
    # 俯视图（上方）：竖向外形 400（15+385），横向只有很小的 R 角注记
    _vdim(pg, 120, 300, 300, 400)
    _vdim(pg, 130, 300, 320, 385)
    _hdim(pg, 300, 320, 305, 60)
    # 正面立面（下方）：宽 1000、高 745
    _hdim(pg, 200, 560, 620, 1000)
    _vdim(pg, 480, 620, 190, 745)
    assert vr.read_depth_geometry(doc[0], w_mm=1000, h_mm=745, strong_only=True) == 400


def test_geometry_repeated_overall_takes_max():
    """T3 重复外形线：同一深度值在≥2 条横线上出现（端视图上下各标一次 1300）→ 取最大，
    盖过同高侧视里更小但更“干净”的 1140。"""
    doc, pg = _page()
    # 深度 1300：端视图上、下各一条（595+110+595 / 425+450+425 无显式合计）
    for y in (250, 500):
        _hdim(pg, 100, 175, y, 595)
        _hdim(pg, 175, 189, y, 110)
        _hdim(pg, 189, 264, y, 595)
    # 另一处标识座 1140（单条），不应压过 1300
    _hdim(pg, 800, 900, 300, 1140)
    _vdim(pg, 120, 300, 795, 2700)
    assert vr.read_depth_geometry(doc[0], w_mm=4000, h_mm=2700, strong_only=True) == 1300


# ══════════════════════════════ 三、回归：锁死已修复的 bug ═══════════════════
def test_regression_hb02_reads_170_not_radius_note():
    """HB-02：曾误读 R30 的 30；应读侧视外形链 20+150=170。"""
    doc, pg = _page()
    _hdim(pg, 300, 320, 200, 20)
    _hdim(pg, 320, 470, 200, 150)
    _hdim(pg, 300, 470, 180, 170)
    pg.insert_text((520, 260), "30", fontsize=8)        # 孤立的 R30 注记（无线、无链）
    assert vr.read_depth_geometry(doc[0], w_mm=886, h_mm=1316) == 170


def test_regression_l03_reads_60_not_gap_note():
    """L-03：曾误读缝隙 20；侧视 60 成对出现（60,60）→ 60。"""
    doc, pg = _page()
    pg.insert_text((300, 300), "20", fontsize=8)        # 孤立缝隙 20（应被忽略）
    _hdim(pg, 800, 860, 200, 60)
    _hdim(pg, 800, 860, 260, 60)
    assert vr.read_depth_geometry(doc[0], w_mm=700, h_mm=770) == 60


def test_regression_l02_reads_700_segment_sum():
    """L-02：曾留空；最外线 670+30=700。"""
    doc, pg = _page()
    _hdim(pg, 60, 400, 300, 1800)
    _vdim(pg, 120, 300, 55, 1360)
    pg.draw_line(fitz.Point(800, 200), fitz.Point(940, 200))
    pg.insert_text((850, 192), "670", fontsize=8)
    pg.draw_line(fitz.Point(940, 200), fitz.Point(948, 200))
    pg.insert_text((944, 192), "30", fontsize=8)
    assert vr.read_depth_geometry(doc[0], w_mm=1800, h_mm=1360) == 700


# ══════════════════════════════ 四、边界 / 异常 ══════════════════════════════
class _TextPage:
    def __init__(self, text):
        self._t = text

    def get_text(self, *_a, **_k):
        return self._t


def test_read_width_diff_note():
    """图上「サイズ違い（W-100）」尺寸差注记 → 宽度增量 -100（据此把 W2000 改成 1900）。"""
    assert vr.read_width_diff(_TextPage("CIY_B-03のサイズ違い（W-100）")) == -100
    assert vr.read_width_diff(_TextPage("variant (W+50)")) == 50       # 半角括号/加号
    assert vr.read_width_diff(_TextPage("ヘッドボード")) == 0            # 无注记 → 0


def test_empty_page_returns_none():
    doc, _pg = _page()
    assert vr.read_depth_mm(doc[0], w_mm=1000, h_mm=1000) is None


def test_bitmap_page_no_vectors_geometry_none_but_prefix_ok():
    """位图页（无矢量线）：几何法读不到；但若文字层有 D 前缀仍可读。"""
    doc, pg = _page()
    pg.insert_text((300, 400), "500", fontsize=8)       # 只有裸数、无线
    assert vr.read_depth_geometry(doc[0], w_mm=1000, h_mm=1000) is None
    pg.insert_text((300, 420), "D480", fontsize=8)
    assert vr.read_depth_prefix(doc[0]) == 480


def test_geometry_none_without_w_or_h():
    doc, pg = _page()
    _hdim(pg, 800, 900, 200, 500)
    assert vr.read_depth_geometry(doc[0], w_mm=None, h_mm=1360) is None
    assert vr.read_depth_geometry(doc[0], w_mm=1800, h_mm=None) is None


def test_lone_note_rejected_returns_none():
    """只有一个孤立小数字（非链、非同高侧视）→ None，宁留空不臆造。"""
    doc, pg = _page()
    _hdim(pg, 800, 810, 200, 20)
    assert vr.read_depth_geometry(doc[0], w_mm=700, h_mm=770) is None


def test_only_front_view_returns_none():
    """整页只有正面图（W 宽线 + H 高线），没有侧视 → 深度读不出。"""
    doc, pg = _page()
    _hdim(pg, 60, 400, 300, 1800)
    _vdim(pg, 120, 300, 55, 1360)
    assert vr.read_depth_geometry(doc[0], w_mm=1800, h_mm=1360) is None


def test_get_drawings_exception_is_swallowed():
    class _Boom:
        def get_text(self, *_a, **_k):
            return []

        def get_drawings(self):
            raise RuntimeError("boom")

    assert vr.read_depth_geometry(_Boom(), w_mm=1000, h_mm=1000) is None
    assert vr.read_depth_prefix(_Boom()) is None


# ══════════════════════════════ 五 & 六、端到端 + 黄金快照 ════════════════════
# 逐场景「模式 → 期望深度」黄金表：任一档逻辑回退都会被这张表抓到。
_GOLDEN = {
    "prefix_D500": 500,
    "chain_20_150": 170,
    "seg_sum_670_30": 700,
    "pair_60_60": 60,
    "lone_note_20": None,
    "front_only": None,
}


def _build(scenario):
    doc, pg = _page()
    if scenario == "prefix_D500":
        pg.insert_text((300, 400), "D500", fontsize=8)
    elif scenario == "chain_20_150":
        _hdim(pg, 800, 820, 200, 20); _hdim(pg, 820, 970, 200, 150); _hdim(pg, 800, 970, 180, 170)
    elif scenario == "seg_sum_670_30":
        _hdim(pg, 60, 400, 300, 1800); _vdim(pg, 120, 300, 55, 1360)
        pg.draw_line(fitz.Point(800, 200), fitz.Point(940, 200)); pg.insert_text((850, 192), "670", fontsize=8)
        pg.draw_line(fitz.Point(940, 200), fitz.Point(948, 200)); pg.insert_text((944, 192), "30", fontsize=8)
    elif scenario == "pair_60_60":
        _hdim(pg, 800, 860, 200, 60); _hdim(pg, 800, 860, 260, 60)
    elif scenario == "lone_note_20":
        _hdim(pg, 800, 810, 200, 20)
    elif scenario == "front_only":
        _hdim(pg, 60, 400, 300, 1800); _vdim(pg, 120, 300, 55, 1360)
    return doc[0]


@pytest.mark.parametrize("scenario,expected", list(_GOLDEN.items()))
def test_golden_snapshot_depth_by_scenario(scenario, expected):
    """黄金快照：每种标注模式读出的深度必须与固化值一致（回归护栏）。"""
    got = vr.read_depth_mm(_build(scenario), w_mm=1800, h_mm=1360)
    assert got == expected, f"[{scenario}] 期望 {expected}，实际 {got}"
