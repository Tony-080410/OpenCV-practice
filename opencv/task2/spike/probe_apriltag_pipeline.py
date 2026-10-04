"""任务二 可行性验证脚本（不需要相机、不需要打印）

用途：在动手写正式代码前，把两件最容易出错的事钉死——
  1. pupil_apriltags 返回的角点顺序，对应 tag 局部坐标系的哪四个点；
  2. 位姿解算链路（含畸变）在已知真值下的实际误差。

做法：用**官方** tag36h11 ID 0 图案（assets/patterns/tag36h11_00000_official.png）当纹理，
用逐像素反向光线求交渲染出“已知 R、t、已知畸变”的仿真相机画面，再走完整的
检测 + 解算流程，把解出的 R、t 与真值比对。

注意：官方图案与 OpenCV aruco 生成器画出来的同 ID 图案相差 180°，
所以打印素材与角点说明都必须以官方图案为准，本脚本因此改用官方纹理。

运行：python spike/probe_apriltag_pipeline.py
"""
import pathlib
import time

import cv2
import numpy as np
from pupil_apriltags import Detector

FAMILY = "tag36h11"
SIDE_M = 0.100              # 黑框外边实际边长（米），打印后实测值才是参数
SP = 800                    # 纹理像素（黑框外边）
W, H = 1280, 960
K = np.array([[900.0, 0, W / 2], [0, 900.0, H / 2], [0, 0, 1]])
DIST = np.array([-0.28, 0.11, 0.001, -0.002, 0.0])      # 典型桶形畸变
OFFICIAL = pathlib.Path(__file__).resolve().parent.parent / \
    "assets/patterns/tag36h11_00000_official.png"

# tag 系：原点在 tag 中心，x 右、y 下、z 垂直纸面指向相机（与相机光学系同向）
# “上下左右”指打印出来的 tag 正着看（方向标记那条边朝上）时的方向。
# 顺序由第 2 节扫描得出：corners[0..3] 依次对应下列 tag 系坐标。
# 即：以左下角为起点、逆时针排列，与 AprilTag 官方文档对角点次序的说明一致。
OBJP = np.array([[-SIDE_M / 2,  SIDE_M / 2, 0.0],      # 0 左下
                 [ SIDE_M / 2,  SIDE_M / 2, 0.0],      # 1 右下
                 [ SIDE_M / 2, -SIDE_M / 2, 0.0],      # 2 右上
                 [-SIDE_M / 2, -SIDE_M / 2, 0.0]])     # 3 左上


def load_official_texture():
    """取官方图案的黑框外边部分（10x10 单元里的第 1..8 行/列），放大到 SP x SP。"""
    png = cv2.imread(str(OFFICIAL), cv2.IMREAD_GRAYSCALE)
    assert png is not None and png.shape == (10, 10), f"官方图案异常: {png.shape}"
    core = png[1:9, 1:9]                                    # 8x8 = 黑框外边
    s = SP // 8
    return np.kron(core, np.ones((s, s), np.uint8))


def render(R, t, K, dist, w, h, tex, side):
    """反向光线求交：每个像素按畸变模型求出真实光线，与 tag 平面求交后取纹理。"""
    u, v = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
    pts = np.stack([u.ravel(), v.ravel()], 1).reshape(-1, 1, 2)
    norm = cv2.undistortPoints(pts, K, dist if np.any(dist) else None).reshape(-1, 2)
    d = np.concatenate([norm, np.ones((len(norm), 1))], 1)
    A = np.stack([np.broadcast_to(R[:, 0], d.shape),
                  np.broadcast_to(R[:, 1], d.shape), -d], 2)
    sol = np.linalg.solve(A, np.broadcast_to((-t).reshape(1, 3, 1), (len(d), 3, 1)))[:, :, 0]
    x, y, s = sol[:, 0], sol[:, 1], sol[:, 2]
    hit = (s > 0) & (np.abs(x) <= side / 2) & (np.abs(y) <= side / 2)
    mx = np.clip(((x / side + 0.5) * SP).astype(int), 0, SP - 1)
    my = np.clip(((y / side + 0.5) * SP).astype(int), 0, SP - 1)
    out = np.full(len(d), 255.0)
    out[hit] = tex[my[hit], mx[hit]]
    return out.reshape(h, w).astype(np.uint8)


def truth(ax, ay, az, tx, ty, tz):
    R, _ = cv2.Rodrigues(np.array([np.deg2rad(ax), np.deg2rad(ay), np.deg2rad(az)]))
    return R, np.array([tx, ty, tz], float)


def pose_error(R_est, t_est, R_t, t_t):
    ang = np.rad2deg(np.arccos(np.clip((np.trace(R_est.T @ R_t) - 1) / 2, -1, 1)))
    return np.linalg.norm(t_est - t_t) * 1000, ang


