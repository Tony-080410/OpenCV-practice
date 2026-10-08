"""单帧流水线：串起各模块，给出一份能直接拿去显示和通信的结果。

只做串联和计时，不管算法：去畸变 -> 检测全部 -> 选目标判可用 -> 解算 -> 组装。
PoseFrame.record() 的字段就是任务三要发的（已转毫米），任务三只按 CV1 协议
格式化成文本写串口。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

import config
from src import pose as pose_mod
from src import target as target_mod
from src.tag_detect import TagDetection, TagDetector
from src.undistort import Undistorter


@dataclass
class PoseFrame:
    """一帧的最终结果。seq/t_ms 由上层维护（这里只记录本帧耗时）。"""
    valid: bool
    reason: str
    target_id: int
    detections: list[TagDetection] = field(default_factory=list)
    pose: pose_mod.PoseResult | None = None
    cost_ms: float = 0.0
    stage_ms: dict[str, float] = field(default_factory=dict)
    K_used: np.ndarray | None = None     # 本帧解算实际用的内参（画坐标轴要用同一套）
    D_used: np.ndarray | None = None     # 本帧解算实际用的畸变系数（去畸变画面为全零）

    def record(self, seq: int, t_ms: int) -> dict:
        """汇总为通信用的字段：长度毫米、姿态用旋转向量（弧度）。"""
        if self.valid and self.pose is not None and self.pose.ok:
            t = self.pose.t
            rv = self.pose.rvec.ravel()
            return {
                "seq": seq, "t_ms": t_ms, "valid": 1, "id": self.target_id,
                "x_mm": float(t[0] * 1000.0), "y_mm": float(t[1] * 1000.0),
                "z_mm": float(t[2] * 1000.0),
                "rx": float(rv[0]), "ry": float(rv[1]), "rz": float(rv[2]),
                "distance_mm": self.pose.distance * 1000.0,
            }
        return {"seq": seq, "t_ms": t_ms, "valid": 0, "id": -1,
                "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
                "rx": 0.0, "ry": 0.0, "rz": 0.0, "distance_mm": 0.0}


class PosePipeline:
    """把检测、目标选择、位姿解算串成一帧的处理流程。"""

    def __init__(self, K: np.ndarray, D: np.ndarray, edge_mm: float = None,
                 target_id: int = None, detector: TagDetector = None,
                 undistorter: Undistorter | None = None):
        self.K = np.asarray(K, dtype=np.float64)
        self.D = np.asarray(D, dtype=np.float64).reshape(-1)
        self.edge_m = (config.TAG_EDGE_MM if edge_mm is None else edge_mm) / 1000.0
        self.target_id = config.TARGET_ID if target_id is None else target_id
        self.detector = detector or TagDetector()
        self.undistorter = undistorter

    def process(self, frame_bgr: np.ndarray) -> tuple[PoseFrame, np.ndarray]:
        """输入原始 BGR 帧，输出 (结果, 用于显示/检测的画面)。"""
        t0 = time.perf_counter()
        stage: dict[str, float] = {}

        if self.undistorter is not None:
            frame = self.undistorter.apply(frame_bgr)
            K, D = self.undistorter.K, self.undistorter.dist_for_solver()
        else:
            frame, K, D = frame_bgr, self.K, self.D
        stage["undistort"] = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        detections = self.detector.detect(frame)
        stage["detect"] = (time.perf_counter() - t1) * 1000

        t2 = time.perf_counter()
        state = target_mod.evaluate(detections, self.target_id)
        result = PoseFrame(valid=False, reason=state.reason, target_id=self.target_id,
                           detections=detections, K_used=K,
                           D_used=np.asarray(D, dtype=np.float64).reshape(-1))
        if state.valid:
            pose = pose_mod.solve(state.detection.corners, K, D, self.edge_m)
            sane, why = (pose_mod.check_pose_sane(pose.tvec) if pose.ok
                         else (False, pose.reason))
            if pose.ok and sane:
                result.pose, result.valid, result.reason = pose, True, "ok"
            else:
                result.pose, result.reason = (pose if pose.ok else None), why
        stage["pose+select"] = (time.perf_counter() - t2) * 1000

        result.stage_ms = stage
        result.cost_ms = (time.perf_counter() - t0) * 1000
        return result, frame
