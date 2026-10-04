# RM 视觉组招新考核 —— 任务一：装甲板灯条识别

从提供的视频中逐帧提取**蓝色装甲板灯条**，用最小外接旋转矩形逐根框选，
并在画面上标注帧号、灯条数量与处理耗时，最后按原顺序保存为标记视频。

---

## 1. 开发与运行环境

| 项目 | 版本 / 说明 |
| --- | --- |
| 操作系统 | Ubuntu 24.04 LTS（WSL2，宿主机 Windows 11） |
| 语言 | Python 3.12 |
| OpenCV | opencv-python 4.x　【请填实际版本，见第 14 节】 |
| 数值库 | numpy【请填实际版本】 |
| 开发工具 | VS Code + Remote-WSL（Python、Pylance、Python Debugger 扩展） |
| 虚拟环境 | `~/OpenCV_python/.venv`（项目上一层的 `.venv`，已在 VS Code 中选为解释器） |

安装与自检：

```bash
# 1) 建立虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 2) 安装依赖
pip install -r requirements.txt

# 3) 最小验证：能打印版本即说明 OpenCV 可用
python -c "import cv2, numpy; print('OpenCV', cv2.__version__, '| numpy', numpy.__version__)"
```

## 2. 目录结构与职责划分

```text
task1/
├── main.py                     入口：参数解析 → 逐帧串联 → 写视频 → 控制台日志
├── config.py                   唯一的参数表（阈值、核大小、几何条件、路径、颜色）
├── requirements.txt            依赖清单
├── src/
│   ├── video_io.py             I/O：打开视频、取尺寸、算真实帧率、取单帧、创建写入器
│   ├── color_segment.py        颜色分割：蓝度阈值法与 HSV inRange 法
│   ├── morph_ops.py            形态学：开运算去噪 + 闭运算补洞
│   ├── bar_detector.py         轮廓提取、多边形近似、最小外接旋转矩形、几何筛选
│   └── visualize.py            只负责画图：框选、HUD、中间结果拼图
├── tools/                      证据生成与诊断脚本（不参与主流程）
│   ├── dump_channels.py        导出原图 / B / G / R / 灰度 / 两种掩膜
│   ├── dump_morph_compare.py   5 组形态学配置对比
│   ├── dump_contours.py        轮廓 / 多边形近似 / 旋转矩形 / 保留与剔除
│   └── probe_video.py          读取视频真实帧数、时长、帧率
├── data/                       输入视频
└── outputs/                    结果视频与截图
```

职责划分对应考核要求：输入与参数处理在 `main.py` 与 `config.py`；
检测算法集中在 `color_segment.py`、`morph_ops.py`、`bar_detector.py`；
结果显示只在 `visualize.py`；视频读写只在 `video_io.py`。
`src/` 中没有任何画图代码，`visualize.py` 中没有任何检测判断。

## 3. 运行方式

所有命令都在项目根目录执行。

### 3.1 主程序

```bash
python main.py                                  # 处理完整视频并输出标记视频
python main.py --max-frames 300                 # 只处理前 300 帧，快速验证
python main.py --show                           # 实时预览（需 WSLg，按 q 或 Esc 退出）
python main.py | tee outputs/log_task1.txt      # 同时把逐帧日志存成文件
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--video` | `config.DEFAULT_VIDEO` | 输入视频路径 |
| `--output` | `config.OUTPUT_VIDEO` | 输出视频路径 |
| `--max-frames` | `0` | 只处理前 N 帧，`0` 表示完整视频 |
| `--show` | 关闭 | 逐帧实时预览窗口 |

### 3.2 生成中间结果（考核要求的三项证据）

```bash
python tools/dump_channels.py --index 120       # 证据 1：通道与颜色分割
python tools/dump_morph_compare.py --index 120  # 证据 2：形态学对比
python tools/dump_contours.py --index 120       # 证据 3：轮廓与几何筛选
python tools/probe_video.py                     # 查看真实帧数 / 时长 / 帧率
```

`--index` 取值 0 ~ 633。源视频真实帧率 13.94 fps，粗换算为 `帧号 ≈ 秒数 × 13.94`。
这三个脚本都是顺序读到第 N 帧，**不使用 seek**（原因见第 10 节第 1 条）。

## 4. 处理流程

