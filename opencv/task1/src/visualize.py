"""可视化：只负责画图。

本模块不读写视频、不做任何检测判断；输入是帧和检测结果，输出是可直接保存或显示的图像。
生成视频左上角会有标识，显示耗时、灯条数量
"""

import cv2
import numpy as np

import config


def draw_bars(frame, bars, color=config.BAR_COLOR, thickness=2, draw_center=True):
    """用最小外接旋转矩形的四条边逐根框选灯条。返回新图像，不修改输入。"""
    canvas = frame.copy()
    for bar in bars:
        points = np.asarray(bar.corners, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [points], True, color, thickness)
        if draw_center:
            cx = int(round(float(bar.center[0])))
            cy = int(round(float(bar.center[1])))
            cv2.circle(canvas, (cx, cy), 2, config.CENTER_COLOR, -1)
    return canvas


def draw_hud(frame, frame_index, bar_count, elapsed_ms, extra_lines=()):
    """在左上角显示帧号、灯条数量和本帧处理耗时，以及可选的附加信息。"""
    lines = [
        f"frame: {frame_index}",
        f"bars: {bar_count}",
        f"cost: {elapsed_ms:.1f} ms",
    ]
    lines.extend(extra_lines)
    return draw_panel(frame, lines)


def draw_panel(frame, lines):
    """在左上角画一块半透明底板，再逐行写字。"""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness = config.HUD_FONT_SCALE, config.HUD_THICKNESS
    pad, line_height = 10, 30
    sizes = [cv2.getTextSize(text, font, scale, thickness)[0] for text in lines]
    box_width = max(size[0] for size in sizes) + pad * 2
    box_height = line_height * len(lines) + pad

    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (8 + box_width, 8 + box_height), (0, 0, 0), -1)
    canvas = cv2.addWeighted(overlay, 0.45, frame, 0.55, 0)

    for index, text in enumerate(lines):
        origin = (8 + pad, 8 + pad + line_height * (index + 1) - 8)
        cv2.putText(canvas, text, origin, font, scale, config.TEXT_COLOR, thickness,
                    cv2.LINE_AA)
    return canvas


def mask_to_bgr(mask):
    """二值掩膜转三通道，便于与原图拼在一起保存。"""
    if mask.ndim == 2:
        return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    return mask


def make_strip(images, labels=None, panel_width=480):
    """把若干张图缩放后横向拼成一条带标签的对比图，用于保存代表帧截图。"""
    if labels is None:
        labels = [""] * len(images)
    panels = []
    for image, label in zip(images, labels):
        panel = mask_to_bgr(image)
        height, width = panel.shape[:2]
        scale = panel_width / float(width)
        panel = cv2.resize(panel, (panel_width, max(int(round(height * scale)), 1)),
                           interpolation=cv2.INTER_AREA)
        panel = cv2.copyMakeBorder(panel, 30, 0, 0, 0, cv2.BORDER_CONSTANT,
                                   value=(0, 0, 0))
        cv2.putText(panel, str(label), (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    config.TEXT_COLOR, 1, cv2.LINE_AA)
        panels.append(panel)

    max_height = max(panel.shape[0] for panel in panels)
    panels = [cv2.copyMakeBorder(panel, 0, max_height - panel.shape[0], 0, 0,
                                 cv2.BORDER_CONSTANT, value=(0, 0, 0))
              for panel in panels]
    return cv2.hconcat(panels)
