# 任务三：模拟串口通信（CV1 文本协议）

把任务二解出的 AprilTag 三维位姿，按手册规定的自定义 ASCII 协议 CV1 持续发到串口，由串口助手作为接收端显示。链路用虚拟串口对（伪终端对）搭起来。

一条完整报文长这样（结尾是真的回车+换行）：

```text
$CV1,42,12345,1,0,100.0,-50.0,800.0,0.000000,0.000000,0.000000*33
```

本任务不含检测、位姿解算或标定代码，位姿一律来自任务二。实时源直接用它的 `Camera` + `PosePipeline`，字段取自它的 `PoseFrame.record()`。

---

## 1. 开发与运行环境

| 项目 | 版本 / 说明 |
| --- | --- |
| 操作系统 | Ubuntu 26.04 LTS |
| 语言 | Python 3.14.4 |
| 虚拟环境 | `~/Projects/PythonProjects/.venv` |
| 串口库 | pyserial 3.5（本任务唯一新增依赖） |
| 虚拟串口对 | `socat`（`sudo apt install socat`），Linux 伪终端对 |
| 接收端 | SerialPortAssistant（KangLin）或 COMTool；本仓库另附等价的命令行接收端 |
| 实时源依赖 | 复用任务二：OpenCV 5.0.0.93、numpy 2.5.3、pupil-apriltags 1.0.4.post11 |

安装与自检：

```bash
cd task3
source ../../.venv/bin/activate       # 或 ../../.venv/bin/python cvlink/main.py ... 直接跑
# 注意路径：仓库根在 PythonProjects，venv 与根同级，所以从 task3 出发是 ../../.venv
unset LD_LIBRARY_PATH                 # 本机 Hermes 运行时必需：否则 venv 里 pip/ssl 不可用
pip install -r requirements.txt

# 不碰串口、不碰相机的最小自检：协议是否与手册示例逐字节一致
python main.py selftest
```

## 2. 目录结构与职责划分

```text
task3/
├── main.py                    入口：selftest（协议自测）/ check（查串口）/ send（发送）
├── t3config.py                唯一参数表：串口、发送节奏、来源、显示
├── requirements.txt
├── cvlink/                    通信层（不叫 src，原因见第 7 节）
│   ├── protocol.py            纯协议层：字段 → CV1 字节（含异或校验、边界归一化）
│   ├── serial_link.py         串口链路：115200/8N1、打开失败的可操作提示、写入完整性检查
│   ├── pose_source.py         位姿来源：live 实时 / dump 重放 / examples 手册固定报文
│   ├── task2bridge.py         把任务二工程当依赖加载，并断言没有同名模块遮蔽
│   └── preview.py             可选预览窗（画状态 + 即将发出的那一行报文）
├── tools/
│   ├── selftest_protocol.py   协议自测：对拍手册给出的两帧（`*33` / `*09`）
│   ├── fake_receiver.py       等价接收端：独立实现，按 CRLF 拆帧、复算校验、写接收日志
│   └── vport.sh               建立虚拟串口对（socat）
└── outputs/logs/              发送日志与接收日志（考核要求的接收日志在这里）
```

职责划分配得上考核要求：报文格式只在 `protocol.py`（不 import 串口、不 import cv2），串口输出只在 `serial_link.py`（只认字节，不认识位姿），输入与参数在 `main.py` + `t3config.py`，位姿来源在 `pose_source.py`，实时接入任务二只在 `task2bridge.py`。

## 3. 三步走：先链路，再格式，最后接实时

顺序就是手册要求的排错顺序（先端口/设置/权限 → 再报文内容）。

### ① 建链路：虚拟串口对

```bash
bash tools/vport.sh                    # 前台运行，Ctrl-C 结束
#   A 端 /tmp/ttyCV1A  <- 本程序用这一端
#   B 端 /tmp/ttyCV1B  <- 串口助手用这一端
#   socat 打印的两行 "N PTY is /dev/pts/N" 就是真实设备号
```

```bash
python main.py check --port /tmp/ttyCV1A      # 只检查能否按 115200/8N1 打开
```

