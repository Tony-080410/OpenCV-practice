"""CV1 报文格式：只做「字段 → 字节」，不 import 串口、不 import cv2。

手册任务三规定的自定义 ASCII 协议（不是 RoboMaster 官方协议）：

    $CV1,seq,t_ms,valid,id,x_mm,y_mm,z_mm,rx,ry,rz*HH\\r\\n

规矩：
  开头是 $，接协议名 CV1，结尾是真 CRLF，接收端据此从字节流切帧；
  *HH 是 $ 与 * 之间所有 ASCII 字节逐字节异或，初值 0，两位大写十六进制，
      不含 $、*、校验字符和换行；
  不含空格，用英文小数点，坐标 1 位小数，旋转向量 6 位小数，不用科学计数法；
  姿态是与 R 等价的 Rodrigues 旋转向量（弧度），不是欧拉角；
  valid=0 时 id 为 -1、坐标与姿态全零；有没有效只看 valid。

纯函数，能完全离线验证：tools/selftest_protocol.py 拿手册给的两帧
（含算好的校验 *33 / *09）逐字节对拍这里的输出。
"""
from __future__ import annotations

import math

PROTOCOL = "CV1"
SEQ_MAX = 0xFFFFFFFF          # seq 是 32 位无符号，到最大值后回绕
INVALID_ID = -1               # valid=0 时 id 只能是 -1

COORD_NDIGITS = 1             # x_mm / y_mm / z_mm 保留 1 位小数
RTVEC_NDIGITS = 6             # rx / ry / rz 保留 6 位小数
TERMINATOR = "\r\n"           # 真正发送的回车 + 换行两个字节

# 字段顺序（手册表格的顺序，不能改）
INT_KEYS = ("seq", "t_ms", "valid", "id")
VALUE_KEYS = ("x_mm", "y_mm", "z_mm", "rx", "ry", "rz")
FIELD_KEYS = ("seq", "t_ms", "valid", "id") + VALUE_KEYS

# 手册任务三给出的两帧示例。左边是手册原文（不含换行），右边是对应字段。
# 这两行的校验值由手册算好，是本实现的独立基准：格式化结果要逐字节等于原文。
MANUAL_EXAMPLES: list[tuple[str, dict]] = [
    ("$CV1,42,12345,1,0,100.0,-50.0,800.0,0.000000,0.000000,0.000000*33",
     {"seq": 42, "t_ms": 12345, "valid": 1, "id": 0,
      "x_mm": 100.0, "y_mm": -50.0, "z_mm": 800.0,
      "rx": 0.0, "ry": 0.0, "rz": 0.0}),
    ("$CV1,43,12445,0,-1,0.0,0.0,0.0,0.000000,0.000000,0.000000*09",
     {"seq": 43, "t_ms": 12445, "valid": 0, "id": -1,
      "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
      "rx": 0.0, "ry": 0.0, "rz": 0.0}),
]


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def xor_checksum(body: str) -> int:
    """`$` 与 `*` 之间所有 ASCII 字节的逐字节异或，初值 0。"""
    value = 0
    for byte in body.encode("ascii"):
        value ^= byte
    return value


def checksum_hex(body: str) -> str:
    """两位大写十六进制。"""
    return f"{xor_checksum(body):02X}"


# --------------------------------------------------------------------------
# 字段归一化：把任何输入收敛成「一定符合协议」的一组字段
# --------------------------------------------------------------------------
def _as_int(value, default: int, name: str, notes: list[str]) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        notes.append(f"{name} 不是整数（{value!r}），按 {default} 处理")
        return default


def _as_float(value, name: str, notes: list[str]) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        notes.append(f"{name} 不是数字（{value!r}），按 0.0 处理")
        return 0.0


