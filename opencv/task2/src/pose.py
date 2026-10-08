"""位姿解算：由角点 + 内参 + 实测边长算 R、t。

约定（README 第 5 节）：
    p_camera = R · p_tag + t
    t（米）就是 Tag 中心在相机系里的位置
    rvec（弧度）是与 R 等价的 Rodrigues 向量，正是任务三要发的那三个数
    distance = |t| 是直线距离，z = t[2] 是沿光轴的深度，两个不一样

不用 SOLVEPNP_IPPE_SQUARE：它按 OpenCV 文档要物体点 y 向上、特定次序，
本项目的 tag 系 y 向下，直接喂进去会得到镜像解（实测旋转差 180°、平移取反，
重投影残差却极小，很难发现）。改用 SOLVEPNP_SQPNP，不挑点序。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

import config

SOLVERS = {
    "sqpnp": cv2.SOLVEPNP_SQPNP,
    "iterative": cv2.SOLVEPNP_ITERATIVE,
}


@dataclass
class PoseResult:
    ok: bool
    rvec: np.ndarray          # (3,1) 弧度
    tvec: np.ndarray          # (3,1) 米
    R: np.ndarray             # (3,3)
    reproj_error: float       # 像素，重投影残差均值，用来判断解算质量
    reason: str = "ok"

    @property
    def t(self) -> np.ndarray:
        return self.tvec.ravel()

    @property
    def distance(self) -> float:
        """相机光心到 Tag 中心的直线距离（米）。"""
        return float(np.linalg.norm(self.t))

    @property
    def depth(self) -> float:
        """沿光轴 Z 的深度（米），与直线距离不同。"""
        return float(self.t[2])

    def axes_points(self, edge_m: float, K: np.ndarray, dist: np.ndarray = None,
                    length_ratio: float = None) -> tuple[np.ndarray, np.ndarray]:
        """画三维坐标轴用：Tag 系下四个点（原点 + 三个轴端点）及其投影。

        要用解算本帧时用的那套内参投影，否则轴会跑到别处；
        dist 也传解算时用的（去畸变画面传全零）。
        """
        r = config.AXIS_LENGTH_RATIO if length_ratio is None else length_ratio
        L = edge_m * r
        pts = np.array([[0, 0, 0], [L, 0, 0], [0, L, 0], [0, 0, L]], dtype=np.float64)
        d = np.zeros(5) if dist is None else np.asarray(dist, dtype=np.float64).reshape(-1)
        img_pts = cv2.projectPoints(pts, self.rvec, self.tvec,
                                    np.asarray(K, dtype=np.float64), d)[0].reshape(-1, 2)
        return pts, img_pts


def tag_object_points(edge_m: float) -> np.ndarray:
    """Tag 系下四个角点的坐标，顺序必须与 tag_detect 得到的 corners 一致。

    corners[0]=左下 1=右下 2=右上 3=左上（tag 系 x 右、y 下）。
    """
    s = float(edge_m) / 2.0
    return np.array([[-s,  s, 0.0],      # 0 左下
                     [ s,  s, 0.0],      # 1 右下
                     [ s, -s, 0.0],      # 2 右上
                     [-s, -s, 0.0]], dtype=np.float64)   # 3 左上


def check_pose_sane(tvec: np.ndarray) -> tuple[bool, str]:
    """位姿合理性检查：目标得在相机前方，数值要有限。"""
    t = np.asarray(tvec, dtype=np.float64).ravel()
    if not np.all(np.isfinite(t)):
        return False, "位姿数值无效"
    if t[2] <= 0:
        return False, f"目标在相机后方 z={t[2]:.3f} m"
    return True, "ok"


def solve(corners: np.ndarray, K: np.ndarray, dist: np.ndarray,
          edge_m: float) -> PoseResult:
    """从四个角点解算位姿。dist 传 np.zeros(5) 表示画面已去畸变。"""
    objp = tag_object_points(edge_m)
    imgp = np.asarray(corners, dtype=np.float64).reshape(4, 2)
    ok, rvec, tvec = cv2.solvePnP(objp, imgp, np.asarray(K, dtype=np.float64),
                                  np.asarray(dist, dtype=np.float64).reshape(-1),
                                  flags=SOLVERS[config.POSE_SOLVER])
    if not ok:
        return PoseResult(False, np.zeros(3), np.zeros(3), np.eye(3), np.inf, "solvePnP 失败")
    R, _ = cv2.Rodrigues(rvec)
    reproj = cv2.projectPoints(objp, rvec, tvec, K, np.asarray(dist).reshape(-1))[0].reshape(-1, 2)
    err = float(np.mean(np.linalg.norm(reproj - imgp, axis=1)))
    return PoseResult(True, rvec, tvec, R, err)
