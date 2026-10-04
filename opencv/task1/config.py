"""任务一（装甲板灯条识别）的参数表。

main.py 与 tools/ 下的脚本都从这里取值, README 按分组解释本文件即可。
"""

# ---------------- 输入输出 ----------------
DEFAULT_VIDEO = "data/test_video2.webm"
OUTPUT_VIDEO = "outputs/videos/task1_result.mp4"
DEBUG_DIR = "outputs/screenshots"           # tools/ 导出的中间结果图
FOURCC = "mp4v"                             # 输出编码，写不出来换 "XVID" 并存 .avi
OUTPUT_FPS = 0.0                            # 0 = 自动(真实帧数/真实时长)，也可写死 13.94

# ---------------- 颜色分割 ----------------
SEGMENT_METHOD = "blue_dominance"   # blue_dominance: B - max(G, R) >= DIFF_THRESH
SEGMENT_METHODS = ("blue_dominance", "hsv")   # 可选的颜色分割方法（命令行 choices 也用它）
DIFF_THRESH = 10                    # 蓝度阈值，越大越严格
HSV_LOW = (90, 80, 60)              # method="hsv" 时生效
HSV_HIGH = (135, 255, 255)

# ---------------- 形态学 ----------------
MORPH_OPEN_KSIZE = (3, 3)           # 开运算：去小白噪点；0 表示关闭
MORPH_CLOSE_KSIZE = (3, 3)          # 闭运算：补灯条内部空洞；核过大易粘连

# ---------------- 轮廓与几何筛选 ----------------
APPROX_EPS_RATIO = 0.02   # approxPolyDP 误差容限系数（乘轮廓周长）
MIN_AREA_RATIO = 5e-5     # 轮廓面积/图像面积 下限：滤掉噪点
MAX_AREA_RATIO = 5e-2     # 上限：滤掉背景大色块
ASPECT_MIN = 1.5          # 长边/短边 下限：灯条细长
ASPECT_MAX = 12.0
FILL_MIN = 0.55           # 轮廓面积/最小外接矩形面积 下限
ANGLE_TOL_DEG = 45.0      # 长轴与竖直方向最大夹角

FILTER_DEFAULTS = {
    "min_area_ratio": MIN_AREA_RATIO,
    "max_area_ratio": MAX_AREA_RATIO,
    "aspect_min": ASPECT_MIN,
    "aspect_max": ASPECT_MAX,
    "fill_min": FILL_MIN,
    "angle_tol_deg": ANGLE_TOL_DEG,
}

# ---------------- 显示 ----------------
BAR_COLOR = (0, 255, 0)     # BGR
CENTER_COLOR = (0, 0, 255)
TEXT_COLOR = (255, 255, 255)
HUD_FONT_SCALE = 0.7
HUD_THICKNESS = 2