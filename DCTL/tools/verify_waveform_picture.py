#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Waveform Picture 验证 / 预览工具
================================
在 numpy 中完整模拟 "Waveform Picture GHYC.dctl" 的算法(Waterfall / 顺排模式), 输出:
  encoded.png  —— DCTL 节点会产出的画面(灰度瀑布条纹)
  waveform.png —— 模拟的波形监视器视图(把 encoded 送进示波器后看到的东西)
  preview.png  —— 并排对比: 原图 | 编码图 | 示波器中的隐藏画面

用法:
  python verify_waveform_picture.py [--input 图.png] [--bins 128] [--rowsub 2]
        [--gamma 1.8] [--exposure 1.0] [--mix 0.0] [--outdir ../preview]

不带 --input 时: 优先使用 Windows 自带壁纸(真实照片), 否则生成合成人脸测试图。
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


# --------------------------------------------------------------------------
# 合成测试图: 深色背景 + 亮色大头 + 暗色眼睛/嘴 —— 在波形图中应能认出"脸"
# --------------------------------------------------------------------------
def make_synthetic_face(w=640, h=480):
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.full((h, w, 3), 0.22, dtype=np.float64)

    def circle(cx, cy, r):
        return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r

    # 头
    head = circle(0.5 * w, 0.44 * h, 0.26 * h)
    img[head] = 0.88
    # 头发(顶部弧)
    hair = (circle(0.5 * w, 0.30 * h, 0.30 * h) & (yy < 0.30 * h))
    img[hair] = 0.12
    # 眼睛
    for cx in (0.5 * w - 0.10 * h, 0.5 * w + 0.10 * h):
        img[circle(cx, 0.44 * h, 0.032 * h)] = 0.03
    # 嘴(弧线)
    mouth = circle(0.5 * w, 0.55 * h, 0.09 * h) & ~circle(0.5 * w, 0.50 * h, 0.09 * h)
    img[mouth] = 0.03
    # 脖子/身体
    img[(xx > 0.5 * w - 0.11 * h) & (xx < 0.5 * w + 0.11 * h) & (yy > 0.66 * h)] = 0.45
    return img


# --------------------------------------------------------------------------
# DCTL 算法模拟(Waterfall / 顺排): 输入 RGB float [0,1] -> 输出灰度 float [0,1]
# --------------------------------------------------------------------------
def encode_dctl(img, bins=128, rowsub=2, gamma=1.8, exposure=1.0, mix=0.0, mono=False):
    h, w, _ = img.shape
    if mono:  # 与 DCTL get_color 一致: 先 Rec.709 转灰度
        luma_img = img @ LUMA
        img = np.repeat(luma_img[:, :, None], 3, axis=2)
    luma = img @ LUMA  # (H, W)

    # ---- Pass 1: 各列亮度剖面 prof[x, j], 每 bin 做 rowsub 次盒式平均 ----
    bins = min(bins, h)  # 与 DCTL 的 bnh 一致: 采样数不超画面高度
    binh = h / bins
    j = np.arange(bins)[:, None]
    s = np.arange(rowsub)[None, :]
    rows = np.clip(((j + (s + 0.5) / rowsub) * binh).astype(int), 0, h - 1)  # (bins, rowsub)
    prof = luma[rows].mean(axis=1).T  # (W, bins)
    w_ = np.clip(prof * exposure, 0.0, 1.0) ** gamma
    total = w_.sum(axis=1)  # (W,)

    # ---- u: 采样位置 = 行位置(自上而下) => 顺排/瀑布。与 DCTL 一致 ----
    u = (np.arange(h) + 0.5) / h  # (H,) -> broadcast (W, H)

    # ---- Pass 2: 逆 CDF -> pos (W, H), 与 DCTL 相同(含 frac 插值) ----
    target = u * total[:, None]  # (W, H)
    pos = np.full((w, h), 1.0)
    acc = np.zeros((w, h))
    for j in range(bins):
        prev = acc.copy()
        acc = acc + w_[:, j][:, None]
        frac = np.where(acc > prev, (target - prev) / np.maximum(acc - prev, 1e-9), 0.0)
        newpos = (j + frac) / bins
        m = (acc >= target) & (pos == 1.0)
        pos = np.where(m, newpos, pos)
    # 全零列: 均匀铺开
    zero_cols = total <= 1e-6
    if zero_cols.any():
        pos[zero_cols, :] = u[None, :]

    # ---- 电平映射(电平 1.0 顶部对应画面最上一行 => 正立) + 灰度 ----
    level = np.clip(1.0 - pos, 0.0, 1.0)
    out = np.repeat(level.T[:, :, None], 3, axis=2)  # (H, W, 3)

    # ---- Reveal 混合 ----
    if mix > 0.0:
        out = mix * img + (1.0 - mix) * out
    return np.clip(out, 0.0, 1.0)


