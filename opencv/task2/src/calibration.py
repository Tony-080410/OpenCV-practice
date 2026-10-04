"""相机标定：只负责“相机参数怎么来”。

流程：棋盘格照片 -> 角点 -> calibrateCamera -> 内参/畸变/分辨率/重投影误差
产出 data/calib_params.json，含：
    K, D, 分辨率, calibrateCamera 的 RMS, 每张图的平均重投影误差, 棋盘格规格, 来源图片清单
重投影误差的含义：用解出的内参把棋盘格角点从三维投回图像，与检测到的角点之差
（像素）。它反映标定质量，不直接等于位姿精度，README 里要写清楚。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import config

CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)
FIND_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
              | cv2.CALIB_CB_FILTER_QUADS)


@dataclass
class BoardSpec:
    inner_cols: int
    inner_rows: int
    square_mm: float

    @property
    def pattern_size(self) -> tuple[int, int]:
        return (self.inner_cols, self.inner_rows)

    def object_points(self) -> np.ndarray:
        """以第一个内角点为原点的平面点阵，单位由 square_mm 决定（这里用毫米）。"""
        pts = np.zeros((self.inner_cols * self.inner_rows, 3), np.float32)
        pts[:, :2] = np.mgrid[0:self.inner_cols, 0:self.inner_rows].T.reshape(-1, 2)
        return pts * float(self.square_mm)


@dataclass
class CalibResult:
    ok: bool
    rms: float
    K: np.ndarray
    D: np.ndarray
    width: int
    height: int
    used_images: list[str] = field(default_factory=list)
    skipped_images: list[str] = field(default_factory=list)
    per_image_error: dict[str, float] = field(default_factory=dict)
    reason: str = "ok"


def find_corners(gray: np.ndarray, spec: BoardSpec):
    """检测棋盘格内角点并做亚像素细化。返回 (ok, corners)。"""
    ok, corners = cv2.findChessboardCorners(gray, spec.pattern_size, None, FIND_FLAGS)
    if not ok:
        return False, None
    corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), CRITERIA)
    return True, corners


def calibrate(image_paths: list[str | Path], spec: BoardSpec | None = None) -> CalibResult:
    """对一批图片做标定。角点找不到的图片会被跳过并记录，不算失败。"""
    spec = spec or BoardSpec(config.BOARD_INNER_COLS, config.BOARD_INNER_ROWS,
                             config.BOARD_SQUARE_MM)
    objp = spec.object_points()
    obj_points, img_points, used, skipped = [], [], [], []
    size = None

    for p in sorted(map(Path, image_paths)):
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            skipped.append(str(p))
            continue
        if size is None:
            size = (img.shape[1], img.shape[0])
        elif (img.shape[1], img.shape[0]) != size:
            skipped.append(str(p))          # 分辨率必须一致，否则内参无法共用
            continue
        ok, corners = find_corners(img, spec)
        if not ok:
            skipped.append(str(p))
            continue
        obj_points.append(objp)
        img_points.append(corners)
        used.append(str(p))

    if len(used) < config.CALIB_MIN_COUNT:
        return CalibResult(False, float("inf"), np.eye(3), np.zeros(5),
                           *(size or (0, 0)), used, skipped,
                           reason=f"有效标定图只有 {len(used)} 张，少于 {config.CALIB_MIN_COUNT}")

    rms, K, D, rvecs, tvecs = cv2.calibrateCamera(obj_points, img_points, size, None, None)

    per_image = {}
    for path, op, ip, rv, tv in zip(used, obj_points, img_points, rvecs, tvecs):
        proj, _ = cv2.projectPoints(op, rv, tv, K, D)
        per_image[path] = float(np.mean(np.linalg.norm(
            proj.reshape(-1, 2) - ip.reshape(-1, 2), axis=1)))

    return CalibResult(True, float(rms), K, D, size[0], size[1], used, skipped, per_image)


def save_params(res: CalibResult, spec: BoardSpec, path: str | Path = None) -> Path:
    path = Path(path or config.CALIB_PARAMS)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "K": np.asarray(res.K).tolist(),
        "D": np.asarray(res.D).reshape(-1).tolist(),
        "width": res.width,
        "height": res.height,
        "rms_reprojection_error_px": res.rms,
        "per_image_mean_error_px": res.per_image_error,
        "board": {"inner_cols": spec.inner_cols, "inner_rows": spec.inner_rows,
                  "square_mm": spec.square_mm},
        "used_images": res.used_images,
        "skipped_images": res.skipped_images,
        "note": ("重投影误差 = 用解出的内参把棋盘格角点投回图像与检测点的偏差（像素），"
                 "反映标定质量；位姿精度还受角点检测与 Tag 边长测量影响。"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


@dataclass
class StoredParams:
    K: np.ndarray
    D: np.ndarray
    width: int
    height: int
    rms: float
    raw: dict


def load_params(path: str | Path = None) -> StoredParams:
    p = Path(path or config.CALIB_PARAMS)
    if not p.exists():
        raise FileNotFoundError(f"没有标定参数文件：{p}（先跑 python main.py calib）")
    d = json.loads(p.read_text())
    return StoredParams(np.array(d["K"], float), np.array(d["D"], float).reshape(-1),
                        int(d["width"]), int(d["height"]),
                        float(d.get("rms_reprojection_error_px", float("nan"))), d)
