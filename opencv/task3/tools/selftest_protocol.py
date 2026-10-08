"""CV1 协议自测：不碰串口、不碰相机，纯离线对拍。

开头两项是最硬的证据：手册任务三的两帧示例（校验 *33 / *09 是手册算好的）
要能被 cvlink.protocol 逐字节重现。对上了就说明字段顺序、数字格式、小数位数、
校验范围与大小写、结尾的真 CRLF 都对，而且是拿手册当基准，不是拿自己当基准。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # tools/ 的上一级才是工程根

from cvlink import protocol                                     # noqa: E402

COORD_RE = re.compile(r"-?\d+\.\d")
RTVEC_RE = re.compile(r"-?\d+\.\d{6}")
INT_RE = re.compile(r"-?\d+")

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok  ' if ok else 'FAIL'}] {name}" + (f"  —  {detail}" if detail else ""))
    if not ok:
        _failures.append(name)
    return bool(ok)


def _body_of(line: str) -> tuple[str, str]:
    """拆出 `$` 与 `*` 之间的正文和校验字段。"""
    body, _, chk = line[1:].rpartition("*")
    return body, chk


def test_manual_examples() -> None:
    """1) 手册两帧示例逐字节重现，本文件的核心。"""
    for line, rec in protocol.MANUAL_EXAMPLES:
        data, norm, notes = protocol.format_frame(rec)
        got = data.decode("ascii")
        expected = line + protocol.TERMINATOR
        check(f"手册示例逐字节重现 {line[:16]}…", got == expected,
              f"期望 {expected!r} 得到 {got!r}")
        check("  该帧没有产生告警", not notes, str(notes))
        body, chk = _body_of(line)
        check("  校验 = $ 与 * 之间所有字节的异或（两位大写十六进制）",
              protocol.checksum_hex(body) == chk,
              f"复算 {protocol.checksum_hex(body)}，手册 {chk}")
        back = protocol.parse_frame(got)
        check("  用自己的参考解析器往返一致",
              all(back[key] == norm[key] for key in protocol.FIELD_KEYS),
              f"{back}")


def test_field_format() -> None:
    """2) 数字格式：小数位数、无空格、无科学计数法、-0.0 收敛。"""
    rec = {"seq": 7, "t_ms": 1234, "valid": 1, "id": 0,
           "x_mm": 1.25, "y_mm": -0.04, "z_mm": 1234.5678,
           "rx": 3.14159265, "ry": -1e-07, "rz": 0.0000004}
    data, norm, notes = protocol.format_frame(rec)
    line = data.decode("ascii")
    body, chk = _body_of(line.rstrip("\r\n"))
    fields = body.split(",")

    check("字段数 = 1 + 10（协议名 + 十个字段）", len(fields) == 11, str(fields))
    check("报文不含空格", " " not in line and "\t" not in line)
    check("正文不含 $ 与 *", "$" not in body and "*" not in body)
    check("整数段都是整数", all(INT_RE.fullmatch(f) for f in fields[1:5]), str(fields[1:5]))
    check("坐标 1 位小数", all(COORD_RE.fullmatch(f) for f in fields[5:8]), str(fields[5:8]))
    check("旋转向量 6 位小数", all(RTVEC_RE.fullmatch(f) for f in fields[8:11]), str(fields[8:11]))
    check("不使用科学计数法", "e" not in body and "E" not in body, body)
    check("坐标 ±0.05 以内收敛成 0.0（不是 -0.0）", fields[6] == "0.0",
          f"y_mm=-0.04 → {fields[6]}")
    check("旋转向量 −1e-07 收敛成 0.000000", fields[9] == "0.000000",
          f"ry=-1e-07 → {fields[9]}")
    check("结尾是真正的回车+换行两个字节，不是字面量 \\r\\n",
          data.endswith(b"\r\n") and b"\\r\\n" not in data, repr(data[-6:]))
    check("整帧是纯 ASCII", all(b < 0x80 for b in data))
    check("本帧无告警", not notes, str(notes))


def test_invalid_frame() -> None:
    """3) 无效帧的规定内容：id=-1、坐标与姿态统一置零。"""
    rec = {"seq": 5, "t_ms": 6, "valid": 0, "id": 7,
           "x_mm": 111.0, "y_mm": 222.0, "z_mm": 333.0,
           "rx": 1.0, "ry": 2.0, "rz": 3.0}
    data, norm, notes = protocol.format_frame(rec)
    line = data.decode("ascii")
    fields = _body_of(line.rstrip("\r\n"))[0].split(",")
    check("无效帧 id 强制为 -1", norm["id"] == -1 and fields[4] == "-1", str(norm["id"]))
    check("无效帧坐标与姿态统一置零",
          all(norm[key] == 0.0 for key in protocol.VALUE_KEYS)
          and fields[5:8] == ["0.0", "0.0", "0.0"]
          and fields[8:11] == ["0.000000"] * 3, str(fields[4:]))
    check("置零动作有告警说明（不是悄悄改）", len(notes) == 1, str(notes))


def test_hostile_input() -> None:
    """4) 协议不允许的内容都得挡住，绝不发出去。"""
    base = {"seq": 1, "t_ms": 1, "valid": 1, "id": 0,
            "x_mm": 1.0, "y_mm": 2.0, "z_mm": 3.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}

    data, norm, notes = protocol.format_frame({**base, "x_mm": float("nan")})
    check("位姿含 nan → 降级为无效帧且报文里没有 nan",
          bool(norm["valid"] == 0 and b"nan" not in data and notes), str(notes))

    data, norm, notes = protocol.format_frame({**base, "z_mm": float("inf")})
    check("位姿含 inf → 降级为无效帧且报文里没有 inf",
          bool(norm["valid"] == 0 and b"inf" not in data and notes), str(notes))

    data, norm, notes = protocol.format_frame({**base, "valid": 1, "id": -1})
    check("valid=1 但 id=-1 → 降级为无效帧",
          bool(norm["valid"] == 0 and notes), str(notes))

    data, norm, notes = protocol.format_frame({**base, "seq": 2 ** 32})
    check("seq 超出 32 位无符号 → 掩码回绕",
          bool(norm["seq"] == 0 and notes),
          str(notes))

    data, norm, notes = protocol.format_frame({**base, "seq": protocol.SEQ_MAX})
    check("seq = 4294967295 可正常发送", norm["seq"] == protocol.SEQ_MAX, str(norm["seq"]))

    data, norm, notes = protocol.format_frame({**base, "t_ms": -5})
    check("t_ms 为负 → 归零", bool(norm["t_ms"] == 0 and notes), str(notes))

    data, norm, notes = protocol.format_frame({**base, "x_mm": None})
    check("字段为 None → 按 0.0 处理并告警",
          bool(norm["x_mm"] == 0.0 and notes), str(notes))


def test_negative_numbers() -> None:
    """5) 可带负号的坐标要原样发出（Tag 在光轴左侧/上方时）。"""
    rec = {"seq": 0, "t_ms": 0, "valid": 1, "id": 0,
           "x_mm": -123.45, "y_mm": -0.5, "z_mm": 800.0,
           "rx": -0.1234567, "ry": 0.0, "rz": 1.5707963}
    data, norm, _ = protocol.format_frame(rec)
    fields = _body_of(data.decode("ascii").rstrip("\r\n"))[0].split(",")
    check("负坐标保留负号且 1 位小数", fields[5] == "-123.5" and fields[6] == "-0.5",
          f"{fields[5]}, {fields[6]}")
    check("负旋转向量保留 6 位小数", fields[8] == "-0.123457" and fields[10] == "1.570796",
          f"{fields[8]}, {fields[10]}")


def main() -> int:
    print("CV1 协议自测（对照手册任务三）")
    print("=" * 72)
    test_manual_examples()
    print("-" * 72)
    test_field_format()
    print("-" * 72)
    test_invalid_frame()
    print("-" * 72)
    test_hostile_input()
    print("-" * 72)
    test_negative_numbers()
    print("=" * 72)
    if _failures:
        print(f"[结论] {len(_failures)} 项未通过：" + "；".join(_failures))
        return 1
    print("[结论] 全部通过。协议实现与手册示例逐字节一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
