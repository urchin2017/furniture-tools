#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把PDF图纸每页渲染成高DPI整页图片，供「视觉读尺寸」用——不裁剪、不涂白，
保留完整图框与所有尺寸线，这样才能看清哪根尺寸线横跨整个产品（=外形/全体寸法）。

与 crop_drawings.py 的区别：
  - crop_drawings.py 是为「报价单里的参考缩略图」服务，会去掉文字块/表题栏/白边；
  - render_pages.py 是为「人/模型用眼睛核对尺寸」服务，**保留整页**，DPI 更高，
    并可选放大左下/右下区域（正面图·侧面图常在此），便于看清尺寸线数字。

用法:
  python3 render_pages.py <pdf> <out_dir> [--pages 2-14] [--dpi 220] [--zoom-quadrants]
  --pages       省略=全部页；"2-14" 或 "2,3,6,10"（1-based）。
  --dpi         整页渲染DPI（默认220；尺寸线密集时可调到 260-300）。
  --zoom-quadrants  额外为每页输出四个象限放大图（_tl/_tr/_bl/_br），看清细小尺寸数字。

输出: out_dir/full_page_02.png（整页）, 可选 full_page_02_bl.png（左下放大）...

读尺寸的方法（核心）:
  1) 先看整页，找到**横跨整个产品**的那根最长尺寸线 → 它的数字就是 W(外形宽)；
     找到**纵跨整个产品**的最长竖直尺寸线 → H(外形高)；侧视图最长水平线 → D(外形深)。
  2) 优先认准标注「外形寸法 / 全体寸法 / 総巾 / 総高 / 全長」或图框总尺寸线的那个数。
  3) 把视觉读到的 W/D/H 和 get_text() 文字提取的数值**交叉核对**；不一致以「整条尺寸线」为准。
  4) 若图上同时有整体线和分段(部件)线，分段数之和 ≈ 整体数可作二次校验；冲突取整体并写备考。
"""
import fitz, os, argparse


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


def render_page(doc, pi, out_dir, dpi=220, zoom_quadrants=False):
    page = doc[pi]
    pm = page.get_pixmap(dpi=dpi)
    full = os.path.join(out_dir, f'full_page_{pi + 1:02d}.png')
    pm.save(full); print('整页渲染:', full)
    if zoom_quadrants:
        W, H = page.rect.width, page.rect.height
        quads = {'tl': (0, 0, W / 2, H / 2), 'tr': (W / 2, 0, W, H / 2),
                 'bl': (0, H / 2, W / 2, H), 'br': (W / 2, H / 2, W, H)}
        for name, (x0, y0, x1, y1) in quads.items():
            clip = fitz.Rect(x0, y0, x1, y1)
            qpm = page.get_pixmap(dpi=dpi + 60, clip=clip)
            qout = os.path.join(out_dir, f'full_page_{pi + 1:02d}_{name}.png')
            qpm.save(qout); print('  象限放大:', qout)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf'); ap.add_argument('out_dir')
    ap.add_argument('--pages', default='')
    ap.add_argument('--dpi', type=int, default=220)
    ap.add_argument('--zoom-quadrants', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    doc = fitz.open(a.pdf)
    for pi in parse_pages(a.pages, doc.page_count):
        render_page(doc, pi, a.out_dir, a.dpi, a.zoom_quadrants)
    print('完成 — 现在用 Read 工具逐张查看这些 PNG，用眼睛量取横跨整个产品的尺寸线。')
