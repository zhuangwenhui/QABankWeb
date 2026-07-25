#!/usr/bin/env python3
"""题面图片截断检测。

题面多为 PDF 截图,跨页会把题目从中间切断 —— 页面上看不出来,但学生看到的题目是残缺的,
对应的题解也就只解了半道题。

判据:正常裁好的题面,上下边缘应是留白;被切断的那一边会有文字直接压在图像边界上。
逐张统计边缘若干行的"墨密度"(暗像素占比),与全图平均墨密度比较:
  · 底边有墨       → 疑似下方被截断(最常见:PDF 换页)
  · 顶边有墨       → 疑似上方被截断
  · 长宽比异常瘦长 → 疑似只截到半页

用法:
    python scripts/audit_images.py <uploads 目录> [--db 库路径] [--json 输出.json]
需要 Pillow;缺失则跳过并以 0 退出。
"""
import argparse
import json
import os
import sqlite3
import sys

EDGE_ROWS = 6        # 参与判定的边缘行数
DARK = 160           # 灰度低于此值算"墨"
EDGE_INK_MIN = 0.012  # 边缘墨密度阈值(占该行像素比)
TALL_RATIO = 3.0     # 高/宽超过此值算瘦长


def analyse(path):
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert('L')
        w, h = im.size
        if w < 20 or h < 20:
            return {'w': w, 'h': h, 'flags': ['图像过小']}
        px = im.load()
        step = max(1, w // 400)   # 宽图抽样,避免逐像素太慢

        def ink(rows):
            n = dark = 0
            for y in rows:
                for x in range(0, w, step):
                    n += 1
                    if px[x, y] < DARK:
                        dark += 1
            return dark / n if n else 0.0

        top = ink(range(0, min(EDGE_ROWS, h)))
        bottom = ink(range(max(0, h - EDGE_ROWS), h))
        overall = ink(range(0, h, max(1, h // 120)))

        flags = []
        if bottom > EDGE_INK_MIN and bottom > overall * 0.35:
            flags.append(f'底边有墨(密度 {bottom:.3f} / 全图 {overall:.3f})→ 疑似下方被截断')
        if top > EDGE_INK_MIN and top > overall * 0.35:
            flags.append(f'顶边有墨(密度 {top:.3f} / 全图 {overall:.3f})→ 疑似上方被截断')
        if h > w * TALL_RATIO:
            flags.append(f'瘦长({w}×{h})→ 疑似只截到部分页面')
        return {'w': w, 'h': h, 'top': round(top, 4), 'bottom': round(bottom, 4),
                'overall': round(overall, 4), 'flags': flags}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('uploads')
    ap.add_argument('--db')
    ap.add_argument('--json')
    args = ap.parse_args()

    try:
        import PIL  # noqa: F401
    except ImportError:
        print('· 跳过:未装 Pillow')
        return 0

    owner = {}
    if args.db:
        con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
        for qid, img, src in con.execute(
                "SELECT id, COALESCE(question_image,''), COALESCE(source,'') FROM questions"):
            if img:
                owner[os.path.basename(img)] = (qid, src)

    names = sorted(n for n in os.listdir(args.uploads)
                   if n.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')))
    report, suspects = [], []
    for n in names:
        try:
            r = analyse(os.path.join(args.uploads, n))
        except Exception as e:
            r = {'flags': [f'读取失败:{e}']}
        qid, src = owner.get(n, (None, ''))
        r.update({'file': n, 'qid': qid, 'source': src})
        report.append(r)
        if r['flags']:
            suspects.append(r)

    print(f"图片 {len(names)} 张,可疑 {len(suspects)} 张\n")
    kinds = {}
    for r in suspects:
        for f in r['flags']:
            kinds[f.split('(')[0]] = kinds.get(f.split('(')[0], 0) + 1
    for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {v:>4}  {k}")

    print("\n明细(按底边墨密度降序):")
    for r in sorted(suspects, key=lambda r: -(r.get('bottom') or 0))[:40]:
        qid = f"id={r['qid']}" if r['qid'] else "(未挂题)"
        print(f"  {qid:<9} {r['file'][:36]:<36} {r.get('w')}×{r.get('h')}  {'; '.join(r['flags'])[:70]}")
    if len(suspects) > 40:
        print(f"  … 还有 {len(suspects) - 40} 张,完整清单见 --json")

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\n完整清单已写入 {args.json}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
