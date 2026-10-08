# RM 视觉组招新考核 —— 任务一：装甲板灯条识别

从提供的视频里逐帧找出蓝色装甲板灯条，用最小外接旋转矩形逐根框选，画面上标帧号、灯条数量和处理耗时，再按原来的顺序存成标记视频。

---

## 1. 开发与运行环境

| 项目 | 版本 / 说明 |
| --- | --- |
| 操作系统 | Ubuntu 26.04 LTS |
| 语言 | Python 3.14.4 |
| OpenCV | opencv-python 5.0.0.93（`cv2.__version__` 打印 `5.0.0`） |
| 数值库 | numpy 2.5.3 |
| 开发工具 | VS Code （+Python、Pylance、Python Debugger 扩展） |
| 虚拟环境 | `~/Projects/PythonProjects/.venv`（在仓库外，从 task1 数过去两级：`../../.venv`） |

安装与自检：

```bash
cd task1
source ../../.venv/bin/activate       # 或 ../../.venv/bin/python main.py ... 直接跑
# 注意路径：仓库根在 PythonProjects，venv 与根同级，所以从 task1 出发是 ../../.venv
pip install -r requirements.txt

# 最小验证：能打印版本即说明 OpenCV 可用
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

职责划分按考核要求安排：输入与参数处理放在 `main.py` 和 `config.py`，检测算法集中在 `color_segment.py`、`morph_ops.py`、`bar_detector.py`，结果显示只在 `visualize.py`，视频读写只在 `video_io.py`。`src/` 里没有画图代码，`visualize.py` 里也没有检测判断。

## 3. 运行方式

所有命令都在项目根目录执行。

### 3.1 主程序

```bash
python main.py                                  # 处理完整视频并输出标记视频
python main.py --max-frames 300                 # 只处理前 300 帧，快速验证
python main.py --show                           # 实时预览（需要一个桌面环境，按 q 或 Esc 退出）
python main.py | tee outputs/log_task1.txt      # 同时把逐帧日志存成文件
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--video` | `config.DEFAULT_VIDEO` | 输入视频路径 |
| `--output` | `config.OUTPUT_VIDEO` | 输出视频路径 |
| `--max-frames` | `0` | 只处理前 N 帧，`0` 表示完整视频 |
| `--show` | 关闭 | 逐帧实时预览窗口 |

### 3.2 生成中间结果

```bash
python tools/dump_channels.py --index 120       # 证据 1：通道与颜色分割
python tools/dump_morph_compare.py --index 120  # 证据 2：形态学对比
python tools/dump_contours.py --index 120       # 证据 3：轮廓与几何筛选
python tools/probe_video.py                     # 查看真实帧数 / 时长 / 帧率
```

`--index` 取值 0 ~ 633。源视频真实帧率 13.94 fps，粗换算 `帧号 ≈ 秒数 × 13.94`。这三个脚本都是顺序读到第 N 帧，不用 seek（原因见第 10 节第 1 条）。

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
  → 写入输出视频    分辨率 1540×986（mp4v 会把奇数边长各减 1，源视频是 1540×987），帧率见第 6 节
```

### 4.1 颜色分割方法

用的是蓝度阈值法（`SEGMENT_METHOD = "blue_dominance"`）：把 B 通道减去 G、R 里较大的那个，差值超过 `DIFF_THRESH` 的像素就算蓝色。

```python
dominance = b.astype(int16) - max(g, r).astype(int16)   # 用 int16，避免负值被截断为 0
mask = dominance >= DIFF_THRESH
```

选它的原因：场地里的橙色灯条和边线都是红高蓝低，相减之后是负值，自然就被排除了。相比之下 HSV 会受到灯条中心过曝（饱和度下降）的影响，而这个方法的阈值含义很直接，就是“蓝色比红绿高出多少”。`tools/dump_channels.py` 会同时导出 HSV 法掩膜作对照，并打印两种方法的白像素占比。

### 4.2 几何筛选判据

这些判据都是相对量或形状量，不依赖固定的像素坐标和帧号，所以画面平移、视角变化、上坡倾斜的片段同样适用。

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
| | `DIFF_THRESH` | `10` | 蓝度阈值：偏小会带入环境蓝光，偏大会漏掉暗侧灯条 |
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

画面标注：每帧左上角写三行，`frame: N` 是帧号（从 0 开始），`bars: N` 是该帧检出的灯条数量（没检出就是 0），`cost: x.x ms` 是该帧处理耗时，只统计颜色分割、形态学和轮廓筛选，不含写盘时间。

输出帧率：源视频容器报告 `1000 fps / 45468 帧`，两个都是假值。这个文件由 GStreamer `matroskamux` 录制，写入的是 1 ms 时间基准，OpenCV 把这个时间基准当成了帧率，FFmpeg 又据此把帧数估成 `时长 × 1000`。真实参数由程序自己测出来：

1. 解析 WebM/Matroska 文件头，得到真实时长 `45.468 s`；
2. 顺序解码，得到真实帧数 `634`；
3. 真实帧率 = `634 / 45.468 = 13.944 fps`。

输出视频就按 13.944 fps 写入（`src/video_io.py` 的 `source_fps()`），成片时长和原视频一致，不会倍速。实测输出文件：`634 帧 / 45.47 s / 13.944 fps / 1540×986`（高度比源少 1 像素，原因见第 4 节），与源视频逐帧对应。

控制台日志：运行时逐帧打印一行，方便核对逐帧处理，下面是示例输出：

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

