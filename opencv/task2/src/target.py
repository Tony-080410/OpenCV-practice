"""目标选择与可用性判定：只负责“哪个是我要的目标、这次结果能不能用”。

按手册要求，把“保留全部检测结果”和“选定目标”分开：
    TagDetector 给出全部 -> select_target 只挑 TARGET_ID -> evaluate 判定 valid
未检测到目标、检测质量差、解算失败、目标跑到相机后面，都返回 valid=False，
绝不沿用上一帧的旧位姿。
"""
from __future__ import annotations

from dataclasses import dataclass

import config
from src.tag_detect import TagDetection


@dataclass
class TargetState:
    """一帧的目标状态。valid=False 时 pose 字段为 None。"""
    valid: bool
    reason: str                      # 不可用时的人类可读原因；可用时为 "ok"
    detection: TagDetection | None   # 选中的检测（即使位姿失败也保留，便于显示）


def select_target(detections: list[TagDetection], target_id: int = None) -> TagDetection | None:
    """按 ID 挑目标；若有多个同 ID，取 decision_margin 最大（更清晰）的那个。"""
    tid = config.TARGET_ID if target_id is None else target_id
    hits = [d for d in detections if d.tag_id == tid]
    if not hits:
        return None
    return max(hits, key=lambda d: d.decision_margin)


def evaluate(detections: list[TagDetection], target_id: int = None) -> TargetState:
    """给出本帧的目标状态（不含位姿，位姿由 pose 模块算）。"""
    tid = config.TARGET_ID if target_id is None else target_id
    det = select_target(detections, tid)
    if det is None:
        return TargetState(False, f"未检测到 ID {tid}", None)
    if det.hamming != 0:
        return TargetState(False, f"解码有误 hamming={det.hamming}", det)
    if det.decision_margin < config.MIN_DECISION_MARGIN:
        return TargetState(False, f"检测质量低 margin={det.decision_margin:.1f}", det)
    return TargetState(True, "ok", det)
