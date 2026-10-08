"""预览窗（可选）：只画图，不改数值。

画当前帧加状态（valid / id / t / rvec / 检测到的 Tag 数），
底下再放一行即将写串口的报文（含校验），录屏时一眼能对上目标在不在、
串口要发什么，不用来回切窗口。不 import 任务二，这是 task3 自己的状态显示。
"""
from __future__ import annotations

import cv2

import t3config


def draw(sample, line: str, extra: list[str] | None = None):
    """在 sample.frame 上叠状态和报文，返回画好的画面（frame 为 None 就返回 None）。

    line 是即将写出的整行报文，不含结尾 CRLF，方便显示。
    """
    if sample.frame is None:
        return None
    img = sample.frame
    rec = sample.record
    color = t3config.PREVIEW_OK_COLOR if rec["valid"] else t3config.PREVIEW_BAD_COLOR

    lines = [f"valid={rec['valid']}  id={rec['id']}  检测到 {sample.n_detected} 个 Tag"
             f"  本帧 {sample.cost_ms:.1f} ms"]
    if rec["valid"]:
        lines.append(f"t = ({rec['x_mm']:.1f}, {rec['y_mm']:.1f}, {rec['z_mm']:.1f}) mm"
                     f"   |t| = {(rec['x_mm'] ** 2 + rec['y_mm'] ** 2 + rec['z_mm'] ** 2) ** 0.5:.1f} mm")
        lines.append(f"rvec = ({rec['rx']:.6f}, {rec['ry']:.6f}, {rec['rz']:.6f}) rad")
    else:
        lines.append(f"原因：{sample.reason}（发无效报文，坐标与姿态置零）")
    if extra:
        lines.extend(extra)

    y = t3config.PREVIEW_LINE_HEIGHT
    for text in lines:
        cv2.putText(img, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                    t3config.PREVIEW_FONT_SCALE, t3config.PREVIEW_TEXT_COLOR, 1, cv2.LINE_AA)
        y += t3config.PREVIEW_LINE_HEIGHT
    cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                t3config.PREVIEW_FONT_SCALE, color, 1, cv2.LINE_AA)
    return img


def handle_key(delay_ms: int = 1) -> str:
    """返回 'quit' / 'shot' / ''。窗口得先开着。"""
    key = cv2.waitKey(delay_ms) & 0xFF
    if key in (ord("q"), 27):
        return "quit"
    if key == ord("s"):
        return "shot"
    return ""


def save_shot(img, index: int):
    """截图。cv2.imwrite 失败只返回 False 不抛异常，所以要看返回值。"""
    t3config.PREVIEW_SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    path = t3config.PREVIEW_SCREENSHOTS / f"task3_send_{index:06d}.png"
    return path if cv2.imwrite(str(path), img) else None


def close() -> None:
    cv2.destroyAllWindows()
