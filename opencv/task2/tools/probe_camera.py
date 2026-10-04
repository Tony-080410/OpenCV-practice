"""探测摄像头的真实能力：支持的像素格式/分辨率、以及可用的 V4L2 控制项。

为什么要单独探一次：`cv2.VideoCapture.isOpened()` 为真不代表拿到了你要的分辨率，
而“内参必须与分辨率成对”，所以标定前必须确认相机到底能给什么。
本机不装 v4l-utils 也能跑（直接 ioctl）。

用法：python tools/probe_camera.py            # 默认探 /dev/video0 /dev/video1 等
      python tools/probe_camera.py /dev/video0
"""
from __future__ import annotations

import fcntl
import os
import struct
import sys

BUF_TYPE_CAPTURE = 1
FRMSIZE_DISCRETE, FRMSIZE_STEPWISE = 1, 2
CTRL_FLAG_DISABLED = 0x0001

# 关心的控制项（cid -> 便于阅读的名字，内核名会一并打印）
CTRLS = [
    (0x00980900, "brightness"),
    (0x00980901, "contrast"),
    (0x00980902, "saturation"),
    (0x00980910, "gamma"),
    (0x009A0901, "exposure_auto"),
    (0x009A0902, "exposure_absolute(曝光时间)"),
    (0x009A090A, "focus_absolute"),
    (0x009A090C, "focus_auto"),
]


def ioc(dir_: int, type_: str, nr: int, size: int) -> int:
    """_IOC(dir,type,nr,size)；_IOR=2, _IOW=1, _IOWR=3。"""
    return (dir_ << 30) | (size << 16) | (ord(type_) << 8) | nr


def call(fd: int, req: int, buf: bytearray) -> bytearray:
    """mutate=True 时 ioctl 返回 int，填充结果在 buf 里，所以要回传 buf。"""
    fcntl.ioctl(fd, req, buf, True)
    return buf


def query_cap(fd: int):
    cap = call(fd, ioc(2, "V", 0, 104), bytearray(104))     # VIDIOC_QUERYCAP
    txt = lambda b: b.split(b"\0")[0].decode("ascii", "replace")   # noqa: E731
    driver, card, bus = txt(cap[0:16]), txt(cap[16:48]), txt(cap[48:80])
    version, capabilities, device_caps = struct.unpack("III", cap[80:92])
    return driver, card, bus, capabilities, device_caps


def enum_formats(fd: int):
    req = ioc(3, "V", 2, 64)                                # VIDIOC_ENUM_FMT
    out = []
    for i in range(16):
        buf = bytearray(struct.pack("IIII", i, BUF_TYPE_CAPTURE, 0, 0)
                        + bytes(32) + struct.pack("III", 0, 0, 0) + bytes(12))
        try:
            res = call(fd, req, buf)
        except OSError:
            break
        out.append((struct.unpack("I", res[44:48])[0],
                    res[12:44].split(b"\0")[0].decode("ascii", "replace")))
    return out


def enum_sizes(fd: int, pixfmt: int):
    req = ioc(3, "V", 74, 44)                               # VIDIOC_ENUM_FRAMESIZES
    out = []
    for i in range(32):
        buf = bytearray(struct.pack("III", i, pixfmt, 0) + bytes(32))
        try:
            res = call(fd, req, buf)
        except OSError:
            break
        kind = struct.unpack("I", res[8:12])[0]
        v = struct.unpack("IIIIII", res[12:36])
        if kind == FRMSIZE_DISCRETE:
            out.append(f"{v[0]}x{v[1]}")
        elif kind == FRMSIZE_STEPWISE:
            out.append(f"{v[0]}~{v[1]}/{v[2]} x {v[3]}~{v[4]}/{v[5]}")
    return out


def query_ctrl(fd: int, cid: int):
    # sizeof(struct v4l2_queryctrl) = 4+4+32+4+4+4+4+4+8 = 68（大小必须精确，否则内核报 ENOTTY）
    res = call(fd, ioc(3, "V", 36, 68), bytearray(struct.pack("II", cid, 0) + bytes(64)))
    _, ctype, cname, mn, mx, step, default, flags = struct.unpack("II32siiiiI", res[:60])
    return cname.split(b"\0")[0].decode("ascii", "replace"), mn, mx, step, default, flags


def get_ctrl(fd: int, cid: int):
    return struct.unpack("Ii", call(fd, ioc(3, "V", 27, 8),
                                    bytearray(struct.pack("Ii", cid, 0))))[1]


def probe(dev: str) -> None:
    print(f"\n=== {dev} ===")
    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except OSError as e:
        print(f"  打不开：{e}")
        return
    try:
        try:
            driver, card, bus, caps, dev_caps = query_cap(fd)
            print(f"  driver={driver}  card={card}  bus={bus}")
            print(f"  可采集：{bool(caps & 0x1)}（本节点 {bool(dev_caps & 0x1)}）")
        except OSError as e:
            print(f"  QUERYCAP 失败：{e}")
        try:
            for pixfmt, desc in enum_formats(fd):
                fourcc = "".join(chr((pixfmt >> (8 * j)) & 0xFF) for j in range(4))
                sizes = list(dict.fromkeys(enum_sizes(fd, pixfmt)))
                print(f"  格式 {fourcc:<5}({desc})：" + (", ".join(sizes) or "无尺寸信息"))
        except OSError as e:
            print(f"  ENUM_FMT 失败：{e}")
        print("  控制项（无输出的项表示该相机不提供）：")
        for cid, name in CTRLS:
            try:
                cname, mn, mx, step, default, flags = query_ctrl(fd, cid)
            except OSError:
                continue
            if flags & CTRL_FLAG_DISABLED:
                print(f"    {name:22s} 存在但禁用（内核名 {cname}）")
                continue
            try:
                cur = get_ctrl(fd, cid)
            except OSError:
                cur = None
            print(f"    {name:22s} 范围 {mn}~{mx} 步长 {step} 默认 {default}"
                  + (f"  当前 {cur}" if cur is not None else "") + f"  (内核名 {cname})")
    finally:
        os.close(fd)


def main() -> int:
    devs = sys.argv[1:] or [f"/dev/video{i}" for i in range(4)]
    for d in devs:
        if os.path.exists(d):
            probe(d)
    print("\n提示：AVFoundation/GStreamer 后端各有差异，本工具读的是 V4L2 层；"
          "OpenCV 是否真的拿到某分辨率，用 main.py demo 启动时打印的相机信息为准。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