> 每次重建 socat，`/dev/pts/N` 的编号都会变（实测两次分别是 2/3 与 0/1），助手里要重新选端口。两端必须分开：程序和助手各开一个，抢占同一个会两边都收发不了。

### ② 用已知数值验证链路与校验

```bash
python main.py send --port /tmp/ttyCV1A --source examples --loop --max-frames 6 \
       --log outputs/logs/task3_send_examples.txt
```

`--source examples` 发的就是手册给的那两帧固定报文（含手册算好的校验），所以助手屏幕上应该能原样看到 `*33` / `*09`。另一边用等价接收端核对：

```bash
python tools/fake_receiver.py --port /tmp/ttyCV1B --max-frames 6 \
       --log outputs/logs/task3_recv_examples.txt
```

### ③ 接入任务二的实时位姿

```bash
# 方式一：实时（进程内用任务二的相机与解算；需要先完成任务二的标定）
python main.py send --port /tmp/ttyCV1A --source live --show \
       --log outputs/logs/task3_send_live.txt

# 还没标定时先验证通路（位姿数值不可信，只证明链路与字段）
python main.py send --port /tmp/ttyCV1A --source live --no-calib --max-frames 60

# 方式二：重放任务二 dump 出的逐帧位姿（没有相机也能验证字段）
cd ../task2 && python main.py demo --no-show --max-frames 40 --dump /tmp/pose.jsonl
cd ../task3 && python main.py send --port /tmp/ttyCV1A --source dump --dump /tmp/pose.jsonl

# 只看报文、不写串口
python main.py send --dry-run --source examples --max-frames 4
```

演示「检测到目标 → 目标消失 → 再次出现」：`--source live --show` 时把 Tag 拿出画面再放回，预览窗上能同时看到 `valid` 翻转与即将发出的那一行报文；接收侧对应的证据是接收日志（见第 9 节）。

## 4. 运行方式与输出路径

所有命令都在 `task3` 目录下执行。

| 命令 | 产物 | 输出路径 |
| --- | --- | --- |
| `main.py selftest` | 无文件 | —（只打印协议自测结果） |
| `main.py check --port <端口>` | 无文件 | —（只检查串口能否按 8N1 打开） |
| `main.py send`（不给 `--log`） | 无文件 | —（只打印到终端 / 写串口） |
| `main.py send --log <路径>` | 发送日志：首行注释 + 实际写出的字节 | 由 `--log` 指定，例如 `outputs/logs/task3_send_live.txt`；同名旧文件会被覆盖 |
| `main.py send --show` 中按 `s` | 当前预览截图 | `outputs/screenshots/task3_send_NNNNNN.png`（NNNNNN 在一次运行内从 0 递增，重新运行会从 0 覆盖） |
| `tools/fake_receiver.py`（不给 `--log`） | 无文件 | —（只打印到终端） |
| `tools/fake_receiver.py --log <路径>` | 接收日志：首行注释 + 收到的原始字节 | 由 `--log` 指定，例如 `outputs/logs/task3_recv_examples.txt`；同名旧文件会被覆盖 |
| `tools/selftest_protocol.py` | 无文件 | —（等价于 `main.py selftest`） |
| `tools/vport.sh` | 两个软链 + 一对伪终端 | 默认 `/tmp/ttyCV1A`、`/tmp/ttyCV1B`（可用第一个参数换目录） |
| `tools/use_comtool.sh` | 一个软链，让 GUI 助手能在端口列表里看到虚拟串口 | `/dev/ttyUSB0` → 助手那一端的真实设备；`remove` 参数删除它（需要输一次密码，见第 5 节） |

`outputs/logs` 与 `outputs/screenshots` 首次运行自动创建，不需要手动建目录；所有路径定义在 `t3config.py` 的「路径」与「显示」两节。