def normalize(rec: dict) -> tuple[dict, list[str]]:
    """把一帧字段收敛成协议允许的取值，返回 (字段, 告警列表)。

    协议不允许的东西在这挡掉，绝不把非法内容发到串口：seq 超 32 位无符号
    按掩码回绕；t_ms 为负归零；坐标/旋转向量出现 nan/inf 整帧降级为无效
    （否则报文被污染成 "nan"）；valid=1 但 id 为负也降级（id 只在有效时有意义）；
    无效帧一律 id=-1、坐标与姿态全零。
    """
    notes: list[str] = []

    seq = _as_int(rec.get("seq", 0), 0, "seq", notes)
    if not 0 <= seq <= SEQ_MAX:
        notes.append(f"seq {seq} 超出 32 位无符号范围，按掩码回绕为 {seq & SEQ_MAX}")
        seq &= SEQ_MAX

    t_ms = _as_int(rec.get("t_ms", 0), 0, "t_ms", notes)
    if t_ms < 0:
        notes.append(f"t_ms {t_ms} 为负，归零（t_ms 是相对程序启动的单调毫秒）")
        t_ms = 0

    valid = 1 if _as_int(rec.get("valid", 0), 0, "valid", notes) else 0
    tid = _as_int(rec.get("id", INVALID_ID), INVALID_ID, "id", notes)

    values = {key: _as_float(rec.get(key, 0.0), key, notes) for key in VALUE_KEYS}

    bad = [key for key in VALUE_KEYS if not math.isfinite(values[key])]
    if bad:
        notes.append("位姿含非有限值（" + "、".join(bad) + "），整帧降级为无效帧")
        if valid:
            valid = 0

    if valid and tid < 0:
        notes.append(f"valid=1 但 id={tid} 非法（有效时 id 应为选中的 Tag ID），降级为无效帧")
        valid = 0

    if not valid:
        # 协议规定无效帧 id 为 -1、坐标姿态全零。上游给反了就按协议改掉，
        # 但如实报出来，别悄悄改，否则上游的 bug 永远看不见。
        offending = tid != INVALID_ID or any(
            math.isfinite(values[key]) and values[key] != 0.0 for key in VALUE_KEYS)
        if offending:
            notes.append("无效帧的 id/坐标/姿态不是规定内容（应为 id=-1 且全零），"
                         "已按协议置零")
        tid = INVALID_ID
        values = {key: 0.0 for key in VALUE_KEYS}

    out = {"seq": seq, "t_ms": t_ms, "valid": valid, "id": tid, **values}
    return out, notes


# --------------------------------------------------------------------------
# 格式化
# --------------------------------------------------------------------------
def format_number(value, ndigits: int) -> str:
    """固定小数位的十进制串。

    先 round 再格式化，顺带把 -0.0 收敛成 0.0：坐标在 ±0.05 mm 以内会格式化成
    "-0.0"，语法上合法但看着像 bug。-0.0 == 0.0 为真，一个判断覆盖正负零。
    """
    rounded = round(float(value), ndigits)
    if rounded == 0.0:
        rounded = 0.0
    return f"{rounded:.{ndigits}f}"


def format_body(rec: dict) -> str:
    """`$` 与 `*` 之间的正文（从 `CV1` 开始）。rec 需已过 normalize()。"""
    coords = ",".join(format_number(rec[key], COORD_NDIGITS) for key in ("x_mm", "y_mm", "z_mm"))
    rvec = ",".join(format_number(rec[key], RTVEC_NDIGITS) for key in ("rx", "ry", "rz"))
    return (f"{PROTOCOL},{rec['seq']},{rec['t_ms']},{rec['valid']},{rec['id']},"
            f"{coords},{rvec}")


def format_line(rec: dict) -> str:
    """完整一行（含 `$`…`*HH` 与结尾 CRLF），rec 需已过 normalize()。"""
    body = format_body(rec)
    return f"${body}*{checksum_hex(body)}{TERMINATOR}"


def format_frame(rec: dict) -> tuple[bytes, dict, list[str]]:
    """一步到位：返回 (要写串口的字节, 归一化后的字段, 告警列表)。

    非 ASCII 字符 encode 时直接抛异常，这是想要的：宁可当场失败，
    也别把编码错乱的字节发出去。
    """
    norm, notes = normalize(rec)
    data = format_line(norm).encode("ascii")
    return data, norm, notes


# --------------------------------------------------------------------------
# 参考解析器（自测往返用；接收端 tools/fake_receiver.py 故意另写一份独立的）
# --------------------------------------------------------------------------
class ParseError(ValueError):
    """报文不符合 CV1 协议。"""


def parse_frame(text: str) -> dict:
    """解析一行完整报文（可带可不带结尾 CRLF），不合法则抛 ParseError。"""
    line = text.rstrip("\r\n")
    if not line.startswith("$"):
        raise ParseError("帧头不是 $")
    if "*" not in line:
        raise ParseError("缺少 * 校验分隔符")
    body, chk = line[1:].rsplit("*", 1)
    if len(chk) != 2 or any(c not in "0123456789ABCDEF" for c in chk):
        raise ParseError(f"校验字段不是两位大写十六进制：{chk!r}")
    if f"{xor_checksum(body):02X}" != chk:
        raise ParseError(f"校验不匹配：报文 {chk}，复算 {f'{xor_checksum(body):02X}'}")
    parts = body.split(",")
    if len(parts) != 1 + len(FIELD_KEYS):
        raise ParseError(f"字段数 {len(parts)}，应为 {1 + len(FIELD_KEYS)}")
    if parts[0] != PROTOCOL:
        raise ParseError(f"协议版本不是 {PROTOCOL}：{parts[0]!r}")
    out: dict = {}
    for key, raw in zip(FIELD_KEYS, parts[1:]):
        try:
            out[key] = int(raw) if key in INT_KEYS else float(raw)
        except ValueError as e:
            raise ParseError(f"{key} 不是合法数字：{raw!r}") from e
    return out