## 8. 中间结果与对比

| 证据 | 路径 | 内容 |
| --- | --- | --- |
| 通道与颜色分割 | `outputs/screenshots/channels/` | `00_original`、`01_channel_B`、`02_channel_G`、`03_channel_R`、`04_gray`、`05_mask_blue_dominance`、`06_mask_hsv`，以及拼图 `07_channels_and_masks.png` |
| 形态学对比 | `outputs/screenshots/morphology/` | 5 组配置的掩膜与拼图 `morphology_compare.png`；控制台同时打印白像素占比、轮廓数、通过筛选数 |
| 轮廓与几何 | `outputs/screenshots/contours/` | 五联图 `contours_and_filtering.png`（原图 / 轮廓 / 多边形近似 / 旋转矩形 / 保留绿框与剔除红框）；控制台打印每个候选的面积、长宽比、填充率、倾角与剔除理由 |

通道与灰度的差别：`B`、`G`、`R` 三张图是把同一画面按通道拆开的结果。蓝色灯条在 B 通道最亮，在 R 通道几乎看不见，橙色场地元素正好相反。灰度图按亮度加权把三通道合成单通道，只留明暗、丢了颜色，所以单靠灰度没法把蓝色灯条跟白色数字、亮色边线分开，这也是选颜色分割而不选灰度的原因。

形态学对比结论：

| 配置 | 现象 |
| --- | --- |
| `A_none`（不处理） | 掩膜上有孤立小白点，灯条内部有细小空洞 |
| `B_open3` | 小白点被去掉，但灯条边缘被削掉一点 |
| `C_close3` | 空洞被补上，个别相邻灯条出现轻微粘连趋势 |
| `D_open3_close3`（当前配置） | 噪点与空洞都消除，且未把成对灯条连成一块 |
| `E_close5` | 闭运算核放大到 5×5，个别位置相邻灯条粘连成一个轮廓，面积与长宽比越界被剔除 |

所以最终保留开运算 3×3 加闭运算 3×3。好处是噪点和孔洞都清掉了，代价是灯条边缘各收缩约 1 像素，框选仍然紧贴灯条，不影响判定。

## 9. 边界情况

| 情况 | 处理 | 位置 |
| --- | --- | --- |
| 路径错误 / 文件打不开 | 打印 `[错误] 打不开视频: <路径>` 并返回状态码 1 | `main.py` 的 `cap.isOpened()` 判断 |
| 视频结束 | `cap.read()` 返回假即跳出循环，正常收尾并释放读写器 | `main.py` 循环条件 |
| 该帧没有有效灯条 | 照常写出该帧，只画 HUD 并标 `bars: 0`，不中断也不跳过 | `main.py` 循环体 |
| 阈值依赖固定坐标 / 帧号 | 全部判据用面积比例、长宽比、填充率、倾角等相对量 | `src/bar_detector.py` |

## 10. 已知问题

1. 源视频是可变帧率，帧间隔 3 ~ 90 ms（中位 76 ms），容器报告的 1000 fps 和 45468 帧都是假值。程序按“真实帧数 / 真实时长”输出恒定帧率视频，总时长一致，个别帧的时间点最多偏移约 ±40 ms。也是因为它，`tools/` 里取帧一律顺序读取，不按时间 seek，seek 会按假帧率换算，直接跳到文件末尾。
2. 形态学对比图是把整幅掩膜缩放的（1540×987 → 420 px 宽），灯条只占几个像素，细节看不太清，要看局部就去看 `outputs/screenshots/channels/05_mask_blue_dominance.png` 原图。
3. HUD 在左上角，灯条进到这块区域会被半透明底板挡住，必要时可以改 `visualize.py` 里的坐标。
4. VS Code 的 Pylance 对 opencv-python 的类型存根有重载误报（`MatLike` 和 `UMat` 两套重载），只在编辑器里显示波浪线，不影响运行。给 `read_frame` 加上 `-> np.ndarray` 返回注解就没了。
5. 输出视频是 `mp4v` 编码的 mp4，一些播放器解析 `mp4v` 时长偏保守，用 VLC 或 `ffprobe` 看时长比较准。

## 11. 参考来源

| 来源 | 用途 |
| --- | --- |
| 考核手册提供的 [Ubuntu 环境部署](https://blog.csdn.net/weixin_43628293/article/details/147103949) | 环境搭建 |
| 考核手册提供的 [Git 仓库构建](https://www.bilibili.com/video/BV1rsdQBpEV5/) | 仓库管理 |
| 考核手册提供的 [OpenCV 教程](https://www.runoob.com/opencv/opencv-tutorial.html) | OpenCV 入门 |
| OpenCV 官方文档：颜色空间转换、形态学操作、轮廓与 `approxPolyDP`、`minAreaRect` | 算法接口 |
| GStreamer matroskamux 采用 1 ms 时间基准 | 解释容器帧率被读成 1000 fps 的原因 |

## 12. 提交清单

| 材料 | 路径 |
| --- | --- |
| 标记视频 | `outputs/videos/task1_result.mp4` |
| 代表帧截图 | `outputs/screenshots/channels/`、`outputs/screenshots/morphology/`、`outputs/screenshots/contours/` |
| 参数对比说明 | 本文第 4.1、4.2、5、8 节 |
| 输入素材 | 考核提供的 `test_video2.webm` |

## 13. 版本核对

```bash
python -c "import sys, cv2, numpy; print(sys.version.split()[0], cv2.__version__, numpy.__version__)"
```