常用参数：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--port` | `t3config.SERIAL_PORT`（空） | 串口设备；留空必须显式给，否则报错并提示先建虚拟串口对 |
| `--source` | `live` | `live` 实时接入任务二 / `dump` 重放 JSONL / `examples` 手册固定报文 |
| `--rate` | `10.0` | 发送频率 Hz（手册建议约 10，不考核精确频率；必须为正） |
| `--seconds` / `--max-frames` | `0` / `0` | 运行秒数 / 最多帧数，0 表示不限 |
| `--dry-run` | 关 | 不写串口，只打印报文（`--log` 仍会记下「本应发出的字节」） |
| `--loop` | 关 | `dump` / `examples` 重放到底后从头再来 |
| `--show` | 关 | 开预览窗（仅 `live` 有画面；`q`/`ESC` 退出，`s` 截图） |
| `--no-calib` | 关 | 不加载标定参数，仅通路自测（内参为估值，位姿数值不可信） |
| `--tag-mm` / `--target-id` | 用任务二 config | 临时覆盖 Tag 实测边长 / 目标 ID |
| `--task2-dir` | `../task2` | 任务二工程目录 |
| `--empty-limit` | `30` | 连续取帧失败多少次后收尾（0 表示一直发无效报文、不收尾） |
| `--baud/--bytesize/--parity/--stopbits/--flow` | `115200/8/N/1/none` | 串口设置，默认即手册要求的 115200/8N1 无流控 |

## 5. 串口设置与链路

* 手册要求 115200 bit/s、8 数据位、无奇偶校验、1 停止位、无硬件与软件流控（115200/8N1）。代码里每一项都是显式参数（`rtscts=False, xonxoff=False, dsrdtr=False`），不依赖库的默认值。
* 虚拟端点不模拟物理速率（手册原话）：两端仍按 8N1 配置，`check` 会打印实际设置；它只是不按 115200 真的定时收发。
* GUI 助手默认看不到 `/dev/pts/N`，这是本任务最容易卡住的一步。这类工具靠枚举列端口，而 pyserial 的枚举（`serial/tools/list_ports_linux.py`）只按名字 glob
  `/dev/ttyS* /dev/ttyUSB* /dev/ttyXRUSB* /dev/ttyACM* /dev/ttyAMA* /dev/rfcomm* /dev/ttyAP*`，
  Qt 系助手（SerialPortAssistant）则按 sysfs 枚举，两边都不包含伪终端。
  本机实测：枚举只给出 `/dev/ttyS0…ttyS31` 这些主板空 UART，下拉框里选不到虚拟串口。
  三条出路：
  1. `bash tools/use_comtool.sh`，把助手那一端软链成 `/dev/ttyUSB0`。pyserial 是按名字
     glob 的，所以软链会被列进端口表（实测 pyserial 的 `SysFS` 类保留这种软链）；
     Qt 系助手吃不到这个软链。需要输一次密码，且每次重建 socat 后要重做。
  2. `python -m serial.tools.miniterm <端口> 115200 -q --raw`，pyserial 自带，
     接受任意路径，不受枚举限制（本仓库实测能原样收到报文）；终端界面，不是 GUI。
  3. 助手若支持手输端口名，直接填 `/dev/pts/N`。

  COMTool 的安装与操作（本机实测可用）：
  ```bash
  python3 -m venv ~/.venvs/comtool
  ~/.venvs/comtool/bin/pip install comtool audioop-lts   # audioop-lts 见第 10 节第 7 条
  bash tools/use_comtool.sh                              # 暴露 /dev/ttyUSB0（输一次密码）
  ~/.venvs/comtool/bin/comtool
  ```
  界面里：端口下拉点一下（点击时会重新枚举）→ 选含 `/dev/ttyUSB0` 的那一项 →
  115200 / 8 / N / 1、Flow control 选 None、rts 与 dtr 都不勾 → OPEN。
  程序侧仍用 A 端（`/tmp/ttyCV1A`），两边不能是同一个端点。
* 打开失败时给的是下一步动作，不是原始异常：端口不存在 → 提示先跑 `vport.sh` 且编号会变；
  被占用 → 提示两端不能是同一个端点；没权限 → 提示物理串口要加 `dialout` 组。
* 发送成功与否看 `write()` 的返回值：写入字节数不等于报文长度就判失败并报错退出，
  不能把「发送端打印了一行」当成发送成功（手册 Tips 明确要求）。
* 本任务只发不收，不要求结果过期计时、接收超时检测或多线程，所以发送循环是单线程 + 绝对节拍。

## 6. CV1 报文格式

```text
$CV1,seq,t_ms,valid,id,x_mm,y_mm,z_mm,rx,ry,rz*HH\r\n
```

| 字段 | 定义 | 本实现 |
| --- | --- | --- |
| `$`、`CV1` | 帧起始符与协议版本 | 固定；校验从 `C` 开始算 |
| `seq` | 32 位无符号发送序号，从 0 开始每帧 +1，到最大值回绕；重启可重置 | 每发一帧 `(seq+1) & 0xFFFFFFFF`；超出范围按掩码回绕并告警 |
| `t_ms` | 本报文生成时相对于程序启动的单调时间，毫秒 | `time.monotonic() - t0`；负数归零 |
| `valid` | 1 = 检测到指定目标且位姿可用；0 = 不可用 | 直接取任务二的判定；不沿用上一帧旧位姿 |
| `id` | 有效时为选中 Tag 的 ID；无效时 -1 | 无效帧强制 -1（valid=1 却给负 id 会降级为无效并告警） |
| `x_mm,y_mm,z_mm` | Tag 中心在相机光学系中的平移，毫米，可带负号 | 取任务二 `record()`（那一层已把米换算成毫米），1 位小数 |
| `rx,ry,rz` | 与 R 等价的 Rodrigues 旋转向量，弧度 | 取任务二 `PoseResult.rvec`，6 位小数；不是欧拉角 |
| `*HH` | `$` 与 `*` 之间所有 ASCII 字节逐字节异或，初值 0，两位大写十六进制 | 不含 `$`、`*`、校验字符与换行；`f"{v:02X}"` |

排版规则与实现细节：

* `\r\n` 是真正发送的两个字节；发送日志里保留原始 CRLF，所以日志本身就是字节流。
* 不含空格，数字用英文小数点；坐标 1 位小数、旋转向量 6 位小数；`f"{v:.1f}"` 天然不使用科学计数法。
* 坐标在 ±0.05 mm 以内会被 round 成 `-0.0`，这里统一收敛成 `0.0`（语法合法但没必要难看）。
* 无效报文：`valid=0` 时 `id=-1`、坐标与姿态统一置零。协议层会强制这一点，
  并且如果上游给的内容与规定不符，会打印告警说明已被改掉，不悄悄改。
* `nan` / `inf` 绝不发出去：出现非有限值就整帧降级为无效报文（否则面会被污染成 `nan`）。
* 手册两帧示例是实现的基准，`main.py selftest` 逐字节对拍：

```text
$CV1,42,12345,1,0,100.0,-50.0,800.0,0.000000,0.000000,0.000000*33
$CV1,43,12445,0,-1,0.0,0.0,0.0,0.000000,0.000000,0.000000*09
```

## 7. 实时接入任务二：为什么包叫 cvlink、配置叫 t3config

任务二的模块内部用的是顶层绝对导入（`import config`、`from src.tag_detect import ...`），所以要让它们可用，必须把 task2 目录放上 `sys.path`，并且顶层名字 `config`、`src` 必须解析到 task2。如果本工程也用这两个名字，Python 不会报错，只会静默导入对面那个模块，结果全错（例如拿到任务二的串口/Tag 参数）。因此：

* 本工程的包叫 `cvlink`，配置叫 `t3config.py`；
* task2 目录追加到 `sys.path` 末尾（不是插到最前），本工程自己的模块优先；
* `cvlink/task2bridge.py` 加载完成后立刻断言 `config` / `src` 确实来自 task2 目录，
  一旦将来有人加了同名的 `config.py` 或 `src/`，会当场失败而不是悄悄用错模块。

数据走进程内直取，不走文件或子进程：每个发送周期调用任务二的
`PosePipeline.process(frame)`，再取 `PoseFrame.record(seq, t_ms)` 作为要发的字段
（该字典里多出的 `distance_mm` 不属于协议字段，协议层只取自己认识的键）。

## 8. 边界情况与异常处理

| 情况 | 处理 | 位置 |
| --- | --- | --- |
| 打不开相机 / 相机被占用 | 打印 `[错误]` 与排查提示（浏览器会抢占），退出码 1 | `pose_source.py` |
| 没有标定参数（未加 `--no-calib`） | 明确报错并给出两条出路（先标定 / 加 `--no-calib`），退出码 1 | `pose_source.py` |
| 标定分辨率与相机实际不一致 | 启动时打印 `[警告]`，说明位姿会明显偏差 | `pose_source.py` |
| 未检测到指定 ID / 解算失败 | 照发 `valid=0, id=-1`、坐标与姿态置零的无效报文 | `pose_source.py` + `protocol.py` |
| 读取到空帧 | 同样照发无效报文；连续失败超过 `--empty-limit` 才收尾 | `pose_source.py` |
| 目标再次出现 | 序号继续递增，恢复 `valid=1`（不重置 seq） | `main.py` |
| 串口打不开 / 被占用 / 没权限 | 翻译成可操作的提示，退出码 1 | `serial_link.py` |
| 写串口字节数不足 / 写失败 | 报错并中止，退出码 1（不假装发送成功） | `serial_link.py` |
| dump 文件不存在 / 某行不是 JSON / 空文件 | 逐条给出明确错误，退出码 1 | `pose_source.py` |
| dump 或 examples 重放到底 | 打印来源结束原因后正常收尾（不再多发一帧） | `pose_source.py` + `main.py` |
| `--rate <= 0`、`--tag-mm <= 0`、`--empty-limit < 0` | 参数下界校验，直接报错退出码 1 | `main.py` |

## 9. 本次实际验证记录（都是跑出来的）

| 验证 | 命令 | 结果 |
| --- | --- | --- |
| 协议自测 | `python main.py selftest` | 全部通过；手册两帧逐字节重现，校验复算 `33` / `09` 与手册一致 |
| 链路（固定报文） | `send --source examples --loop --max-frames 6` + 等价接收端 | 发出 6 帧、收到 6 帧、不合规 0 帧；覆盖 `首帧 valid=1 → 目标消失 → 目标重现` |
| 发送/接收日志一致性 | `--log` 两侧各一份 | 两侧字节流逐字节相同（examples 387 B；dump 重放任务二真实位姿 35429 B / 538 帧），且含真 CRLF、无字面量 `\r\n` |
| 链路（重放任务二真实 dump） | `send --source dump --dump ../task2/outputs/logs/pose.jsonl` + 等价接收端 | 538 帧全部合规、序号 0…537 连续，`--strict-seq` 下序号异常 0 次；其中 274 帧有效，与任务二演示那次的有效帧数一致 |
| 实时接入任务二（真实检测） | 打印 Tag 实测 + 标定完成后 `send --source live --log outputs/logs/task3_send_live.txt` | 292 帧全部合规、`seq` 0…291 连续、230 帧有效（78.8%），覆盖 出现 → 消失 → 重现 |
| 助手侧接收（与上一行同一次运行） | COMTool 接收显示区，人工复制成 `outputs/logs/task3_recv_comtool.txt` | 292 帧、校验全部合规；与发送日志逐帧比对 **0 处不同** |
| 入口矩阵（含错误路径） | 14 条命令 | 成功/失败的退出码全部与预期一致（0 / 1） |
| 预览绘制（无头） | 直接调用 `preview.draw` / `save_shot` | 有效帧与无效帧都能叠加状态与报文；无画面来源返回 `None`；截图落盘成功 |

`examples` 与 `dump` 两对都是**同一次运行**里收发各写一份日志（`--log` 两侧）：日期相同、帧数相同、字节流逐字节一致。`dump` 那对重放的是任务二演示那次的真实位姿（538 帧、274 帧有效），和演示视频同源；`examples` 那对用的是手册固定报文。

`live` 那次的收发两侧都有日志：发送侧 292 帧、230 帧有效，接收侧是 COMTool 显示区复制下来的 292 帧，与发送日志逐帧比对 0 处不同。`examples`、`dump` 两对同样都是收发各一份、逐字节一致。