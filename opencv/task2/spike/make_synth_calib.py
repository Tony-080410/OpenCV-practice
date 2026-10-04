"""合成一组"不同视角"的棋盘格图，用来在没打印的情况下验证主程序 calib 的落盘路径。

做法：取已生成的棋盘格页 PNG，施加随机单应（平移/旋转/缩放/透视），
存成一叠图。它验证的是 CLI -> 角点检测 -> calibrateCamera -> save_params 这条链路
和输出文件位置，不代表真实相机的标定质量。
"""
import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402

SRC = config.ASSETS / "patterns" / "chessboard_9x6_20mm.png"
OUT = pathlib.Path("/tmp/vfix/board")
N = 12


def main() -> int:
    page = cv2.imread(str(SRC), cv2.IMREAD_GRAYSCALE)
    if page is None:
        print(f"[错误] 缺少 {SRC}")
        return 1
    h, w = page.shape
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    made = 0
    for i in range(N):
        # 画布比棋盘格页大一圈，方便制造"棋盘格不在画面正中"的样本
        canvas = np.full((int(h * 1.15), int(w * 1.15)), 255, np.uint8)
        ang, scale = rng.uniform(-12, 12), rng.uniform(0.72, 0.95)
        tx, ty = rng.uniform(0.03, 0.12) * w, rng.uniform(0.03, 0.12) * h
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, scale)
        M[0, 2] += tx
        M[1, 2] += ty
        warped = cv2.warpAffine(page, M, (canvas.shape[1], canvas.shape[0]),
                                borderValue=255)
        # 再叠一点透视，避免所有样本都共面同解
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        j = 0.02 * min(w, h)
        dst = src + rng.uniform(-j, j, src.shape).astype(np.float32)
        H = cv2.getPerspectiveTransform(src, dst)
        view = cv2.warpPerspective(warped, H, (canvas.shape[1], canvas.shape[0]),
                                   borderValue=255)
        cv2.imwrite(str(OUT / f"synth_{i:03d}.png"), view)
        made += 1
    print(f"[完成] 合成 {made} 张 -> {OUT}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os
    os._exit(code)
