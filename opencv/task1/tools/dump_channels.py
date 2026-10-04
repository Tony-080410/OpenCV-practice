"""原图、B/G/R 分通道、灰度图、两种颜色分割掩膜。

用法:
    python tools/dump_channels.py                                        # 默认第 0 帧
    python tools/dump_channels.py --index 120 --out outputs/screenshots/f0120
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 允许直接运行本脚本

import config                                              # noqa: E402
from src import color_segment, video_io, visualize         # noqa: E402


def white_ratio(mask):
    """白像素占比（百分比）。"""
    return float(np.count_nonzero(mask)) / float(mask.size) * 100.0


def main(argv=None):
    parser = argparse.ArgumentParser(description="导出单帧通道图与颜色分割结果")
    parser.add_argument("--video", default=config.DEFAULT_VIDEO)
    parser.add_argument("--index", type=int, default=0, help="取第 N 帧（从 0 开始）")
    parser.add_argument("--out", default=f"{config.DEBUG_DIR}/channels")
    args = parser.parse_args(argv)

    try:
        frame = video_io.read_frame(args.video, args.index)
    except video_io.VideoIOError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    b, g, r = cv2.split(frame)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mask_diff = color_segment.blue_dominance_mask(frame)
    mask_hsv = color_segment.hsv_mask(frame)

    saved = [
        ("00_original.png", frame),
        ("01_channel_B.png", b),
        ("02_channel_G.png", g),
        ("03_channel_R.png", r),
        ("04_gray.png", gray),
        ("05_mask_blue_dominance.png", mask_diff),
        ("06_mask_hsv.png", mask_hsv),
    ]
    for name, image in saved:
        cv2.imwrite(str(out_dir / name), image)

    strip = visualize.make_strip(
        [frame, b, g, r, gray, mask_diff, mask_hsv],
        ["original", "B", "G", "R", "gray", "B-max(G,R)", "HSV"],
    )
    cv2.imwrite(str(out_dir / "07_channels_and_masks.png"), strip)

    print(f"[信息] 已写入 {len(saved) + 1} 张图到 {out_dir}")
    print(f"[信息] 白像素占比  通道差分 {white_ratio(mask_diff):.3f}%  "
          f"HSV {white_ratio(mask_hsv):.3f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())