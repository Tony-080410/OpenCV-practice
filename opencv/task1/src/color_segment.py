"""颜色分割: BGR 帧 → 0/255 二值掩膜。

两种方法都保留，方便在报告里做对比：
  blue_dominance —— 蓝色通道比最强的红/绿通道高出多少，抗过曝；
  hsv            —— 色相/饱和度/明度三通道同时限制，语义直观。
"""

import cv2
import numpy as np

import config


def blue_dominance_mask(frame, thresh=config.DIFF_THRESH):
    """蓝度超过阈值的区域置 255。

    用 int16 相减而不是 cv2.subtract: 8 位减法会把负值截断为 0,
    "橙红区域蓝度更低"这一信息就丢了，无法再用同一个阈值区分强弱。
    """
    b, g, r = cv2.split(frame)
    dominance = b.astype(np.int16) - np.maximum(g, r).astype(np.int16)
    return np.where(dominance >= float(thresh), 255, 0).astype(np.uint8)


def hsv_mask(frame, low=config.HSV_LOW, high=config.HSV_HIGH):
    """OpenCV 8 位 HSV 中 H ∈ [0,179]、S/V ∈ [0,255]。"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lower = np.array(low, dtype=np.uint8)
    upper = np.array(high, dtype=np.uint8)
    return cv2.inRange(hsv, lower, upper)


def build_mask(frame, method=config.SEGMENT_METHOD, thresh=config.DIFF_THRESH,
               hsv_low=config.HSV_LOW, hsv_high=config.HSV_HIGH):
    """按方法名分发；主程序只调用这一个入口。"""
    if method == "blue_dominance":
        return blue_dominance_mask(frame, thresh)
    if method == "hsv":
        return hsv_mask(frame, hsv_low, hsv_high)
    raise ValueError(f"未知的颜色分割方法: {method}")
