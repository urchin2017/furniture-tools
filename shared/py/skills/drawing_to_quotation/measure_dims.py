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

def numbers(page, clip=None):
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
        if v in YEARS or not (DIM_MIN<=v<=DIM_MAX): continue
        out.append((v,cx,cy))
    return out

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
    inner=sorted([L for L in kept if L is not ov
                  and ov['a']-3<=L['a'] and L['b']<=ov['b']+3
                  and abs(L['pos']-ov['pos'])>5], key=lambda L:L['a'])
    chain=sum(L['label'] for L in inner) if inner else None
    ext_ok=extent_est is None or abs(overall-extent_est)<=max(5,0.06*overall)
    chain_ok=chain is None or abs(chain-overall)<=max(2,0.03*overall)
    suspect_local=extent_est is not None and overall<0.9*extent_est
    return {'overall_value':overall,'overall_by_extent':extent_est,
            'overall_span_px':round(ov['len'],1),
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
