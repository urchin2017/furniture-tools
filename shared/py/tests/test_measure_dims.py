"""measure_dims 几何量取：整体宽/高外形读取，尤其「最外侧尺寸线」的边距补齐。"""
from __future__ import annotations

import fitz

from skills.drawing_to_quotation import measure_dims as md


def _page():
    doc = fitz.open()
    return doc, doc.new_page(width=1200, height=842)


def _hdim(pg, x0, x1, y, label):
    pg.draw_line(fitz.Point(x0, y), fitz.Point(x1, y))
    pg.insert_text(((x0 + x1) / 2 - 6, y - 8), str(label), fontsize=8)


def _vdim(pg, y0, y1, x, label):
    pg.draw_line(fitz.Point(x, y0), fitz.Point(x, y1))
    pg.insert_text((x - 20, (y0 + y1) / 2), str(label), fontsize=8)


def test_extend_with_margins_sums_side_gaps_into_width():
    """挂衣套装：宽度画成 22│886│22（两端 22 的线太短/<30 被丢），
    整体宽应补成 886+22+22=930（最外侧尺寸线才算外形）。"""
    doc, pg = _page()
    # 主宽段 886（长线，能被检出）
    _hdim(pg, 220, 640, 300, 886)
    # 两侧各一小段 22（线很短），数字贴在主段两端外侧、同一行
    pg.insert_text((205, 292), "22", fontsize=8)
    pg.insert_text((648, 292), "22", fontsize=8)
    # 高度给一条，凑出比例尺
    _vdim(pg, 120, 300, 190, 700)
    m = md.measure_page(pg)
    assert m["W"]["overall_value"] == 930, m["W"].get("overall_value")
    assert m["W"].get("margin_added") == [22, 22]


def test_extend_with_margins_not_added_when_overall_is_full_line():
    """整体宽本就是一条完整外形线（内部小数落在其跨度内）→ 不重复补边距。"""
    doc, pg = _page()
    _hdim(pg, 200, 620, 300, 700)      # 完整外形线 700
    pg.insert_text((205, 285), "10", fontsize=8)   # 内部小数，在 700 线跨度内
    pg.insert_text((610, 285), "10", fontsize=8)
    _vdim(pg, 120, 300, 190, 770)
    m = md.measure_page(pg)
    assert m["W"]["overall_value"] == 700, "内部小数不该被重复加成 720"


def test_vector_ok_probe_matches_measure_page_on_vector_and_blank():
    """轻量探测的 vector_ok 必须与 measure_page 的判定逐页一致（判断预览与生成分流同源）。"""
    doc, pg = _page()
    _hdim(pg, 220, 640, 300, 886)
    _vdim(pg, 120, 300, 190, 700)
    assert md.vector_ok_probe(pg) is True
    assert md.measure_page(pg)["vector_ok"] is True

    # 空白页（无任何矢量线）→ 两者都判 False
    doc2 = fitz.open()
    blank = doc2.new_page(width=800, height=600)
    assert md.vector_ok_probe(blank) is False
    assert md.measure_page(blank)["vector_ok"] is False
