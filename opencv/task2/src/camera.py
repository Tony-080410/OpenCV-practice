"""相机接入：打开、设置采集参数、抓帧。

职责只有一件事：把 BGR 帧交给上层。不含任何检测、位姿或画图逻辑。

V4L2 的坑：不显式设 MJPG，驱动只会给 640x480。所以顺序是
先设 FOURCC，再设宽高，最后读回确认——设置可能被驱动拒绝，
这时要如实报出实际分辨率，不能默默按请求的分辨率处理
（内参与分辨率必须成对，见 README）。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

import config


@dataclass
class CameraInfo:
    index: int
    width: int
    height: int
    fourcc: str
    fps: float
    note: str = ""

    def describe(self) -> str:
        base = (f"相机 {self.index}：{self.width}x{self.height} @{self.fps:.1f}fps "
                f"fourcc={self.fourcc}")
        return f"{base}；{self.note}" if self.note else base


class CameraError(RuntimeError):
    """打不开相机或读不到帧。"""


class Camera:
    """with Camera(0) as cam: ok, frame = cam.read()"""

    def __init__(self, index: int = None, width: int = None, height: int = None,
                 fourcc: str = None):
        self.index = config.CAMERA_INDEX if index is None else index
        self.req_width = config.CAMERA_WIDTH if width is None else width
        self.req_height = config.CAMERA_HEIGHT if height is None else height
        self.req_fourcc = config.CAMERA_FOURCC if fourcc is None else fourcc
        self.cap: cv2.VideoCapture | None = None
        self.info: CameraInfo | None = None

    def open(self) -> CameraInfo:
        cap = cv2.VideoCapture(self.index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            raise CameraError(f"打不开相机索引 {self.index}")

        if self.req_fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.req_fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.req_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.req_height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, config.CAMERA_BUFFERSIZE)

        ok, _ = cap.read()                      # 先读一帧，让驱动把格式定下来
        if not ok:
            cap.release()
            raise CameraError(f"相机 {self.index} 打开但读不到帧")

        self.cap = cap
        note = self._apply_exposure(cap)
        self.info = CameraInfo(
            index=self.index,
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fourcc=self._fourcc_str(cap),
            fps=float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
            note=note,
        )
        return self.info

    @staticmethod
    def _apply_exposure(cap: cv2.VideoCapture) -> str:
        """曝光策略：默认保持相机的自动曝光；配置要求锁定时切手动并回读确认。

        OpenCV 的 CAP_PROP_AUTO_EXPOSURE 在 V4L2 下 0.25=手动、0.75=自动。
        回读很重要：驱动可能拒绝设置，这时要如实说出来，不能假装锁上了。
        """
        if not config.CAMERA_LOCK_EXPOSURE:
            return "自动曝光（config.CAMERA_LOCK_EXPOSURE=False）"
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        cap.set(cv2.CAP_PROP_EXPOSURE, float(config.CAMERA_EXPOSURE_ABSOLUTE))
        got = cap.get(cv2.CAP_PROP_EXPOSURE)
        if abs(float(got) - float(config.CAMERA_EXPOSURE_ABSOLUTE)) > 1.0:
            return (f"手动曝光设置未生效：请求 {config.CAMERA_EXPOSURE_ABSOLUTE}，"
                    f"驱动回读 {got:.1f}（该相机可能不支持，或范围不同）")
        return f"手动曝光 {got:.0f}（已锁定）"

    @staticmethod
    def _fourcc_str(cap: cv2.VideoCapture) -> str:
        v = int(cap.get(cv2.CAP_PROP_FOURCC))
        return "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4)).strip()

    def read(self) -> tuple[bool, np.ndarray | None]:
        """返回 (是否成功, BGR 帧)。失败时帧为 None，不抛异常，交给上层决定。"""
        if self.cap is None:
            return False, None
        ok, frame = self.cap.read()
        return (ok, frame) if ok else (False, None)

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