# --------------------------------------------------------------------------
# 模拟波形监视器视图: 统计输出值分布并按"电平-位置"渲染
# 电平轴: 0 在底, 1 在顶(和 Resolve waveform 一致)
# --------------------------------------------------------------------------
def render_waveform(gray, levels=768):
    h, w = gray.shape
    idx = np.clip((gray * (levels - 1)).astype(int), 0, levels - 1)  # (H, W)
    counts = np.zeros((w, levels), dtype=np.float64)
    for x in range(w):
        counts[x] = np.bincount(idx[:, x], minlength=levels)

    maxc = counts.max()
    if maxc > 0:
        intensity = (counts / maxc) ** 0.55  # 模拟示波器点亮的非线性
    else:
        intensity = counts
    # 电平 0 在底部 -> 画布行 0 为顶部(电平 1); 返回 [0,1] 浮点
    canvas = np.zeros((levels, w))
    canvas[:, :] = 0.03  # 深色底
    for k in range(levels):
        canvas[levels - 1 - k, :] = 0.03 + 0.97 * intensity[:, k]
    return canvas.astype(np.float64)


def save(img, path):
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(path)


def main():
    ap = argparse.ArgumentParser(description="Waveform Picture DCTL 验证/预览")
    ap.add_argument("--input", default=None, help="输入图片路径(缺省自动选壁纸/合成图)")
    ap.add_argument("--bins", type=int, default=128)
    ap.add_argument("--rowsub", type=int, default=2, help="每 bin 的行采样数(盒式平均)")
    ap.add_argument("--gamma", type=float, default=1.8)
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--mix", type=float, default=0.0)
    ap.add_argument("--mono", action="store_true", help="先 Rec.709 转灰度(与 DCTL Convert to B&W 一致)")
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview"))
    args = ap.parse_args()

    # ---- 输入 ----
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
        print(f"输入: {path}  {im.size}")
    else:
        img = make_synthetic_face()
        print("无输入图片, 使用合成人脸测试图 640x480")

    h, w, _ = img.shape
    print(f"编码参数: bins={args.bins} rowsub={args.rowsub} "
          f"gamma={args.gamma} exposure={args.exposure} mix={args.mix}")

    # ---- 编码(即 DCTL 输出) ----
    out = encode_dctl(img, bins=args.bins, rowsub=args.rowsub, gamma=args.gamma,
                      exposure=args.exposure, mix=args.mix, mono=args.mono)
    gray = out @ LUMA

    # ---- 模拟示波器 ----
    scope = render_waveform(gray, levels=args.bins * 8)

    # ---- 保存 ----
    os.makedirs(args.outdir, exist_ok=True)
    enc = os.path.join(args.outdir, "encoded.png")
    scp = os.path.join(args.outdir, "waveform.png")
    save(out, enc)
    save(np.stack([scope] * 3, axis=-1), scp)
    print(f"已保存: {enc}")
    print(f"已保存: {scp}")

    # ---- 并排预览 ----
    sh = 480
    def scale(im):
        ih, iw = im.shape[:2]
        nw = int(iw * sh / ih)
        imn = Image.fromarray((np.clip(im, 0, 1) * 255).astype(np.uint8))
        return np.asarray(imn.resize((nw, sh), Image.LANCZOS), dtype=np.float64) / 255.0

    a = scale(img)
    b = scale(out)
    c = scale(np.stack([scope] * 3, axis=-1))
    gap = 6
    total = a.shape[1] + b.shape[1] + c.shape[1] + 2 * gap
    canvas = np.full((sh, total, 3), 0.05, dtype=np.float64)
    x0 = 0
    for part in (a, b, c):
        canvas[:, x0:x0 + part.shape[1]] = part
        x0 += part.shape[1] + gap
    prev = os.path.join(args.outdir, "preview.png")
    save(canvas, prev)
    print(f"已保存: {prev}")
    print("\n说明: 左=原图  中=DCTL输出(直接看是灰度瀑布条纹)  右=示波器中的隐藏画面")
    print("     右图应当能看出和左图相同的画面内容。")


if __name__ == "__main__":
    main()
