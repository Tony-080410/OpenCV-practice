"""同一帧套几组形态学配置，比白像素占比、轮廓数、筛出的灯条数，另出拼图。"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 允许直接运行本脚本

import config                                              # noqa: E402
from src import bar_detector, color_segment, morph_ops, video_io, visualize  # noqa: E402

# (标签, 开运算核, 闭运算核)；None 表示不做该操作
CONFIGS = [
    ("A_none", None, None),
    ("B_open3", (3, 3), None),
    ("C_close3", None, (3, 3)),
    ("D_open3_close3", (3, 3), (3, 3)),
    ("E_close5", None, (5, 5)),
]


def count_contours(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return len(contours)


def main(argv=None):
    parser = argparse.ArgumentParser(description="形态学配置对比")
    parser.add_argument("--video", default=config.DEFAULT_VIDEO)
    parser.add_argument("--index", type=int, default=0, help="取第 N 帧（从 0 开始）")
    parser.add_argument("--method", default=config.SEGMENT_METHOD,
                        choices=config.SEGMENT_METHODS)
    parser.add_argument("--out", default=f"{config.DEBUG_DIR}/morphology")
    args = parser.parse_args(argv)

    try:
        frame = video_io.read_frame(args.video, args.index)
    except video_io.VideoIOError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_mask = color_segment.build_mask(frame, method=args.method)
    panels, labels, rows = [raw_mask], [f"{args.method} (raw)"], []

    for label, open_ksize, close_ksize in CONFIGS:
        mask = morph_ops.cleanup(raw_mask, open_ksize, close_ksize)
        bars, rejected = bar_detector.detect(mask)
        white = float(np.count_nonzero(mask)) / float(mask.size) * 100.0
        rows.append((label, white, count_contours(mask), len(bars), len(rejected)))
        cv2.imwrite(str(out_dir / f"mask_{label}.png"), mask)
        panels.append(mask)
        labels.append(label)

    cv2.imwrite(str(out_dir / "morphology_compare.png"),
                visualize.make_strip(panels, labels, panel_width=420))

    print(f"[信息] 对比图: {out_dir / 'morphology_compare.png'}")
    print(f"{'配置':<18}{'白像素占比':>12}{'轮廓数':>8}{'通过筛选':>10}{'被剔除':>8}")
    for label, white, contour_count, kept, rejected in rows:
        print(f"{label:<18}{white:>11.3f}%{contour_count:>8}{kept:>10}{rejected:>8}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())