def scan_convention(det, tex, poses):
    """扫 8 种 objp 配对，取在全部位姿上都对的唯一解。"""
    base = [(-SIDE_M / 2, -SIDE_M / 2, 0.0), (SIDE_M / 2, -SIDE_M / 2, 0.0),
            (SIDE_M / 2, SIDE_M / 2, 0.0), (-SIDE_M / 2, SIDE_M / 2, 0.0)]  # 左上起顺时针
    print(f"   {'配对':>10s} | " + " | ".join(f"{p[0]:>16s}" for p in poses))
    for rev in (False, True):
        seq = base[::-1] if rev else base
        for k in range(4):
            op = np.array(seq[k:] + seq[:k])
            cells = []
            ok = True
            for name, ax, ay, az, tx, ty, tz in poses:
                R_t, t_t = truth(ax, ay, az, tx, ty, tz)
                img = render(R_t, t_t, K, np.zeros(5), W, H, tex, SIDE_M)
                res = det.detect(img)
                if not res:
                    cells.append("未检出")
                    ok = False
                    continue
                c = np.asarray(res[0].corners, np.float64)
                _, rv, tv = cv2.solvePnP(op, c, K, np.zeros(5), flags=cv2.SOLVEPNP_SQPNP)
                Rr, _ = cv2.Rodrigues(rv)
                e, a = pose_error(Rr, tv.ravel(), R_t, t_t)
                ok = ok and e < 20 and a < 5
                cells.append(f"{e:6.2f}mm{a:6.2f}°")
            flag = "   <== 正确" if ok else ""
            print(f"   {'逆' if rev else '顺'}序起始{k}: " + " | ".join(cells) + flag)


def main():
    print("=" * 90)
    print("0. 环境与素材")
    print(f"   OpenCV {cv2.__version__} / numpy {np.__version__}")
    import pupil_apriltags
    print(f"   pupil-apriltags {pupil_apriltags.__version__}（家族 {FAMILY}）")
    tex = load_official_texture()
    print(f"   纹理：官方图案黑框外边 {tex.shape}，边长参数 {SIDE_M*1000:.1f} mm")

    det = Detector(families=FAMILY, nthreads=2, quad_decimate=1.0, refine_edges=1)

    print("=" * 90)
    print("1. 角点顺序约定：多个已知位姿下扫描 8 种 objp 配对（无畸变，先排除几何干扰）")
    scan_convention(det, tex, [("位姿A", -15, 25, 0, 0.08, -0.03, 0.75),
                               ("位姿B", 20, -30, 10, -0.06, 0.04, 0.60)])

    print("=" * 90)
    print("2. 位姿链路验证（仿真画面 + 已知畸变，真值 -> 解算），objp 用上面扫描出的正确配对")
    print(f"   {'场景':12s} {'路径':12s} {'解出 t (m)':32s} {'平移误差':>9s} {'旋转误差':>9s}")
    cases = [("正对 0.8m", 0, 0, 0, 0.00, 0.00, 0.80),
             ("倾斜+偏移", -15, 25, 0, 0.08, -0.03, 0.75),
             ("强倾斜 45°", 0, 45, 0, -0.05, 0.02, 0.55)]
    for name, ax, ay, az, tx, ty, tz in cases:
        R_t, t_t = truth(ax, ay, az, tx, ty, tz)
        for path in ("A 原图+dist", "B 去畸变", "C 错误内参"):
            img = render(R_t, t_t, K, DIST, W, H, tex, SIDE_M)
            if path == "B 去畸变":
                img, K2, d2 = cv2.undistort(img, K, DIST), K, np.zeros(5)
            elif path == "C 错误内参":
                K2, d2 = K.copy(), DIST
                K2[0, 0] /= 2; K2[1, 1] /= 2; K2[0, 2] /= 2; K2[1, 2] /= 2
            else:
                K2, d2 = K, DIST
            res = det.detect(img)
            if not res:
                print(f"   {name:12s} {path:12s} 未检出")
                continue
            c = np.asarray(res[0].corners, np.float64)
            _, rv, tv = cv2.solvePnP(OBJP, c, K2, d2, flags=cv2.SOLVEPNP_SQPNP)
            Rr, _ = cv2.Rodrigues(rv)
            e, a = pose_error(Rr, tv.ravel(), R_t, t_t)
            print(f"   {name:12s} {path:12s} {np.array2string(tv.ravel(), precision=4, floatmode='fixed'):32s} "
                  f"{e:7.2f}mm {a:7.3f}°")

    print("=" * 90)
    blank = np.full((480, 640), 127, np.uint8)
    t0 = time.perf_counter()
    for _ in range(30):
        det.detect(blank)
    print(f"3. 检测耗时（640x480，无目标）{(time.perf_counter() - t0) / 30 * 1000:.2f} ms/帧")
    print("   结论：路径 B（去畸变、不裁剪、内参保持不变）误差最小，作为正式方案；")
    print("         路径 C 说明内参与画面分辨率必须成对，否则平移误差可达数百毫米。")
    print("         正式代码的 objp 必须与第 1 节扫描出的配对一致（见文件顶部 OBJP）。")


if __name__ == "__main__":
    main()
