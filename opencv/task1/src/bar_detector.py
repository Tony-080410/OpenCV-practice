"""轮廓提取和几何筛选：掩膜进，灯条列表出。"""

import math
from dataclasses import dataclass

import cv2
import numpy as np

import config


@dataclass
class Candidate:
    """一个轮廓候选及其几何量。"""

    contour: np.ndarray
    polygon: np.ndarray
    box: tuple
    corners: np.ndarray
    area: float
    rect_area: float
    length: float
    width: float
    tilt: float

    @property
    def center(self):
        return self.box[0]

    @property
    def aspect(self):
        """长边 / 短边。"""
        return self.length / max(self.width, 1e-6)

    @property
    def fill(self):
        """填充率：轮廓面积占最小外接旋转矩形面积的比例。"""
        return self.area / max(self.rect_area, 1e-6)


def long_axis_tilt(corners):
    """灯条长轴与竖直方向（图像 y 轴）的夹角，单位度，范围 [0, 90]。

    corners 是 4×2 的四角坐标（cv2.boxPoints 的结果或等价的序列）。
    """
    points = [(float(point[0]), float(point[1])) for point in corners]
    best_length, tilt = -1.0, 90.0
    for index in range(4):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % 4]
        dx, dy = x1 - x0, y1 - y0
        segment = math.hypot(dx, dy)
        if segment > best_length:
            best_length = segment
            angle = math.degrees(math.atan2(dy, dx)) % 180.0
            tilt = abs(angle - 90.0)
    return tilt


def find_candidates(mask):
    """轮廓提取、多边形近似、最小面积旋转矩形。"""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area <= 0.0:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, config.APPROX_EPS_RATIO * perimeter, True)
        box = cv2.minAreaRect(contour)
        corners = cv2.boxPoints(box).astype(np.float32)
        rect_width, rect_height = float(box[1][0]), float(box[1][1])
        candidates.append(
            Candidate(
                contour=contour,
                polygon=polygon,
                box=box,
                corners=corners,
                area=area,
                rect_area=rect_width * rect_height,
                length=max(rect_width, rect_height),
                width=min(rect_width, rect_height),
                tilt=long_axis_tilt(corners),
            )
        )
    return candidates


def reject_reason(candidate, image_area):
    """返回被剔除的原因；通过全部条件时返回 None。"""
    thresholds = config.FILTER_DEFAULTS
    if candidate.area < thresholds["min_area_ratio"] * image_area:
        return "area_too_small"
    if candidate.area > thresholds["max_area_ratio"] * image_area:
        return "area_too_large"
    if not (thresholds["aspect_min"] <= candidate.aspect <= thresholds["aspect_max"]):
        return "aspect_out_of_range"
    if candidate.fill < thresholds["fill_min"]:
        return "fill_too_low"
    if candidate.tilt > thresholds["angle_tol_deg"]:
        return "tilt_too_large"
    return None


def filter_candidates(candidates, image_shape):
    """筛一遍全部候选，返回 (通过的, [(被剔除的, 原因)])。"""
    image_area = float(image_shape[0] * image_shape[1])
    kept, rejected = [], []
    for candidate in candidates:
        reason = reject_reason(candidate, image_area)
        if reason is None:
            kept.append(candidate)
        else:
            rejected.append((candidate, reason))
    kept.sort(key=lambda item: item.area, reverse=True)
    return kept, rejected


def detect(mask):
    """掩膜进，(灯条列表, 被剔除列表) 出。"""
    return filter_candidates(find_candidates(mask), mask.shape)


def metrics(candidate):
    """打日志、写报告用的可读指标。"""
    return {
        "center": (round(float(candidate.center[0]), 1),
                   round(float(candidate.center[1]), 1)),
        "area": round(candidate.area, 1),
        "length": round(candidate.length, 1),
        "width": round(candidate.width, 1),
        "aspect": round(candidate.aspect, 2),
        "fill": round(candidate.fill, 3),
        "tilt": round(candidate.tilt, 1),
    }


REASON_TEXT = {
    "area_too_small": "面积过小（噪点）",
    "area_too_large": "面积过大（整片背景或灯条粘连）",
    "aspect_out_of_range": "长宽比不符（不是细长形状）",
    "fill_too_low": "填充率过低（形状不规则）",
    "tilt_too_large": "倾角过大（接近水平）",
}


def format_reason(reason):
    """原因码转成中文。"""
    return REASON_TEXT.get(reason, reason)
