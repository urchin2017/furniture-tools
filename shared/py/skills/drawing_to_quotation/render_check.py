#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染验证：把填好的报价 xlsx 转 PDF 再渲染成 PNG，供目视确认无溢出/对齐/数据正确。
需要 LibreOffice(soffice)。

用法:
  python3 render_check.py <xlsx> <out_dir> [--area A1:N53] [--dpi 135]
输出: out_dir/check_1.png, check_2.png ...
检查清单(人工目视):
  □ E列内容最多的产品是否完整显示、上下左右有留白(未填满)
  □ 所有参考图尺寸一致、居中、未越界
  □ I列(数量)已加粗放大、无背景色、千位格式
  □ C/E/N 列日中均以空行分隔
  □ 数据与图纸一致；单价空时合计为 US$0
"""
import argparse, os, subprocess, shutil, fitz
from openpyxl import load_workbook
from openpyxl.worksheet.properties import PageSetupProperties


def render_xlsx(xlsx, out_dir, area='A1:N53', dpi=135):
    """xlsx → pdf → 逐页 PNG。返回 PNG 路径列表（原 __main__ 逻辑原样包装成函数）。"""
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, '_render.xlsx'); shutil.copy(xlsx, tmp)
    wb = load_workbook(tmp); ws = wb.active
    ws.print_area = area
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    wb.save(tmp)
    subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', '--outdir', out_dir, tmp],
                   check=True, timeout=120)
    pdf = tmp[:-5] + '.pdf'
    doc = fitz.open(pdf); print('页数:', doc.page_count)
    outs = []
    for i in range(doc.page_count):
        out = os.path.join(out_dir, f'check_{i + 1}.png')
        doc[i].get_pixmap(dpi=dpi).save(out); print('渲染:', out)
        outs.append(out)
    print('完成')
    return outs


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx'); ap.add_argument('out_dir')
    ap.add_argument('--area', default='A1:N53'); ap.add_argument('--dpi', type=int, default=135)
    a = ap.parse_args()
    render_xlsx(a.xlsx, a.out_dir, a.area, a.dpi)
