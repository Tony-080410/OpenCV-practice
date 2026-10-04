"""轮廓、多边形近似、最小外接旋转矩形，以及几何筛选的接受/拒绝理由。

用法:
    python tools/dump_contours.py --index 120
"""

import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 允许直接运行本脚本

import config                                              # noqa: E402
from src import bar_detector, color_segment, morph_ops, video_io, visualize  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="轮廓与几何筛选中间结果")
    parser.add_argument("--video", default=config.DEFAULT_VIDEO)
    parser.add_argument("--index", type=int, default=0, help="取第 N 帧（从 0 开始）")
    parser.add_argument("--method", default=config.SEGMENT_METHOD,
                        choices=config.SEGMENT_METHODS)
    parser.add_argument("--out", default=f"{config.DEBUG_DIR}/contours")
    args = parser.parse_args(argv)

    try:
        frame = video_io.read_frame(args.video, args.index)
    except video_io.VideoIOError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    mask = morph_ops.cleanup(color_segment.build_mask(frame, method=args.method))
    candidates = bar_detector.find_candidates(mask)
    kept, rejected = bar_detector.filter_candidates(candidates, frame.shape[:2])
    reason_of = {id(candidate): reason for candidate, reason in rejected}

    contour_panel = frame.copy()
    cv2.drawContours(contour_panel, [c.contour for c in candidates], -1, (0, 255, 0), 2)

    polygon_panel = frame.copy()
    for candidate in candidates:
        points = candidate.polygon.reshape(-1, 1, 2).astype("int32")
        cv2.polylines(polygon_panel, [points], True, (0, 255, 255), 2)

    rect_panel = visualize.draw_bars(frame, candidates, color=(255, 200, 0),
                                     thickness=2, draw_center=False)

    final_panel = visualize.draw_bars(frame, kept)
    final_panel = visualize.draw_bars(final_panel, [c for c, _ in rejected],
                                      color=(0, 0, 255), thickness=1, draw_center=False)

    cv2.imwrite(
        str(out_dir / "contours_and_filtering.png"),
        visualize.make_strip(
            [frame.copy(), contour_panel, polygon_panel, rect_panel, final_panel],
            ["original", "contours", "approxPolyDP", "minAreaRect",
             "kept(green)/rejected(red)"],
            panel_width=460,
        ),
    )
    cv2.imwrite(str(out_dir / "mask_cleaned.png"), mask)

    print(f"[信息] 中间结果: {out_dir / 'contours_and_filtering.png'}")
    print(f"[信息] 候选 {len(candidates)} 个 → 保留 {len(kept)} 个，剔除 {len(rejected)} 个")
    print(f"{'#':<4}{'面积':>10}{'长':>8}{'宽':>8}{'长宽比':>9}{'填充率':>9}"
          f"{'倾角':>8}  结论")
    for index, candidate in enumerate(candidates):
        m = bar_detector.metrics(candidate)
        reason = reason_of.get(id(candidate))
        verdict = "保留" if reason is None else f"剔除：{bar_detector.format_reason(reason)}"
        print(f"{index:<4}{m['area']:>10.1f}{m['length']:>8.1f}{m['width']:>8.1f}"
              f"{m['aspect']:>9.2f}{m['fill']:>9.3f}{m['tilt']:>8.1f}  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())