# 任务二 前期验证记录（spike）

这个目录是动手写代码前的可行性验证，不属于正式交付源码（提交前可以删，或者把
`probe_apriltag_pipeline.py` 移进 `tools/` 当回归测试）。脚本不需要相机、不需要打印就能跑通：

```bash
cd task2 && python spike/probe_apriltag_pipeline.py
```

已顺带生成打印素材（`tools/make_patterns.py`）：`assets/patterns/` 下的 A4 PDF，
尺寸精确到 MediaBox 校验过的 210.00 × 297.00 mm。

---

## 一、环境

| 项 | 实测结果 | 说明 |
| --- | --- | --- |
| 系统 | Ubuntu 26.04.1 LTS，内核 7.0.0-38 | 不是 WSL2，是实体机（task1 README 写的 WSL2 / 24.04 要更正） |
| Python | 3.14.4 | task1 README 写的 3.12 已过期 |
| 虚拟环境 | `/home/tony/Projects/PythonProjects/.venv` | 上一层，与 task1 共用 |
| OpenCV |  | 手册写的是 4.x，本机装的是 5.0，已和出题方确认可用。之后若要严格贴合手册，`pip install "opencv-python<5"` 可降到 4.14.0.94（有 `cp37-abi3` 轮子，py3.14 可用）。已知问题见第六节第 6 条 |
| numpy | 2.5.3 | |
| AprilTag 库 | pupil-apriltags 1.0.4.post11 | PyPI 无 py3.14 预编译轮子，本地源码构建成功（约 2 分钟），依赖 cmake / g++ / python3.14-dev，都已具备 |
| 图像库 | Pillow 12.3.0（本次安装） | 仅用于生成打印素材 |
| 构建工具 | gcc 15.2、g++、cmake、make 齐全 | `v4l2-utils`、`ffmpeg`、`curl` 未安装（不影响本任务） |

## 二、摄像头实测

| 设备 | 内容 | 分辨率 | 帧率 |
| --- | --- | --- | --- |
| `/dev/video0`（cv2 索引 0） | 彩色，画面正常 | YUYV 只能 640×480；设 MJPG 后可 1280×720 / 1920×1080 | 30 fps |
| `/dev/video1` | 同一相机的元数据节点，不能取流 | — | — |
| `/dev/video2`（cv2 索引 2） | 灰度/红外画面，不适合本任务 | 640×360（MJPG 也上不去） | 30 fps |
| `/dev/video3` | 元数据节点 | — | — |

结论：用索引 0，并且必须先设 `CAP_PROP_FOURCC = MJPG` 再设分辨率，
否则驱动只给 640×480，标定与检测精度都吃亏：

```python
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
```

## 三、结论 1：角点顺序约定（用官方图案）

扫描 8 种 `objp` 配对，在两个不同位姿下都只有一种能把旋转误差压到 0.3° 以内，
其余都是 90° 或 180°：

`detection.corners[0..3]` 与 tag 局部坐标系的对应关系（原点在 tag 中心，x 右、y 下、z 垂直纸面指向纸背、背离相机）：

| 索引 | tag 系坐标 | 位置（打印好的 tag 正着看、方向标记朝上时） |
| --- | --- | --- |
| `corners[0]` | `(-s/2, +s/2, 0)` | 左下 |
| `corners[1]` | `(+s/2, +s/2, 0)` | 右下 |
| `corners[2]` | `(+s/2, -s/2, 0)` | 右上 |
| `corners[3]` | `(-s/2, -s/2, 0)` | 左上 |

也就是以左下角为起点、逆时针，和 AprilTag 官方文档的角点次序说明一致。
这个次序由库固定，不随 tag 在画面里怎么转、怎么倾斜而变，换 ID 也一样。
正式代码的 `objp` 必须按这个顺序写，不要按自己的习惯重排。

## 四、结论 2：位姿解算链路在已知真值下的误差

仿真画面由逐像素光线求交渲染，自带已知 R、t 与桶形畸变（k1=-0.28, k2=0.11），
再用同一检测器 + `cv2.solvePnP(SOLVEPNP_SQPNP)` 解算，与真值比对：

| 场景 | A 原图+畸变系数解算 | B 去畸变后 dist=0 解算 | C 内参误用半分辨率 |
| --- | --- | --- | --- |
| 正对 0.8 m | 5.01 mm / 1.14° | 4.16 mm / 0.24° | 590 mm / 1.4° |
| 倾斜 + 偏移 0.75 m | 1.88 mm / 0.17° | 1.19 mm / 0.16° | 551 mm / 39° |
| 强倾斜 45° 0.55 m | 0.79 mm / 0.19° | 0.47 mm / 0.22° | 399 mm / 65° |

- 两条路径都可用，B 略优；正式方案取 B：`cv2.undistort(img, K, D)` 不裁剪、不换内参，
  之后以 `dist=0` 解算。这样“解算用的内参”和“画面”天生匹配，也好在 README 里讲清楚。
- C 是故意错的对照组：内参与分辨率必须成对使用，错配时 Z 深度成倍偏掉。
  正对评分表里“畸变处理和所用图像内参匹配（2 分）”。

## 五、打印素材（已生成）

| 文件 | 内容 | 关键尺寸（已程序核对） |
| --- | --- | --- |
| `assets/patterns/tag36h11_00000_official.png` | 官方 patterns 仓原件（10×10 单元，含 1 单元白边） | 每单元 1 px，仅作来源留存 |
| `assets/patterns/apriltag_36h11_id0_100mm.pdf` | A4 竖版 tag 页，含方向标记、100 mm 校验尺 | 黑框外边 100.00 mm，检出四边 99.98～100.03 mm |
| `assets/patterns/chessboard_9x6_20mm.pdf` | A4 横版棋盘格，含校验尺 | 9×6 内角点，方格 20.0 mm，整体 200.0 × 140.0 mm |

用 `python tools/make_patterns.py` 重新生成；`--square-mm 25 --page a3` 可出 25 mm 方格的 A3 版，
`--tag-id N` 可换 ID，`--tag-mm` 可改 tag 边长（手册建议 80～120 mm）。
A4 上棋盘格只能做到 20 mm 方格：25 mm 的板（250×175 mm）加页眉与校验尺共需约 240 mm，
超过 A4 横版的 210 mm。

两个 PDF 的 MediaBox 已校验为 210.00 × 297.00 mm 与 297.00 × 210.00 mm，
打印时选「实际大小 / 100%」就能得到准确物理尺寸；页内都印了 100 mm 校验尺，
打完量一下，误差超过约 1 mm 就重新打印。打印后用直尺或卡尺实测黑框外边与方格边长，
实测值才是程序参数。


## 六、性能

`Detector.detect()` 在 640×480 空画面约 0.5 ms/帧；有目标时约 2～4 ms/帧，
相对 30 fps 取流（33 ms/帧）完全不是瓶颈，不需要为性能做取舍。