```text
读取一帧（BGR）
  → 颜色分割        得到 0/255 掩膜（蓝度阈值法，另有 HSV 法可对照）
  → 形态学优化      开运算去小白噪点 + 闭运算补灯条内部空洞
  → 轮廓提取        cv2.findContours(RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)
  → 多边形近似      cv2.approxPolyDP（误差容限 = 0.02 × 轮廓周长）
  → 几何筛选        面积比例 / 长宽比 / 填充率 / 倾角 四项判据
  → 最小外接旋转矩形 cv2.minAreaRect → cv2.boxPoints，逐根框选
  → 标注            帧号、灯条数量、本帧处理耗时
  → 写入输出视频    分辨率与源一致，帧率见第 6 节
```

### 4.1 颜色分割方法

采用**蓝度阈值法**（`SEGMENT_METHOD = "blue_dominance"`）：把 B 通道减去 G、R 中较大者，
差值超过 `DIFF_THRESH` 的像素判为蓝色。

```python
dominance = b.astype(int16) - max(g, r).astype(int16)   # 用 int16，避免负值被截断为 0
mask = dominance >= DIFF_THRESH
```

选择依据：场地橙色灯条与边线是“红高蓝低”，相减后为负值，天然被排除；
相比 HSV，本方法不受灯条中心过曝（饱和度下降）影响，阈值语义也直接
——“蓝色比红绿高出多少”。`tools/dump_channels.py` 会同时导出 HSV 法掩膜作对照，
并打印两种方法的白像素占比。

### 4.2 几何筛选判据

所有判据都是相对量或形状量，不含固定像素坐标与固定帧号，
因此在平移、视角变化、上坡倾斜的片段上同样成立。

| 判据 | 参数 | 作用 |
| --- | --- | --- |
| 面积比例 | `MIN_AREA_RATIO` / `MAX_AREA_RATIO` | 下限滤掉噪点，上限滤掉背景大色块与粘连区域 |
| 长宽比 | `ASPECT_MIN` / `ASPECT_MAX` | 灯条细长，排除方正色块 |
| 填充率 | `FILL_MIN` | 轮廓面积 / 最小外接矩形面积，排除不规则色斑 |
| 倾角 | `ANGLE_TOL_DEG` | 长轴与竖直方向夹角，为倾斜留余量 |

## 5. 参数说明（`config.py`）

| 分组 | 参数 | 取值 | 含义与依据 |
| --- | --- | --- | --- |
| 输入输出 | `DEFAULT_VIDEO` | `data/test_video2.webm` | 考核提供的模拟器录屏 |
| | `OUTPUT_VIDEO` | `outputs/videos/task1_result.mp4` | 标记视频输出路径 |
| | `FOURCC` | `mp4v` | 输出编码；OpenCV 不支持写回 webm |
| | `OUTPUT_FPS` | `0.0` | 0 = 自动取真实帧率（13.94 fps），写死数值可跳过统计 |
| 颜色分割 | `SEGMENT_METHOD` | `blue_dominance` | 见 4.1 的选择依据 |
| | `DIFF_THRESH` | `45` | 蓝度阈值：偏小会带入环境蓝光，偏大会漏掉暗侧灯条 |
| | `HSV_LOW` / `HSV_HIGH` | `(90,80,60)` / `(135,255,255)` | HSV 法门限，仅作对照 |
| 形态学 | `MORPH_OPEN_KSIZE` | `(3, 3)` | 开运算去掉掩膜上的孤立小白点 |
| | `MORPH_CLOSE_KSIZE` | `(3, 3)` | 闭运算填补灯条内部空洞；核再大易把相邻灯条粘连 |
| 几何筛选 | `APPROX_EPS_RATIO` | `0.02` | 多边形近似误差容限（× 轮廓周长） |
| | `MIN_AREA_RATIO` | `5e-5` | 面积下限（占整幅图像的比例） |
| | `MAX_AREA_RATIO` | `5e-2` | 面积上限 |
| | `ASPECT_MIN` / `ASPECT_MAX` | `1.5` / `12.0` | 长宽比允许区间 |
| | `FILL_MIN` | `0.55` | 填充率下限 |
| | `ANGLE_TOL_DEG` | `45.0` | 与竖直方向夹角上限（度） |
| 显示 | `BAR_COLOR` | `(0, 255, 0)` | 灯条框颜色（BGR） |
| | `CENTER_COLOR` / `TEXT_COLOR` | 红 / 白 | 中心点与文字颜色 |
| | `HUD_FONT_SCALE` / `HUD_THICKNESS` | `0.7` / `2` | HUD 字号与线宽 |

