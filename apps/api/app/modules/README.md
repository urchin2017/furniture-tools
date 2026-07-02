# 后端功能模块占位

按三大模块组织，功能实现留给各自 session（每个 session 只写自己的子目录）：

| 子目录 | 来源 skill |
|---|---|
| `quote/generate` | `drawing-to-quotation-2026-07-02-v5`（原 `-2026-07-01-v3` 已下架） |
| `quote/compare` | `excel-quote-compare-2026-03-24` |
| `drawings/translate` | `drawing-translator-2026-04-21` |
| `drawings/revision_diff` | `drawing-revision-diff-remark-2026-06-01`（单品）/ `zhengtao-tuzhi-gaiban-chayi-2026-06-02`（整套） |
| `shipping_marks` | `product-list-to-shipping-marks-2026-04-23`（先占位） |

搬运约定：机械脚本原样复用，判断步骤改调 `shared/py/claude_client`。术语相关调 `shared/py/glossary`（单一真相源）。
