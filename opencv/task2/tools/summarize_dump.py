"""把 `demo --dump` 出来的逐帧位姿 JSONL 汇总成一张表：距离/角度变化、有效帧统计、异常原因。

为什么需要它
------------
「检测演示 2 分」的给分细则是"距离与角度有所变化""能观察到检测和位姿输出随之变化"。
视频本身能看，但**变化幅度是个可量化的东西** —— 本脚本从 dump 里把
Z 深度、X/Y、直线距离、Tag 倾角（由 R 的第三列与光轴夹角算出）的范围统计出来，
把"有变化"变成数字；顺便统计有效帧比例与各种异常原因，对应「目标选择与异常处理 3 分」。

用法
----
  python tools/summarize_dump.py                          # 默认 outputs/logs/pose.jsonl
  python tools/summarize_dump.py --dump <路径> [--json <报告>]

退出码：0 = 统计成功；2 = 文件不存在或没有可用帧。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                            # noqa: E402

EXIT_OK, EXIT_PRECOND = 0, 2


def tilt_deg(R) -> float:
    """Tag 平面法线（R 第三列）与相机光轴的夹角：0° 正对，越大越斜。"""
    R = np.asarray(R, float)
    n = R[:, 2] / (np.linalg.norm(R[:, 2]) + 1e-12)
    return float(np.degrees(np.arccos(float(np.clip(abs(n[2]), 0.0, 1.0)))))


def main() -> int:
    ap = argparse.ArgumentParser(description="演示 dump 汇总")
    ap.add_argument("--dump", default="outputs/logs/pose.jsonl")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    p = Path(a.dump)
    if not p.exists():
        print(f"[错误] 没有 dump 文件：{p}（用 python main.py demo --dump {p} 生成）")
        return EXIT_PRECOND
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    valid = [r for r in rows if r.get("valid") and "R" in r]
    if not rows:
        print(f"[错误] {p} 是空的")
        return EXIT_PRECOND

    span_s = (rows[-1]["t_ms"] - rows[0]["t_ms"]) / 1000.0 if len(rows) > 1 else 0.0
    print(f"{p}：{len(rows)} 帧 / {span_s:.1f} s"
          f"（约 {len(rows)/span_s:.1f} 帧/s）；valid {len(valid)} 帧"
          f"（{len(valid)/len(rows)*100:.1f}%）")

    stats = {}
    runs: list[int] = []
    if valid:
        series = {
            "Z 深度(mm)": [r["z_mm"] for r in valid],
            "X(mm)": [r["x_mm"] for r in valid],
            "Y(mm)": [r["y_mm"] for r in valid],
            "直线距离|t|(mm)": [r.get("distance_mm", r["distance_mm"] if "distance_mm" in r else 0.0)
                                for r in valid],
            "Tag 倾角(°)": [tilt_deg(r["R"]) for r in valid],
            "重投影残差(px)": [r.get("reproj_error_px", float("nan")) for r in valid],
        }
        print(f"\n{'量':<18}{'最小':>9}{'最大':>9}{'跨度':>9}")
        for name, vals in series.items():
            v = np.asarray(vals, float)
            v = v[np.isfinite(v)]
            if not v.size:
                continue
            stats[name] = [float(v.min()), float(v.max())]
            print(f"{name:<18}{v.min():>9.1f}{v.max():>9.1f}{v.max()-v.min():>9.1f}")

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

    reasons: dict[str, int] = {}
    for r in rows:
        if not r.get("valid"):
            reasons[r.get("reason", "?")] = reasons.get(r.get("reason", "?"), 0) + 1
    if reasons:
        print("\n无效帧的原因分布：")
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {v:>4} 帧  {k}")

    if a.json:
        Path(a.json).write_text(json.dumps(
            dict(dump=str(p), frames=len(rows), span_s=span_s, valid=len(valid),
                 ranges=stats, valid_runs=(runs if valid else []), reasons=reasons),
            ensure_ascii=False, indent=2))
        print(f"\n[信息] 报告已写入 {a.json}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