## 6. 输出视频与帧率的确定

**画面标注**：每帧左上角写三行——`frame: N`（帧号，从 0 开始）、
`bars: N`（该帧检出的灯条数量，无目标时为 0）、`cost: x.x ms`（该帧处理耗时，
只统计“颜色分割 + 形态学 + 轮廓筛选”，不含写盘时间）。

**输出帧率**：源视频容器报告 `1000 fps / 45468 帧`，两者都是假值——
该文件由 GStreamer `matroskamux` 录制，写入的是 1 ms 时间基准，
OpenCV 把时间基准当成了帧率，FFmpeg 又据此把帧数估算为 `时长 × 1000`。
真实参数由程序自行测量：

1. 解析 WebM/Matroska 文件头，得到真实时长 `45.468 s`；
2. 顺序解码，得到真实帧数 `634`；
3. 真实帧率 = `634 / 45.468 = 13.944 fps`。

输出视频即按 13.944 fps 写入（`src/video_io.py` 的 `source_fps()`），
成片时长与原视频一致，不会倍速播放。实测输出文件：
`634 帧 / 45.47 s / 13.944 fps / 1540×986`，与源视频逐帧对应。

**控制台日志**：运行时逐帧打印一行，便于核对逐帧处理（下为示例输出）：

```text
[信息] 1540x987，输出 13.94 fps → outputs/videos/task1_result.mp4
frame    0 | bars 4 | cost   12.3 ms
frame    1 | bars 4 | cost   11.8 ms
...
[完成] 处理 634 帧，视频已保存到 outputs/videos/task1_result.mp4
[统计] 平均耗时 12.05 ms/帧，平均灯条 4.00 条/帧
```

## 7. 坐标与单位

| 项 | 约定 |
| --- | --- |
| 图像坐标 | 原点在左上角，x 向右，y 向下，单位像素 |
| 帧号 | 从 0 开始，按解码顺序递增，与画面上的 `frame:` 一致 |
| 面积 | 轮廓面积与整幅图像面积之比（无量纲） |
| 角度 | 灯条长轴与图像竖直方向的夹角，单位度，范围 0 ~ 90 |
| 耗时 | 毫秒（ms），单帧处理时间 |
| 长度 | 长边 / 短边，单位像素 |

## 8. 中间结果与对比（提交证据）

| 证据 | 路径 | 内容 |
| --- | --- | --- |
| 通道与颜色分割 | `outputs/screenshots/channels/` | `00_original`、`01_channel_B`、`02_channel_G`、`03_channel_R`、`04_gray`、`05_mask_blue_dominance`、`06_mask_hsv`，以及拼图 `07_channels_and_masks.png` |
| 形态学对比 | `outputs/screenshots/morphology/` | 5 组配置的掩膜与拼图 `morphology_compare.png`；控制台同时打印白像素占比、轮廓数、通过筛选数 |
| 轮廓与几何 | `outputs/screenshots/contours/` | 五联图 `contours_and_filtering.png`（原图 / 轮廓 / 多边形近似 / 旋转矩形 / 保留绿框与剔除红框）；控制台打印每个候选的面积、长宽比、填充率、倾角与剔除理由 |

**通道与灰度的差别**：`B`、`G`、`R` 三张图是同一画面按通道拆分的结果——
蓝色灯条在 B 通道最亮、在 R 通道几乎不可见，橙色场地元素恰好相反；
灰度图按亮度加权把三通道合成单通道，只保留明暗、丢掉颜色区分，
因此单靠灰度无法把蓝色灯条与白色数字、亮色边线分开，这也是选择颜色分割而非灰度的原因。

**形态学对比结论**：

| 配置 | 现象 |
| --- | --- |
| `A_none`（不处理） | 掩膜上有孤立小白点，灯条内部有细小空洞 |
| `B_open3` | 小白点被去掉，但灯条边缘被削掉一点 |
| `C_close3` | 空洞被补上，个别相邻灯条出现轻微粘连趋势 |
| `D_open3_close3`（当前配置） | 噪点与空洞都消除，且未把成对灯条连成一块 |
| `E_close5` | 闭运算核放大到 5×5，个别位置相邻灯条粘连成一个轮廓，面积与长宽比越界被剔除 |

