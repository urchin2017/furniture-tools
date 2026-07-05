#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V5 数据管线 · 第 1 步：文字层分诊 + 光栅判定 + 整页渲染 + 生成 products.json 骨架。

======================================================================
V5（2026-07-02）在 V3 基础上新增三个防呆闸门（源自石垣島案件 6 处尺寸事故复盘，
详见 references/case_ishigaki_2026-07-02.md）：

  闸门A「光栅页显式报警」——图纸本体是位图（CAD导出图片再排版）时，矢量层零直线，
        几何引擎必然 vector_ok=false。V3 只是静默跳过，导致尺寸退化成照抄文字注记。
    ⇒ V5 逐页判定光栅特征（无矢量线 + 有整页大图），在 measured 里写 raster_page=true，
      并在终端打印 ⚠RASTER 页清单：这些页【必须】走看图协议，别指望几何结果。

  闸门B「文字注记陷阱标记」——页角 W/D/H 注记常是局部/本体/分段尺寸
      （W600=半块台面、H1135=靠背段、W1660/H2610=柜体不含フィラー…）。
    ⇒ text_dims 仅作交叉参考（与 V3 相同：绝不预填 W/D/H），V5 额外附 text_dims_note
      提醒阅读者：注记≠外形，外形认「最外侧尺寸链」。

  闸门C「款号缩写展开 + 数量解析」——「款号：F07，07A」中的 07A 是 F07A 的缩写，
      V3 漏拆了该行；「数量：2pcs」「F04：2台」「数量：F07：1pcs。F07A：2pcs」没被解析。
    ⇒ V5 展开缩写款号；按品番解析数量写入 qty_hint（仅候选，仍需看图确认后填 qty）。

继承 V3 的两大铁律：W/D/H 一律置 null 必须看图/几何确认后填；一个品番=一条记录。
======================================================================

用法:
  python3 extract_scaffold.py <pdf> <out_json> \
      [--img-dir <dir>] [--dpi 150] [--skip-pages 1] [--project "项目名"]

