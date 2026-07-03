"""drawing-to-quotation-2026-07-02-v5 的机械脚本（原样搬运，仅加 import 入口）。

四步管线（顺序不可省，见 SKILL.md）：
  ① extract_scaffold.build_scaffold —— 文字层分诊 + 光栅判定 + 整页渲染 + products.json 骨架
  ② 定外形尺寸（判断步骤，**不在本包**）：apps/api/app/modules/quote 里改调
     claude_client.complete_vision，看图读「最外侧尺寸链」
  ③ fill_quote.build —— 从 products.json 填 Excel 模板（含视觉确认闸门 ⚠ 高亮）
  ④ render_check.render_xlsx —— xlsx→pdf→png 渲染目视验证（需 LibreOffice）

辅助：measure_dims.measure_page（矢量几何量取）、render_pages.render_page（高DPI看图渲染）、
crop_drawings.crop_page（报价单参考缩略图裁剪）。
references/ 与 SKILL.md 原样保留——SKILL.md 的 prose 是判断步骤的 system prompt 来源。
"""
from .extract_scaffold import build_scaffold
from .fill_quote import QuoteAuditError, build as fill_quote_build
from .render_check import render_xlsx
from .render_pages import render_page as render_page_png

__all__ = [
    "build_scaffold",
    "fill_quote_build",
    "QuoteAuditError",
    "render_xlsx",
    "render_page_png",
]
