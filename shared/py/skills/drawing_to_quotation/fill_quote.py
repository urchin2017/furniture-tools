#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3 数据管线 · 第 3 步：从 products.json 填 Excel 报价模板（drawing-to-quotation-2026-07-01-v3）。

与 V2 的根本区别（这就是 V2 两大病根的根治处）：
  ① **不再有写死的 DATA 列表**。全部产品数据从 <json> 读取；json 由 extract_scaffold.py
     生成骨架、再由「看图读尺寸」填好。尺寸不看图就没有来源——从结构上杜绝「照搬旧数据」。
  ② **一条 json 记录 = 一行**。不同型号(F01/F01A)在 extract_scaffold 阶段已各成一条记录，
     这里只是逐条渲染 → 不同型号自动分两行，绝不合并求和。
  ③ **视觉确认闸门**：任何 dim_source≠"visual" 或 W/D/H 缺失的记录，行首品番加 ⚠、
     品番格+备考格淡黄高亮，并在终端打印醒目清单。加 --require-visual 则「只要有未确认项就拒绝出终版」。

沿用 V2 全部排版规范：日中双语空行分隔 / 统一行高留白 / 图片居中 / 数量列14pt粗体无底色千位 /
单价留空 / メラミン化粧板→防火板术语订正 / 不覆盖原模板另存新文件。

用法:
  python3 fill_quote.py --pdf <图纸.pdf> --template <模板.xlsx> --json <products.json> \
      --out <御見積書_项目_v1_YYYY-MM-DD.xlsx> [--project "项目名"] \
      [--start-row 18] [--last-row 50] [--require-visual]

