"""形态学：掩膜进，掩膜出。参数从 config 取，方便成组对比。"""

import cv2

import config


def make_kernel(ksize):
    """把 int 或 (w, h) 转成矩形结构元素: 0/None/1 表示该步骤关闭。"""
    if ksize is None:
        return None
    if isinstance(ksize, int):
        ksize = (ksize, ksize)
    width, height = int(ksize[0]), int(ksize[1])
    if min(width, height) <= 1:
        return None
    return cv2.getStructuringElement(cv2.MORPH_RECT, (width, height))


def cleanup(mask, open_ksize=config.MORPH_OPEN_KSIZE, close_ksize=config.MORPH_CLOSE_KSIZE):
    """开运算去小白噪点，闭运算补灯条内部空洞。

    闭运算核大了会在相邻两根灯条之间架桥，连成一大块。
    """
    result = mask
    kernel = make_kernel(open_ksize)
    if kernel is not None:
        result = cv2.morphologyEx(result, cv2.MORPH_OPEN, kernel)
    kernel = make_kernel(close_ksize)
    if kernel is not None:
        result = cv2.morphologyEx(result, cv2.MORPH_CLOSE, kernel)
    return result
