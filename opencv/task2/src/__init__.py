"""任务二源码包。

模块职责（与手册“程序职责划分”对应）：
    camera.py       取流
    tag_detect.py   只看“画面里有哪些 Tag”
    target.py       只看“哪个是我要的目标、结果是否可用”
    pose.py         只看“R、t 是多少”
    undistort.py    只看“畸变怎么处理”
    calibration.py  只看“相机参数怎么来”
    visualize.py    只画图，不做任何判断
    simulate.py     仿真画面（回归测试用，不参与实时流程）
"""