依赖: pip install pymupdf openpyxl Pillow numpy --break-system-packages
"""
import fitz, numpy as np, os, math, json, sys, argparse
from PIL import Image, ImageDraw
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils.units import pixels_to_EMU
from openpyxl.utils import get_column_letter
from openpyxl.formula.translate import Translator
from copy import copy as _copy
import re as _re
import unicodedata

# 术语订正：メラミン化粧板（フォーミカ）= 防火板(HPL)，非直译三聚氰胺板
GLOSSARY = [("三聚氰胺装饰板（富美家/防火板）", "防火板（富美家）"),
            ("三聚氰胺装饰板（富美家／防火板）", "防火板（富美家）"),
            ("三聚氰胺装饰板", "防火板"), ("三聚氰胺板", "防火板")]
def fix_terms(s):
    s = unicodedata.normalize('NFC', str(s))
    for a, b in GLOSSARY:
        s = s.replace(a, b)
    return s
HL_FILL = PatternFill("solid", fgColor="FFFFF2CC")   # 待确认项淡黄高亮
WHITE_FILL = PatternFill("solid", fgColor="FFFFFFFF")  # 数据行显式纯白（防某些查看器把“无填充”渲染成灰）


class QuoteAuditError(RuntimeError):
    """审计不通过（--require-visual 下有未确认项 / JSON 无记录）。

    原脚本用 sys.exit()——CLI 下没问题，但服务端后台任务里 SystemExit
    不是 Exception 的子类，会绕过 runner 的兜底把 job 卡在 running，
    所以改抛普通异常；CLI 行为不变（未捕获异常同样非零退出）。
    """

# ===================== 排版常量（按项目微调）=====================
FONT = '微软雅黑'
CW, CH       = 660, 440       # 裁剪画布
IMG_W, IMG_H = 208, 139       # 图片嵌入物理尺寸(px)
COL_OFF      = 16             # 图片左偏移(px)，水平居中+左右留白
LINE_PT      = 14.0           # 行距(pt)
PAD_PT       = 34.0           # 上下留白(pt)
CPL_E        = 17             # E列每行可容纳全角字数（越小越保守=行越高=留白越多）
SZ_NORMAL, SZ_SPEC, SZ_NOTE, SZ_QTY = 11, 10, 9, 14
DPI = 200
KW = ['案件名', '产品名', '産品名', '款号', '品番']


def crop_page(doc, pi, save):
    """裁剪产品图形：去说明文字块+底部表题栏+白边，统一画布居中。pi 为 0-based。"""
    page = doc[pi]; W, H = page.rect.width, page.rect.height; sc = DPI / 72.0
    wo = [b[:4] for b in page.get_text('blocks')
          if len(b[4].strip()) >= 60 and any(k in b[4] for k in KW)]
    pix = page.get_pixmap(dpi=DPI)
    img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
    dr = ImageDraw.Draw(img); pad = 8
    for (x0, y0, x1, y1) in wo:
        dr.rectangle([x0 * sc - pad, y0 * sc - pad, x1 * sc + pad, y1 * sc + pad], fill='white')
    dr.rectangle([0, H * 0.93 * sc, W * sc, H * sc], fill='white')
    pw, ph = img.size; mx, my = int(pw * 0.045), int(ph * 0.045)
    inner = img.crop((mx, my, pw - mx, ph - my))
    arr = np.asarray(inner.convert('L')); ys, xs = np.where(arr < 235)
    if len(xs):
        x0, x1 = xs.min(), xs.max(); y0, y1 = ys.min(), ys.max(); p = 10
        crop = inner.crop((max(0, x0 - p), max(0, y0 - p),
                           min(inner.size[0], x1 + p), min(inner.size[1], y1 + p)))
    else:
        crop = inner
    canvas = Image.new('RGB', (CW, CH), 'white')
    r = min(CW * 0.94 / crop.width, CH * 0.94 / crop.height)
    nw, nh = max(1, int(crop.width * r)), max(1, int(crop.height * r))
    canvas.paste(crop.resize((nw, nh), Image.LANCZOS), ((CW - nw) // 2, (CH - nh) // 2))
    canvas.save(save)


def vlines(text, cpl):
    """估算文本在每行 cpl 全角字宽度下的视觉行数（含显式空行）。"""
    t = 0
    for seg in text.split('\n'):
        if seg.strip() == '':
            t += 1
        else:
            w = sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in seg)
            t += max(1, math.ceil(w / cpl))
    return t


def cell_C(jp, cn): return f"{jp}\n\n{fix_terms(cn)}"
def cell_E(mjp, mcn):
    mjp = mjp or []; mcn = mcn or []
    return "\n".join(mjp) + "\n\n" + "\n".join(fix_terms(x) for x in mcn)
def cell_N(njp, ncn):
    if not njp and not ncn: return ''
    if njp and ncn: return f"{njp}\n\n{ncn}"
    return njp or ncn


def load_products(json_path):
    with open(json_path, encoding='utf-8') as f:
        payload = json.load(f)
    products = payload.get('products', [])
    project = payload.get('project', '')
    return products, project


def audit(products, require_visual):
    """出行前审计：列出未视觉确认 / 缺尺寸的记录。返回 (unconfirmed_codes, missing_codes)。"""
    unconfirmed, missing = [], []
    for p in products:
        code = p.get('row_code') or '(空品番)'
        if p.get('dim_source') not in ('visual','geometry') or not (p.get('dim_evidence') or '').strip():
            unconfirmed.append(code)
        if any(p.get(k) in (None, '', 0) for k in ('W', 'D', 'H')):
            missing.append(code)
    print('—' * 56)
    print(f'审计：共 {len(products)} 条记录（=报价单 {len(products)} 行）')
    if unconfirmed:
        print(f'⚠ 未经确认(dim_source 非 visual/geometry 或无 dim_evidence) {len(unconfirmed)} 条：')
        print('   ' + '、'.join(unconfirmed))
        print('   → 这些行会被标 ⚠ 淡黄高亮。请先看整页图确认外形尺寸线后再出终版。')
    if missing:
        print(f'⚠ W/D/H 仍缺失 {len(missing)} 条：' + '、'.join(missing))
    if not unconfirmed and not missing:
        print('✅ 全部记录已视觉确认且三维齐全。')
    print('—' * 56)
    if require_visual and (unconfirmed or missing):
        raise QuoteAuditError('--require-visual 已开启：存在未确认/缺尺寸项，拒绝出终版。'
                              '请补齐后重跑（去掉该开关可先出带⚠的草稿版）。')
    return unconfirmed, missing


def build(pdf, template, json_path, out_xlsx, project_arg,
          start_row, last_row, require_visual):
    thumb = os.path.join(os.path.dirname(os.path.abspath(out_xlsx)) or '.', '_thumbs')
    os.makedirs(thumb, exist_ok=True)

    products, project_json = load_products(json_path)
    if not products:
        raise QuoteAuditError('products.json 里没有任何产品记录。请先运行 extract_scaffold.py 生成骨架并看图填好。')
    project = project_arg or project_json

    unconfirmed, missing = audit(products, require_visual)

    doc = fitz.open(pdf)
    # 统一行高 = max(E列文字所需高, 图片所需高)。
    # 只按 E 列材质文字定高时，材质很短的图纸（如 SEKI，本地提取无材质文字）行会矮到
    # 76pt，而参考写真图片固定 139px≈116pt → 图片纵向溢出、跨行叠到下一行。故取二者较大值，
    # 保证每行至少能整张容下图片（上下各留 IMG_PAD 像素）。
    IMG_PAD = 8
    img_row_h = round((IMG_H + 2 * IMG_PAD) * 3 / 4, 1)   # 图片纵向所需最小行高(pt)
    max_e = max(vlines(cell_E(p.get('mat_jp'), p.get('mat_cn')), CPL_E) for p in products)
    row_h = max(round(max_e * LINE_PT + PAD_PT, 1), img_row_h)
    row_px = int(row_h * 4 / 3); row_off = max(0, (row_px - IMG_H) // 2)
    print(f'E列最多视觉行={max_e}  统一行高={row_h}pt（图片下限={img_row_h}pt）  图片row_off={row_off}px')

    wb = load_workbook(template); ws = wb.active
    if project:
        ws['C11'] = project

    # ===== 行数自适应（任务1）：写数据前先捕获“页脚块”（合計〜備考），之后整块搬到数据末尾 =====
    # --last-row 语义 = 数据预留段末行 = 合計行的上一行；据此定位页脚起点。
    FOOTER_START = last_row + 1          # 页脚第一行（合計行）
    def _last_content_row(top, maxscan=250):
        last = top; empty = 0; r = top
        while r < top + maxscan:
            has = any(ws.cell(r, c).value not in (None, '') for c in range(1, 15))
            if has:
                last = r; empty = 0
            else:
                empty += 1
                if empty > 15:
                    break
            r += 1
        return last
    FOOTER_END = _last_content_row(FOOTER_START)
    _footer_cells = []
    for rr in range(FOOTER_START, FOOTER_END + 1):
        for cc in range(1, 15):
            cell = ws.cell(rr, cc)
            _footer_cells.append((rr - FOOTER_START, cc, cell.value,
                _copy(cell.font), _copy(cell.fill), _copy(cell.border),
                _copy(cell.alignment), cell.number_format))
    _footer_heights = {rr - FOOTER_START: ws.row_dimensions[rr].height
                       for rr in range(FOOTER_START, FOOTER_END + 1)}
    _footer_merges = []
    for mr in list(ws.merged_cells.ranges):
        c1, r1, c2, r2 = mr.bounds
        if r1 >= FOOTER_START and r2 <= FOOTER_END:
            _footer_merges.append((r1 - FOOTER_START, c1, r2 - FOOTER_START, c2))
    # 解除“数据起始行往下”的全部合并（数据扩展区 + 旧页脚），避免写入/搬迁报错
    for mr in list(ws.merged_cells.ranges):
        c1, r1, c2, r2 = mr.bounds
        if r1 >= start_row:
            ws.unmerge_cells(str(mr))

    thin = Side(style='thin', color='808080'); BORDER = Border(thin, thin, thin, thin)
    Fn = lambda sz, b=False: Font(name=FONT, size=sz, bold=b)
    NO_FILL = PatternFill(fill_type=None)
    Al = Alignment

    for i, p in enumerate(products):
        r = start_row + i
        code = p.get('row_code', '')
        w, d, h = p.get('W'), p.get('D'), p.get('H')
        qty = p.get('qty')
        notejp, notecn = p.get('note_jp', ''), p.get('note_cn', '')
        ws.row_dimensions[r].height = row_h
        # 先整行刷纯白（黄色⚠高亮随后覆盖 B/N，数量列 I 随后置 NO_FILL 去底色）
        for _c in 'ABCDEFGHIJKLMN':
            ws[f'{_c}{r}'].fill = WHITE_FILL

        # 待确认判定：备考含要確認/重複 / W·D·H 缺失 / 尺寸未视觉确认
        flag = (any(k in (notejp or '') for k in ('要確認', '重複'))
                or any(k in (notecn or '') for k in ('待确认', '重复'))
                or any(v in (None, '', 0) for v in (w, d, h))
                or p.get('dim_source') not in ('visual','geometry')
                or not (p.get('dim_evidence') or '').strip())

        ws[f'A{r}'] = i + 1
        ws[f'B{r}'] = (f"⚠ {code}" if flag else code)
        ws[f'C{r}'] = cell_C(p.get('name_jp', ''), p.get('name_cn', ''))
        ws[f'E{r}'] = cell_E(p.get('mat_jp'), p.get('mat_cn'))
        ws[f'F{r}'] = w; ws[f'G{r}'] = d; ws[f'H{r}'] = h
        ws[f'I{r}'] = qty
        ws[f'J{r}'] = 'pcs'
        ws[f'K{r}'] = f'=F{r}*G{r}*H{r}*I{r}/1000000000*1.1'
        ws[f'M{r}'] = f'=IF(L{r}="","",L{r}*I{r})'
        ws[f'N{r}'] = cell_N(notejp, notecn)
        ws[f'A{r}'].font = Fn(SZ_NORMAL); ws[f'A{r}'].alignment = Al(horizontal='center', vertical='center')
        ws[f'B{r}'].font = Fn(SZ_NORMAL, True); ws[f'B{r}'].alignment = Al('center', vertical='center', wrap_text=True)
        ws[f'C{r}'].font = Fn(SZ_NORMAL); ws[f'C{r}'].alignment = Al('center', vertical='center', wrap_text=True)
        ws[f'D{r}'].alignment = Al('center', vertical='center')
        ws[f'E{r}'].font = Fn(SZ_SPEC); ws[f'E{r}'].alignment = Al('left', vertical='center', wrap_text=True, indent=1)
        # F/G/H 逐维：若该维在 confirm_dims 里，单格标淡黄（覆盖白底；可与整行⚠叠加）
        _confirm = p.get('confirm_dims') or []
        for col, _key in (('F', 'W'), ('G', 'D'), ('H', 'H')):
            ws[f'{col}{r}'].font = Fn(SZ_NORMAL); ws[f'{col}{r}'].alignment = Al('center', vertical='center')
            if _key in _confirm:
                ws[f'{col}{r}'].fill = HL_FILL
        # 数量列：去底色 + 14pt 粗体 + 千位分隔
        ws[f'I{r}'].font = Fn(SZ_QTY, True); ws[f'I{r}'].alignment = Al('center', vertical='center')
        ws[f'I{r}'].fill = NO_FILL; ws[f'I{r}'].number_format = '#,##0'
        ws[f'J{r}'].font = Fn(SZ_NORMAL); ws[f'J{r}'].alignment = Al('center', vertical='center')
        ws[f'K{r}'].font = Fn(SZ_NORMAL); ws[f'K{r}'].alignment = Al('center', vertical='center'); ws[f'K{r}'].number_format = '0.00'
        ws[f'L{r}'].font = Fn(SZ_NORMAL); ws[f'L{r}'].alignment = Al('right', vertical='center'); ws[f'L{r}'].number_format = '"US$"#,##0;\\-"US$"#,##0'
        ws[f'M{r}'].font = Fn(SZ_NORMAL); ws[f'M{r}'].alignment = Al('right', vertical='center'); ws[f'M{r}'].number_format = '"US$"#,##0;\\-"US$"#,##0'
        ws[f'N{r}'].font = Fn(SZ_NOTE); ws[f'N{r}'].alignment = Al('left', vertical='center', wrap_text=True, indent=1)
        for col in 'ABCDEFGHIJKLMN':
            ws[f'{col}{r}'].border = BORDER
        if flag:
            ws[f'B{r}'].fill = HL_FILL; ws[f'N{r}'].fill = HL_FILL

        # 裁剪 + 居中嵌入（页号 1-based → fitz 0-based）
        page = p.get('page')
        if isinstance(page, int) and 1 <= page <= doc.page_count:
            safe = (code or f'p{page}').replace('/', '-')
            png = os.path.join(thumb, f"p{page:02d}_{safe}.png")
            crop_page(doc, page - 1, png)
            im = XLImage(png)
            im.anchor = OneCellAnchor(
                _from=AnchorMarker(col=3, colOff=pixels_to_EMU(COL_OFF), row=r - 1, rowOff=pixels_to_EMU(row_off)),
                ext=XDRPositiveSize2D(pixels_to_EMU(IMG_W), pixels_to_EMU(IMG_H)))
            ws.add_image(im)

    # ===== 行数自适应（任务1）：数据 N 行 → 1 空白行 → 页脚整块搬到其后 =====
    N = len(products)
    data_end = start_row + N - 1
    blank_row = data_end + 1
    new_footer_start = blank_row + 1
    shift = new_footer_start - FOOTER_START
    new_footer_end = FOOTER_END + shift
    clear_to = max(FOOTER_END, new_footer_end)
    # 清掉“空白行〜clear_to”（值+样式+行高），空白行保持真空白
    _blank_font = Font(name=FONT); _no_fill = PatternFill(fill_type=None)
    _no_border = Border(); _no_align = Alignment()
    for rr in range(blank_row, clear_to + 1):
        for cc in range(1, 15):
            cell = ws.cell(rr, cc)
            cell.value = None; cell.font = _blank_font; cell.fill = _no_fill
            cell.border = _no_border; cell.alignment = _no_align; cell.number_format = 'General'
        ws.row_dimensions[rr].height = None
    # 把页脚块盖章到新位置（公式随之修正）
    for (rel, cc, val, fnt, fil, brd, aln, nf) in _footer_cells:
        nr = new_footer_start + rel
        cell = ws.cell(nr, cc)
        if isinstance(val, str) and val.startswith('='):
            if rel == 0:
                # 合計行：把“从数据起始行开始的 SUM 范围”末尾改成真实数据末行
                val = _re.sub(rf'([A-Z]+){start_row}:([A-Z]+)\d+',
                              lambda m: f"{m.group(1)}{start_row}:{m.group(2)}{data_end}", val)
            else:
                # 其余页脚行：按行位移平移内部引用（船運/契约等）
                origin = f"{get_column_letter(cc)}{FOOTER_START + rel}"
                val = Translator(val, origin=origin).translate_formula(f"{get_column_letter(cc)}{nr}")
        cell.value = val
        cell.font = _copy(fnt); cell.fill = _copy(fil); cell.border = _copy(brd)
        cell.alignment = _copy(aln); cell.number_format = nf
        if _footer_heights.get(rel) is not None:
            ws.row_dimensions[nr].height = _footer_heights[rel]
    # 页脚合并单元格在新位置重建
    for (r1, c1, r2, c2) in _footer_merges:
        ws.merge_cells(start_row=new_footer_start + r1, start_column=c1,
                       end_row=new_footer_start + r2, end_column=c2)
    # 顶部引用页脚的公式（如 C9=合計）随之修正
    for rr in range(1, start_row):
        for cc in range(1, 20):
            cell = ws.cell(rr, cc); v = cell.value
            if isinstance(v, str) and v.startswith('='):
                def _rep(m):
                    col, row = m.group(1), int(m.group(2))
                    if FOOTER_START <= row <= FOOTER_END:
                        return f"{col}{row + shift}"
                    return m.group(0)
                cell.value = _re.sub(r'([A-Z]+)(\d+)', _rep, v)

    wb.save(out_xlsx)
    print('已保存:', out_xlsx, ' 产品数(=行数):', len(products), ' 图片数:', len(ws._images))
    return {'out': out_xlsx, 'rows': len(products), 'images': len(ws._images),
            'unconfirmed': unconfirmed, 'missing': missing}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--template', required=True)
    ap.add_argument('--json', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--project', default='')
    ap.add_argument('--start-row', type=int, default=18)
    ap.add_argument('--last-row', type=int, default=50)
    ap.add_argument('--require-visual', action='store_true',
                    help='存在未视觉确认/缺尺寸项时拒绝出终版（终版交付闸门）')
    a = ap.parse_args()
    build(a.pdf, a.template, a.json, a.out, a.project,
          a.start_row, a.last_row, a.require_visual)
