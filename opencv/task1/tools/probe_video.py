"""打印视频的容器帧率、真实帧数、真实时长、真实帧率。"""

import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config                                # noqa: E402
from src import video_io                     # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="视频真实参数")
    parser.add_argument("--video", default=config.DEFAULT_VIDEO)
    args = parser.parse_args()

    cap = video_io.open_video(args.video)
    if not cap.isOpened():
        print(f"[错误] 打不开视频: {args.video}")
        return 1
    container_fps = cap.get(cv2.CAP_PROP_FPS)
    container_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    duration = video_io.read_duration(args.video)
    print(f"容器帧率 : {container_fps}（可能是时间基准，不可信）")
    print(f"容器帧数 : {container_frames}（可能是估算值，不可信）")
    print(f"真实帧数 : {video_io.count_frames(args.video)}")
    print(f"真实时长 : {duration:.2f} s" if duration else "真实时长 : 读不到（非 WebM/MKV）")
    print(f"真实帧率 : {video_io.source_fps(args.video):.2f} fps")
    return 0


if __name__ == "__main__":
    sys.exit(main())