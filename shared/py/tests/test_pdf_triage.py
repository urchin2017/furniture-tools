"""pdf_triage 单元测试：happy + 边界（min_chars / coverage / vec 三个门）+ 异常。无网络。"""
import pathlib

import pytest

fitz = pytest.importorskip("fitz")  # PyMuPDF 未装则跳过

from pdf_triage import PageKind, render_page_png, triage_pdf  # noqa: E402

_LONG = "壁面 W1200 D600 H750 収納棚 化粧板 メラミン 天板 t25 施工図 詳細 断面"  # >40 字符


def _build(tmp_path: pathlib.Path) -> str:
    """4 页：0=长文本+矢量矩形, 1=仅长文本, 2=短文本+矢量矩形, 3=空白。"""
    doc = fitz.open()
    p0 = doc.new_page()
    p0.insert_text((72, 72), _LONG)
    p0.draw_rect(fitz.Rect(40, 120, 520, 400), color=(0, 0, 0), width=1)
    p1 = doc.new_page()
    p1.insert_text((72, 72), _LONG)
    p2 = doc.new_page()
    p2.insert_text((72, 72), "abc")  # <40 字符
    p2.draw_rect(fitz.Rect(40, 120, 520, 400), color=(0, 0, 0), width=1)
    doc.new_page()  # p3 空白
    out = str(tmp_path / "multi.pdf")
    doc.save(out)
    doc.close()
    return out


def test_default_thresholds(tmp_path):
    pages = triage_pdf(_build(tmp_path))
    assert [p.kind for p in pages] == [
        PageKind.VECTOR_TEXT,  # 长文本 + 矢量
        PageKind.VECTOR_TEXT,  # 仅长文本（走 coverage 门）
        PageKind.SCAN_RASTER,  # 短文本 <40，chars 门挡住
        PageKind.SCAN_RASTER,  # 空白
    ]
    assert pages[0].has_vector_segments is True
    assert pages[1].has_vector_segments is False
    assert pages[2].has_vector_segments is True  # 有矩形但仍被 chars 门挡为 SCAN
    assert pages[3].char_count == 0
    # VECTOR_TEXT 页带 text_blocks，SCAN 页不带
    assert pages[0].text_blocks and not pages[3].text_blocks


def test_vec_gate_isolated(tmp_path):
    """把 min_coverage 抬到 0.99，隔离出「靠矢量」和「靠覆盖率」两条路径。"""
    pages = triage_pdf(_build(tmp_path), min_coverage=0.99)
    # p0 长文本+矢量：coverage 达不到 0.99，但 has_vec=True → 仍 VECTOR
    assert pages[0].kind is PageKind.VECTOR_TEXT
    # p1 仅长文本：无矢量且 coverage<0.99 → SCAN（证明 coverage 门此时失效、vec 门决定）
    assert pages[1].kind is PageKind.SCAN_RASTER


def test_min_chars_boundary(tmp_path):
    """min_chars 阈值：仅长文本页在 min_chars 超过其字数时降级为 SCAN。"""
    pdf = _build(tmp_path)
    n = triage_pdf(pdf)[1].char_count
    assert triage_pdf(pdf, min_chars=n)[1].kind is PageKind.VECTOR_TEXT  # 恰好达标
    assert triage_pdf(pdf, min_chars=n + 1)[1].kind is PageKind.SCAN_RASTER  # 差 1 即降级


def test_render_page_png_ok(tmp_path):
    png = render_page_png(_build(tmp_path), 0, dpi=100)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 100


def test_render_bad_index_raises(tmp_path):
    with pytest.raises(Exception):
        render_page_png(_build(tmp_path), 999)


def test_triage_missing_file_raises():
    with pytest.raises(Exception):
        triage_pdf("/no/such/file_xyz.pdf")
