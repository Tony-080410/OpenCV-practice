"""视频读写：打开、取尺寸、算真实帧率、创建写入器。"""

import struct
from pathlib import Path

import cv2


class VideoIOError(RuntimeError):
    """读不到视频或画面。"""


def open_video(path):
    return cv2.VideoCapture(str(path))


def video_info(cap):
    """返回 (宽, 高)。"""
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    return width, height


def count_frames(path):
    """数出真实帧数。grab() 只解码不转图像，比 read() 快。"""
    cap = open_video(path)
    total = 0
    while cap.grab():
        total += 1
    cap.release()
    return total


def read_duration(path):
    """从 WebM/Matroska 文件头读时长（秒），读不到返回 None。

    录屏工具常把时间基准 1 ms 写进去, OpenCV 会把它当成 1000 fps,
    所以帧率要用"真实帧数 / 真实时长"算，不能直接用容器帧率。
    """
    with open(path, "rb") as handle:
        head = handle.read(65536)

    scale = 1_000_000                             # TimecodeScale 默认 1 ms
    pos = head.find(b"\x2a\xd7\xb1")
    if pos >= 0:
        size, start = _read_vint(head, pos + 3)
        if size and start + size <= len(head):
            scale = int.from_bytes(head[start:start + size], "big")

    pos = head.find(b"\x44\x89")                  # Duration
    if pos < 0:
        return None
    size, start = _read_vint(head, pos + 2)
    if size not in (4, 8):
        return None
    value = struct.unpack(">f" if size == 4 else ">d", head[start:start + size])[0]
    return value * scale / 1.0e9


def _read_vint(data, pos):
    """解析 EBML 可变长度整数。"""
    first = data[pos]
    length, mask = 1, 0x80
    while not (first & mask):
        mask >>= 1
        length += 1
    value = first & (mask - 1)
    for index in range(1, length):
        value = (value << 8) | data[pos + index]
    return value, pos + length


def source_fps(path):
    """真实帧率 = 真实帧数 / 真实时长；算不出来时按 30 fps。"""
    duration = read_duration(path)
    frames = count_frames(path)
    return frames / duration if duration and frames else 30.0


def read_frame(path, index=0):
    """顺序读到第 index 帧（tools/ 用）。
    """
    cap = open_video(path)
    frame = None
    for _ in range(index + 1):
        ok, frame = cap.read()
        if not ok:
            frame = None
            break
    cap.release()
    if frame is None:
        raise VideoIOError(f"读不到第 {index} 帧: {path}")
    return frame

def create_writer(path, fps, size, fourcc="mp4v"):
    """创建输出视频；size 是 (宽, 高)，写入帧的分辨率必须完全一致。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    code = fourcc if isinstance(fourcc, int) else cv2.VideoWriter_fourcc(*str(fourcc))
    return cv2.VideoWriter(str(path), code, float(fps), tuple(size))