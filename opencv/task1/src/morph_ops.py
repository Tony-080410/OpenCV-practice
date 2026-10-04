"""形态学优化：掩膜进，掩膜出。参数全部来自 config, 便于成组对比。"""

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
    """先开运算去掉小白噪点，再闭运算补灯条内部的空洞。

    闭运算核不能过大：它会在两根相邻灯条之间架桥，把一对灯条连成一个大块。
    """
    result = mask
    kernel = make_kernel(open_ksize)
    if kernel is not None:
        result = cv2.morphologyEx(result, cv2.MORPH_OPEN, kernel)
    kernel = make_kernel(close_ksize)
    if kernel is not None:
        result = cv2.morphologyEx(result, cv2.MORPH_CLOSE, kernel)
    return result
