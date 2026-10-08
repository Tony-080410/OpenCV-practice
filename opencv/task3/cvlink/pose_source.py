"""位姿来源：把「位姿从哪来」和「怎么发」分开。

--source 选三种：
    live      实时接入任务二的相机与位姿解算（考核要求的那条）
    dump      重放任务二 demo --dump 写出的 JSONL（没相机也能验链路）
    examples  手册任务三给的两帧固定数值（先验链路校验，再换实时）

三种只回答一件事：这一帧要发的字段是什么。都不碰串口，也不自己拼报文
（拼报文是 cvlink.protocol 的事）。record 的字段名跟手册表格一一对应。

约定：read(seq, t_ms) 返回 Sample；返回 None 表示没有下一帧可发了，
发送循环据此收尾，stop_reason 写明原因。取到空帧或检测不到目标不算没帧可发，
手册要求这时发一帧 valid=0 的无效报文。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import t3config
from cvlink import protocol
from cvlink.task2bridge import Task2ImportError, load_task2


class PoseSourceError(RuntimeError):
    """来源打不开或读不了（相机、dump 文件、任务二工程）。"""


@dataclass
class Sample:
    """一帧的位姿结果。

    record: CV1 要发的字段（seq/t_ms 已填好，其余见 protocol.FIELD_KEYS）
    reason: 不可用时的人可读原因，会写进日志，用来查为什么 valid=0
    frame : 只有 live 有，给预览窗画图；其它来源是 None
    """
    record: dict
    reason: str = ""
    cost_ms: float = 0.0
    n_detected: int = 0
    frame: np.ndarray | None = None


def invalid_record(seq: int, t_ms: int) -> dict:
    """无效报文的规定内容：id=-1、坐标与姿态全零（是否有效只看 valid）。"""
    rec: dict = {"seq": seq, "t_ms": t_ms, "valid": 0, "id": protocol.INVALID_ID}
    rec.update({key: 0.0 for key in protocol.VALUE_KEYS})
    return rec


# ==========================================================================
# live：实时接入任务二
# ==========================================================================
class LivePoseSource:
    """进程内用任务二的 Camera + PosePipeline。

    手册要求的「实时接入任务二结果」：不走文件、不走子进程，直接拿任务二
    每帧的字段（PoseFrame.record()），米到毫米的换算那层已经做了。
    """

    name = "live"

    def __init__(self, camera=None, width=None, height=None, tag_mm=None, target_id=None,
                 use_calib=True, task2_dir=None, empty_limit=None):
        self.camera = camera
        self.width = width
        self.height = height
        self.tag_mm = tag_mm
        self.target_id = target_id
        self.use_calib = use_calib
        self.task2_dir = task2_dir or t3config.TASK2_DIR
        self.empty_limit = t3config.EMPTY_LIMIT if empty_limit is None else empty_limit
        self.notes: list[str] = []
        self.stop_reason = ""
        self.t2 = None
        self.cam = None
        self.pipe = None
        self.info = None
        self.undistorter = None
        self.calib_note = ""
        self._empty = 0

    def open(self) -> str:
        try:
            self.t2 = load_task2(self.task2_dir)
        except Task2ImportError as e:
            raise PoseSourceError(str(e)) from e

        cfg = self.t2.config
        self.camera = cfg.CAMERA_INDEX if self.camera is None else self.camera
        self.width = cfg.CAMERA_WIDTH if self.width is None else self.width
        self.height = cfg.CAMERA_HEIGHT if self.height is None else self.height
        self.target_id = cfg.TARGET_ID if self.target_id is None else self.target_id
        self.tag_mm = cfg.TAG_EDGE_MM if self.tag_mm is None else self.tag_mm

        if self.use_calib:
            try:
                stored = self.t2.load_params()
            except FileNotFoundError as e:
                raise PoseSourceError(
                    f"{e}\n       先做任务二的标定（cd ../task2 && python main.py calib），"
                    f"或加 --no-calib 只看检测通路（此时位姿数值不可信）。") from e
            K, D = stored.K, stored.D
            self.undistorter = self.t2.Undistorter(stored.K, stored.D,
                                                   stored.width, stored.height)
            self.calib_note = f"标定参数 {stored.width}x{stored.height}，RMS {stored.rms:.4f} px"
        else:
            f = float(self.width)
            K = np.array([[f, 0, self.width / 2], [0, f, self.height / 2], [0, 0, 1]],
                         dtype=np.float64)
            D = np.zeros(5)
            self.undistorter = None
            self.calib_note = "未使用标定参数（内参为估值，位姿数值不可信）"

        try:
            self.cam = self.t2.Camera(self.camera, self.width, self.height)
            self.info = self.cam.open()
        except self.t2.CameraError as e:
            raise PoseSourceError(
                f"{e}\n       检查相机是否被占用（浏览器/会议软件会抢占），"
                f"或换 --camera 索引。") from e

        self.pipe = self.t2.PosePipeline(K, D, self.tag_mm, self.target_id,
                                         undistorter=self.undistorter)
        if self.undistorter is not None and not self.undistorter.resolution_ok(
                self.info.width, self.info.height):
            self.notes.append(
                f"标定分辨率 {self.undistorter.width}x{self.undistorter.height} 与相机实际 "
                f"{self.info.width}x{self.info.height} 不一致，位姿会明显偏大/偏小")
        return self.describe()

    def describe(self) -> str:
        cam = self.info.describe() if self.info is not None else "相机未打开"
        directory = self.t2.dir if self.t2 is not None else self.task2_dir
        return (f"live 实时接入任务二（{directory}）：{cam}；{self.calib_note}；"
                f"Tag 边长 {self.tag_mm:.1f} mm，目标 ID {self.target_id}")

    def read(self, seq: int, t_ms: int) -> Sample | None:
        if self.cam is None or self.pipe is None:
            raise PoseSourceError("live 来源还没打开，先调用 open()")
        ok, frame = self.cam.read()
        if not ok or frame is None:
            # 手册说读到空帧要发 valid=0：空帧本身照发无效报文，
            # 只是连续失败到 EMPTY_LIMIT 就收尾，不无限空转。
            self._empty += 1
            if self.empty_limit and self._empty > self.empty_limit:
                self.stop_reason = f"连续 {self._empty - 1} 次取帧失败"
                return None
            return Sample(invalid_record(seq, t_ms),
                          reason="读取到空帧（相机断开或流结束）")
        self._empty = 0
        result, shown = self.pipe.process(frame)
        # 直接用任务二那层的字段。record() 多出的 distance_mm 不是协议字段，
        # 协议层只取自己认识的键，整个丢过去也没事。
        return Sample(result.record(seq, t_ms),
                      reason=result.reason,
                      cost_ms=result.cost_ms,
                      n_detected=len(result.detections),
                      frame=shown)

    def close(self) -> None:
        if self.cam is not None:
            self.cam.close()
            self.cam = None


# ==========================================================================
# dump：重放任务二的 JSONL
# ==========================================================================
class DumpPoseSource:
    """重放源：读任务二 python main.py demo --dump <路径> 写出的逐帧 JSONL。

    那些行的字段就是 CV1 要发的字段（x_mm/y_mm/z_mm/rx/ry/rz），直接取用；
    只有 seq 和 t_ms 重新计：协议规定 seq 从 0 递增，t_ms 相对本次程序启动。
    """

    name = "dump"

    def __init__(self, path=None, loop: bool = False):
        self.path = Path(path).expanduser() if path else None
        self.loop = loop
        self.rows: list[dict] = []
        self.index = 0
        self.stop_reason = ""

    def open(self) -> str:
        if self.path is None:
            raise PoseSourceError("--source dump 需要 --dump <jsonl 路径>"
                                  "（由任务二的 python main.py demo --dump <路径> 生成）")
        if not self.path.exists():
            raise PoseSourceError(
                f"找不到 dump 文件：{self.path}\n"
                f"       生成：cd ../task2 && python main.py demo --dump {self.path}")
        rows = []
        for lineno, text in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            text = text.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError as e:
                raise PoseSourceError(f"{self.path} 第 {lineno} 行不是合法 JSON：{e}") from e
        if not rows:
            raise PoseSourceError(f"{self.path} 里没有任何帧")
        self.rows = rows
        return self.describe()

    def describe(self) -> str:
        n_valid = sum(1 for row in self.rows if row.get("valid"))
        loop = "；重放到底后循环" if self.loop else "；重放到底后结束"
        return (f"dump 重放 {self.path}：{len(self.rows)} 帧，其中有效 {n_valid} 帧"
                f"；seq/t_ms 按本次发送重新计数{loop}")

    def read(self, seq: int, t_ms: int) -> Sample | None:
        if self.index >= len(self.rows):
            if not self.loop:
                self.stop_reason = f"重放到底（共 {len(self.rows)} 帧）"
                return None
            self.index = 0
        row = self.rows[self.index]
        self.index += 1
        rec = {"seq": seq, "t_ms": t_ms,
               "valid": row.get("valid", 0), "id": row.get("id", protocol.INVALID_ID)}
        rec.update({key: row.get(key, 0.0) for key in protocol.VALUE_KEYS})
        return Sample(rec, reason=str(row.get("reason", "")),
                      cost_ms=float(row.get("frame_cost_ms", 0.0) or 0.0),
                      n_detected=len(row.get("detections") or []))

    def close(self) -> None:
        pass


# ==========================================================================
# examples：手册给出的固定报文
# ==========================================================================
class ExamplePoseSource:
    """发手册任务三给的两帧已知数值（校验 *33 / *09 是手册算好的）。

    手册要求的顺序就是先用已知数值验链路和校验，再换实时检测结果。
    为了让校验能逐字节对拍，这里连 seq/t_ms 都用示例的固定值（42/43、12345/12445），
    所以它不符合 seq 从 0 递增、t_ms 相对本次启动的常规约定，只用于链路验证。
    """

    name = "examples"

    def __init__(self, loop: bool = False):
        self.loop = loop
        self.index = 0
        self.stop_reason = ""

    def open(self) -> str:
        return self.describe()

    def describe(self) -> str:
        loop = "；发完一遍后循环" if self.loop else "；发完一遍就结束"
        return ("examples 手册固定报文：重放任务三示例的两帧"
                "（seq/t_ms 用示例的固定值 42/43、12345/12445，仅用于验证链路与校验）"
                f"{loop}")

    def read(self, seq: int, t_ms: int) -> Sample | None:
        if self.index >= len(protocol.MANUAL_EXAMPLES):
            if not self.loop:
                self.stop_reason = "示例发完"
                return None
            self.index = 0
        _, rec = protocol.MANUAL_EXAMPLES[self.index]
        self.index += 1
        return Sample(dict(rec), reason="手册示例固定报文")

    def close(self) -> None:
        pass


# ==========================================================================
def build_source(args) -> LivePoseSource | DumpPoseSource | ExamplePoseSource:
    """按命令行参数造出来源对象（不打开）。"""
    if args.source == "live":
        return LivePoseSource(camera=args.camera, width=args.width, height=args.height,
                              tag_mm=args.tag_mm, target_id=args.target_id,
                              use_calib=not args.no_calib, task2_dir=args.task2_dir,
                              empty_limit=args.empty_limit)
    if args.source == "dump":
        return DumpPoseSource(args.dump, loop=args.loop)
    if args.source == "examples":
        return ExamplePoseSource(loop=args.loop)
    raise PoseSourceError(f"未知来源 {args.source!r}（可选 live / dump / examples）")