因此最终保留“开运算 3×3 + 闭运算 3×3”：**改善**是噪点与孔洞都被清除；
**损伤**是灯条边缘各收缩约 1 像素，框选仍紧贴灯条，不影响判定。

## 9. 边界情况

| 情况 | 处理 | 位置 |
| --- | --- | --- |
| 路径错误 / 文件打不开 | 打印 `[错误] 打不开视频: <路径>` 并返回状态码 1 | `main.py` 的 `cap.isOpened()` 判断 |
| 视频结束 | `cap.read()` 返回假即跳出循环，正常收尾并释放读写器 | `main.py` 循环条件 |
| 该帧没有有效灯条 | 照常写出该帧，只画 HUD 并标 `bars: 0`，不中断也不跳过 | `main.py` 循环体 |
| 阈值依赖固定坐标 / 帧号 | 全部判据用面积比例、长宽比、填充率、倾角等相对量 | `src/bar_detector.py` |

## 10. 已知问题

1. **源视频是可变帧率**：帧间隔 3 ~ 90 ms（中位 76 ms），容器报告的 1000 fps 与 45468 帧均为假值。
   程序按“真实帧数 / 真实时长”输出恒定帧率视频，总时长一致，个别帧的时间点最多偏移约 ±40 ms。
   同样因为它，`tools/` 中取帧一律顺序读取、不使用按时间 seek——seek 会按假帧率换算，直接跳到文件末尾。
2. **形态学对比图是整幅掩膜缩放**（1540×987 → 420 px 宽），灯条只占几个像素，细节不醒目；
   需要看局部时请查看 `outputs/screenshots/channels/05_mask_blue_dominance.png` 原图。
3. **HUD 位于左上角**，若灯条进入该区域会被半透明底板遮挡，必要时可调整 `visualize.py` 中的坐标。
4. VS Code 的 Pylance 对 opencv-python 类型存根存在重载误报（`MatLike` 与 `UMat` 两套重载），
   只在编辑器中显示波浪线，不影响运行；给 `read_frame` 加 `-> np.ndarray` 返回注解即可消除。
5. 输出视频为 `mp4v` 编码的 mp4，个别播放器对 `mp4v` 的时长解析偏保守，
   建议用 VLC 或 `ffprobe` 查看时长。

## 11. 未完成事项

任务二（相机标定与 AprilTag 位姿）与任务三（模拟串口发送）尚未实现，
本仓库目前只包含任务一。已完成的是环境部署、仓库结构、参数与证据整理。
计划方案：任务二用棋盘格标定得到内参与畸变，用 `apriltag` 检测 tag36h11 并解算 `R`、`t`；
任务三按考核规定的 CV1 文本协议把位姿通过串口发出，依赖项已在 `requirements.txt` 中以注释列出。

## 12. 参考来源

| 来源 | 用途 |
| --- | --- |
| 考核手册提供的 [Ubuntu 环境部署](https://blog.csdn.net/weixin_43628293/article/details/147103949) | 环境搭建 |
| 考核手册提供的 [Git 仓库构建](https://www.bilibili.com/video/BV1rsdQBpEV5/) | 仓库管理 |
| 考核手册提供的 [OpenCV 教程](https://www.runoob.com/opencv/opencv-tutorial.html) | OpenCV 入门 |
| 考核视频（百度网盘，提取码 `xik2`） | 输入素材 |
| OpenCV 官方文档：颜色空间转换、形态学操作、轮廓与 `approxPolyDP`、`minAreaRect` | 算法接口 |
| GStreamer matroskamux 采用 1 ms 时间基准 | 解释容器帧率被读成 1000 fps 的原因 |

## 13. 提交物清单

| 材料 | 路径 |
| --- | --- |
| 标记视频 | `outputs/videos/task1_result.mp4` |
| 代表帧截图 | `outputs/screenshots/channels/`、`outputs/screenshots/morphology/`、`outputs/screenshots/contours/` |
| 逐帧处理日志 | 运行 `python main.py | tee outputs/log_task1.txt` 得到 |
| 参数对比说明 | 本文第 4.1、4.2、5、8 节 |
| 输入素材 | 考核提供的 `test_video2.webm`（体积较大，未纳入 git，下载地址见考核手册） |

## 14. 版本核对

```bash
python -c "import sys, cv2, numpy; print(sys.version.split()[0], cv2.__version__, numpy.__version__)"
```

把输出填回第 1 节的版本表格即可。
