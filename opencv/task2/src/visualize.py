"""只画图：框、中心、角点、三维坐标轴、HUD。这里没有任何检测或判断逻辑。

颜色约定见 config：选中目标绿框，其它检测到的 Tag 淡红框。
坐标轴按 Tag 系 x 右、y 下、z 出纸面朝相机画：X 红、Y 绿、Z 蓝。
"""
from __future__ import annotations

import cv2
import numpy as np

import config
from src.pose import PoseResult
from src.tag_detect import TagDetection


def draw_hud(image: np.ndarray, lines: list[str], origin: tuple[int, int] = None) -> None:
    """左上角半透明底板上写多行信息。

    只在底板大小那块 ROI 上做混合，不整帧 copy——整帧 copy+addWeighted 是每帧都付的固定开销。
    """
    ox, oy = origin or config.HUD_ORIGIN
    h = config.HUD_LINE_HEIGHT * len(lines) + 12
    w = 0
    for s in lines:
        (tw, _), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX,
                                     config.HUD_FONT_SCALE, config.HUD_THICKNESS)
        w = max(w, tw)
    x0, y0 = max(ox - 6, 0), max(oy - 6, 0)
    x1, y1 = min(ox + w + 8, image.shape[1]), min(oy + h, image.shape[0])
    roi = image[y0:y1, x0:x1]
    plate = np.zeros_like(roi)
    cv2.addWeighted(plate, 0.45, roi, 0.55, 0, roi)      # 就地写回原图
    for i, s in enumerate(lines):
        cv2.putText(image, s, (ox, oy + 14 + i * config.HUD_LINE_HEIGHT),
                    cv2.FONT_HERSHEY_SIMPLEX, config.HUD_FONT_SCALE,
                    config.COLOR_HUD_TEXT, config.HUD_THICKNESS, cv2.LINE_AA)


def draw_tag(image: np.ndarray, det: TagDetection, is_target: bool,
             label: str = "") -> None:
    """画一个检测：四角、中心、ID 标注。"""
    color = config.COLOR_TARGET if is_target else config.COLOR_OTHER
    corners = det.corners.astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(image, [corners], True, color, 2, cv2.LINE_AA)
    for i, c in enumerate(det.corners):
        cv2.circle(image, (int(c[0]), int(c[1])), 4, color, -1, cv2.LINE_AA)
        cv2.putText(image, str(i), (int(c[0]) + 5, int(c[1]) - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    cv2.circle(image, (int(det.center[0]), int(det.center[1])), 3,
               config.COLOR_CENTER, -1, cv2.LINE_AA)
    text = label or f"id={det.tag_id}"
    cv2.putText(image, text, (int(det.corners[0][0]), int(det.corners[0][1]) + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def draw_pose_axes(image: np.ndarray, det: TagDetection, pose: PoseResult,
                   K: np.ndarray, edge_m: float, dist: np.ndarray = None) -> None:
    """在 Tag 上画三维坐标轴：把 Tag 系的三根轴端点投影到图像再连线。

    K/dist 必须是解算这一帧时用的那一套（见 PosePipeline 的 K_used/D_used）。
    """
    pts, img_pts = pose.axes_points(edge_m, K, dist)
    if not np.all(np.isfinite(img_pts)):
        return
    origin = tuple(np.round(img_pts[0]).astype(int))
    for i, color in enumerate((config.COLOR_AXIS_X, config.COLOR_AXIS_Y,
                               config.COLOR_AXIS_Z), start=1):
        tip = tuple(np.round(img_pts[i]).astype(int))
        cv2.arrowedLine(image, origin, tip, color, 2, cv2.LINE_AA, tipLength=0.2)


def format_pose_lines(det: TagDetection | None, pose: PoseResult | None,
                      valid: bool, reason: str, extra: list[str] = None) -> list[str]:
    """把一帧的结论整理成 HUD 文本（只做格式化，不做判断）。"""
    lines = []
    if det is None:
        lines.append(f"valid={int(valid)}  未检测到目标：{reason}")
    else:
        lines.append(f"valid={int(valid)}  id={det.tag_id}  hamming={det.hamming}  "
                     f"margin={det.decision_margin:.1f}")
        if pose is not None and pose.ok:
            t = pose.t
            lines.append(f"t(m) = ({t[0]:+.3f}, {t[1]:+.3f}, {t[2]:+.3f})")
            lines.append(f"距离 |t| = {pose.distance:.3f} m    Z 深度 = {pose.depth:.3f} m")
            rv = pose.rvec.ravel()
            lines.append(f"rvec(rad) = ({rv[0]:+.3f}, {rv[1]:+.3f}, {rv[2]:+.3f})")
            lines.append(f"重投影残差 {pose.reproj_error:.2f} px")
        else:
            lines.append(f"位姿不可用：{reason}")
    if extra:
        lines.extend(extra)
    return lines
