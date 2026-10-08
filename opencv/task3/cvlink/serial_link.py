"""串口链路：只管把字节真写出去。

手册要求 115200 bit/s、8 数据位、无奇偶校验、1 停止位、无硬件/软件流控，
这里每项都写成显式字段，不靠 pyserial 的默认值。

手册的两条硬要求落在这：send() 用 write() 的返回值判断整帧有没有写完，
少一个字节就算失败，不能把发送端打印当成接收成功；打开失败时给出
可操作的提示（端口不存在 / 被占用 / 没权限），不把原始异常直接甩给用户。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import serial
from serial import SerialException

BYTESIZE_MAP = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS,
                8: serial.EIGHTBITS}
PARITY_MAP = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD,
              "M": serial.PARITY_MARK, "S": serial.PARITY_SPACE}
STOPBITS_MAP = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE,
                2: serial.STOPBITS_TWO}
FLOW_CHOICES = ("none", "rtscts", "xonxoff")

PTY_PREFIX = "/dev/pts/"


class LinkError(RuntimeError):
    """串口打不开或写不出去。"""


@dataclass
class LinkInfo:
    port: str
    real_path: str
    baudrate: int
    bytesize: int
    parity: str
    stopbits: float
    flow: str
    is_pty: bool
    note: str = ""

    def settings(self) -> str:
        flow = {"none": "无硬件/软件流控", "rtscts": "硬件流控 RTS/CTS",
                "xonxoff": "软件流控 XON/XOFF"}[self.flow]
        return f"{self.baudrate}/{self.bytesize}{self.parity}{self.stopbits:g}，{flow}"

    def describe(self) -> str:
        kind = ("伪终端（虚拟串口对：不模拟真实串口的物理速率，两端仍按上面的配置）"
                if self.is_pty else "物理串口")
        base = f"{self.port} → {self.real_path}：{kind}，{self.settings()}"
        return f"{base}；{self.note}" if self.note else base


class SerialLink:
    """with SerialLink(port) as link: link.send(data)"""

    def __init__(self, port: str, baudrate: int = 115200, bytesize: int = 8,
                 parity: str = "N", stopbits: float = 1, flow: str = "none",
                 timeout: float = 0.2, write_timeout: float = 1.0):
        if not port:
            raise LinkError("没有指定串口。先用 tools/vport.sh 建虚拟串口对，"
                            "再用 --port <设备> 指定（socat 会打印 /dev/pts/N 编号）")
        if parity not in PARITY_MAP:
            raise LinkError(f"不支持的校验方式 {parity!r}，可选 {sorted(PARITY_MAP)}")
        if bytesize not in BYTESIZE_MAP:
            raise LinkError(f"不支持的数据位 {bytesize!r}，可选 {sorted(BYTESIZE_MAP)}")
        if stopbits not in STOPBITS_MAP:
            raise LinkError(f"不支持的停止位 {stopbits!r}，可选 {sorted(STOPBITS_MAP)}")
        if flow not in FLOW_CHOICES:
            raise LinkError(f"不支持的流控 {flow!r}，可选 {FLOW_CHOICES}")
        self.port = port
        self.baudrate = int(baudrate)
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.flow = flow
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.ser: serial.Serial | None = None
        self.info: LinkInfo | None = None
        self.frames_sent = 0
        self.bytes_sent = 0

    # ------------------------------------------------------------------
    def open(self) -> LinkInfo:
        if self.ser is not None:
            return self.info
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=BYTESIZE_MAP[self.bytesize],
                parity=PARITY_MAP[self.parity],
                stopbits=STOPBITS_MAP[self.stopbits],
                timeout=self.timeout,
                write_timeout=self.write_timeout,
                rtscts=(self.flow == "rtscts"),
                xonxoff=(self.flow == "xonxoff"),
                dsrdtr=False,
            )
        except (SerialException, OSError, ValueError) as e:
            raise LinkError(self.explain_failure(self.port, e)) from e

        real = os.path.realpath(self.port)
        is_pty = real.startswith(PTY_PREFIX)
        info = LinkInfo(self.port, real, self.baudrate, self.bytesize,
                        self.parity, self.stopbits, self.flow, is_pty)
        self.info = info
        return info

    @staticmethod
    def explain_failure(port: str, exc: Exception) -> str:
        """把打开失败的原始异常翻译成「下一步该查什么」。"""
        text = str(exc)
        low = text.lower()
        tips: list[str] = []
        if isinstance(exc, FileNotFoundError) or "no such file" in low or "errno 2" in low:
            tips.append("端口不存在：先跑 bash tools/vport.sh 建虚拟串口对；"
                        "注意每次重建 socat 后 /dev/pts/N 的编号都会变")
        if isinstance(exc, PermissionError) or "permission" in low or "errno 13" in low:
            tips.append("没有权限：物理串口通常要把用户加进 dialout 组"
                        "（sudo usermod -aG dialout $USER，重新登录生效）")
        if "busy" in low or "errno 16" in low:
            tips.append("端口被占用：发送程序和串口助手必须打开两个不同的端点，"
                        "不能抢占同一个")
        if isinstance(exc, ValueError) or "invalid" in low:
            tips.append("参数不合法：检查波特率与 8N1 设置")
        head = f"打不开串口 {port}：{text}"
        return head + "".join("\n       提示：" + t for t in tips)

    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self.ser is not None

    def send(self, data: bytes) -> int:
        """写出一整帧。写出的字节数不等于长度就算失败，不假装发成功了。"""
        if self.ser is None:
            raise LinkError("串口还没打开，不能发送")
        try:
            written = self.ser.write(data)
            self.ser.flush()          # 等数据真的离开缓冲区（tcdrain）
        except (SerialException, OSError) as e:
            raise LinkError(f"写串口 {self.port} 失败：{e}") from e
        written = int(written or 0)
        if written != len(data):
            raise LinkError(f"只写出 {written}/{len(data)} 字节，报文不完整")
        self.frames_sent += 1
        self.bytes_sent += written
        return written

    def close(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except (SerialException, OSError):
                pass
            finally:
                self.ser = None

    def __enter__(self) -> "SerialLink":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
