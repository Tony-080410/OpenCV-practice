"""标定采集质量体检：把“位置、距离和倾斜方向有变化”量成数字，供评分项核查。

为什么需要它
------------
任务二的「标定采集与配置 6 分」里，给分细则是：
  * 自行采集并保存清晰标定原图                     2 分
  * **位置、距离和倾斜方向有变化**                 2 分
  * 棋盘格内角点数及方格尺寸设置正确               2 分
前两条不能只靠“我拍了 20 张”这种说法，得让数字说话。本脚本用**同一套标定参数**
把每张图的棋盘位姿解出来，于是每张图的**距离**和**倾斜角**都成了可核查的数字，
配合九宫格覆盖与清晰度，一次把这三条都验完。

判据（可用命令行参数放宽/收紧）
-------------------------------
  有效图数    ≥ CALIB_MIN_COUNT（config，默认 8）
  九宫格覆盖  ≥ 8/9（9/9 最好）
  距离跨度    最远 ÷ 最近 ≥ 1.3（说明远近有变化）
  最大倾斜角  ≥ 25°（说明倾斜方向/角度有变化）
  最低清晰度  ≥ 60（Laplacian 方差，低于此值偏糊，角点定位会漂）

用法
----
  python tools/check_calib_quality.py                       # 用 config 的目录与参数
  python tools/check_calib_quality.py --images <目录>
  python tools/check_calib_quality.py --params <json> --json /tmp/quality.json

退出码：0 = 全部达标；1 = 有项目不达标；2 = 前置条件缺失（没有参数文件 / 没有标定图）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                            # noqa: E402
from src.calibration import BoardSpec, find_corners, load_params   # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_PRECOND = 0, 1, 2


def euler_tilt_deg(R: np.ndarray) -> float:
    """棋盘平面法线与相机光轴的夹角（0° = 正对相机）。用绝对值，避免法线朝向符号影响结果。"""
    n = R[:, 2] / (np.linalg.norm(R[:, 2]) + 1e-12)
    c = float(np.clip(abs(n[2]), 0.0, 1.0))
    return float(np.degrees(np.arccos(c)))


def region_of(cx_px: float, cy_px: float, w: int, h: int) -> str:
    """把图像中心点归到 3x3 九宫格里。"""
    col = "左" if cx_px < w / 3 else ("中" if cx_px < 2 * w / 3 else "右")
    row = "上" if cy_px < h / 3 else ("中" if cy_px < 2 * h / 3 else "下")
    return row + col


def main() -> int:
    ap = argparse.ArgumentParser(description="标定采集质量体检")
    ap.add_argument("--images", default=str(config.CALIB_IMAGES), help="标定图目录")
    ap.add_argument("--params", default=str(config.CALIB_PARAMS), help="标定参数 JSON")
    ap.add_argument("--min-span", type=float, default=1.3, help="距离跨度下限（最远/最近）")
    ap.add_argument("--min-tilt", type=float, default=25.0, help="最大倾斜角下限（度）")
    ap.add_argument("--min-sharp", type=float, default=60.0, help="最低清晰度下限")
    ap.add_argument("--json", default="", help="把报告另存为 JSON")
    a = ap.parse_args()

    try:
        par = load_params(a.params)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        return EXIT_PRECOND

    d = par.raw
    board = d.get("board", {})
    spec = BoardSpec(int(board.get("inner_cols", config.BOARD_INNER_COLS)),
                     int(board.get("inner_rows", config.BOARD_INNER_ROWS)),
                     float(board.get("square_mm", config.BOARD_SQUARE_MM)))
    files = sorted(Path(a.images).glob("*.png")) + sorted(Path(a.images).glob("*.jpg"))
    if not files:
        print(f"[错误] 标定图目录里没有图片：{a.images}")
        return EXIT_PRECOND

    # 棋盘格的物体点：与 src/calibration.py 生成标定用点的方式保持一致
    objp = np.zeros((spec.inner_rows * spec.inner_cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:spec.inner_cols, 0:spec.inner_rows].T.reshape(-1, 2) * spec.square_mm

    print(f"标定参数 {a.params}：{par.width}x{par.height}，RMS {par.rms:.4f} px，"
          f"方格 {spec.square_mm} mm，内角点 {spec.inner_cols}x{spec.inner_rows}")
    print(f"标定图 {len(files)} 张于 {a.images}\n")
    print(f"{'文件':<16}{'位置':<6}{'棋盘宽px':>9}{'占比':>7}{'距离mm':>9}{'倾角°':>8}{'清晰度':>8}")

    rows, skipped = [], []
    for p in files:
        gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            skipped.append((p.name, "读不出图"))
            continue
        h, w = gray.shape
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        ok_cb, corners = find_corners(gray, spec)
        if not ok_cb or corners is None:
            skipped.append((p.name, "检不到角点"))
            print(f"{p.name:<16}{'—':<6}{'—':>9}{'—':>7}{'—':>9}{'—':>8}{sharp:>8.0f}   ← 检不到角点")
            continue
        ok, rvec, tvec = cv2.solvePnP(objp, corners, par.K, par.D)
        R, _ = cv2.Rodrigues(rvec)
        dist_mm = float(np.linalg.norm(tvec))
        tilt = euler_tilt_deg(R)
        pts = corners.reshape(-1, 2)
        bw = float(pts[:, 0].max() - pts[:, 0].min())
        cxy = pts.mean(axis=0)
        reg = region_of(cxy[0], cxy[1], w, h)
        rows.append(dict(file=p.name, region=reg, board_px=bw, ratio=bw / w,
                         distance_mm=dist_mm, tilt_deg=tilt, sharpness=sharp,
                         ok_pnp=bool(ok)))
        print(f"{p.name:<16}{reg:<6}{bw:>9.0f}{bw/w*100:>6.0f}%{dist_mm:>9.0f}{tilt:>8.1f}{sharp:>8.0f}")

    if not rows:
        print("\n[错误] 一张都没解出来，无法评估。")
        return EXIT_PRECOND

    dists = [r["distance_mm"] for r in rows]
    tilts = [r["tilt_deg"] for r in rows]
    sharps = [r["sharpness"] for r in rows]
    cover = {r["region"] for r in rows}
    span = max(dists) / max(min(dists), 1e-6)

    checks = [
        ("有效标定图 ≥ 最少张数", len(rows) >= config.CALIB_MIN_COUNT,
         f"{len(rows)} 张（>= {config.CALIB_MIN_COUNT}）"),
        ("九宫格覆盖 ≥ 8/9", len(cover) >= 8, f"{len(cover)}/9 个区域：{''.join(sorted(cover))}"),
        ("距离跨度 ≥ %.2f" % a.min_span, span >= a.min_span,
         f"最近 {min(dists):.0f} mm → 最远 {max(dists):.0f} mm，跨度 {span:.2f}"),
        ("最大倾斜角 ≥ %.0f°" % a.min_tilt, max(tilts) >= a.min_tilt,
         f"倾斜 {min(tilts):.1f}° ~ {max(tilts):.1f}°（正对 ~0°，越大越斜）"),
        ("最低清晰度 ≥ %.0f" % a.min_sharp, min(sharps) >= a.min_sharp,
         f"清晰度 {min(sharps):.0f} ~ {max(sharps):.0f}"),
    ]
    if skipped:
        checks.append(("全部图都能解出角点", False,
                       "失败：" + "、".join(f"{n}({r})" for n, r in skipped)))

    print("\n=== 逐条判据 ===")
    for name, ok, detail in checks:
        print(f"  [{'通过' if ok else '不通过'}] {name}：{detail}")

    bad = [c for c in checks if not c[1]]
    print("\n" + ("[通过] 标定采集满足评分项对“位置、距离、倾斜有变化”的要求 ✅"
                  if not bad else f"[不通过] {len(bad)} 条未达标，见上"))
    if a.json:
        Path(a.json).write_text(json.dumps(
            dict(params=a.params, images=a.images, board=vars(spec), per_image=rows,
                 skipped=skipped, summary=dict(n=len(rows), regions=sorted(cover),
                 distance_mm=[min(dists), max(dists)], tilt_deg=[min(tilts), max(tilts)],
                 sharpness=[min(sharps), max(sharps)],
                 checks=[dict(name=n, ok=o, detail=t) for n, o, t in checks])),
            ensure_ascii=False, indent=2))
        print(f"[信息] 报告已写入 {a.json}")
    return EXIT_OK if not bad else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
