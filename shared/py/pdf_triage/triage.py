"""PyMuPDF 文本层分流 —— 成本控制的关键分叉。

有文本层的矢量 CAD 页走廉价文字提取；扫描/手绘/曲线化的页才送视觉模型（最贵）。
判据与报价 skill 的 measure_dims 的 vector_ok 一致，可交叉复用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PageKind(str, Enum):
    VECTOR_TEXT = "vector_text"  # 有文本层 + 矢量线 → 廉价文字提取
    SCAN_RASTER = "scan_raster"  # 几乎无文本 / 曲线化 → 送视觉模型


@dataclass
class PageTriage:
    page_index: int
    kind: PageKind
    char_count: int  # get_text("text") 去空白后的字符数
    text_coverage: float  # 文本块 bbox 面积和 / 页面积
    has_vector_segments: bool  # 是否有矢量绘制（get_drawings）
    text_blocks: list = field(default_factory=list)  # VECTOR_TEXT 时的文本块（get_text("dict")）


def triage_pdf(
    pdf_path: str, *, min_chars: int = 40, min_coverage: float = 0.002
) -> list[PageTriage]:
    """逐页判定 VECTOR_TEXT vs SCAN_RASTER。仅依赖 pymupdf。

    判据：chars>=min_chars 且 (有矢量绘制 或 文本覆盖率>=min_coverage) → VECTOR_TEXT，否则 SCAN_RASTER。
    """
    import fitz  # PyMuPDF

    out: list[PageTriage] = []
    doc = fitz.open(pdf_path)
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = page.get_text("text") or ""
            chars = len(text.strip())
            has_vec = len(page.get_drawings()) > 0

            page_area = float(page.rect.width * page.rect.height) or 1.0
            block_area = 0.0
            blocks = []
            for b in page.get_text("dict").get("blocks", []):
                if b.get("type", 0) != 0:  # 只算文本块（type==0）
                    continue
                x0, y0, x1, y1 = b.get("bbox", (0, 0, 0, 0))
                block_area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
                blocks.append(b)
            coverage = block_area / page_area

            is_vec = chars >= min_chars and (has_vec or coverage >= min_coverage)
            kind = PageKind.VECTOR_TEXT if is_vec else PageKind.SCAN_RASTER
            out.append(
                PageTriage(
                    page_index=i,
                    kind=kind,
                    char_count=chars,
                    text_coverage=round(coverage, 5),
                    has_vector_segments=has_vec,
                    text_blocks=blocks if kind is PageKind.VECTOR_TEXT else [],
                )
            )
        return out
    finally:
        doc.close()


def render_page_png(pdf_path: str, page_index: int, *, dpi: int = 150) -> bytes:
    """把某页渲染成 PNG bytes（供 SCAN_RASTER 页 / 视觉兜底喂给 claude_client）。"""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        pix = doc.load_page(page_index).get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()