依赖: pip install pymupdf --break-system-packages
"""
import fitz, os, re, json, argparse, unicodedata, sys
try:
    from .measure_dims import measure_page   # 包内引用（shared/py 在 PYTHONPATH 上时）
except ImportError:                            # 直接当 CLI 脚本跑时
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from measure_dims import measure_page      # 几何尺寸引擎（矢量图纸时有效）

CODE_KEYS = ['款号', '品番', '型番', 'ITEM', 'item', 'No.', 'CODE', 'Code']
DIM_MIN, DIM_MAX = 30, 8000
YEARS = {'2023', '2024', '2025', '2026', '2027'}

# 品番形态：1~3 个大写字母 + 可选连字符 + 1~3 位数字 + 可选字母后缀（变体）
CODE_RE = re.compile(r'\b([A-Z]{1,3}-?\d{1,3}[A-Z]?)\b')
# 缩写变体（「F07，07A」里的 07A）：纯数字+字母后缀，需借用前一个完整品番的字母前缀
SHORT_RE = re.compile(r'(?<![A-Za-z0-9-])(\d{1,3}[A-Z])(?![0-9A-Za-z])')
# 尺寸轴 token（W1200/D850/H725/SH420…）不是品番
DIM_AXIS_RE = re.compile(r'^(SH|SW|DIA|[WDHLTRP])\d{2,4}$')

TEXT_DIMS_NOTE = ('※文字层注记可能是局部/本体/分段尺寸（如半块台面、柜体不含フィラー、'
                  '只到靠背），仅作交叉参考；外形必须以图面最外侧尺寸链为准')


def norm(s):
    return unicodedata.normalize('NFC', s or '')


def find_codes(text):
    """找出全部品番（含「F07，07A」缩写展开），去重保序。"""
    text = norm(text)
    keyed_lines = [ln for ln in text.splitlines()
                   if any(k in ln for k in CODE_KEYS)]
    scope_lines = keyed_lines if keyed_lines else text.splitlines()
    codes, seen = [], set()
    for ln in scope_lines:
        # 记录本行出现的完整品番及其位置，供缩写展开取前缀
        fulls = []
        for m in CODE_RE.finditer(ln):
            c = m.group(1)
            if c in YEARS or DIM_AXIS_RE.match(c):
                continue
            fulls.append((m.start(), c))
            if c not in seen:
                seen.add(c); codes.append(c)
        # 缩写展开：07A → F07A（借最近的前一个完整品番的字母前缀）
        for m in SHORT_RE.finditer(ln):
            prevs = [c for pos, c in fulls if pos < m.start()]
            if not prevs:
                continue
            prefix = re.match(r'[A-Z]{1,3}-?', prevs[-1])
            cand = (prefix.group(0) if prefix else '') + m.group(1)
            if CODE_RE.fullmatch(cand) and cand not in seen and not DIM_AXIS_RE.match(cand):
                seen.add(cand); codes.append(cand)
    return codes


def find_qty_hints(text, codes):
    """按品番解析数量候选：「F04：2台」「F07：1pcs」；单品番页兜底「数量：2pcs」。
    返回 {code: int}。仅是候选（qty_hint），最终 qty 仍须看图确认。"""
    text = norm(text)
    hints = {}
    unit = r'(?:pcs|PCS|台|個|个|脚|セット|set)'
    for code in codes:
        if not code:
            continue
        m = re.search(rf'{re.escape(code)}\s*[：:]\s*(\d+)\s*{unit}', text)
        if m:
            hints[code] = int(m.group(1))
    if len([c for c in codes if c]) == 1 and codes[0] and codes[0] not in hints:
        m = re.search(rf'数量\s*[：:]\s*(\d+)\s*{unit}', text)
        if m:
            hints[codes[0]] = int(m.group(1))
    # 「数量：各3pcs」→ 页内所有品番各 N（共Npcs 只做校验，不采用）
    m = re.search(rf'各\s*(\d+)\s*{unit}', text)
    if m:
        for code in codes:
            if code and code not in hints:
                hints[code] = int(m.group(1))
    return hints


def find_text_dims(text):
    """从文字层抽 W/D/H 候选（仅参考交叉核对，非最终值）。"""
    text = norm(text)
    out = {'W': None, 'D': None, 'H': None}
    for axis in ('W', 'D', 'H'):
        m = re.search(rf'{axis}\s*[:：=＝]?\s*(\d{{2,4}})', text)
        if m:
            v = int(m.group(1))
            if DIM_MIN <= v <= DIM_MAX and str(v) not in YEARS:
                out[axis] = v
    m = re.search(r'(\d{2,4})\s*[×xX]\s*(\d{2,4})\s*[×xX]\s*(\d{2,4})', text)
    if m:
        trio = [int(g) for g in m.groups()]
        if all(DIM_MIN <= v <= DIM_MAX for v in trio):
            for axis, v in zip(('W', 'D', 'H'), trio):
                if out[axis] is None:
                    out[axis] = v
    return out


# 标题栏（图框）品番：CIY_B-02 / TV-01 / RE-01 / HB-01 / CIY_M-01 / CIY_L-03 …
# ——SEKI 等厂把品番放图框「DRAWING NO.」栏、正文 find_codes 抓不到，这里从图框解析。
TITLE_CODE_RE = re.compile(r'\b([A-Z]{2,4}(?:_[A-Z0-9]{1,3})?-\d{1,3}[A-Z]?)\b')
_DRAWNO_KEYS = ('DRAWING NO', 'DWG NO', '図番', '図面番号')


def parse_title_block(text):
    """从图框标题栏解析 (品番, 数量)。图框把值与标签拆成相邻行（位置文本被拉平），
    故在「DRAWING NO.」「QTY」标签的相邻行里就近取值。取不到返回 (None, None)。"""
    lines = [ln.strip() for ln in norm(text).splitlines()]
    up = [ln.upper() for ln in lines]
    code = None
    for i, u in enumerate(up):
        if any(k in u for k in _DRAWNO_KEYS):
            for j in (i - 1, i + 1, i - 2, i + 2):
                if 0 <= j < len(lines):
                    m = TITLE_CODE_RE.search(lines[j])
                    if m:
                        code = m.group(1)
                        break
            if code:
                break
    qty = None
    for i, u in enumerate(up):
        if u in ('QTY', "Q'TY", 'Q’TY', '数量') or u.startswith('QTY'):
            for j in (i + 1, i - 1):
                if 0 <= j < len(lines) and re.fullmatch(r'\d{1,4}', lines[j]):
                    qty = int(lines[j])
                    break
            if qty is not None:
                break
    return code, qty


def _propagate_same_code_dims(products):
    """同一品番跨页（如 CIY_B-02 图纸 1/2、2/2）：某页缺 text_dims，借同品番另一页已量到的。"""
    by_code = {}
    for r in products:
        c = r.get('row_code')
        if c:
            by_code.setdefault(c, []).append(r)
    for recs in by_code.values():
        donor = next((r for r in recs
                      if any((r.get('text_dims') or {}).get(k) for k in 'WDH')), None)
        if not donor:
            continue
        for r in recs:
            if not any((r.get('text_dims') or {}).get(k) for k in 'WDH'):
                r['text_dims'] = dict(donor['text_dims'])


def guess_names_mats(text):
    text = norm(text)
    name = ''
    for key in ('产品名', '産品名', '品名', '商品名'):
        m = re.search(rf'{key}\s*[:：]?\s*([^\n]+)', text)
        if m:
            name = m.group(1).strip()[:30]; break
    return name


def detect_raster(page, measured):
    """光栅页判定：矢量层无可用直线 + 页面挂着大图 → 图纸本体是位图。"""
    if measured.get('vector_ok'):
        return False
    try:
        imgs = page.get_images()
    except Exception:
        imgs = []
    # 有任何较大的嵌入图（>500px 边长）即视为光栅图纸页
    return any(im[2] >= 500 and im[3] >= 500 for im in imgs)


def render_page(page, out_png, dpi):
    page.get_pixmap(dpi=dpi).save(out_png)


def build_scaffold(pdf, out_json, img_dir=None, dpi=150, skip_pages=(), project=''):
    """核心入口（供后端 import；main() 是它的 CLI 皮）。

    把骨架写到 out_json 并返回 payload dict。payload 比原版多带一个
    'raster_pages'（1-based 页码列表）供上层强制走看图协议——fill_quote
    只读 'project'/'products'，多这个键无影响。
    """
    img_dir = img_dir or os.path.join(os.path.dirname(os.path.abspath(out_json)) or '.', 'pages')
    os.makedirs(img_dir, exist_ok=True)
    skip = {int(x) for x in skip_pages}

    doc = fitz.open(pdf)
    products, raster_pages = [], []
    for pi in range(doc.page_count):
        pageno = pi + 1
        if pageno in skip:
            continue
        page = doc[pi]
        text = page.get_text()
        codes = find_codes(text)
        tb_code, tb_qty = parse_title_block(text)   # 图框标题栏：品番/数量（SEKI 等放图框）
        if not codes and tb_code:                    # 正文无品番 → 用图框品番（不再是空占位）
            codes = [tb_code]
        tdims = find_text_dims(text)
        qhints = find_qty_hints(text, codes)
        if tb_qty is not None:                        # 图框数量兜底：给还没数量候选的品番
            for c in codes:
                if c:
                    qhints.setdefault(c, tb_qty)
        name = guess_names_mats(text)

        img = os.path.join(img_dir, f'full_page_{pageno:02d}.png')
        render_page(page, img, dpi)

        try:
            measured = measure_page(page)
        except Exception as e:
            measured = {'vector_ok': False, 'reason': f'量取异常:{e}'}
        if detect_raster(page, measured):
            measured['raster_page'] = True
            measured['reason'] = (measured.get('reason', '') +
                                  '｜光栅图纸页（图纸本体是位图）：几何引擎不可用，必须看图读最外侧尺寸链')
            raster_pages.append(pageno)

        if not codes:
            codes = ['']   # 无文本层页也建占位记录（如 F14），看图补品番/品名

        for code in codes:
            rec = {
                'row_code': code,
                'page': pageno,
                'page_image': img,
                'name_jp': '',
                'name_cn': name,
                'mat_jp': [],
                'mat_cn': [],
                'W': None, 'D': None, 'H': None,       # ★看图/几何确认后填入
                'qty': None,                            # ★看图确认后填入（qty_hint 只是候选）
                'qty_hint': qhints.get(code),           # 文字层解析的数量候选
                'dim_source': 'PENDING',
                'dim_evidence': '',
                'measured': measured,
                'text_dims': tdims,
                'note_jp': '', 'note_cn': ''
            }
            if any(v is not None for v in tdims.values()):
                rec['text_dims_note'] = TEXT_DIMS_NOTE
            products.append(rec)

    _propagate_same_code_dims(products)   # 同品番跨页补 text_dims（图纸 1/2、2/2）
    payload = {'project': project, 'products': products, 'raster_pages': raster_pages}
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf'); ap.add_argument('out_json')
    ap.add_argument('--img-dir', default='')
    ap.add_argument('--dpi', type=int, default=150)
    ap.add_argument('--skip-pages', default='')
    ap.add_argument('--project', default='')
    a = ap.parse_args()

    skip = [int(x) for x in a.skip_pages.split(',') if x.strip().isdigit()]
    payload = build_scaffold(a.pdf, a.out_json, img_dir=a.img_dir or None,
                             dpi=a.dpi, skip_pages=skip, project=a.project)
    products, raster_pages = payload['products'], payload['raster_pages']
    img_dir = os.path.dirname(products[0]['page_image']) if products else (a.img_dir or 'pages')

    n_pending = sum(1 for p in products if p['dim_source'] not in ('visual', 'geometry'))
    n_geom_hi = sum(1 for p in products
                    if isinstance(p.get('measured'), dict)
                    and p['measured'].get('confidence') == 'high'
                    and p['measured'].get('W', {}) and not p['measured']['W'].get('suspect_local'))
    print(f'✅ 已生成骨架: {a.out_json}')
    print(f'   记录数(=行数)={len(products)}  整页图目录={img_dir}')
    if raster_pages:
        print(f'   ⚠⚠ RASTER 光栅图纸页 ×{len(raster_pages)}：{raster_pages}')
        print('      这些页图纸本体是位图，几何引擎不可用——【必须】逐页 Read 整页图，')
        print('      按看图协议读「最外侧尺寸链」定外形；页角 W/D/H 文字注记只能当参考，')
        print('      与图面不一致时以图面为准并把缘由写进备考（见 references/case_ishigaki_2026-07-02.md）。')
    print(f'   其中约 {n_geom_hi} 条已由几何引擎高置信量出外形（见 measured.W/H.overall_value）。')
    print(f'   ⚠ 仍有 {n_pending} 条 W/D/H 未确认（尺寸留空）。下一步（按此优先级）：')
    print('   1) 矢量页：measured confidence=high 且 suspect_local=false、extent_ok=true')
    print('      → 采用 overall_value，dim_source="geometry"。')
    print('   2) suspect_local=true 或 extent_ok=false → 用 overall_by_extent 并 Read 整页图核对。')
    print('   3) 光栅页/vector_ok=false/confidence=low → Read full_page_XX.png，')
    print('      找最外侧尺寸链（贯穿整个产品、常为多段之和，如 40+1660+40）；')
    print('      造作柜 W 含两侧フィラー、H 按 CH（天井高）基准；CH=xxxx 注记是总高旁证。')
    print('   4) D(深度)看侧视图/断面图最外链。')
    print('   5) qty 与 qty_hint、图框角「FXX：N台」互为旁证，不一致标 ⚠。')
    print('   确认后务必写 dim_source(geometry/visual) 与 dim_evidence，否则该行会被标⚠。')


if __name__ == '__main__':
    main()
