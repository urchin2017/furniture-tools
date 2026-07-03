# shared/py/skills · 从 skill 搬来的机械脚本

各模块 session 把对应 skill 的**机械脚本**（PyMuPDF/openpyxl/裁图/渲染/weasyprint/reportlab，
可原样复用的部分）搬进这里，判断步骤改调 `claude_client`。

搬运来源（skill 磁盘路径见 plan 的「路线图」）：

- **报价生成 ✅ 已搬入 `drawing_to_quotation/`（2026-07-02）** ← `drawing-to-quotation-2026-07-02-v5`
  （原 `-2026-07-01-v3` 已下架）。6 个脚本 + references + SKILL.md 原样搬入，仅加 import 入口
  （`build_scaffold`/`fill_quote_build`/`render_xlsx`；fill_quote 的 `sys.exit` 改抛 `QuoteAuditError`，
  否则后台任务里 SystemExit 绕过 runner 兜底）。判断步骤「定外形尺寸」在
  `apps/api/app/modules/quote/{prompts,dims}.py`（complete_vision）。四步管线（顺序不可省）+ 1 个辅助脚本：
  1. `extract_scaffold.py` —— 文字层分诊 + **光栅页判定**(矢量层无线条+整页大图 → 打 `⚠ RASTER` 警告，
     强制走看图协议，不静默跳过) + 生成 `products.json` 骨架（含款号缩写`F07，07A`展开、数量解析）。
  2. **定外形尺寸**（判断步骤，非脚本）：矢量图纸优先用 `measure_dims.py` 的双信号几何量取
     （尺度一致性 + 跨度×比例尺，双重交叉核对锁定外形，非文本注记）；光栅图纸或几何低置信时走
     「看图协议」，配合 `render_pages.py`（整页高 DPI 渲染，不裁剪不涂白，可选四象限放大）改调
     `claude_client.complete_vision` 人工/视觉核对——铁律：文本层 W/D/H 注记只当线索，绝不直接采用，
     外形以图面「最外侧尺寸链」为准（造作家具含フィラー/按 CH 天井高基准）。
  3. `fill_quote.py` —— 从 `products.json` 填 Excel 报价模板，非视觉确认的记录加 ⚠ 高亮，日中双语排版规范；
     无照片时用 `crop_drawings.py`（去文字块+表题栏+白边，统一画布尺寸）从图纸裁产品参考图。
  4. `render_check.py` —— 转 PDF 再渲染 PNG，供目视验证无溢出/对齐/数据正确（需 LibreOffice）。

  日→中术语调 `glossary.load_map("ja","zh")`。`products.json` 字段结构见 skill 包内 `references/data_schema.md`。
- **报价对比** ← `excel-quote-compare-2026-03-24`：`generate_report.py`(openpyxl 解析 + weasyprint 出 PDF)，纯脚本。
- **图纸翻译** ← `drawing-translator-2026-04-21`：`translate_drawings.py`(内嵌 EN_DICT/JP_DICT 换成 `glossary.load_map`)、
  `positioning_utils.py`、`rasterize_overlay.py`；45s bash hack 改成 `tasks/runner.py` 异步 + 进度轮询。
- **改版差异** ← `drawing-revision-diff-remark-2026-06-01`(单品) / `zhengtao-tuzhi-gaiban-chayi-2026-06-02`(整套)：
  `extract_and_render.sh`、`annotate_remark.py`、`html_to_pdf.py`；「真改动 vs 文字回流」核对调 `claude_client.complete_vision`。
- **唛头** ← `product-list-to-shipping-marks-2026-04-23`：`parse_source.py`、`fill_target.py`、`report.py`(纯脚本)；
  元数据缺失（PI/PO）从 AskUserQuestion 改成网页表单（jobs `needs_input`）。
