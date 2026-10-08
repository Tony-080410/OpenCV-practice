"""采集标定图：实时预览 + 覆盖率提示 + 存图。

用法（在 task2 目录下）：
    python tools/capture_calib.py                 # 交互：SPACE 存图，q/ESC 退出
    python tools/capture_calib.py --auto 20 --interval 1.2   # 自动连拍（可配 --no-show 无窗口）
    python tools/capture_calib.py --camera 0 --width 1280 --height 720

要点（对应评分项“标定采集”）：
  * 图片分辨率必须一致，且与后面检测时的分辨率相同，否则内参不能共用；
  * 覆盖画面中部与四角、改变距离与倾斜方向 —— 界面上的 3x3 覆盖图会实时提示；
  * 角点必须完整可见（别让棋盘格出画），存图时会立刻校验并提示“未找到角点”。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                  # noqa: E402
from src.calibration import BoardSpec, find_corners   # noqa: E402
from src.camera import Camera, CameraError     # noqa: E402


class Coverage:
    """3x3 覆盖统计：记录哪些区域出现过完整的棋盘格。"""

    def __init__(self, grid: int = config.COVERAGE_GRID):
        self.grid = grid
        self.hits = np.zeros((grid, grid), dtype=int)

    def update(self, corners: np.ndarray, width: int, height: int) -> None:
        if corners is None:
            return
        c = corners.reshape(-1, 2)
        cx, cy = c[:, 0].mean(), c[:, 1].mean()
        gx = min(int(cx / width * self.grid), self.grid - 1)
        gy = min(int(cy / height * self.grid), self.grid - 1)
        self.hits[gy, gx] += 1

    @property
    def covered(self) -> int:
        return int((self.hits > 0).sum())

    def draw(self, img: np.ndarray) -> None:
        h, w = img.shape[:2]
        for gy in range(self.grid):
            for gx in range(self.grid):
                x0, y0 = int(gx * w / self.grid), int(gy * h / self.grid)
                x1, y1 = int((gx + 1) * w / self.grid), int((gy + 1) * h / self.grid)
                color = (0, 180, 0) if self.hits[gy, gx] else (80, 80, 80)
                cv2.rectangle(img, (x0, y0), (x1, y1), color, 1)
                cv2.putText(img, str(self.hits[gy, gx]), (x0 + 6, y0 + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)

    def hint(self) -> str:
        if self.covered >= self.grid * self.grid:
            return "覆盖已满，可以收工"
        return f"已覆盖 {self.covered}/{self.grid * self.grid} 个区域，继续换位置/距离/倾斜"


def save_frame(frame: np.ndarray, corners, outdir: Path, coverage: Coverage,
               index: int) -> bool:
    """存图。corners 是调用方（预览循环）已经算出的角点，这里不重复检测。

    ★ 存下去的必须是**没有任何标记的原始帧**：角点标记会盖住黑白边界，
    之后 `main.py calib` 就再也检测不到角点 —— 实测把标记画进保存的图里，
    16/16 张全部失效、有效图 0 张、标定直接失败。
    所以标记只画在预览用的 `view`（frame 的副本）上，见下面的预览循环。
    """
    ok = corners is not None
    if ok:
        coverage.update(corners, frame.shape[1], frame.shape[0])
    path = outdir / f"calib_{index:03d}.png"
    saved = cv2.imwrite(str(path), frame)
    print(f"[存图] {path.name}  角点{'找到' if ok else '未找到（这张大概率会被标定跳过，建议重拍）'}"
          f"{'' if saved else '  ⚠ 写盘失败'}"
          f"  {coverage.hint()}")
    return bool(ok and saved)


def main() -> int:
    ap = argparse.ArgumentParser(description="采集标定图")
    ap.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    ap.add_argument("--width", type=int, default=config.CAMERA_WIDTH)
    ap.add_argument("--height", type=int, default=config.CAMERA_HEIGHT)
    ap.add_argument("--auto", type=int, default=0, help="自动连拍张数，0 表示手动按键")
    ap.add_argument("--interval", type=float, default=1.2, help="自动连拍间隔（秒）")
    ap.add_argument("--inner-cols", type=int, default=config.BOARD_INNER_COLS)
    ap.add_argument("--inner-rows", type=int, default=config.BOARD_INNER_ROWS)
    ap.add_argument("--square-mm", type=float, default=config.BOARD_SQUARE_MM)
    ap.add_argument("--outdir", default=str(config.CALIB_IMAGES))
    ap.add_argument("--no-show", dest="show", action="store_false",
                    help="不开窗口（配合 --auto 做无界面采集；默认开窗口，SPACE 存图要开窗口）")
    a = ap.parse_args()

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    spec = BoardSpec(a.inner_cols, a.inner_rows, a.square_mm)
    coverage = Coverage()
    existing = sorted(outdir.glob("calib_*.png"))
    index = len(existing)

    print(f"[信息] 标定板 {spec.inner_cols}x{spec.inner_rows} 内角点，方格 {spec.square_mm:.2f} mm")
    print(f"[信息] 输出目录 {outdir}（已有 {index} 张）")
    try:
        cam = Camera(a.camera, a.width, a.height)
        info = cam.open()
    except CameraError as e:
        print(f"[错误] {e}")
        return 1
    print(f"[信息] {info.describe()}")
    print(f"[提示] {'自动连拍 ' + str(a.auto) + ' 张' if a.auto else 'SPACE 存图，q/ESC 退出'}"
          f"；目标 {config.CALIB_TARGET_COUNT} 张，至少 {config.CALIB_MIN_COUNT} 张")

    saved = good = 0
    last_auto = time.monotonic()
    try:
        while True:
            ok, frame = cam.read()
            if not ok or frame is None:
                print("[信息] 取帧失败，收尾。")
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            view = frame.copy()
            ok_cb, corners = find_corners(gray, spec)
            if ok_cb:
                cv2.drawChessboardCorners(view, spec.pattern_size, corners, True)
            coverage.draw(view)
            cv2.putText(view, f"saved {saved}  board {'OK' if ok_cb else 'not found'}",
                        (12, view.shape[0] - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 255, 0) if ok_cb else (0, 0, 255), 2, cv2.LINE_AA)

            if a.show:
                cv2.imshow("capture calib (SPACE 存图 / q 退出)", view)

            do_save = False
            if a.auto:
                if time.monotonic() - last_auto >= a.interval and saved < a.auto:
                    do_save = True
                    last_auto = time.monotonic()
                if saved >= a.auto:
                    print(f"[信息] 自动连拍完成 {saved} 张。")
                    break
            else:
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                do_save = key == ord(" ")

            if do_save:
                # 存原始帧（不存画了提示的 view）：标记会污染标定图，见 save_frame 的说明。
                # 直接复用预览循环里已经算出的角点，不再重复检测一次
                if save_frame(frame.copy(), corners if ok_cb else None,
                              outdir, coverage, index):
                    good += 1
                saved += 1
                index += 1
    except KeyboardInterrupt:
        print("\n[信息] 手动中断。")
    finally:
        if a.show:
            cv2.destroyAllWindows()
        cam.close()

    print(f"[完成] 本次保存 {saved} 张（其中角点可用的 {good} 张），目录共 "
          f"{len(list(outdir.glob('calib_*.png')))} 张")
    print(f"[完成] {coverage.hint()}")
    print("[下一步] python main.py calib")
    return 0


if __name__ == "__main__":
    sys.exit(main())
