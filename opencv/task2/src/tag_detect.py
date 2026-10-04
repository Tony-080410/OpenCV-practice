"""AprilTag 检测：只负责“画面里有哪些 Tag”，不做目标选择、不解算位姿。

角点次序（实测确定，见 spike/RESULTS.md 第三节）：
    corners[0] 左下 (-s/2, +s/2)
    corners[1] 右下 (+s/2, +s/2)
    corners[2] 右上 (+s/2, -s/2)
    corners[3] 左上 (-s/2, -s/2)
即 tag 系（x 右、y 下）下以左下角为起点、逆时针。
官方图案与 cv2.aruco 生成的同 ID 图案相差 180°，本项目的 objp 以官方图案为准。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from pupil_apriltags import Detector

import config


@dataclass
class TagDetection:
    """一次检测结果，字段直接对应库的输出，不做取舍。"""
    tag_id: int
    center: tuple[float, float]
    corners: np.ndarray            # (4, 2) float64，顺序见模块说明
    hamming: int
    decision_margin: float


class TagDetector:
    """pupil-apriltags 的薄封装：家族、线程数、参数集中在这里。"""

    def __init__(self, families: str = None, nthreads: int = 2,
                 quad_decimate: float = None, refine_edges: int = None):
        self.families = config.TAG_FAMILY if families is None else families
        self.detector = Detector(
            families=self.families,
            nthreads=nthreads,
            quad_decimate=config.TAG_QUAD_DECIMATE if quad_decimate is None else quad_decimate,
            refine_edges=config.TAG_REFINE_EDGES if refine_edges is None else refine_edges,
            debug=0,
        )

    def detect(self, image_bgr: np.ndarray) -> list[TagDetection]:
        """输入 BGR 或灰度图；返回全部检测结果（可能为空列表）。"""
        gray = image_bgr if image_bgr.ndim == 2 else cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        out = []
        for d in self.detector.detect(gray):
            out.append(TagDetection(
                tag_id=int(d.tag_id),
                center=(float(d.center[0]), float(d.center[1])),
                corners=np.asarray(d.corners, dtype=np.float64).reshape(4, 2),
                hamming=int(d.hamming),
                decision_margin=float(d.decision_margin),
            ))
        return out
