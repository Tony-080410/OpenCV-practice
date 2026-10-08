"""等价接收端：用另一份独立实现，验证串口上真的出现了合规的 CV1 报文。

为什么另写一遍解析、不复用 cvlink.protocol：这是交叉验证。收发共用同一个
解析器时，同一个 bug 会藏在两边还互相印证为对。这里拆帧规则、异或范围、
小数位数、无效帧语义都自己判一遍。手册也提醒串口是字节流，一次发送不保证
对应一次接收，所以这里按 CRLF 累积拆帧，不假设一次 read 就是一帧。

它同时当接收日志的生成器：日志里写的是收到的原始字节，能跟发送日志逐字节比对。
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import serial

INT_RE = re.compile(r"-?\d+")
COORD_RE = re.compile(r"-?\d+\.\d")
RTVEC_RE = re.compile(r"-?\d+\.\d{6}")
HEX_RE = re.compile(r"[0-9A-F]{2}")

FIELD_NAMES = ("seq", "t_ms", "valid", "id", "x_mm", "y_mm", "z_mm", "rx", "ry", "rz")
INT_FIELDS = ("seq", "t_ms", "valid", "id")
VALUE_FIELDS = ("x_mm", "y_mm", "z_mm", "rx", "ry", "rz")


def parse_frame(raw: bytes):
    """拆一帧并校验。返回 (字段 dict, 错误说明)；任一不合规都返回错误。"""
    if not raw.endswith(b"\r\n"):
        return None, f"结尾不是真正的 CRLF：{raw[-4:]!r}"
    try:
        text = raw[:-2].decode("ascii")
    except UnicodeDecodeError:
        return None, f"含非 ASCII 字节：{raw[:40]!r}"
    if not text.startswith("$"):
        return None, f"帧头不是 $：{text[:20]!r}"
    if "*" not in text:
        return None, "缺少 * 校验分隔符"
    body, _, chk = text[1:].rpartition("*")
    if not HEX_RE.fullmatch(chk):
        return None, f"校验字段不是两位大写十六进制：{chk!r}"
    value = 0
    for byte in body.encode("ascii"):
        value ^= byte
    if f"{value:02X}" != chk:
        return None, f"校验不匹配：报文 {chk}，复算 {value:02X}"

    parts = body.split(",")
    if len(parts) != 1 + len(FIELD_NAMES):
        return None, f"字段数 {len(parts)}，应为 {1 + len(FIELD_NAMES)}"
    if parts[0] != "CV1":
        return None, f"协议版本不是 CV1：{parts[0]!r}"

    out: dict = {}
    for name, token in zip(FIELD_NAMES, parts[1:]):
        if name in INT_FIELDS:
            if not INT_RE.fullmatch(token):
                return None, f"{name} 不是整数：{token!r}"
            out[name] = int(token)
        else:
            pattern = COORD_RE if name in ("x_mm", "y_mm", "z_mm") else RTVEC_RE
            if not pattern.fullmatch(token):
                want = "1 位小数" if pattern is COORD_RE else "6 位小数"
                return None, f"{name} 不是{want}的定点小数（不能是科学计数法）：{token!r}"
            out[name] = float(token)

    if out["valid"] not in (0, 1):
        return None, f"valid 只能是 0 或 1，收到 {out['valid']}"
    if out["valid"]:
        if out["id"] < 0:
            return None, f"valid=1 但 id={out['id']}（有效时应是选中的 Tag ID）"
    else:
        if out["id"] != -1:
            return None, f"valid=0 但 id={out['id']}（协议规定无效时 id=-1）"
        if any(out[key] != 0.0 for key in VALUE_FIELDS):
            return None, "valid=0 但坐标/姿态不是零（协议规定统一置零）"
    return out, None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="CV1 等价接收端：按 CRLF 拆帧、复算校验、打印并写接收日志",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--port", required=True,
                   help="串口设备：虚拟串口对里跟发送程序不同的那一端")
    p.add_argument("--log", default=None, help="把收到的原始字节写盘（首行注释 + 字节流）")
    p.add_argument("--seconds", type=float, default=0.0, help="接收秒数，0 表示不限")
    p.add_argument("--max-frames", type=int, default=0, help="收满多少帧后退出，0 表示不限")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--strict-seq", action="store_true",
                   help="序号异常也算失败（examples 用固定 seq，会回跳）")
    p.add_argument("--quiet", action="store_true", help="只打印错误与汇总，不逐帧打印")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        ser = serial.Serial(a.port, a.baud, bytesize=8, parity="N", stopbits=1,
                            timeout=0.2, rtscts=False, xonxoff=False, dsrdtr=False)
    except (serial.SerialException, OSError, ValueError) as e:
        print(f"[错误] 打不开串口 {a.port}：{e}")
        print("       先跑 bash tools/vport.sh 建虚拟串口对；"
              "注意另一端由发送程序打开，两边不能是同一个端点。")
        return 1

    log = None
    if a.log:
        log = open(a.log, "wb")
        log.write(f"# task3 接收日志（收到的原始字节，含真实 CRLF）\n".encode("utf-8"))
        log.write(f"# 时间：{time.strftime('%Y-%m-%d %H:%M:%S%z')}\n".encode("utf-8"))
        log.write(f"# 端口：{a.port}，{a.baud}/8N1\n".encode("utf-8"))

    buffer = bytearray()
    frames = errors = seq_anomalies = 0
    transitions: list[str] = []
    prev_valid = None
    prev_seq = None
    ever_valid = False
    t0 = time.monotonic()
    rc = 0
    print(f"[信息] 正在监听 {a.port}（{a.baud}/8N1）；Ctrl-C 结束")
    try:
        while True:
            try:
                chunk = ser.read(max(1, ser.in_waiting))
            except (serial.SerialException, OSError) as e:
                print(f"[错误] 读串口失败：{e}")
                rc = 1
                break
            if chunk:
                buffer += chunk
            while b"\n" in buffer:                       # 按换行拆帧，不假设一次读一帧
                raw, _, rest = buffer.partition(b"\n")
                buffer = bytearray(rest)
                raw += b"\n"
                if a.log:
                    log.write(raw)
                rec, err = parse_frame(raw)
                if err is not None:
                    errors += 1
                    print(f"[错误] 第 {frames + errors} 帧不合规：{err}")
                    print(f"       原始字节：{raw!r}")
                    continue
                frames += 1
                if not a.quiet:
                    print(f"[帧 {frames:>5d}] seq {rec['seq']:>10d} t {rec['t_ms']:>8d} ms "
                          f"valid {rec['valid']} id {rec['id']:>3d} | "
                          f"x {rec['x_mm']:>9.1f} y {rec['y_mm']:>9.1f} z {rec['z_mm']:>9.1f} mm | "
                          f"rvec {rec['rx']:.6f},{rec['ry']:.6f},{rec['rz']:.6f} | 校验 ok")
                if prev_seq is not None and rec["seq"] != (prev_seq + 1) & 0xFFFFFFFF:
                    seq_anomalies += 1
                    print(f"[提示] 序号不连续：上一帧 {prev_seq} → 本帧 {rec['seq']}"
                          f"（examples 来源用示例的固定 seq，属正常）")
                prev_seq = rec["seq"]
                if rec["valid"] != prev_valid:
                    if prev_valid is None:
                        kind = "首帧"
                    elif rec["valid"]:
                        kind = "目标重现" if ever_valid else "目标出现"
                    else:
                        kind = "目标消失"
                    transitions.append(f"帧 {frames}（seq {rec['seq']}）：{kind}，valid "
                                       f"{prev_valid} → {rec['valid']}")
                if rec["valid"]:
                    ever_valid = True
                prev_valid = rec["valid"]
                if a.max_frames and frames >= a.max_frames:
                    break
            if a.max_frames and frames >= a.max_frames:
                break
            if a.seconds and (time.monotonic() - t0) >= a.seconds:
                break
    except KeyboardInterrupt:
        print("\n[信息] 手动中断。")
    finally:
        ser.close()
        if log is not None:
            log.close()

    print("-" * 72)
    print(f"[汇总] 收到 {frames} 帧，不合规 {errors} 帧，序号异常 {seq_anomalies} 次")
    if transitions:
        print("[状态] 有效性变化序列（提交要求的 出现→消失→重现 就是这一段）：")
        for item in transitions:
            print(f"       {item}")
    if buffer:
        print(f"[提示] 结束时还剩 {len(buffer)} 字节不构成完整一帧（字节流被截断处）")
    if a.log:
        print(f"[完成] 接收日志 {a.log}（原始字节，可与发送日志逐字节比对）")

    if frames == 0:
        print("[错误] 一帧都没收到：检查两端是否打开了不同的端点、发送端是否在发。")
        return 1
    if errors:
        return 1
    if a.strict_seq and seq_anomalies:
        return 1
    print("[结论] 收到的每一帧都符合 CV1 协议。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
