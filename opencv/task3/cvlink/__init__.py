"""任务三的通信层：CV1 报文格式、串口链路、位姿来源、任务二桥接、预览。

包叫 cvlink 不叫 src：任务二顶层包就叫 src，还有个顶层模块 config，
而且任务二内部用的是顶层绝对导入（import config / from src.x import y）。
两边同名会静默互相遮蔽，导到对方的模块还不报错，结果全错。
所以本包叫 cvlink、本工程配置叫 t3config。详见 cvlink/task2bridge.py。
"""
