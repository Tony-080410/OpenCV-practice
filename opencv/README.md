# OpenCV 视觉招新考核：任务一 / 二 / 三

三个任务的源码、说明与证据都在本仓库。这里只做总览与素材索引，细节在每个任务自己的 README 里。

## 1. 环境

- Ubuntu 26.04 LTS
- Python 3.14.4，虚拟环境建在**仓库外**：`../.venv`
  从 task1 / task2 / task3 目录里数过去是两级：`../../.venv/bin/python`
- 依赖与实测版本：

| 包 | 实测版本 | 用于 |
| --- | --- | --- |
| opencv-python | 5.0.0.93（`cv2.__version__` 打印 `5.0.0`） | 三个任务 |
| numpy | 2.5.3 | 三个任务 |
| pupil-apriltags | 1.0.4.post11 | 任务二（家族 36h11、位姿接口） |
| pyserial | 3.5 | 任务三 |
| pillow | 12.3.0 | 任务二生成打印素材（`tools/make_patterns.py`） |

手册按 OpenCV 4.x 写的；本机实测 5.0.0.93 跑得通，代码没用 5.x 独有接口，各 `requirements.txt` 的版本范围据此写。

重建环境：

```bash
cd task2                                  # 换成任务一 / 三也一样
python3 -m venv ../../.venv
../../.venv/bin/pip install -r requirements.txt
../../.venv/bin/python -c "import sys, cv2, numpy; print(sys.version.split()[0], cv2.__version__, numpy.__version__)"
```

## 2. 三个任务

| 任务 | 做什么 | 入口（在各自目录下） | 细节 |
| --- | --- | --- | --- |
| 一 | 装甲板灯条识别，逐帧标记并输出结果视频 | `python main.py` | `task1/README.md`：§3 运行方式、§12 提交清单 |
| 二 | AprilTag 打印与实测、相机标定、位姿检测与演示 | `python main.py demo` / `calib` / `check` | `task2/README.md`：§3 运行方式、§14 对照评分表自查 |
| 三 | 把位姿按 CV1 协议经串口发出 | `python main.py selftest` / `check` / `send` | `task3/README.md`：§3 三步走、§4 运行方式与输出路径 |

## 3. 素材对应表

### 任务一

| 文件 | 是什么 |
| --- | --- |
| `task1/outputs/videos/task1_result.mp4` | 逐帧标记视频，每帧标注帧号、灯条数、本帧耗时 |
| `task1/outputs/screenshots/channels/` | 原图、B/G/R 分通道、灰度、两种蓝色掩膜（要求 1） |
| `task1/outputs/screenshots/morphology/` | 形态学五组参数对比 A~E 及对比图（要求 2） |
| `task1/outputs/screenshots/contours/` | 轮廓与多边形近似、几何筛选（要求 3） |
| `task1/outputs/screenshots/f0120/` | 代表帧的整套截图（原图到掩膜） |
| `task1/data/test_video2.webm` | 考核统一提供的模拟器录屏（输入素材） |

### 任务二

| 文件 | 是什么 |
| --- | --- |
| `task2/data/measurements.md` | Tag 与打印棋盘的实测尺寸（黑框外边 138.0 mm、方格 15.98 mm） |
| `task2/assets/patterns/*.png` | 打印素材（A4、304.8 dpi，带 100 mm 校验尺） |
| `task2/data/calib_images/` | 20 张标定采集原图 |
| `task2/data/calib_params.json` | 标定参数（1280×720，重投影 RMS 0.9948 px） |
| `task2/outputs/videos/task2_pose_demo.mp4` | 位姿演示（含目标出现、消失、非目标 ID 三种情形） |
| `task2/outputs/screenshots/shot_*.png` | 代表帧截图（2 张目标帧 + 3 张非目标帧） |
| `task2/outputs/logs/pose.jsonl` | 逐帧位姿（含旋转矩阵） |
| `task2/assets/docs/frames_and_corners.png` | 坐标系与角点次序示意 |

### 任务三

收发日志成对提供，每一对都来自同一次运行（同一天、帧数相同、两侧字节流逐字节一致）：

| 文件 | 说明 |
| --- | --- |
| `task3_send_examples.txt`、`task3_recv_examples.txt` | 手册固定报文（`seq` 42/43、`t_ms` 12345/12445），6 帧。接收侧复算校验 `*33` / `*09`，与手册一致。用途：先验帧格式、CRLF 帧边界与校验 |
| `task3_send_dump.txt`、`task3_recv_dump.txt` | 重放任务二演示那次的真实位姿（`task2/outputs/logs/pose.jsonl`，538 帧、274 帧有效）。用途：验证 dump 重放链路与拆帧，帧内容与位姿演示视频同源 |
| `task3_send_live.txt`、`task3_recv_comtool.txt` | 实时接入任务二，同一次运行：发送侧 292 帧、230 帧有效（78.8%），覆盖出现 → 消失 → 重现；接收侧 292 帧（COMTool 显示区复制），与发送日志逐帧比对 0 处不同。检测与状态切换的主证据 |

接收侧的独立证据就是每一对里的接收日志：`examples`、`dump` 是接收端程序写下的原始字节，`live` 那次是 COMTool 显示区的内容（人工复制），三者都与各自的发送日志逐帧比对一致。

## 4. 约定速查

- **任务二 Tag 坐标系**：原点在 tag 中心，x 向右、y 向下、z 垂直纸面指向纸背（背离相机），右手系（x×y=z，det R=+1），可直接把旋转向量发给任务三；单位 mm。详见 `task2/README.md` 第 5 节。
- **任务三 CV1 报文**：`$CV1,seq,t_ms,valid,id,x_mm,y_mm,z_mm,rx,ry,rz*HH\r\n`
  校验 = `$` 与 `*` 之间所有字节逐字节异或（初值 0，两位大写十六进制）；无目标时 `valid=0`、`id=-1`、坐标与姿态全 0。详见 `task3/README.md` 第 6 节。



## 5. 参考来源

三份子 README 各有「参考来源」表：`task1/README.md` §11、`task2/README.md` §12、`task3/README.md` §11。跨任务共用的几条：考核手册（任务要求与基准）、OpenCV 官方文档、[pupil-apriltags](https://github.com/pupil-labs/apriltags)、[AprilTag 官方站](https://april.eecs.umich.edu/software/apriltag)、[AprilRobotics/apriltag-imgs](https://github.com/AprilRobotics/apriltag-imgs)（官方 tag36h11 图案）。

## 6. 提交清单速查

| 任务 | 清单在 |
| --- | --- |
| 一 | `task1/README.md` §12 |
| 二 | `task2/README.md` §13、§14 |
| 三 | `task3/README.md` §12 |
