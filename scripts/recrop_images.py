#!/usr/bin/env python3
"""把被 PDF 跨页切断的题面图裁到干净的边界。

被切断的图,底部(或顶部)会有半行文字直接压在图像边界上,看起来像"题目没给全"。
完整的题面文字本来就在 question_latex 里,所以那半行没有信息价值 —— 把它连同紧邻的
文字块一起裁掉,让图片以留白收边即可,观感恢复正常且不丢内容。

做法:从边界往里扫,找到第一段足够长的空白行带(段落间距),在那里切。
安全阀:单边裁掉超过 MAX_TRIM_FRAC 的高度就放弃(说明这张图整体密排,乱裁会切掉正文)。

用法:
    python scripts/recrop_images.py <uploads 目录> [--apply] [--backup 备份目录]
默认只试算不落盘;--apply 才真的改,且改前把原图复制到备份目录。

配对与生命周期:与 scripts/audit_images.py 成对 —— 那个检测截断,这个重裁。
**不是跑完就作废的一次性脚本**:只要还从 PDF 采题,跨页截断就会再次出现。
"""
import argparse
import os
import shutil
import sys

EDGE_ROWS = 6
DARK = 160
EDGE_INK_MIN = 0.012
BLANK_ROW_MAX_INK = 0.002   # 低于此墨密度视为空白行
BLANK_RUN = 8               # 连续多少空白行算一处"段落间距"
MAX_TRIM_FRAC = 0.18        # 单边最多裁掉的高度占比


def row_ink(px, w, y, step):
    n = dark = 0
    for x in range(0, w, step):
        n += 1
        if px[x, y] < DARK:
            dark += 1
    return dark / n if n else 0.0


def plan(path):
    """返回 (w, h, top_cut, bottom_cut, 说明)。cut 为 0 表示该边不动。"""
    from PIL import Image
    with Image.open(path) as im:
        g = im.convert('L')
        w, h = g.size
        if w < 20 or h < 40:
            return w, h, 0, 0, '图像过小,跳过'
        px = g.load()
        step = max(1, w // 400)
        rows = [row_ink(px, w, y, step) for y in range(h)]

        edge_top = sum(rows[:EDGE_ROWS]) / EDGE_ROWS
        edge_bottom = sum(rows[-EDGE_ROWS:]) / EDGE_ROWS
        overall = sum(rows) / h

        def find_gap(indices):
            """沿 indices 方向找第一段长度 >= BLANK_RUN 的空白行带,返回其起点在原图的行号。"""
            run = 0
            for y in indices:
                if rows[y] <= BLANK_ROW_MAX_INK:
                    run += 1
                    if run >= BLANK_RUN:
                        return y
                else:
                    run = 0
            return None

        bottom_cut = top_cut = 0
        notes = []
        if edge_bottom > EDGE_INK_MIN and edge_bottom > overall * 0.35:
            y = find_gap(range(h - 1, -1, -1))
            if y is None:
                notes.append('底部找不到空白带')
            elif (h - y) > h * MAX_TRIM_FRAC:
                notes.append(f'底部需裁 {h - y}px 超过 {MAX_TRIM_FRAC:.0%},放弃')
            else:
                bottom_cut = h - y
        if edge_top > EDGE_INK_MIN and edge_top > overall * 0.35:
            y = find_gap(range(0, h))
            if y is None:
                notes.append('顶部找不到空白带')
            elif y > h * MAX_TRIM_FRAC:
                notes.append(f'顶部需裁 {y}px 超过 {MAX_TRIM_FRAC:.0%},放弃')
            else:
                top_cut = y
        return w, h, top_cut, bottom_cut, '; '.join(notes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('uploads')
    ap.add_argument('--apply', action='store_true', help='真的改写图片(默认只试算)')
    ap.add_argument('--backup', default='', help='改写前把原图复制到这里')
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print('· 跳过:未装 Pillow')
        return 0

    if args.apply and args.backup:
        os.makedirs(args.backup, exist_ok=True)

    names = sorted(n for n in os.listdir(args.uploads)
                   if n.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')))
    changed = skipped = 0
    for n in names:
        path = os.path.join(args.uploads, n)
        try:
            w, h, top, bottom, note = plan(path)
        except Exception as e:
            print(f"  ✗ {n} 读取失败 {e}")
            continue
        if not top and not bottom:
            if note:
                print(f"  △ {n[:34]:<34} {w}×{h}  {note}")
                skipped += 1
            continue
        newh = h - top - bottom
        print(f"  {'✂' if args.apply else '·'} {n[:34]:<34} {w}×{h} → {w}×{newh}"
              f"  顶裁{top} 底裁{bottom}")
        if args.apply:
            if args.backup:
                shutil.copy2(path, os.path.join(args.backup, n))
            with Image.open(path) as im:
                im.crop((0, top, w, h - bottom)).save(path)
        changed += 1

    print(f"\n{'已裁剪' if args.apply else '待裁剪'} {changed} 张;放弃 {skipped} 张(安全阀拦下)")
    if not args.apply:
        print("加 --apply 才会真的改写;建议同时给 --backup 目录")
    return 0


if __name__ == '__main__':
    sys.exit(main())
