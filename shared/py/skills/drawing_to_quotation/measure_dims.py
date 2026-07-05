#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""measure_dims.py（V3 尺寸几何引擎）—— 用几何而非肉眼，量出每页图纸的【外形/全体寸法】。

为什么这样能根治"总是读到局部尺寸"：
  纯视觉的弱点是"判断哪条线跨越整个产品"。本脚本改由代码测量，用两个独立几何信号锁定外形：
    信号A · 尺度一致性：每条真尺寸线的 (标注值 ÷ 像素跨度) 收敛到同一比例尺(mm/px)；
            被误配标注的产品轮廓边/引出线，其比例尺是离群值 → 自动剔除。
    信号B · 跨度×比例尺：某轴最长线段的像素跨度 × 比例尺 = 外形估算值；
            →【关键兜底】即便外形线漏标/读错，也能算出真实外形，识破"把局部当外形"。
  外形值 = 尺度过滤后该轴标注最大的线；再与"跨度估算""局部段之和"三方交叉核对。
  band_overalls：每个"尺寸带"（≈每个视图）各自的外形值 → 侧视图那条即产品深度 D 的线索。
  矢量层无线（扫描/曲线化）→ vector_ok=False，回退看图协议。

用法:
  python3 measure_dims.py <pdf> [--page 2] [--clip x0,y0,x1,y1] [--json out.json]
  --clip 只量某个视图区域（PDF点坐标），用于隔离侧视图取 D。仅依赖 pymupdf。
