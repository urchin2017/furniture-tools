# shared/py/skills · 从 skill 搬来的机械脚本

各模块 session 把对应 skill 的**机械脚本**（PyMuPDF/openpyxl/裁图/渲染/weasyprint/reportlab，
可原样复用的部分）搬进这里，判断步骤改调 `claude_client`。当前为占位。

搬运来源（skill 磁盘路径见 plan 的「路线图」）：

- **报价生成** ← `drawing-to-quotation-2026-07-01-v3`：`measure_dims.py`(几何量取)、
  `extract_scaffold.py`(文字层分诊+渲染)、`fill_quote.py`(openpyxl 填表)、`render_check.py`(LibreOffice 渲染验证)。
  「定尺寸」低置信时改调 `claude_client.complete_vision`。日→中术语调 `glossary.load_map("ja","zh")`。
- **报价对比** ← `excel-quote-compare-2026-03-24`：`generate_report.py`(openpyxl 解析 + weasyprint 出 PDF)，纯脚本。
- **图纸翻译** ← `drawing-translator-2026-04-21`：`translate_drawings.py`(内嵌 EN_DICT/JP_DICT 换成 `glossary.load_map`)、
  `positioning_utils.py`、`rasterize_overlay.py`；45s bash hack 改成 `tasks/runner.py` 异步 + 进度轮询。
- **改版差异** ← `drawing-revision-diff-remark-2026-06-01`(单品) / `zhengtao-tuzhi-gaiban-chayi-2026-06-02`(整套)：
  `extract_and_render.sh`、`annotate_remark.py`、`html_to_pdf.py`；「真改动 vs 文字回流」核对调 `claude_client.complete_vision`。
- **唛头** ← `product-list-to-shipping-marks-2026-04-23`：`parse_source.py`、`fill_target.py`、`report.py`(纯脚本)；
  元数据缺失（PI/PO）从 AskUserQuestion 改成网页表单（jobs `needs_input`）。
