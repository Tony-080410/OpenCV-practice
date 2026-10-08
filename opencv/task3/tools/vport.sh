#!/usr/bin/env bash
# 建立一对虚拟串口（伪终端对）：发送程序开 A 端，串口助手开 B 端。
#
# 用法：
#     bash tools/vport.sh                 # 链接建在 /tmp
#     bash tools/vport.sh ~/vport         # 换个目录
#
# 三个必须知道的点：
#   1. 每次重建，socat 打印的 /dev/pts/N 编号都会变，助手那边要重新选端口；
#   2. 两端必须分开：程序开 A、助手开 B，抢占同一个端点会两边都收发不了；
#   3. 前台运行，Ctrl-C 结束；结束后 /dev/pts/N 会消失，链接变成悬空的软链。
set -euo pipefail

DIR=${1:-/tmp}

if ! command -v socat >/dev/null 2>&1; then
    echo "缺少 socat。Ubuntu 上：sudo apt install socat" >&2
    exit 1
fi

mkdir -p "$DIR"
echo "正在建立虚拟串口对（保持本终端开着，Ctrl-C 结束）："
echo "  A 端  $DIR/ttyCV1A   <- 任务三程序：python main.py send --port $DIR/ttyCV1A ..."
echo "  B 端  $DIR/ttyCV1B   <- 串口助手用这一端"
echo "下面 socat 打印的两行 'N PTY is /dev/pts/N' 就是两个端点的真实设备号。"
echo
exec socat -d -d pty,raw,echo=0,link="$DIR/ttyCV1A" pty,raw,echo=0,link="$DIR/ttyCV1B"
