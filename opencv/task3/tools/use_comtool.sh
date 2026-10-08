#!/usr/bin/env bash
# 让「下拉框型」串口助手（COMTool 等）能在端口列表里看到虚拟串口。
#
# 为什么需要这一步：GUI 助手靠**枚举**列端口，而 pyserial 的枚举
# （serial/tools/list_ports_linux.py）只按文件名 glob：
#     /dev/ttyS*  /dev/ttyUSB*  /dev/ttyXRUSB*  /dev/ttyACM*  /dev/ttyAMA*
#     /dev/rfcomm*  /dev/ttyAP*
# **不包含 /dev/pts/N**，所以伪终端对默认不会出现在助手的下拉框里
# （实测：枚举只给出 /dev/ttyS0…ttyS31 这些主板空 UART）。
#
# 因为它是按名字 glob 的，把 pty 软链成一个 /dev/ttyUSB* 名字就会被列出来
# （实测 pyserial 的 SysFS 类会保留这种软链）。Qt 系的助手（SerialPortAssistant）
# 是按 sysfs 枚举的，这个软链对它无效 —— 那种工具只能看它能不能手输端口名。
#
# /dev 目录普通用户不可写，所以这里要输一次密码。
#
# 用法：
#     bash tools/use_comtool.sh                # 把助手那一端（/tmp/ttyCV1B）链成 /dev/ttyUSB0
#     bash tools/use_comtool.sh /tmp/ttyCV1B   # 指定要暴露的端点
#     bash tools/use_comtool.sh remove         # 删掉软链
#
# 注意：每次重建 socat，/dev/pts/N 的编号都会变，需要重新执行本脚本。
set -euo pipefail

LINK=/dev/ttyUSB0

if [ "${1:-}" = "remove" ]; then
    sudo rm -f "$LINK"
    echo "已删除 $LINK"
    exit 0
fi

PORT=${1:-/tmp/ttyCV1B}          # 默认暴露 B 端：串口助手用这一端
if [ ! -e "$PORT" ]; then
    echo "找不到 $PORT —— 先跑 bash tools/vport.sh 建立虚拟串口对" >&2
    exit 1
fi
REAL=$(readlink -f "$PORT")

echo "把 $PORT（真实设备 $REAL）链成 $LINK，好让助手在端口列表里看到它。"
sudo ln -sf "$REAL" "$LINK"

echo "完成：$LINK -> $(readlink -f "$LINK")"
echo
echo "助手里的操作："
echo "  1. 端口下拉框点一下（COMTool 点击时会重新枚举）"
echo "  2. 选含 /dev/ttyUSB0 的那一项"
echo "  3. 115200 / 8 / N / 1，Flow control 选 None，rts、dtr 都不勾"
echo "  4. 点 OPEN"
echo
echo "程序侧仍然用原来的 A 端："
echo "  python main.py send --port $PORT的对应A端（默认 /tmp/ttyCV1A）..."