"""
import fitz, re, json, argparse, statistics as st
NUM_RE = re.compile(r'\d[\d,]*')
DIM_MIN, DIM_MAX = 30, 8000
YEARS = {2023, 2024, 2025, 2026, 2027}

def _in(x, y, clip):
    return clip is None or (clip[0]-2<=x<=clip[2]+2 and clip[1]-2<=y<=clip[3]+2)

def segments(page, clip=None):
    segs=[]
    for d in page.get_drawings():
        for it in d.get('items', []):
            if it[0]=='l':
                p1,p2=it[1],it[2]
                if _in(p1.x,p1.y,clip) or _in(p2.x,p2.y,clip):
                    segs.append((p1.x,p1.y,p2.x,p2.y))
            elif it[0]=='re':
                r=it[1]
                if _in(r.x0,r.y0,clip) or _in(r.x1,r.y1,clip):
                    segs+=[(r.x0,r.y0,r.x1,r.y0),(r.x0,r.y1,r.x1,r.y1),
                           (r.x0,r.y0,r.x0,r.y1),(r.x1,r.y0,r.x1,r.y1)]
    return segs

def classify(segs, eps=1.5, min_len=20):
    hor,ver=[],[]
    for x0,y0,x1,y1 in segs:
        dx,dy=abs(x1-x0),abs(y1-y0)
        if dy<=eps and dx>=min_len:
            hor.append({'a':min(x0,x1),'b':max(x0,x1),'pos':(y0+y1)/2,'len':dx})
        elif dx<=eps and dy>=min_len:
            ver.append({'a':min(y0,y1),'b':max(y0,y1),'pos':(x0+x1)/2,'len':dy})
    return hor,ver

def numbers(page, clip=None, vmin=DIM_MIN):
    out=[]
    for w in page.get_text('words'):
        x0,y0,x1,y1,word=w[0],w[1],w[2],w[3],w[4]
        cx,cy=(x0+x1)/2,(y0+y1)/2
        if not _in(cx,cy,clip): continue
        m=NUM_RE.search(word)
        if not m: continue
        raw=m.group(0).replace(',','')
        if not raw.isdigit(): continue
        v=int(raw)
        if v in YEARS or not (vmin<=v<=DIM_MAX): continue
        out.append((v,cx,cy))
    return out


def extend_with_margins(res, margin_nums, scale, axis, band=16):
    """最外侧尺寸线才算外形：外形段两侧常还有很窄的边距段（如 886 两侧各 22，线太短/数值 <30 被丢），
    使「标注外形」比「像素跨度」窄一截。只在**外形线所在行、紧邻其左右**找这类小边距，把外形补到
    ≈像素跨度为止（886+22+22=930≈跨度）。若标注外形已≈跨度（如 700 本就含两侧 10）则不补，防重复加。"""
    if not res or not res.get('labeled_ok') or not scale:
        return res
    overall=res['overall_value']
    ov_pos=res.get('overall_pos'); a=res.get('overall_a'); b=res.get('overall_b')
    if ov_pos is None or a is None:
        return res
    # 只认「紧贴外形线两端外侧、同一行、很窄」的边距段。整体外形线（如 700 含两端 10）里的
    # 内部小数落在 a..b 之间、不在两端外侧 → 天然不会被加，避免重复计。
    add=[]
    for v,cx,cy in margin_nums:
        if v>=overall or v>0.08*overall:
            continue
        pos, along = (cy, cx) if axis=='h' else (cx, cy)
        seg_px=v/scale
        if abs(pos-ov_pos)<=band and (a-seg_px-28<=along<a or b<along<=b+seg_px+28):
            add.append(v)
    if not add:
        return res
    new=overall+sum(add)
    if new<1.3*overall:                          # 边距总量不该超过外形三成，防噪声乱加
        res=dict(res); res['overall_value']=int(round(new)); res['margin_added']=add
    return res

def attach_labels(lines, nums, axis, band=16):
    for L in lines:
        mid=(L['a']+L['b'])/2; best,bestd=None,1e9
        for v,cx,cy in nums:
            if axis=='h':
                on=(L['a']-5<=cx<=L['b']+5) and abs(cy-L['pos'])<=band
                d=abs(cy-L['pos'])*2+abs(cx-mid)
            else:
                on=(L['a']-5<=cy<=L['b']+5) and abs(cx-L['pos'])<=band
                d=abs(cx-L['pos'])*2+abs(cy-mid)
            if on and d<bestd: best,bestd=v,d
        L['label']=best
    return lines

def consensus_scale(hor, ver, tol=0.06):
    scales=[L['label']/L['len'] for L in hor+ver if L.get('label') and L['len']>1]
    if not scales: return None,0.0,0
    best_s,best_cnt=None,-1
    for s in scales:
        cnt=sum(1 for t in scales if abs(t-s)<=tol*s)
        if cnt>best_cnt: best_s,best_cnt=s,cnt
    cluster=[t for t in scales if abs(t-best_s)<=tol*best_s]
    return st.median(cluster), len(cluster)/len(scales), len(scales)

def band_overalls(kept, scale, band_gap=10):
    """把 kept 线按 pos 分带（≈每视图一带），每带取跨度最大者的标注 → 各视图外形。"""
    bands=[]
    for L in sorted(kept, key=lambda L:L['pos']):
        for grp in bands:
            if abs(grp[0]['pos']-L['pos'])<=band_gap:
                grp.append(L); break
        else:
            bands.append([L])
    outs=[]
    for grp in bands:
        top=max(grp, key=lambda L:L['len'])
        outs.append({'value':top['label'],'span_px':round(top['len'],1),'pos':round(top['pos'],1)})
    return sorted(outs, key=lambda o:-o['value'])

def pick_overall(lines, scale, tol=0.10):
    if not lines: return None
    kept=[L for L in lines if L.get('label') and scale
          and abs(L['label']/L['len']-scale)<=tol*scale]
    longest=max(lines, key=lambda L:L['len'])
    extent_est=round(longest['len']*scale) if scale else None
    if not kept:
        return {'overall_value':None,'overall_by_extent':extent_est,
                'labeled_ok':False,'band_overalls':[],'note':'无可信标注线，仅给跨度估算'}
    ov=max(kept, key=lambda L:L['label']); overall=ov['label']
    # 最外侧尺寸线才算外形：若外形被拆成同一行的几段（如 22│886│22，无显式合计 930），
    # 取该尺寸行各段之和为外形——用像素跨度×比例尺交叉核对，防止把重叠/内部段乱加。
    row=[L for L in kept if abs(L['pos']-ov['pos'])<=10]
    if len(row)>1 and scale:
        row_sum=sum(L['label'] for L in row)
        row_extent=(max(L['b'] for L in row)-min(L['a'] for L in row))*scale
        if row_sum>overall and abs(row_sum-row_extent)<=max(5,0.06*row_sum):
            overall=row_sum
    inner=sorted([L for L in kept if L is not ov
                  and ov['a']-3<=L['a'] and L['b']<=ov['b']+3
                  and abs(L['pos']-ov['pos'])>5], key=lambda L:L['a'])
    chain=sum(L['label'] for L in inner) if inner else None
    ext_ok=extent_est is None or abs(overall-extent_est)<=max(5,0.06*overall)
    chain_ok=chain is None or abs(chain-overall)<=max(2,0.03*overall)
    suspect_local=extent_est is not None and overall<0.9*extent_est
    return {'overall_value':overall,'overall_by_extent':extent_est,
            'overall_span_px':round(ov['len'],1),
            'overall_pos':ov['pos'],'overall_a':ov['a'],'overall_b':ov['b'],
            'chain_segments':[L['label'] for L in inner],'chain_sum':chain,
            'chain_ok':chain_ok,'extent_ok':ext_ok,'suspect_local':suspect_local,
            'labeled_ok':True,'all_labels_on_axis':sorted({L['label'] for L in kept}),
            'band_overalls':band_overalls(kept, scale)}

def measure_page(page, clip=None):
    segs=segments(page,clip); hor,ver=classify(segs); nums=numbers(page,clip)
    if not segs or (not hor and not ver):
        return {'vector_ok':False,'reason':'矢量层无可用直线（扫描/曲线化），回退看图协议'}
    attach_labels(hor,nums,'h'); attach_labels(ver,nums,'v')
    scale,frac,n=consensus_scale(hor,ver)
    W=pick_overall(hor,scale); H=pick_overall(ver,scale)
    if scale:   # 最外侧尺寸线：把宽度外形段两侧被丢的窄边距（<30、线太短）补进整体宽（如 886+22+22=930）。
        # 只补宽度轴：高度轴的「顶板 15」等常是整体高的一段（745=15+730），补了会重复计，故不动 H。
        W=extend_with_margins(W,numbers(page,clip,vmin=10),scale,'h')
    conf='high' if frac>=0.6 and n>=3 else ('mid' if n>=2 else 'low')
    return {'vector_ok':True,'scale_mm_per_px':round(scale,3) if scale else None,
            'scale_inlier_frac':round(frac,2),'n_labeled_lines':n,'confidence':conf,
            'n_segments':len(segs),'W':W,'H':H,
            'hint':'外形取 W/H.overall_value；suspect_local=true 或 extent_ok=false → 看 overall_by_extent 并回图核对；'
                   'D(深度)看 W.band_overalls / H.band_overalls 里侧视图那一带；confidence=low 或 vector_ok=false → 回退看图协议'}

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('pdf')
    ap.add_argument('--page',type=int,default=1); ap.add_argument('--clip',default='')
    ap.add_argument('--json',default='')
    a=ap.parse_args(); doc=fitz.open(a.pdf)
    clip=[float(x) for x in a.clip.split(',')] if a.clip else None
    res=measure_page(doc[a.page-1], clip)
    print(json.dumps(res,ensure_ascii=False,indent=2))
    if a.json: json.dump(res,open(a.json,'w'),ensure_ascii=False,indent=2)
