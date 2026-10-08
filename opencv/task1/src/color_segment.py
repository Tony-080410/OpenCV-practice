"""颜色分割：BGR 帧进，0/255 掩膜出。

两种方法都留着方便对比：blue_dominance 是 B 比最强的 G/R 高多少（抗过曝），
hsv 是 H/S/V 三通道一起卡范围。
"""

import cv2
import numpy as np

import config


def blue_dominance_mask(frame, thresh=config.DIFF_THRESH):
    """蓝度超过阈值的置 255。

    得用 int16 算 B - max(G,R)：8 位减法把负值截成 0，橙红区也会跟着变白，分不开。
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
    """按方法名分发，主程序只走这一个入口。"""
    if method == "blue_dominance":
        return blue_dominance_mask(frame, thresh)
    if method == "hsv":
        return hsv_mask(frame, hsv_low, hsv_high)
    raise ValueError(f"未知的颜色分割方法: {method}")
