"""任务三入口：把任务二的 AprilTag 位姿按 CV1 协议经串口发出去。

send 的流程：位姿来源(pose_source) -> 字段(record) -> CV1 报文字节(protocol) -> 串口(serial_link)。
分工：报文格式只在 cvlink/protocol.py，串口只在 cvlink/serial_link.py，
实时接入任务二在 cvlink/task2bridge.py + pose_source.py，画图在 cvlink/preview.py。
检测、位姿解算、标定不在这，都在任务二。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

import t3config
from cvlink import protocol
from cvlink.pose_source import PoseSourceError, build_source
from cvlink.serial_link import LinkError, SerialLink

EXIT_OK, EXIT_ERROR = 0, 1
ROOT = Path(__file__).resolve().parent

# 保活表：OpenCV 5.0.x + apriltag 在解释器退出、以及释放 main() 局部变量时
# 会随机段错误（exit 139），重定向输出还可能整段丢。把重对象挂这活到
# os._exit，返回前先 flush，避开会崩的清理。见 task2/README.md 已知问题第 1 条。
_KEEP_ALIVE: list = []


def _ensure_dirs() -> None:
    for path in (t3config.OUTPUTS_LOGS, t3config.PREVIEW_SCREENSHOTS):
        path.mkdir(parents=True, exist_ok=True)


def _open_log(path: str, header: list[str]):
    """发送日志 = 首行注释（UTF-8 文本）加之后的原样字节。

    所以日志里每条就是串口上实际写出的字节：结尾是真的 CRLF，不是字面量 \\r\\n，
    接收日志能直接跟它逐字节比对。
    """
    fp = open(path, "wb")
    for line in header:
        fp.write(f"# {line}\n".encode("utf-8"))
    return fp


# --------------------------------------------------------------------------
# send
# --------------------------------------------------------------------------
def cmd_send(a: argparse.Namespace) -> int:
    if a.rate <= 0:
        print("[错误] --rate 必须为正数（手册建议约 10 Hz）")
        return EXIT_ERROR
    if a.tag_mm is not None and a.tag_mm <= 0:
        print("[错误] --tag-mm 必须为正数，单位毫米（Tag 黑框外边的实测边长）")
        return EXIT_ERROR
    if a.empty_limit < 0:
        print("[错误] --empty-limit 不能为负（0 表示一直发无效报文、不收尾）")
        return EXIT_ERROR
    _ensure_dirs()
    if a.show and a.source != "live":
        print(f"[信息] 提示：--show 只在 --source live 时有画面，当前来源 {a.source} 没有帧可显示")

    # ---- 位姿来源 ----
    try:
        source = build_source(a)
        note = source.open()
    except PoseSourceError as e:
        print(f"[错误] {e}")
        return EXIT_ERROR
    _KEEP_ALIVE.append(source)
    print(f"[信息] 位姿来源：{note}")
    for warning in getattr(source, "notes", []):
        print(f"[警告] {warning}")

    # ---- 串口 ----
    link = None
    if a.dry_run:
        print("[信息] --dry-run：只把报文打到屏幕，不写串口")
    else:
        link = SerialLink(a.port, baudrate=a.baud, bytesize=a.bytesize, parity=a.parity,
                          stopbits=a.stopbits, flow=a.flow,
                          timeout=t3config.SERIAL_TIMEOUT,
                          write_timeout=t3config.SERIAL_WRITE_TIMEOUT)
        try:
            info = link.open()
        except LinkError as e:
            print(f"[错误] {e}")
            source.close()
            return EXIT_ERROR
        print(f"[信息] 串口：{info.describe()}")
        print("[信息] 接收端（串口助手）请打开另一个端点，不能与上面这个相同。")
    _KEEP_ALIVE.append(link)

    log = None
    if a.log:
        try:
            log = _open_log(a.log, [
                "task3 发送日志（CV1 协议）",
                f"时间：{time.strftime('%Y-%m-%d %H:%M:%S%z')}",
                f"端口：{'(dry-run，未写串口)' if a.dry_run else a.port}",
                f"来源：{note}",
                "说明：下面每一条就是串口上实际写出的字节（结尾是真的 CRLF = 回车+换行）。",
            ])
        except OSError as e:
            print(f"[错误] 打不开发送日志 {a.log}：{e}")
            source.close()
            if link is not None:
                link.close()
            return EXIT_ERROR

    preview_mod = None
    if a.show:
        from cvlink import preview as preview_mod      # 只在要看画面时才引入 cv2

    interval = 1.0 / a.rate
    t0 = time.monotonic()
    next_t = t0
    seq = 0
    n_sent = n_valid = n_bytes = n_shot = 0
    prev_valid = None
    ever_valid = False
    rc = EXIT_OK
    print(f"[信息] 开始发送：{a.rate:g} Hz，"
          f"{'不限时' if not a.seconds else f'{a.seconds:g} 秒'}，"
          f"{'不限帧数' if not a.max_frames else f'最多 {a.max_frames} 帧'}；Ctrl-C 结束")
    try:
        while True:
            now = time.monotonic()
            if now < next_t:
                time.sleep(min(next_t - now, interval))
            t_ms = int((time.monotonic() - t0) * 1000)

            sample = source.read(seq, t_ms)
            if sample is None:
                print(f"[信息] 来源结束（{getattr(source, 'stop_reason', '')}），收尾。")
                break
            data, rec, notes = protocol.format_frame(sample.record)
            for warning in notes:
                print(f"[警告] {warning}")
            line = data.decode("ascii").rstrip("\r\n")

            # 先真写出去再记账，打印一行不算发送成功
            if link is not None:
                try:
                    link.send(data)
                except LinkError as e:
                    print(f"[错误] {e}")
                    rc = EXIT_ERROR
                    break
            if log is not None:
                log.write(data)
            n_bytes += len(data)

            print(f"seq {rec['seq']:>10d} | t {rec['t_ms']:>8d} ms | valid {rec['valid']} | "
                  f"id {rec['id']:>3d} | x {rec['x_mm']:>9.1f} y {rec['y_mm']:>9.1f} "
                  f"z {rec['z_mm']:>9.1f} mm | "
                  f"rx {rec['rx']:>10.6f} ry {rec['ry']:>10.6f} rz {rec['rz']:>10.6f} | "
                  f"检测 {sample.n_detected} | {sample.cost_ms:5.1f} ms | {len(data)} B")

            if rec["valid"] != prev_valid:
                if prev_valid is None:
                    kind = "首帧"
                elif rec["valid"]:
                    kind = "目标重现" if ever_valid else "目标出现"
                else:
                    kind = f"目标消失（{sample.reason}）"
                print(f"[状态] seq {rec['seq']}：{kind}（valid {prev_valid} → {rec['valid']}）")

            if preview_mod is not None:
                shown = preview_mod.draw(sample, line)
                if shown is not None:
                    import cv2
                    cv2.imshow(t3config.PREVIEW_WINDOW, shown)
                    action = preview_mod.handle_key(1)
                    if action == "quit":
                        print("[信息] 手动退出预览窗。")
                        break
                    if action == "shot":
                        saved = preview_mod.save_shot(shown, n_shot)
                        n_shot += 1
                        print(f"[信息] 截图{'已保存 ' + str(saved) if saved else '保存失败'}")

            seq = (seq + 1) & protocol.SEQ_MAX
            n_sent += 1
            n_valid += int(rec["valid"])
            if rec["valid"]:
                ever_valid = True
            prev_valid = rec["valid"]

            if a.seconds and (time.monotonic() - t0) >= a.seconds:
                break
            if a.max_frames and n_sent >= a.max_frames:
                break
            next_t += interval
            if time.monotonic() > next_t + interval:      # 落后太多就重新对齐，不追赶爆发
                next_t = time.monotonic()
    except KeyboardInterrupt:
        print("\n[信息] 手动中断，收尾。")
    finally:
        if preview_mod is not None:
            preview_mod.close()
        source.close()
        if link is not None:
            link.close()
        if log is not None:
            log.close()

    if n_sent == 0:
        print("[错误] 一帧都没有发出。")
        return EXIT_ERROR
    mode = "（dry-run，未写串口）" if a.dry_run else ""
    print(f"[完成] 发送 {n_sent} 帧（有效 {n_valid}，无效 {n_sent - n_valid}），"
          f"{n_bytes} 字节{mode}。")
    if link is not None and link.bytes_sent != n_bytes:
        print(f"[警告] 串口统计 {link.bytes_sent} 字节与记账 {n_bytes} 不一致。")
    if log is not None:
        print(f"[完成] 发送日志 {a.log}（含真实 CRLF，可与接收日志逐字节比对）")
    return rc


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------
def cmd_check(a: argparse.Namespace) -> int:
    link = SerialLink(a.port, baudrate=a.baud, bytesize=a.bytesize, parity=a.parity,
                      stopbits=a.stopbits, flow=a.flow,
                      timeout=t3config.SERIAL_TIMEOUT,
                      write_timeout=t3config.SERIAL_WRITE_TIMEOUT)
    try:
        info = link.open()
    except LinkError as e:
        print(f"[错误] {e}")
        return EXIT_ERROR
    print(f"[信息] {info.describe()}")
    link.close()
    if info.is_pty:
        print("[信息] 这是伪终端：另外一端必须由串口助手打开（同一端点会被两边抢占）。")
    print("[信息] 端口可以用上面的设置打开。下一步："
          "python main.py send --port <同一个端口> --source examples")
    return EXIT_OK


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------
def _run_protocol_selftest() -> int:
    path = ROOT / "tools" / "selftest_protocol.py"
    spec = importlib.util.spec_from_file_location("task3_selftest_protocol", path)
    if spec is None or spec.loader is None:
        print(f"[错误] 找不到协议自测脚本：{path}")
        return EXIT_ERROR
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.main())


def cmd_selftest(a: argparse.Namespace) -> int:
    return _run_protocol_selftest()


# --------------------------------------------------------------------------
def _add_serial_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", default=t3config.SERIAL_PORT,
                   help="串口设备，如 /dev/pts/3（用 tools/vport.sh 建虚拟串口对）")
    p.add_argument("--baud", type=int, default=t3config.SERIAL_BAUD, help="波特率")
    p.add_argument("--bytesize", type=int, default=t3config.SERIAL_BYTESIZE, help="数据位")
    p.add_argument("--parity", default=t3config.SERIAL_PARITY, help="校验：N 无 / E 偶 / O 奇")
    p.add_argument("--stopbits", type=float, default=t3config.SERIAL_STOPBITS, help="停止位")
    p.add_argument("--flow", default=t3config.SERIAL_FLOW,
                   help="流控：none 无 / rtscts 硬件 / xonxoff 软件")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="任务三：模拟串口通信（CV1 文本协议，发送任务二的 AprilTag 位姿）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("send", help="按 CV1 协议发送位姿",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    s.add_argument("--source", choices=("live", "dump", "examples"), default=t3config.SOURCE,
                   help="位姿来源：live 实时 / dump 重放 / examples 手册报文")
    s.add_argument("--dump", default=t3config.DUMP_PATH or None,
                   help="source=dump 时读的 JSONL（任务二 demo --dump 生成）")
    s.add_argument("--loop", action="store_true",
                   help="重放到底后从头再来（examples 的出现→消失→重现需要）")
    s.add_argument("--rate", type=float, default=t3config.SEND_RATE_HZ,
                   help="发送频率 Hz（手册建议约 10，不考核精确频率）")
    s.add_argument("--seconds", type=float, default=0.0, help="运行秒数，0 表示不限")
    s.add_argument("--max-frames", type=int, default=0, help="最多发多少帧，0 表示不限")
    s.add_argument("--log", default=None,
                   help="把发出的字节写盘（首行注释+字节流），提交用")
    s.add_argument("--dry-run", action="store_true", help="不写串口，只把报文打到屏幕")
    s.add_argument("--show", action="store_true", help="开预览窗（仅 source=live）")
    s.add_argument("--camera", type=int, default=None, help="相机索引（默认用任务二的 config）")
    s.add_argument("--width", type=int, default=None, help="请求宽度（默认用任务二的 config）")
    s.add_argument("--height", type=int, default=None, help="请求高度（默认用任务二的 config）")
    s.add_argument("--tag-mm", type=float, default=t3config.TAG_EDGE_MM,
                   help="Tag 黑框外边实测值 mm（默认取任务二的 config.TAG_EDGE_MM）")
    s.add_argument("--target-id", type=int, default=t3config.TARGET_ID,
                   help="要发布的 Tag ID（默认用任务二的 config.TARGET_ID）")
    s.add_argument("--no-calib", action="store_true",
                   help="不加载标定参数（内参用估值，位姿不可信）")
    s.add_argument("--task2-dir", default=None, help="任务二工程目录（默认 ../task2）")
    s.add_argument("--empty-limit", type=int, default=t3config.EMPTY_LIMIT,
                   help="连续取帧失败多少次后收尾（0 = 一直发无效报文）")
    _add_serial_args(s)
    s.set_defaults(func=cmd_send)

    c = sub.add_parser("check", help="只检查串口能否按 8N1 打开",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    _add_serial_args(c)
    c.set_defaults(func=cmd_check)

    t = sub.add_parser("selftest", help="CV1 协议自测（不碰串口与相机）",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    t.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    if not getattr(a, "cmd", None):
        parser.print_help()
        return EXIT_OK
    code = a.func(a)
    sys.stdout.flush()          # 先落盘：之后的清理阶段可能出问题（见文件顶部 _KEEP_ALIVE）
    sys.stderr.flush()
    return code


if __name__ == "__main__":
    _code = main()
    # 同任务二：OpenCV 5.0.x 与 apriltag 退出阶段会随机段错误（exit 139），
    # 跟本程序逻辑无关。用 os._exit 带退出码直接退，跳过会崩的清理。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code)
