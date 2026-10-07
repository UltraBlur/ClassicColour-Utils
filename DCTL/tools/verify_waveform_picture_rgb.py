#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Waveform Picture · RGB Parade 验证 / 预览工具
=============================================
在 numpy 中完整模拟 "Waveform Picture GHYC RGB.dctl" 的算法(三通道独立逆 CDF,
共用行位置 u)。输出一张拼接图(只出 1 张):
  preview_rgb.png —— 左: 原图 | 中: 彩色瀑布(节点输出) | 右三: R/G/B Parade 波形面板

用法:
  python verify_waveform_picture_rgb.py [--input 图.png] [--bins 128] [--rowsub 2]
        [--gamma 1.8] [--exposure 1.0] [--mix 0.0] [--outdir DCTL/preview]
"""

import argparse
import os
import sys

import numpy as np

try:
    from PIL import Image
except ImportError:
    print("需要 Pillow:  pip install pillow")
    sys.exit(1)

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)  # Rec.709

WINDOWS_WALLPAPERS = [
    r"C:\Windows\Web\Wallpaper\Windows\img0.jpg",
    r"C:\Windows\Web\Wallpaper\Windows\img1.jpg",
    r"C:\Windows\Web\Wallpaper\Windows\img2.jpg",
    r"C:\Windows\Web\Wallpaper\Windows\img3.jpg",
]


def make_synthetic_face(w=640, h=480):
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.full((h, w, 3), 0.22, dtype=np.float64)
    def circle(cx, cy, r):
        return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    head = circle(0.5 * w, 0.44 * h, 0.26 * h)
    img[head] = 0.88
    hair = (circle(0.5 * w, 0.30 * h, 0.30 * h) & (yy < 0.30 * h))
    img[hair] = 0.12
    for cx in (0.5 * w - 0.10 * h, 0.5 * w + 0.10 * h):
        img[circle(cx, 0.44 * h, 0.032 * h)] = 0.03
    mouth = circle(0.5 * w, 0.55 * h, 0.09 * h) & ~circle(0.5 * w, 0.50 * h, 0.09 * h)
    img[mouth] = 0.03
    img[(xx > 0.5 * w - 0.11 * h) & (xx < 0.5 * w + 0.11 * h) & (yy > 0.66 * h)] = 0.45
    return img


# 单通道编码: 2D (H,W) -> 输出电平 (H,W)。与 DCTL 的 invcdf 一致(含 frac 插值)。
def encode_channel(ch, bins, rowsub, gamma, exposure):
    h, w = ch.shape
    bins = min(bins, h)  # 与 DCTL 的 bnh 一致: 采样数不超画面高度
    binh = h / bins
    j = np.arange(bins)[:, None]
    s = np.arange(rowsub)[None, :]
    rows = np.clip(((j + (s + 0.5) / rowsub) * binh).astype(int), 0, h - 1)
    prof = np.clip(ch[rows].mean(axis=1).T * exposure, 0.0, 1.0) ** gamma  # (W, bins)
    total = prof.sum(axis=1)  # (W,)
    u = (np.arange(h) + 0.5) / h  # (H,)
    target = u * total[:, None]  # (W, H)
    pos = np.full((w, h), 1.0)
    acc = np.zeros((w, h))
    for jj in range(bins):
        prev = acc.copy()
        acc = acc + prof[:, jj][:, None]
        with np.errstate(invalid="ignore"):
            frac = np.where(acc > prev, (target - prev) / np.maximum(acc - prev, 1e-9), 0.0)
        newpos = (jj + frac) / bins
        m = (acc >= target) & (pos == 1.0)
        pos = np.where(m, newpos, pos)
    zero_cols = total <= 1e-6
    if zero_cols.any():
        pos[zero_cols, :] = u[None, :]
    level = np.clip(1.0 - pos, 0.0, 1.0).T  # (H, W)
    return level


def render_waveform(gray, levels=768):
    h, w = gray.shape
    idx = np.clip((gray * (levels - 1)).astype(int), 0, levels - 1)
    counts = np.zeros((w, levels), dtype=np.float64)
    for x in range(w):
        counts[x] = np.bincount(idx[:, x], minlength=levels)
    maxc = counts.max()
    intensity = (counts / maxc) ** 0.55 if maxc > 0 else counts
    canvas = np.zeros((levels, w))
    canvas[:, :] = 0.03
    for k in range(levels):
        canvas[levels - 1 - k, :] = 0.03 + 0.97 * intensity[:, k]
    return canvas


def save(img, path):
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(path)


def main():
    ap = argparse.ArgumentParser(description="Waveform Picture RGB Parade 验证/预览")
    ap.add_argument("--input", default=None)
    ap.add_argument("--bins", type=int, default=128)
    ap.add_argument("--rowsub", type=int, default=2)
    ap.add_argument("--gamma", type=float, default=1.8)
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--mix", type=float, default=0.0)
    ap.add_argument("--mono", action="store_true", help="先 Rec.709 转灰度(与 DCTL Convert to B&W 一致)")
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview"))
    args = ap.parse_args()

    path = args.input
    if path is None or not os.path.exists(path):
        path = None
        for p in WINDOWS_WALLPAPERS:
            if os.path.exists(p):
                path = p
                print(f"使用系统壁纸: {p}")
                break
    if path:
        im = Image.open(path).convert("RGB")
        w0, h0 = im.size
        maxw = 1920
        if w0 > maxw:
            im = im.resize((maxw, int(h0 * maxw / w0)), Image.LANCZOS)
        img = np.asarray(im, dtype=np.float64) / 255.0
    else:
        img = make_synthetic_face()
        print("无输入图片, 使用合成人脸测试图 640x480")

    h, w, _ = img.shape
    print(f"编码参数: bins={args.bins} rowsub={args.rowsub} "
          f"gamma={args.gamma} exposure={args.exposure} mix={args.mix}")

    # ---- 三通道独立编码 (RGB 与 DCTL 一致, 共用 u) ----
    if args.mono:  # 与 DCTL get_color 一致: 先 Rec.709 转灰度
        luma_img = img @ LUMA
        img = np.repeat(luma_img[:, :, None], 3, axis=2)
    lr = encode_channel(img[..., 0], args.bins, args.rowsub, args.gamma, args.exposure)
    lg = encode_channel(img[..., 1], args.bins, args.rowsub, args.gamma, args.exposure)
    lb = encode_channel(img[..., 2], args.bins, args.rowsub, args.gamma, args.exposure)
    encoded = np.stack([lr, lg, lb], axis=-1)  # (H, W, 3)
    if args.mix > 0.0:
        encoded = np.clip(args.mix * img + (1.0 - args.mix) * encoded, 0.0, 1.0)

    # ---- 三条 Parade 波形面板 ----
    levels = args.bins * 8
    pR = render_waveform(lr, levels)
    pG = render_waveform(lg, levels)
    pB = render_waveform(lb, levels)

    # ---- 拼接: 原图 | 彩色瀑布 | R/G/B 面板 ----
    sh = 480
    def scale(im):
        ih, iw = im.shape[:2]
        nw = int(iw * sh / ih)
        imn = Image.fromarray((np.clip(im, 0, 1) * 255).astype(np.uint8))
        return np.asarray(imn.resize((nw, sh), Image.LANCZOS), dtype=np.float64) / 255.0

    def scale_panel(p):
        ih, iw = p.shape
        nw = int(iw * sh / ih)
        imn = Image.fromarray((np.clip(p, 0, 1) * 255).astype(np.uint8))
        gray = np.asarray(imn.resize((nw, sh), Image.LANCZOS), dtype=np.float64) / 255.0
        return np.stack([gray] * 3, axis=-1)  # 3 通道, 便于拼进画布

    a = scale(img)
    b = scale(encoded)
    panels = [scale_panel(p) for p in (pR, pG, pB)]
    gap = 6
    widths = [x.shape[1] for x in [a, b] + panels]
    total = sum(widths) + gap * (len(widths) - 1)
    canvas = np.full((sh, total, 3), 0.05, dtype=np.float64)
    x0 = 0
    for part in [a, b] + panels:
        canvas[:, x0:x0 + part.shape[1]] = part
        x0 += part.shape[1] + gap

    os.makedirs(args.outdir, exist_ok=True)
    out = os.path.join(args.outdir, "preview_rgb.png")
    save(canvas, out)
    print(f"已保存: {out}")
    print("说明: 左=原图  中=彩色瀑布(节点输出)  右三=R/G/B Parade 波形面板(各应还原对应通道)")
    print("     把 R/G/B 三面板并排看, 即可合成彩色原图。")


if __name__ == "__main__":
    main()
