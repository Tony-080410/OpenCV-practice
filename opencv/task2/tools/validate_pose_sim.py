"""位姿链路回归测试，不用相机不用打印。

用 src/simulate.py 渲染出已知 R、t、已知畸变的画面，交给正式代码路径
（src/tag_detect.py + src/pose.py + src/undistort.py）解算，跟真值比。

三条路径：
  A 原图 + 畸变系数直接解算
  B 去畸变（不裁剪、内参不变）+ dist=0 解算     <- 正式方案
  C 内参误用半分辨率（故意做错，验证内参必须跟画面成对）

运行：python tools/validate_pose_sim.py
退出码非 0 说明 A/B 两条路径误差超阈值（阈值见 MAX_ERR_MM / MAX_ERR_DEG）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                    # noqa: E402
from src import simulate                          # noqa: E402
from src import pose as pose_mod                  # noqa: E402
from src.tag_detect import TagDetector            # noqa: E402
from src.target import select_target              # noqa: E402

MAX_ERR_MM = 15.0          # 平移误差阈值（毫米）
MAX_ERR_DEG = 3.0          # 旋转误差阈值（度）
W, H = 1280, 960
DIST = np.array([-0.28, 0.11, 0.001, -0.002, 0.0])     # 典型桶形畸变

# main() 返回时局部变量会被释放，实测 OpenCV 5.0.x + apriltag 在这一步会随机段错误。
# 把重对象挂到模块级引用上活到 os._exit，避开那段清理。
_KEEP_ALIVE: list = []


def rotation_error(R_est: np.ndarray, R_true: np.ndarray) -> float:
    cos = np.clip((np.trace(R_est.T @ R_true) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.rad2deg(np.arccos(cos)))


def half_resolution_K(K: np.ndarray) -> np.ndarray:
    """故意做错的内参：按半分辨率缩放（用来验证"内参必须与画面成对"）。"""
    wrong = K.copy()
    wrong[0, 0] /= 2; wrong[1, 1] /= 2; wrong[0, 2] /= 2; wrong[1, 2] /= 2
    return wrong


def main() -> int:
    tex_path = config.TAG_PATTERN
    try:
        tex = simulate.load_official_texture(tex_path)
    except ValueError as e:
        print(f"[错误] {e}（python tools/make_patterns.py 可重新获取图案）")
        return 1
    side_m = config.TAG_EDGE_MM / 1000.0
    K = simulate.default_intrinsics(W, H)
    det = TagDetector()
    _KEEP_ALIVE.extend([tex, K, det])

    print(f"OpenCV {cv2.__version__} / 图案 {tex_path.name} / 边长 {config.TAG_EDGE_MM:.1f} mm")
    print(f"阈值：平移 < {MAX_ERR_MM} mm，旋转 < {MAX_ERR_DEG}°")
    print("-" * 96)
    print(f"{'场景':<12}{'路径':<14}{'解出 t (m)':<34}{'平移误差':>10}{'旋转误差':>10}")

    failures = []
    for name, ax, ay, az, tx, ty, tz in simulate.CASES:
        R_t, t_t = simulate.truth_pose(ax, ay, az, tx, ty, tz)
        # 渲染是这里最贵的一步（约 240 ms/次），只依赖场景，与路径无关，所以每个场景只渲染一次
        raw = simulate.render(R_t, t_t, K, DIST, W, H, tex, side_m)
        variants = {
            "A 原图+dist": (raw, K, DIST),
            "B 去畸变": (cv2.undistort(raw, K, DIST), K, np.zeros(5)),
            "C 错误内参": (raw, half_resolution_K(K), DIST),
        }
        for path, (img, K_use, D_use) in variants.items():
            target = select_target(det.detect(img), config.TARGET_ID)
            if target is None:
                print(f"{name:<12}{path:<14}未检出")
                failures.append(f"{name} / {path} 未检出")
                continue
            res = pose_mod.solve(target.corners, K_use, D_use, side_m)
            if not res.ok:
                print(f"{name:<12}{path:<14}解算失败")
                failures.append(f"{name} / {path} 解算失败")
                continue
            e_t = float(np.linalg.norm(res.t - t_t) * 1000.0)
            e_r = rotation_error(res.R, R_t)
            cell = np.array2string(res.t, precision=4, floatmode="fixed")
            print(f"{name:<12}{path:<14}{cell:<34}{e_t:8.2f}mm{e_r:8.3f}°")

            if path.startswith(("A", "B")) and (e_t > MAX_ERR_MM or e_r > MAX_ERR_DEG):
                failures.append(f"{name} / {path} 误差超阈值：{e_t:.2f}mm {e_r:.3f}°")
            if path.startswith("C") and e_t < 50.0:
                failures.append(f"{name} / C 本应因内参错配而明显偏差，实测仅 {e_t:.2f}mm")

    print("-" * 96)
    if failures:
        print("[失败] 以下检查未通过：")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("[通过] 路径 A/B 均在阈值内；路径 C 如预期出现数百毫米偏差（说明内参必须与画面成对）")
    return 0


if __name__ == "__main__":
    code = main()
    # 解释器退出阶段 OpenCV 5.0.x + apriltag 会段错误（实测 exit 139），与检查结果无关。
    # 用 os._exit 带退出码直接退出，跳过会崩的清理，脚本才能当回归测试用（退出码 0/1 可信）。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
