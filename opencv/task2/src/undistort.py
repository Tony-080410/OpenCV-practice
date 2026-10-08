"""畸变处理：把画面变直，交出跟画面匹配的内参。

用 cv2.undistort(frame, K, D)，不裁剪、不改内参（新投影矩阵就是 K 本身），
之后检测和解算一律用 dist=0 + 同一个 K。这样"解算用的内参"和"画面"天然成对，
不会出现原图内参配裁剪画面这类错配。
实测（见 spike/RESULTS.md 第四节）：去畸变后误差更小（强倾斜 0.79mm -> 0.47mm），
内参分辨率错配时平移误差能到数百毫米。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Undistorter:
    K: np.ndarray                 # (3,3) 标定得到的内参，也是去畸变后画面的内参
    D: np.ndarray                 # (k1,k2,p1,p2,k3)，长度可变
    width: int                    # 与该内参对应的标定分辨率
    height: int

    def __post_init__(self) -> None:
        # 这里统一成一维：cv2 既收 (5,) 也收 (1,5)，后面就不用到处 reshape
        self.K = np.asarray(self.K, dtype=np.float64)
        self.D = np.asarray(self.D, dtype=np.float64).reshape(-1)

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """BGR/灰度进，同类型出；尺寸不变。畸变系数全零时直通。"""
        if not np.any(self.D):
            return frame
        return cv2.undistort(frame, self.K, self.D)

    def dist_for_solver(self) -> np.ndarray:
        """去畸变之后解算该用的畸变系数：全零。"""
        return np.zeros(5)

    def resolution_ok(self, width: int, height: int) -> bool:
        """检测内参与当前画面分辨率是否成对。"""
        return (int(width), int(height)) == (self.width, self.height)
