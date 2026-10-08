"""任务三参数表，本工程唯一的参数来源。

叫 t3config.py 不叫 config.py：任务二顶层已经有 config 这个模块名，
同名会静默遮蔽（见 cvlink/task2bridge.py）。

坐标沿用任务二的约定：相机光学系，原点在光心，X 右、Y 下、Z 向镜头前方，
p_camera = R · p_tag + t。程序内部用米，报文里用毫米，姿态是 Rodrigues
旋转向量（弧度）。
"""
from pathlib import Path

# ---------- 路径 ----------
ROOT = Path(__file__).resolve().parent            # task3/
OUTPUTS = ROOT / "outputs"
OUTPUTS_LOGS = OUTPUTS / "logs"
TASK2_DIR = ROOT.parent / "task2"                 # 任务二工程（实时接入用）

# ---------- 串口 ----------
# 手册：115200 bit/s，8 数据位，无奇偶校验，1 停止位，无硬件或软件流控
SERIAL_PORT = ""                 # 例：/dev/pts/3（bash tools/vport.sh 会打印真实编号）
SERIAL_BAUD = 115200
SERIAL_BYTESIZE = 8
SERIAL_PARITY = "N"              # N 无校验 / E 偶 / O 奇
SERIAL_STOPBITS = 1
SERIAL_FLOW = "none"             # none 无流控 / rtscts 硬件 / xonxoff 软件
SERIAL_TIMEOUT = 0.2             # 读超时（本任务只发不收，留着便于诊断）
SERIAL_WRITE_TIMEOUT = 1.0

# ---------- 发送节奏 ----------
SEND_RATE_HZ = 10.0              # 手册建议约 10 Hz，不考核精确频率
# 连续取帧失败（空帧）到多少次就收尾。失败期间照发 valid=0 的无效报文（手册要求）。
# 设为 0 表示一直发无效报文不收尾。
EMPTY_LIMIT = 30

# ---------- 位姿来源 ----------
SOURCE = "live"                  # live 实时接入任务二 / dump 重放 JSONL / examples 手册固定报文
DUMP_PATH = ""                   # source=dump 时的 JSONL 路径（任务二 demo --dump 的产物）

# ---------- 实时源（默认沿用任务二的参数，None = 用任务二 config 里的值）----------
USE_CALIB = True                 # False 时内参用估值，位姿数值不可信，仅通路自测
TARGET_ID = None                 # None → 任务二的 config.TARGET_ID
TAG_EDGE_MM = None               # None → 任务二的 config.TAG_EDGE_MM（打印后实测值）

# ---------- 显示（可选，仅 live）----------
PREVIEW_WINDOW = "task3 - CV1 send (q/ESC 退出, s 截图)"
PREVIEW_SCREENSHOTS = OUTPUTS / "screenshots"
PREVIEW_FONT_SCALE = 0.5
PREVIEW_LINE_HEIGHT = 20
PREVIEW_TEXT_COLOR = (255, 255, 255)
PREVIEW_OK_COLOR = (0, 255, 0)      # 有效帧
PREVIEW_BAD_COLOR = (0, 0, 255)     # 无效帧
