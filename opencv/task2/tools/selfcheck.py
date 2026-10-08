"""任务二自检：把评分项里要留痕的东西算成可复现的数字（对应 README 第 14 节）。

    python tools/selfcheck.py calib     # 标定采集：逐图位置/棋盘像素宽/距离/倾角/清晰度 + 判据
    python tools/selfcheck.py demo      # 演示 dump：距离/倾角范围、有效帧比例、异常原因分布

两条都用 R 第三列（平面法线）跟相机光轴的夹角来量化角度变化：calib 用标定参数解出每张
棋盘图的位姿，demo 用 dump 里每帧的 R 算 Tag 倾角。都支持 --json <路径> 导报告。
退出码：0 全达标，1 有判据不达标，2 前置条件缺失。
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


# ---------- 共用 ----------

def normal_tilt_deg(R) -> float:
    """平面法线（R 第三列）与相机光轴的夹角，0° = 正对。取绝对值，免去法线朝向的正负歧义。"""
    R = np.asarray(R, float)
    n = R[:, 2] / (np.linalg.norm(R[:, 2]) + 1e-12)
    return float(np.degrees(np.arccos(float(np.clip(abs(n[2]), 0.0, 1.0)))))


def finite(a) -> np.ndarray:
    v = np.asarray(a, float)
    return v[np.isfinite(v)]


def report_ranges(series: dict) -> dict:
    """打印 最小/最大/跨度 表，返回 {量: [最小, 最大]}。"""
    print(f"\n{'量':<18}{'最小':>9}{'最大':>9}{'跨度':>9}")
    out = {}
    for name, vals in series.items():
        v = finite(vals)
        if not v.size:
            continue
        out[name] = [float(v.min()), float(v.max())]
        print(f"{name:<18}{v.min():>9.1f}{v.max():>9.1f}{v.max()-v.min():>9.1f}")
    return out


def dump_json(path: str, payload: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"[信息] 报告已写入 {path}")


def verdict(checks: list, pass_msg: str) -> int:
    print("\n=== 逐条判据 ===")
    for name, ok, detail in checks:
        print(f"  [{'通过' if ok else '不通过'}] {name}：{detail}")
    bad = [c for c in checks if not c[1]]
    print("\n" + (f"[通过] {pass_msg}" if not bad else f"[不通过] {len(bad)} 条未达标，见上"))
    return EXIT_OK if not bad else EXIT_FAIL


# ---------- 子命令 1：标定采集 ----------

def region_of(cx: float, cy: float, w: int, h: int) -> str:
    col = "左" if cx < w / 3 else ("中" if cx < 2 * w / 3 else "右")
    row = "上" if cy < h / 3 else ("中" if cy < 2 * h / 3 else "下")
    return row + col


def cmd_calib(a) -> int:
    try:
        par = load_params(a.params)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        return EXIT_PRECOND
    b = par.raw.get("board", {})
    spec = BoardSpec(int(b.get("inner_cols", config.BOARD_INNER_COLS)),
                     int(b.get("inner_rows", config.BOARD_INNER_ROWS)),
                     float(b.get("square_mm", config.BOARD_SQUARE_MM)))
    files = sorted(Path(a.images).glob("*.png")) + sorted(Path(a.images).glob("*.jpg"))
    if not files:
        print(f"[错误] 标定图目录里没有图片：{a.images}")
        return EXIT_PRECOND

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
        _, rvec, tvec = cv2.solvePnP(objp, corners, par.K, par.D)
        R, _ = cv2.Rodrigues(rvec)
        pts = corners.reshape(-1, 2)
        bw = float(pts[:, 0].max() - pts[:, 0].min())
        cxy = pts.mean(axis=0)
        reg = region_of(cxy[0], cxy[1], w, h)
        rows.append(dict(file=p.name, region=reg, board_px=bw, ratio=bw / w,
                         distance_mm=float(np.linalg.norm(tvec)),
                         tilt_deg=normal_tilt_deg(R), sharpness=sharp))
        r = rows[-1]
        print(f"{p.name:<16}{reg:<6}{bw:>9.0f}{bw/w*100:>6.0f}%{r['distance_mm']:>9.0f}"
              f"{r['tilt_deg']:>8.1f}{sharp:>8.0f}")

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
        (f"距离跨度 ≥ {a.min_span:.2f}", span >= a.min_span,
         f"最近 {min(dists):.0f} → 最远 {max(dists):.0f} mm，跨度 {span:.2f}"),
        (f"最大倾斜角 ≥ {a.min_tilt:.0f}°", max(tilts) >= a.min_tilt,
         f"倾斜 {min(tilts):.1f}° ~ {max(tilts):.1f}°"),
        (f"最低清晰度 ≥ {a.min_sharp:.0f}", min(sharps) >= a.min_sharp,
         f"清晰度 {min(sharps):.0f} ~ {max(sharps):.0f}"),
    ]
    if skipped:
        checks.append(("全部图都能解出角点", False,
                       "失败：" + "、".join(f"{n}({r})" for n, r in skipped)))
    code = verdict(checks, "标定采集满足评分项对\u201c位置、距离、倾斜有变化\u201d的要求")
    dump_json(a.json, dict(images=a.images, params=a.params, board=vars(spec), per_image=rows,
                           skipped=skipped, summary=dict(n=len(rows), regions=sorted(cover),
                           distance_mm=[min(dists), max(dists)], tilt_deg=[min(tilts), max(tilts)],
                           sharpness=[min(sharps), max(sharps)],
                           checks=[dict(name=n, ok=o, detail=t) for n, o, t in checks])))
    return code


# ---------- 子命令 2：演示 dump ----------

def cmd_demo(a) -> int:
    p = Path(a.dump)
    if not p.exists():
        print(f"[错误] 没有 dump 文件：{p}（用 python main.py demo --dump {p} 生成）")
        return EXIT_PRECOND
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        print(f"[错误] {p} 是空的")
        return EXIT_PRECOND
    valid = [r for r in rows if r.get("valid") and "R" in r]
    span_s = (rows[-1]["t_ms"] - rows[0]["t_ms"]) / 1000.0 if len(rows) > 1 else 0.0
    print(f"{p}：{len(rows)} 帧 / {span_s:.1f} s（约 {len(rows)/span_s:.1f} 帧/s）；"
          f"valid {len(valid)} 帧（{len(valid)/len(rows)*100:.1f}%）")

    ranges = {}
    if valid:
        ranges = report_ranges({
            "Z 深度(mm)": [r["z_mm"] for r in valid],
            "X(mm)": [r["x_mm"] for r in valid],
            "Y(mm)": [r["y_mm"] for r in valid],
            "直线距离|t|(mm)": [r.get("distance_mm", 0.0) for r in valid],
            "Tag 倾角(°)": [normal_tilt_deg(r["R"]) for r in valid],
            "重投影残差(px)": [r.get("reproj_error_px", float("nan")) for r in valid],
        })
        runs, cur = [], 0
        for r in rows:
            if r.get("valid"):
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0
        if cur:
            runs.append(cur)
        print(f"\n有效帧连续段（帧数）：{runs}")
    else:
        runs = []

    reasons: dict = {}
    for r in rows:
        if not r.get("valid"):
            k = r.get("reason", "?")
            reasons[k] = reasons.get(k, 0) + 1
    if reasons:
        print("\n无效帧的原因分布：")
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {v:>4} 帧  {k}")

    dump_json(a.json, dict(dump=str(p), frames=len(rows), span_s=span_s, valid=len(valid),
                           ranges=ranges, valid_runs=runs, reasons=reasons))
    return EXIT_OK


# ---------- 入口 ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="任务二自检（标定采集 / 演示）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calib", help="标定采集体检")
    c.add_argument("--images", default=str(config.CALIB_IMAGES))
    c.add_argument("--params", default=str(config.CALIB_PARAMS))
    c.add_argument("--min-span", type=float, default=1.3, help="距离跨度下限（最远/最近）")
    c.add_argument("--min-tilt", type=float, default=25.0, help="最大倾斜角下限（度）")
    c.add_argument("--min-sharp", type=float, default=60.0, help="最低清晰度下限")
    c.add_argument("--json", default="")
    c.set_defaults(func=cmd_calib)

    d = sub.add_parser("demo", help="演示 dump 汇总")
    d.add_argument("--dump", default="outputs/logs/pose.jsonl")
    d.add_argument("--json", default="")
    d.set_defaults(func=cmd_demo)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
