"""任务二 入口：相机标定（calib）与 AprilTag 位姿演示（demo）。

所有命令都在 task2 目录下执行：

    python main.py demo                 # 实时演示：检测 + 位姿 + 显示（需先标定）
    python main.py demo --no-calib      # 没标定时先看检测效果（位姿数值不可信，仅用于通路自测）
    python main.py demo --seconds 30 --record    # 录 30 秒并保存演示视频与日志
    python main.py calib                # 用 data/calib_images 里的图做标定，保存参数
    python main.py check                # 查看标定参数摘要，并检查与当前相机分辨率是否成对
    python main.py --help

处理流程（demo）：
    取帧 -> 去畸变 -> 检测全部 Tag -> 选定目标并判 valid -> 解算 R、t -> 画框/中心/角点/坐标轴/HUD
职责划分：取流在 src/camera.py，检测在 tag_detect.py，目标选择在 target.py，
解算在 pose.py，标定在 calibration.py，画图在 visualize.py，串联在 pipeline.py。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import config
from src import visualize
from src.calibration import BoardSpec, calibrate, load_params, save_params
from src.camera import Camera, CameraError
from src.pipeline import PosePipeline
from src.target import select_target
from src.undistort import Undistorter

EXIT_OK, EXIT_ERROR = 0, 1

# 保活表：实测 OpenCV 5.0.x + apriltag 在解释器退出、以及释放 main() 局部变量时会随机段错误
# （exit 139，重定向输出时还可能整段丢失）。把这些重对象挂在模块级引用上活到 os._exit，
# 并在返回前先 flush，避开那段会崩的清理。详见 README 已知问题第 1 条。
_KEEP_ALIVE: list = []


# --------------------------------------------------------------------------
# 公共小工具
# --------------------------------------------------------------------------
def _ensure_dirs() -> None:
    for p in (config.OUTPUTS_VIDEOS, config.OUTPUTS_LOGS, config.OUTPUTS_SHOTS,
              config.CALIB_IMAGES):
        p.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# demo
# --------------------------------------------------------------------------
def cmd_demo(a: argparse.Namespace) -> int:
    _ensure_dirs()
    try:
        sp = None if a.no_calib else load_params()
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        print("       先标定，或用 python main.py demo --no-calib 只看检测效果。")
        return EXIT_ERROR

    if sp is None:
        f = float(a.width)                                   # 粗略经验值，绝不是标定结果
        K = np.array([[f, 0, a.width / 2], [0, f, a.height / 2], [0, 0, 1]], dtype=np.float64)
        D = np.zeros(5)
        undist, calib_note = None, "未使用标定参数（内参为估值，位姿数值不可信）"
    else:
        K, D = sp.K, sp.D
        undist = Undistorter(sp.K, sp.D, sp.width, sp.height)
        calib_note = f"标定参数 {sp.width}x{sp.height}，RMS {sp.rms:.4f} px"

    try:
        cam = Camera(a.camera, a.width, a.height)
        info = cam.open()
    except CameraError as e:
        print(f"[错误] {e}")
        print("       检查相机是否被占用（浏览器/会议软件会抢占），或换 --camera 索引。")
        return EXIT_ERROR

    print(f"[信息] {info.describe()}")
    print(f"[信息] {calib_note}；去畸变{'开' if undist else '关'}；"
          f"Tag 边长 {a.tag_mm:.1f} mm；目标 ID {a.target_id}")
    if undist is not None and not undist.resolution_ok(info.width, info.height):
        print(f"[警告] 标定分辨率 {undist.width}x{undist.height} 与相机实际 "
              f"{info.width}x{info.height} 不一致，位姿会明显偏大/偏小，"
              f"请按同一分辨率重新标定或用 --width/--height 指定标定时的分辨率。")

    pipe = PosePipeline(K, D, a.tag_mm, a.target_id, undistorter=undist)
    _KEEP_ALIVE.append(pipe)

    writer = None
    if a.record:
        fourcc = cv2.VideoWriter_fourcc(*config.OUTPUT_VIDEO_FOURCC)
        writer = cv2.VideoWriter(str(config.DEMO_VIDEO), fourcc,
                                 max(info.fps, 1.0), (info.width, info.height))
        if not writer.isOpened():
            print(f"[警告] 打不开视频写入器，跳过录像：{config.DEMO_VIDEO}")
            writer = None

    log_lines: list[str] = []
    dump_fp = None
    if a.dump:
        Path(a.dump).parent.mkdir(parents=True, exist_ok=True)
        dump_fp = open(a.dump, "w", encoding="utf-8")
    t_start = time.monotonic()
    seq = 0
    n_frame = n_valid = 0
    prev_valid = False
    try:
        while True:
            ok, frame = cam.read()
            if not ok:
                print("[信息] 取帧失败（相机断开或流结束），正常收尾。")
                break
            result, shown = pipe.process(frame)
            t_ms = int((time.monotonic() - t_start) * 1000)

            rec = result.record(seq, t_ms)
            line = (f"seq {rec['seq']:6d} | t {t_ms:7d} ms | valid {rec['valid']} | id {rec['id']:3d} | "
                    f"x {rec['x_mm']:8.1f} y {rec['y_mm']:8.1f} z {rec['z_mm']:8.1f} mm | "
                    f"|t| {rec['distance_mm']:7.1f} mm | cost {result.cost_ms:5.1f} ms")
            print(line)
            log_lines.append(line)

            # 目标刚变成有效时，把完整的 R、t、rvec 打一份出来（"输出有效 R、t"的证据，
            # 也便于人工核对变换方向；逐帧只打转移点，避免刷屏）
            if result.valid and not prev_valid:
                p = result.pose
                block = [f"[位姿] seq={seq}  t_ms={t_ms}",
                         f"       t (m)      = {np.array2string(p.t, precision=4, floatmode='fixed')}",
                         f"       R          = {np.array2string(p.R, precision=4, floatmode='fixed', prefix='                     ')}",
                         f"       rvec (rad) = {np.array2string(p.rvec.ravel(), precision=6, floatmode='fixed')}",
                         f"       直线距离 {p.distance:.4f} m   Z 深度 {p.depth:.4f} m   "
                         f"重投影残差 {p.reproj_error:.3f} px"]
                for b in block:
                    print(b)
                    log_lines.append(b)
            if dump_fp is not None:
                json.dump(_pose_json(seq, t_ms, result), dump_fp, ensure_ascii=False)
                dump_fp.write("\n")
            prev_valid = result.valid

            target_det = select_target(result.detections, a.target_id)
            for det in result.detections:
                visualize.draw_tag(shown, det, det is target_det)
            if result.valid and target_det is not None:
                visualize.draw_pose_axes(shown, target_det, result.pose, result.K_used,
                                         pipe.edge_m, result.D_used)

            extra = [f"frame {n_frame}  seq {seq}  cost {result.cost_ms:.1f} ms",
                     f"detected {len(result.detections)} tag(s)"]
            hud = visualize.format_pose_lines(target_det, result.pose,
                                              result.valid, result.reason, extra)
            visualize.draw_hud(shown, hud)

            if writer is not None:
                writer.write(shown)
            n_frame += 1
            n_valid += int(result.valid)
            seq += 1

            if a.show:
                cv2.imshow("task2 - AprilTag pose (q/ESC 退出, s 截图)", shown)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("s"):
                    shot = config.OUTPUTS_SHOTS / f"shot_{seq:06d}.png"
                    if cv2.imwrite(str(shot), shown):
                        print(f"[信息] 截图已保存 {shot}")
                    else:
                        print(f"[警告] 截图保存失败 {shot}")
            if a.seconds and (time.monotonic() - t_start) >= a.seconds:
                break
            if a.max_frames and n_frame >= a.max_frames:
                break
    except KeyboardInterrupt:
        print("\n[信息] 手动中断，收尾。")
    finally:
        if a.show:
            cv2.destroyAllWindows()
        cam.close()
        if writer is not None:
            writer.release()
        if dump_fp is not None:
            dump_fp.close()

    print(f"[完成] 处理 {n_frame} 帧，其中位姿有效 {n_valid} 帧"
          f"（{100.0 * n_valid / max(n_frame, 1):.1f}%）。")
    if a.record:
        config.DEMO_LOG.parent.mkdir(parents=True, exist_ok=True)
        config.DEMO_LOG.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        print(f"[完成] 演示视频 {config.DEMO_VIDEO}；日志 {config.DEMO_LOG}")
    if dump_fp is not None:
        print(f"[完成] 逐帧完整位姿（含 R 矩阵）{a.dump}")
    return EXIT_OK


def _pose_json(seq: int, t_ms: int, result) -> dict:
    """把一帧结果整理成 JSON 行：含完整 R 矩阵、t、距离与耗时。

    这份文件既可作为任务二“输出有效 R、t”的证据，也可被任务三直接消费
    （seq/t_ms/valid/id/毫米坐标/rx,ry,rz 就是 CV1 协议要的字段）。
    """
    out = dict(result.record(seq, t_ms))
    out["reason"] = result.reason
    out["frame_cost_ms"] = round(result.cost_ms, 3)
    out["stage_ms"] = {k: round(v, 3) for k, v in result.stage_ms.items()}
    out["detections"] = [{"id": d.tag_id,
                          "center_px": [round(d.center[0], 2), round(d.center[1], 2)],
                          "hamming": d.hamming,
                          "decision_margin": round(d.decision_margin, 2)}
                         for d in result.detections]
    if result.valid and result.pose is not None:
        p = result.pose
        out["t_m"] = [float(v) for v in p.t]
        out["R"] = [[float(v) for v in row] for row in np.asarray(p.R)]
        out["depth_m"] = p.depth
        out["distance_m"] = p.distance
        out["reproj_error_px"] = round(p.reproj_error, 4)
    return out


# --------------------------------------------------------------------------
# calib / check
# --------------------------------------------------------------------------
def cmd_calib(a: argparse.Namespace) -> int:
    _ensure_dirs()
    spec = BoardSpec(a.inner_cols, a.inner_rows, a.square_mm)
    src_dir = Path(a.images) if a.images else config.CALIB_IMAGES
    images = [p for p in sorted(src_dir.glob("*"))
              if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp")]
    if not images:
        print(f"[错误] {src_dir} 里没有标定图片。")
        print("       先用 python tools/capture_calib.py 采集，或用 --images 指定目录。")
        return EXIT_ERROR
    print(f"[信息] 标定板 {spec.inner_cols}x{spec.inner_rows} 内角点，方格 {spec.square_mm:.2f} mm；"
          f"候选图片 {len(images)} 张（来自 {src_dir}）")

    res = calibrate(images, spec)
    print(f"[信息] 采用 {len(res.used_images)} 张，跳过 {len(res.skipped_images)} 张")
    if not res.ok:
        print(f"[错误] 标定失败：{res.reason}")
        return EXIT_ERROR

    out = save_params(res, spec, a.out)
    print(f"[信息] 分辨率 {res.width}x{res.height}（解算时必须用同一分辨率）；"
          f"RMS 重投影误差 {res.rms:.4f} px")
    print(f"[信息] 内参 K = \n{np.array2string(res.K, precision=3, suppress_small=True)}")
    print(f"[信息] 畸变 D = {np.array2string(np.asarray(res.D).reshape(-1), precision=4)}")
    worst = sorted(res.per_image_error.items(), key=lambda kv: -kv[1])[:3]
    for p, e in worst:
        print(f"       [最差] {Path(p).name} 平均重投影误差 {e:.4f} px")
    print(f"[完成] 参数已保存 {out}")
    return EXIT_OK


def cmd_check(a: argparse.Namespace) -> int:
    try:
        sp = load_params(a.params)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        return EXIT_ERROR
    board = sp.raw.get("board", {})
    board_note = (f"，标定板 {board['inner_cols']}x{board['inner_rows']} 内角点，"
                  f"方格 {board['square_mm']} mm") if board else ""
    print(f"[信息] 参数文件 {Path(a.params or config.CALIB_PARAMS)}")
    print(f"[信息] 分辨率 {sp.width}x{sp.height}，RMS {sp.rms:.4f} px，"
          f"采用 {len(sp.raw.get('used_images', []))} 张"
          f"（跳过 {len(sp.raw.get('skipped_images', []))} 张）{board_note}")
    print(f"[信息] K = \n{np.array2string(sp.K, precision=3, suppress_small=True)}")
    print(f"[信息] D = {np.array2string(sp.D, precision=4)}")
    if a.camera is not None:
        try:
            with Camera(a.camera, a.width, a.height) as cam:
                info = cam.info
                if Undistorter(sp.K, sp.D, sp.width, sp.height).resolution_ok(
                        info.width, info.height):
                    print(f"[信息] 当前相机 {info.describe()}；分辨率与标定一致")
                else:
                    print(f"[警告] 当前相机 {info.describe()}；分辨率与标定 "
                          f"{sp.width}x{sp.height} 不一致，位姿会明显偏差，"
                          f"请重新标定或改 --width/--height")
        except CameraError as e:
            print(f"[错误] {e}")
            return EXIT_ERROR
    return EXIT_OK


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="任务二：相机标定与 AprilTag 位姿",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("demo", help="实时演示：检测 + 位姿 + 显示", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    d.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    d.add_argument("--width", type=int, default=config.CAMERA_WIDTH)
    d.add_argument("--height", type=int, default=config.CAMERA_HEIGHT)
    d.add_argument("--seconds", type=float, default=0.0, help="运行秒数，0 表示不限（按 q/ESC 退出）")
    d.add_argument("--max-frames", type=int, default=0, help="只处理前 N 帧，0 表示不限")
    d.add_argument("--record", action="store_true", help="保存演示视频与日志")
    d.add_argument("--no-calib", action="store_true", help="不加载标定参数（只看检测通路）")
    d.add_argument("--tag-mm", type=float, default=config.TAG_EDGE_MM,
                   help="Tag 黑框外边实测边长（mm），临时覆盖 config")
    d.add_argument("--target-id", type=int, default=config.TARGET_ID,
                   help="要选中并发布位姿的 Tag ID（临时覆盖 config）")
    d.add_argument("--dump", default=None,
                   help="逐帧完整位姿写 JSONL（含 R 矩阵），例如 outputs/logs/pose.jsonl")
    d.add_argument("--no-show", dest="show", action="store_false",
                   help="不开窗口，只打日志/录像（默认开窗口；要按 s 截图必须开窗口）")
    d.set_defaults(func=cmd_demo)

    c = sub.add_parser("calib", help="用 data/calib_images 里的图做标定", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    c.add_argument("--images", default=None, help="标定图片目录（默认 config.CALIB_IMAGES）")
    c.add_argument("--inner-cols", type=int, default=config.BOARD_INNER_COLS)
    c.add_argument("--inner-rows", type=int, default=config.BOARD_INNER_ROWS)
    c.add_argument("--square-mm", type=float, default=config.BOARD_SQUARE_MM)
    c.add_argument("--out", default=None, help="参数输出路径")
    c.set_defaults(func=cmd_calib)

    k = sub.add_parser("check", help="查看标定参数，并检查与相机分辨率是否成对", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    k.add_argument("--params", default=None)
    k.add_argument("--camera", type=int, default=None, help="给定时顺便打开相机核对分辨率")
    k.add_argument("--width", type=int, default=config.CAMERA_WIDTH)
    k.add_argument("--height", type=int, default=config.CAMERA_HEIGHT)
    k.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    if not getattr(a, "cmd", None):
        parser.print_help()
        return EXIT_OK
    code = a.func(a)
    sys.stdout.flush()          # 先落盘：之后的清理阶段可能出问题（见文件顶部 _KEEP_ALIVE 说明）
    sys.stderr.flush()
    return code


if __name__ == "__main__":
    _code = main()
    # OpenCV 5.0.x 与 apriltag 库在解释器退出阶段会段错误（实测 exit 139），与本程序逻辑无关。
    # 用 os._exit 带退出码直接退出，跳过会崩的清理阶段，保证退出码可信。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code)
