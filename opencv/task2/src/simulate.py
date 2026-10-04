"""仿真画面生成（不需要相机、不需要打印），用于回归测试位姿链路。

做法：逐个像素反向光线求交——对每个像素按畸变模型求出真实光线方向，
与 tag 平面求交，落在 tag 范围内的取图案像素。这样生成的画面在几何上
与真实相机一致（含桶形畸变），可以作为“已知真值”的测试输入。

不是实时流程的一部分，只在 tools/validate_pose_sim.py 里用。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

FAMILY_CELLS = 8              # tag36h11 黑框外边 = 8 x 8 个单元
OFFICIAL_10X10 = 10           # 官方图案含 1 单元白边


def load_official_texture(path: str | Path, pixels: int = 800) -> np.ndarray:
    """取官方图案的黑框外边部分（10x10 单元里的第 1..8 行/列）并放大。"""
    png = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if png is None or png.shape != (OFFICIAL_10X10, OFFICIAL_10X10):
        raise ValueError(f"官方图案异常：{path} -> {None if png is None else png.shape}")
    core = png[1:9, 1:9]
    s = pixels // FAMILY_CELLS
    return np.kron(core, np.ones((s, s), np.uint8))


def render(R: np.ndarray, t: np.ndarray, K: np.ndarray, dist: np.ndarray,
           width: int, height: int, texture: np.ndarray, side_m: float,
           background: float = 255.0) -> np.ndarray:
    """渲染一帧：R、t 是 tag 系到相机系的真值，side_m 是黑框外边边长（米）。"""
    tex_px = texture.shape[0]
    u, v = np.meshgrid(np.arange(width, dtype=np.float64), np.arange(height, dtype=np.float64))
    pts = np.stack([u.ravel(), v.ravel()], 1).reshape(-1, 1, 2)
    norm = cv2.undistortPoints(pts, K, dist if np.any(dist) else None).reshape(-1, 2)
    d = np.concatenate([norm, np.ones((len(norm), 1))], 1)
    A = np.stack([np.broadcast_to(R[:, 0], d.shape),
                  np.broadcast_to(R[:, 1], d.shape), -d], 2)
    sol = np.linalg.solve(A, np.broadcast_to((-t).reshape(1, 3, 1), (len(d), 3, 1)))[:, :, 0]
    x, y, s = sol[:, 0], sol[:, 1], sol[:, 2]
    hit = (s > 0) & (np.abs(x) <= side_m / 2) & (np.abs(y) <= side_m / 2)
    mx = np.clip(((x / side_m + 0.5) * tex_px).astype(int), 0, tex_px - 1)
    my = np.clip(((y / side_m + 0.5) * tex_px).astype(int), 0, tex_px - 1)
    out = np.full(len(d), background)
    out[hit] = texture[my[hit], mx[hit]]
    return out.reshape(height, width).astype(np.uint8)


def truth_pose(ax_deg: float, ay_deg: float, az_deg: float,
               tx: float, ty: float, tz: float) -> tuple[np.ndarray, np.ndarray]:
    """按 (X, Y, Z) 顺序的欧拉角构造真值 R、t（度 / 米）。"""
    R, _ = cv2.Rodrigues(np.array([np.deg2rad(ax_deg), np.deg2rad(ay_deg),
                                   np.deg2rad(az_deg)]))
    return R, np.array([tx, ty, tz], dtype=np.float64)


# 常用测试场景：(名字, ax, ay, az, tx, ty, tz)
CASES = [
    ("正对 0.8m", 0, 0, 0, 0.00, 0.00, 0.80),
    ("倾斜+偏移", -15, 25, 0, 0.08, -0.03, 0.75),
    ("强倾斜 45°", 0, 45, 0, -0.05, 0.02, 0.55),
]


def default_intrinsics(width: int, height: int, f_px: float = 900.0) -> np.ndarray:
    return np.array([[f_px, 0, width / 2], [0, f_px, height / 2], [0, 0, 1]], dtype=np.float64)
