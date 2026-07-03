#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从PDF技术图纸裁剪「产品图形」：去除规格说明大文字块 + 底部表题栏 + 四周白边，
统一画布尺寸、内容居中。每页输出一张尺寸完全一致的PNG。

用法:
  python3 crop_drawings.py <pdf> <out_dir> [--pages 2-14] [--cw 660] [--ch 440] [--dpi 200]
  --pages 省略=全部页；可写 "2-14" 或 "2,3,6,10"（1-based）。封面/无文本页建议排除。

算法:
  1) get_text('blocks') 找「规格说明大文字块」(len>=60 且含 案件名/产品名/款号/品番)→涂白
  2) 涂白底部表题栏(最底 title_bar 比例，常含图框/公司名)
  3) 裁掉四周外框边距(margin)以排除图框线
  4) 去白边(灰度<235 的内容包围盒 + padding)
  5) 等比缩放贴入统一画布(cw×ch)，居中、白底
说明: 贴在视图上的局部部位标注(防火板/小口PVC/白橡木等)会保留——属产品图形的一部分。
"""
import fitz, numpy as np, os, argparse
from PIL import Image, ImageDraw

KW = ['案件名', '产品名', '産品名', '款号', '品番']

def parse_pages(s, n):
    if not s:
        return list(range(n))
    out = []
    for part in s.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-'); out += list(range(int(a) - 1, int(b)))
        elif part:
            out.append(int(part) - 1)
    return [p for p in out if 0 <= p < n]

def crop_page(doc, pi, save, cw=660, ch=440, dpi=200, margin=0.045, title_bar=0.07,
              whiteout_extra=None):
    """裁剪单页。whiteout_extra: 可选 [(x0,y0,x1,y1)...]（PDF点坐标）追加涂白区(如红字批注)。"""
    page = doc[pi]; W, H = page.rect.width, page.rect.height; sc = dpi / 72.0
    wo = [b[:4] for b in page.get_text('blocks')
          if len(b[4].strip()) >= 60 and any(k in b[4] for k in KW)]
    if whiteout_extra:
        wo += list(whiteout_extra)
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
    dr = ImageDraw.Draw(img); pad = 8
    for (x0, y0, x1, y1) in wo:
        dr.rectangle([x0 * sc - pad, y0 * sc - pad, x1 * sc + pad, y1 * sc + pad], fill='white')
    dr.rectangle([0, H * (1 - title_bar) * sc, W * sc, H * sc], fill='white')   # 底部表题栏
    pw, ph = img.size; mx, my = int(pw * margin), int(ph * margin)
    inner = img.crop((mx, my, pw - mx, ph - my))
    arr = np.asarray(inner.convert('L')); ys, xs = np.where(arr < 235)
    if len(xs):
        x0, x1 = xs.min(), xs.max(); y0, y1 = ys.min(), ys.max(); p = 10
        crop = inner.crop((max(0, x0 - p), max(0, y0 - p),
                           min(inner.size[0], x1 + p), min(inner.size[1], y1 + p)))
    else:
        crop = inner
    canvas = Image.new('RGB', (cw, ch), 'white')
    r = min(cw * 0.94 / crop.width, ch * 0.94 / crop.height)
    nw, nh = max(1, int(crop.width * r)), max(1, int(crop.height * r))
    canvas.paste(crop.resize((nw, nh), Image.LANCZOS), ((cw - nw) // 2, (ch - nh) // 2))
    canvas.save(save)
    return save

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf'); ap.add_argument('out_dir')
    ap.add_argument('--pages', default='')
    ap.add_argument('--cw', type=int, default=660); ap.add_argument('--ch', type=int, default=440)
    ap.add_argument('--dpi', type=int, default=200)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    doc = fitz.open(a.pdf)
    for pi in parse_pages(a.pages, doc.page_count):
        out = os.path.join(a.out_dir, f'page_{pi + 1:02d}.png')
        crop_page(doc, pi, out, a.cw, a.ch, a.dpi)
        print('裁剪:', out)
    print('完成')
