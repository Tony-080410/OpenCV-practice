"""任务一入口：读视频，逐帧分割、形态学、检测、画框，输出标记视频。"""

import argparse
import time

import cv2

import config
from src import bar_detector, color_segment, morph_ops, video_io, visualize


def detect(frame):
    """一帧的完整处理链：帧 → 灯条列表。"""
    mask = morph_ops.cleanup(color_segment.build_mask(frame))
    bars, _ = bar_detector.detect(mask)
    return bars


def main():
    parser = argparse.ArgumentParser(description="任务一：装甲板灯条识别")
    parser.add_argument("--video", default=config.DEFAULT_VIDEO)
    parser.add_argument("--output", default=config.OUTPUT_VIDEO)
    parser.add_argument("--show", action="store_true", help="实时预览（WSL 需 WSLg）")
    parser.add_argument("--max-frames", type=int, default=0, help="只处理前 N 帧，0=全部")
    args = parser.parse_args()

    cap = video_io.open_video(args.video)
    if not cap.isOpened():                       # 路径写错或文件打不开
        print(f"[错误] 打不开视频: {args.video}")
        return 1

    width, height = video_io.video_info(cap)
    fps = config.OUTPUT_FPS or video_io.source_fps(args.video)
    writer = video_io.create_writer(args.output, fps, (width, height), config.FOURCC)
    if not writer.isOpened():                    # 编码器不支持或路径不可写，否则会静默产出空视频
        print(f"[错误] 打不开视频写入器: {args.output}"
              f"（检查路径与编码 fourcc={config.FOURCC}）")
        cap.release()
        return 1
    print(f"[信息] {width}x{height}，输出 {fps:.2f} fps → {args.output}")

    index = 0
    total_ms = 0.0
    total_bars = 0
    while True:
        ok, frame = cap.read()
        if not ok:                               # 视频结束
            break

        start = time.perf_counter()
        bars = detect(frame)
        cost_ms = (time.perf_counter() - start) * 1000.0
        total_ms += cost_ms
        total_bars += len(bars)
        print(f"frame {index:>4} | bars {len(bars)} | cost {cost_ms:6.1f} ms")

        canvas = visualize.draw_bars(frame, bars)
        canvas = visualize.draw_hud(canvas, index, len(bars), cost_ms)
        writer.write(canvas)

        if args.show:
            cv2.imshow("task1", canvas)
            if (cv2.waitKey(1) & 0xFF) in (27, ord("q")):
                break

        index += 1
        if args.max_frames and index >= args.max_frames:
            break

    cap.release()
    writer.release()
    if args.show:
        cv2.destroyAllWindows()
    print(f"[完成] 处理 {index} 帧，视频已保存到 {args.output}")
    if index:
        print(f"[统计] 平均耗时 {total_ms / index:.2f} ms/帧，"
              f"平均灯条 {total_bars / index:.2f} 条/帧")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())