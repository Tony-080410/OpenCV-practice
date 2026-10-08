"""生成「手机屏专用棋盘格」——只有格子、铺满屏宽，比整页 A4 干脆大 2~3 倍。

为什么需要这张图：`make_patterns.py` 产出的 `chessboard_9x6_20mm.png` 是**整页 A4 版式**
（含页眉、说明、100 mm 校验尺，页面 297x210 mm）。把它丢到手机上全屏显示，缩放是以**整页**
为基准的，棋盘只占页宽的 67%，格子被压到 ~2.8 mm —— 角点像素间距太小，标定质量很差。

这张图只画棋盘本身（没有任何文字/刻度），并且**把棋盘竖起来放**（格子多的方向朝竖直），
于是竖屏手机上是"宽度受限"：棋盘横向铺满屏幕宽度，格子能到 ~9~10 mm。

产物：assets/patterns/chessboard_{cols}x{rows}_phone_screen.png

用法：
    python tools/make_screen_chessboard.py                       # 默认 9x6 内角点（与 config 一致）
    python tools/make_screen_chessboard.py --inner-cols 5 --inner-rows 4 --cell-px 160

显示与实测：
    传到手机 -> 用"全屏/无 UI"的看图方式显示 -> 用直尺量**棋盘整体宽度**再除以格数，
    得到单个方格的毫米数 -> 填 config.py: BOARD_SQUARE_MM 与 data/measurements.md

注意：
  * 图上没有任何文字（文字会被当成噪声干扰角点检测），所以尺寸只能靠实测，别用文件名里的数字。
  * 手机竖着拿，屏幕上显示的就是这张图，不要旋转图片。
"""
import argparse
import os
import pathlib
import sys

import cv2
import numpy as np


def build_board(inner_cols: int, inner_rows: int, cell_px: int,
                margin_ratio: float) -> np.ndarray:
    """画一块纯棋盘格：方格数 = (inner_cols+1) x (inner_rows+1)，格子边长 cell_px 像素。

    竖屏优化：把方格数多的方向转到竖直（手机上竖直方向不受限，宽度才是瓶颈）。
    """
    n_c, n_r = inner_cols + 1, inner_rows + 1
    if n_c > n_r:
        n_c, n_r = n_r, n_c

    rr = np.arange(n_r).repeat(cell_px)[:, None]
    cc = np.arange(n_c).repeat(cell_px)[None, :]
    board = np.where((rr + cc) % 2 == 1, 255, 0).astype(np.uint8)   # (0,0) 为黑

    h, w = board.shape
    margin = int(round(w * margin_ratio))
    canvas = np.full((h + 2 * margin, w + 2 * margin), 255, np.uint8)
    canvas[margin:margin + h, margin:margin + w] = board
    return canvas


def main() -> int:
    ap = argparse.ArgumentParser(description="生成手机屏专用棋盘格（只有格子、铺满屏宽）")
    ap.add_argument("--inner-cols", type=int, default=9, help="内角点列数（默认 9，与 config 一致）")
    ap.add_argument("--inner-rows", type=int, default=6, help="内角点行数（默认 6，与 config 一致）")
    ap.add_argument("--cell-px", type=int, default=120, help="每个方格的像素边长（整数，保证边缘对齐）")
    ap.add_argument("--margin-ratio", type=float, default=0.05,
                    help="棋盘四周留白占棋盘宽的比例（避免被屏幕圆角/状态栏裁掉）")
    ap.add_argument("--outdir", default="assets/patterns")
    a = ap.parse_args()

    if a.inner_cols < 3 or a.inner_rows < 3:
        print("[错误] 内角点数太少（至少要 3x3），标定需要足够的点")
        return 1
    if a.cell_px < 20:
        print("[错误] --cell-px 太小，边缘会出现锯齿影响角点检测")
        return 1

    img = build_board(a.inner_cols, a.inner_rows, a.cell_px, a.margin_ratio)
    outdir = pathlib.Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"chessboard_{a.inner_cols}x{a.inner_rows}_phone_screen.png"
    if not cv2.imwrite(str(out), img):
        print(f"[错误] 写盘失败：{out}")
        return 1

    n_c, n_r = a.inner_cols + 1, a.inner_rows + 1
    if n_c > n_r:                      # 与 build_board 保持一致
        n_c, n_r = n_r, n_c
    board_w = n_c * a.cell_px
    board_h = n_r * a.cell_px
    frac = board_w / img.shape[1]

    print(f"[1] 已生成 {out}")
    print(f"    方格 {n_c} 列 x {n_r} 行 = {a.inner_cols + 1} x {a.inner_rows + 1} 个方格，"
          f"内角点 {a.inner_cols} x {a.inner_rows}（与 config.py 一致）")
    print(f"    图片 {img.shape[1]}x{img.shape[0]} px；棋盘占图片宽度的 {frac * 100:.1f}%")
    print(f"    → 手机上全屏显示时：若屏幕宽 W mm，则单格 ≈ {frac * 100:.1f}% x W / {n_c} mm")
    print(f"      例如 W = 70 mm → 单格 ≈ {frac * 70 / n_c:.1f} mm（务必自己量，以实测为准）")
    print("    关键：量**棋盘整体宽度**再除以格数，比量单个格子准；实测值填 "
          "config.py: BOARD_SQUARE_MM")

    # 自检：图上能不能检出棋盘（用 config 的角点顺序，以及转 90 度后的顺序）
    for size in ((a.inner_cols, a.inner_rows), (a.inner_rows, a.inner_cols)):
        ok, corners = cv2.findChessboardCorners(img, size, None)
        print(f"[2] findChessboardCorners{size} = {ok}"
              + (f"，首个内角点 {np.round(corners[0, 0], 1)}" if ok else ""))
    return 0


if __name__ == "__main__":
    _code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code)          # 本机 OpenCV 在解释器清理阶段会随机段错误，直接带码退出
