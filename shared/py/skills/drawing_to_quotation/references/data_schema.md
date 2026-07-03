# products.json 数据格式（drawing-to-quotation-2026-07-02-v5）

用一份结构化 JSON 作为「图纸 → 报价单」的中间数据层。
`extract_scaffold.py` 生成骨架（尺寸留空），看图读尺寸后填好，再交 `fill_quote.py` 渲染。
**关键设计：尺寸不写死在代码里，而是必须几何/看图确认后写进 JSON。**

## V5 新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `qty_hint` | int / null | 文字层解析的数量候选（「数量：2pcs」「F04：2台」「各3pcs」）。**仅候选**，看图确认后才填 `qty`。 |
| `text_dims_note` | str | 当 text_dims 有值时自动附上的警示：注记可能是局部/本体/分段尺寸，外形认最外侧尺寸链。 |
| `measured.raster_page` | bool | **光栅图纸页标记**：图纸本体是位图，几何引擎不可用，必须走看图协议。 |

## 顶层结构

```json
{
  "project": "石垣島美咲町ビル",   // 项目名，写入模板 C11（也可用 --project 覆盖）
  "products": [ { …一条=一行… }, … ]
}
```

## 每条产品记录（= 报价单一行）

| 字段 | 类型 | 说明 |
|------|------|------|
| `row_code` | str | **品番**（如 `F01`）。**一个品番一条记录**；`F01`/`F01A` 是两条，绝不合并。 |
| `page` | int | 该产品所在图纸页码（**1-based**），用于裁剪参考缩略图。 |
| `page_image` | str | 该页整页图路径（看图读尺寸时用；渲染不依赖它）。 |
| `name_jp` / `name_cn` | str | 日/中商品名（填入 C 列，空行分隔）。 |
| `mat_jp` / `mat_cn` | list[str] | 日/中材质规格逐条（填入 E 列，空行分隔）。 |
| `W` / `D` / `H` | int / null | **外形/全体寸法(mm)**。骨架里是 `null`，**必须看图确认后填**。 |
| `qty` | int / null | 该品番数量（**这个型号自己的数量**，不与其它型号相加）。 |
| `dim_source` | str | `"PENDING"`(未定) / `"geometry"`(几何量取确认) / `"visual"`(看图确认) / `"text"`(仅文字层,需复核)。 |
| `dim_evidence` | str | 一句话记「采用了哪条尺寸线/哪个 measured 值」。 |
| `measured` | obj | **（V3 核心）** `measure_dims.py` 的几何量取结果，定尺寸时**优先看这里**（见下）。 |
| `text_dims` | obj | 文字层抽到的 W/D/H 候选，仅作再参考。 |
| `note_jp` / `note_cn` | str | 日/中备考（填入 N 列，空行分隔）。 |

## `measured` 结构（几何量取，定外形优先看它）

```json
"measured": {
  "vector_ok": true,            // false=扫描/曲线化，回退看图协议
  "scale_mm_per_px": 3.0,       // 共识比例尺
  "confidence": "high",         // high/mid/low
  "W": {
    "overall_value": 1200,      // 尺度过滤后标注最大的线=外形宽（首选）
    "overall_by_extent": 1200,  // 最长线跨度×比例尺（兜底/交叉核对）
    "chain_sum": 1200,          // 局部段之和，应≈overall_value
    "chain_ok": true, "extent_ok": true,
    "suspect_local": false,     // true=很可能读到了局部！改用 overall_by_extent
    "band_overalls": [ {"value":1200,...}, {"value":450,...} ]  // 各视图带外形→侧视图那带即 D
  },
  "H": { …同上… }
}
```

**取值优先级**（也写在 SKILL Step 2）：
1. `confidence=="high"` 且该轴 `suspect_local==false`、`extent_ok==true` → 用 `overall_value`，`dim_source="geometry"`。
2. `suspect_local==true` 或 `extent_ok==false` → 用 `overall_by_extent`，Read 整页图核对后 `dim_source="visual"`。
3. `vector_ok==false` 或 `confidence=="low"` → Read `full_page_XX.png` 按看图协议量外形线。
4. D（深度）看 `band_overalls` 里侧视图那一带，或 Read 侧视图确认。

## 视觉/确认闸门（fill_quote 强制）

`fill_quote.py` 出行前会审计每条记录。满足以下任一 → 该行标 `⚠` + 品番格/备考格淡黄高亮：
- `dim_source` 不是 `"visual"` 也不是 `"geometry"`（没确认过）
- `dim_evidence` 为空
- `W`/`D`/`H` 任一缺失
- 备考含「要確認 / 待确认 / 重複 / 重复」

加 `--require-visual`：只要还有未确认/缺尺寸项，**直接拒绝出终版**（终版交付闸门）。
不加则照常出「带 ⚠ 的草稿版」，方便先看效果、再回头补确认。

## 示例（一页含 F01、F01A 两个型号 → 两条记录 → 两行）

```json
{
  "project": "石垣島美咲町ビル",
  "products": [
    {
      "row_code": "F01", "page": 2, "page_image": "pages/full_page_02.png",
      "name_jp": "テーブル-01", "name_cn": "餐桌-01",
      "mat_jp": ["天板：メラミン化粧板（フォーミカ）", "小口：PVC"],
      "mat_cn": ["台面：防火板（富美家）", "封边：PVC"],
      "W": 1200, "D": 850, "H": 725, "qty": 3,
      "dim_source": "visual",
      "dim_evidence": "正面図下端の外形寸法線 W1200／側面図 D850／立面 H725（部品線ではない）",
      "text_dims": {"W": 1200, "D": 850, "H": 725},
      "note_jp": "脚は客先支給・現場取付", "note_cn": "脚为客供·现场安装"
    },
    {
      "row_code": "F01A", "page": 2, "page_image": "pages/full_page_02.png",
      "name_jp": "テーブル-01A", "name_cn": "餐桌-01A",
      "mat_jp": ["天板：メラミン化粧板（フォーミカ）", "小口：PVC"],
      "mat_cn": ["台面：防火板（富美家）", "封边：PVC"],
      "W": 1400, "D": 850, "H": 725, "qty": 2,
      "dim_source": "visual",
      "dim_evidence": "正面図の全体寸法 W1400 を採用",
      "text_dims": {"W": 1400, "D": 850, "H": 725},
      "note_jp": "F01 と同仕様・幅違い", "note_cn": "与F01同规格·仅宽度不同"
    }
  ]
}
```
