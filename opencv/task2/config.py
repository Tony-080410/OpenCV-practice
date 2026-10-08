"""任务二 参数表（唯一的参数来源）

约定（README 第 5 节有图与说明）：
  相机光学坐标系：原点在光心，X 向右、Y 向下、Z 向镜头前方
  Tag 局部坐标系 ：原点在 tag 中心，x 右、y 下、z 垂直纸面指向相机
  变换关系       ：p_camera = R · p_tag + t
  程序内部长度单位统一用米；只有通信时才转毫米。

注意：TAG_EDGE_MM 必须是**打印后实测**的黑框外边边长，标称值只是参考。
"""
from pathlib import Path

# ---------- 路径 ----------
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"
CALIB_IMAGES = DATA / "calib_images"
CALIB_PARAMS = DATA / "calib_params.json"          # 内参、畸变、分辨率、重投影误差
TAG_PATTERN = ASSETS / "patterns" / "tag36h11_00000_official.png"

# ---------- 相机 ----------
CAMERA_INDEX = 0                 # 索引 0 是彩色相机；索引 2 是红外/灰度，不要用
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FOURCC = "MJPG"           # 不设 MJPG，驱动只给 640x480
CAMERA_BUFFERSIZE = 1            # 取最新帧，避免积压
# 曝光：本机相机默认是自动曝光（exposure_auto=3），靠近/远离时亮度会自动变化。
# 自动曝光一般够用；若 Tag 在远处检测不稳定，把它改成 True 锁死手动曝光，
# 手动值用 tools/probe_camera.py 看到的那台相机的当前值（本机约 156，范围 2~1250）。
CAMERA_LOCK_EXPOSURE = False
CAMERA_EXPOSURE_ABSOLUTE = 156.0

# ---------- AprilTag ----------
TAG_FAMILY = "tag36h11"
TARGET_ID = 0                    # 要选中并发布位姿的 Tag ID
TAG_EDGE_MM = 138.0              # 【实测】A4 打印 phone_screen 版 ID 0 页，直尺量黑框外边 = 138 mm
TAG_QUAD_DECIMATE = 1.0          # 1.0 = 不降采样，最准；小图别调小
TAG_REFINE_EDGES = 1

# ---------- 相机标定 ----------
BOARD_INNER_COLS = 9             # 内角点列数（对应 10 个方格）
BOARD_INNER_ROWS = 6             # 内角点行数（对应 7 个方格）
BOARD_SQUARE_MM = 15.98           # 【实测填写】单个方格边长，毫米
CALIB_TARGET_COUNT = 20          # 采集目标张数（手册建议 15~25）
CALIB_MIN_COUNT = 8              # 少于这个数量不出结果
# 采集时的覆盖率提示：把画面分 3x3，希望各区域都拍到
COVERAGE_GRID = 3

# ---------- 位姿解算 ----------
# SQPNP 不挑剔点序，配 y 向下、x 向右的 tag 系最稳；
# IPPE_SQUARE 按 OpenCV 文档要求 y 向上、特定次序，用错会得到镜像解（旋转差 180°）。
POSE_SOLVER = "sqpnp"
AXIS_LENGTH_RATIO = 0.5          # 画坐标轴的长度 = 该比例 × tag 边长
MIN_DECISION_MARGIN = 10.0       # 低于此值认为检测质量差，位姿不可用

# ---------- 显示 ----------
COLOR_TARGET = (0, 255, 0)       # 选中目标：绿
COLOR_OTHER = (128, 128, 255)    # 其它检测到的 Tag：淡红
COLOR_CENTER = (0, 0, 255)
COLOR_AXIS_X = (0, 0, 255)
COLOR_AXIS_Y = (0, 255, 0)
COLOR_AXIS_Z = (255, 0, 0)
COLOR_HUD_TEXT = (255, 255, 255)
HUD_FONT_SCALE = 0.55
HUD_THICKNESS = 1
HUD_ORIGIN = (12, 12)
HUD_LINE_HEIGHT = 20

# ---------- 输出目录 ----------
OUTPUTS_VIDEOS = OUTPUTS / "videos"
OUTPUTS_LOGS = OUTPUTS / "logs"
OUTPUTS_SHOTS = OUTPUTS / "screenshots"

# ---------- 演示输出 ----------
OUTPUT_VIDEO_FOURCC = "mp4v"     # 演示录屏用的编码
DEMO_VIDEO = OUTPUTS_VIDEOS / "task2_pose_demo.mp4"
DEMO_LOG = OUTPUTS_LOGS / "task2_pose_demo.txt"
