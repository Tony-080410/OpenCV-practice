"""生成 README 用的示意图：坐标系、角点次序、相机与变换关系。

输出：assets/docs/frames_and_corners.png
运行：python tools/make_docs_figures.py
"""
from __future__ import annotations

import math
import os
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config                                  # noqa: E402

OUT = config.ASSETS / "docs" / "frames_and_corners.png"
W, H = 1680, 940
CJK_FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
BLACK, GRAY, BLUE, RED, GREEN = (0, 0, 0), (150, 150, 150), (30, 90, 200), (200, 40, 40), (20, 140, 60)


def font(px: int) -> ImageFont.FreeTypeFont:
    for p in CJK_FONTS:
        if pathlib.Path(p).exists():
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


def arrow(d: ImageDraw.ImageDraw, p0, p1, color=BLACK, width=3, head=14) -> None:
    d.line([p0, p1], fill=color, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    for s in (+1, -1):
        a = ang + math.pi - s * 0.42
        d.line([p1, (p1[0] + head * math.cos(a), p1[1] + head * math.sin(a))],
               fill=color, width=width)


def dot(d: ImageDraw.ImageDraw, p, r=7, color=RED) -> None:
    d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)


def label_box(d: ImageDraw.ImageDraw, xy, text, f, color=BLACK, anchor="mm",
              pad=5) -> None:
    """带白底的标注：线交叉处也能看清，不用为了避让把版面挪来挪去。"""
    x0, y0, x1, y1 = d.textbbox(xy, text, font=f, anchor=anchor)
    d.rectangle([x0 - pad, y0 - pad, x1 + pad, y1 + pad], fill=(255, 255, 255))
    d.text(xy, text, font=f, fill=color, anchor=anchor)


def tag_texture(px: int) -> np.ndarray:
    """官方图案的黑框外边部分（8x8 单元），放大到 px x px。"""
    png = cv2.imread(str(config.TAG_PATTERN), cv2.IMREAD_GRAYSCALE)
    if png is None or png.shape != (10, 10):
        return np.full((px, px), 0, np.uint8)          # 退化：纯黑方块
    core = png[1:9, 1:9]
    s = max(1, px // 8)
    big = np.kron(core, np.ones((s, s), np.uint8))
    return big[:px, :px]


def panel_tag(d: ImageDraw.ImageDraw, img: Image.Image) -> None:
    """左图：Tag 正面、角点次序与 tag 系三根轴。"""
    cx, cy, side = 420, 500, 380
    tex = tag_texture(side)
    img.paste(Image.fromarray(tex).convert("L"), (cx - side // 2, cy - side // 2))
    d.rectangle([cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2],
                outline=GRAY, width=1)

    # 四个角：0 左下、1 右下、2 右上、3 左上（tag 系 x 右 y 下）
    corners = {"0 左下": (cx - side // 2, cy + side // 2),
               "1 右下": (cx + side // 2, cy + side // 2),
               "2 右上": (cx + side // 2, cy - side // 2),
               "3 左上": (cx - side // 2, cy - side // 2)}
    off = {"0 左下": (-24, 24), "1 右下": (24, 24), "2 右上": (24, -24), "3 左上": (-24, -24)}
    for name, (px, py) in corners.items():
        dx, dy = off[name]
        dot(d, (px, py), 8)
        tx, ty = px + dx * 1.6, py + dy * 1.6
        anchor = "lm" if dx > 0 else "rm"
        if dy < 0:
            ty -= 10
        d.text((tx, ty), f"corners[{name.split()[0]}] {name.split()[1]}",
               font=font(22), fill=RED, anchor=anchor)

    body = font(23)
    # tag 系三根轴
    arrow(d, (cx, cy), (cx + 190, cy), BLUE, 3)                    # x
    d.text((cx + 200, cy - 16), "x 右", font=body, fill=BLUE)
    arrow(d, (cx, cy), (cx, cy + 190), GREEN, 3)                   # y
    d.text((cx + 10, cy + 200), "y 下", font=body, fill=GREEN)
    # z 出纸面：原点画 ⊙，用引线把说明拉到 tag 外面，避免压住图案
    d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=BLACK, width=3)
    dot(d, (cx, cy), 5, BLACK)
    lx, ly = cx - side // 2 - 20, cy - 40
    d.line([(cx - 16, cy - 6), (lx, ly)], fill=BLACK, width=2)
    d.text((lx - 10, ly), "z 出纸面朝相机", font=font(21), fill=BLACK, anchor="rm")

    d.text((60, 60), "① Tag 局部坐标系与角点次序", font=font(30), fill=BLACK)
    d.text((60, 108), "corners[0..3] = 左下、右下、右上、左上（左下起、逆时针）",
           font=font(23), fill=BLACK)
    d.text((60, 146), "tag 系：原点在 Tag 中心，x 右、y 下、z 垂直纸面指向相机",
           font=font(23), fill=BLACK)
    d.text((60, 850), "⚠ 角点顺序错了不会报错，只会让位姿整体差 90°/180°（重投影残差依然很小）",
           font=font(23), fill=RED)


def panel_camera(d: ImageDraw.ImageDraw, img: Image.Image) -> None:
    """右图：相机光学系、变换关系、直线距离与 Z 深度。"""
    x0 = 900
    d.text((x0, 60), "② 相机光学系与变换关系", font=font(30), fill=BLACK)
    d.text((x0, 108), "相机系：原点在光心，X 右、Y 下、Z 向镜头前方（右手系）",
           font=font(23), fill=BLACK)
    d.text((x0, 146), "p_camera = R · p_tag + t（内部用米，通信转毫米）", font=font(23), fill=BLACK)

    cam = (x0 + 80, 640)                  # 光心
    foot = (x0 + 560, 640)                # Tag 在同一深度处的垂足
    tag_c = (x0 + 560, 470)               # Tag 中心（略高，便于把两条线分开）
    side = 150

    # 相机图标
    d.rounded_rectangle([cam[0] - 52, cam[1] - 62, cam[0] + 34, cam[1] + 62],
                        radius=10, outline=BLACK, width=3)
    d.ellipse([cam[0] + 16, cam[1] - 26, cam[0] + 94, cam[1] + 52], outline=BLACK, width=3)
    d.text((cam[0] - 54, cam[1] + 74), "相机光心", font=font(21), fill=BLACK)

    # Tag
    d.rectangle([tag_c[0] - side // 2, tag_c[1] - side // 2,
                 tag_c[0] + side // 2, tag_c[1] + side // 2], outline=BLACK, width=3)
    d.text((tag_c[0] - 24, tag_c[1] - side // 2 - 40), "Tag 中心", font=font(21), fill=BLACK)

    # 光轴：灰色虚线，延伸到 Tag 之后
    ox_end = tag_c[0] + 150
    x = cam[0] + 90
    while x < ox_end:
        d.line([(x, cam[1]), (min(x + 16, ox_end), cam[1])], fill=GRAY, width=2)
        x += 28
    d.text((ox_end + 8, cam[1] - 14), "Z 光轴", font=font(21), fill=GRAY)

    # Z 深度：光心 -> 垂足（沿光轴）
    d.line([cam, foot], fill=BLUE, width=4)
    label_box(d, ((cam[0] + foot[0]) / 2, cam[1] + 26), "Z 深度 t[2]（沿光轴）",
              font(22), BLUE)

    # 直线距离：光心 -> Tag 中心
    d.line([cam, tag_c], fill=RED, width=4)
    label_box(d, ((cam[0] + tag_c[0]) / 2 - 30, (cam[1] + tag_c[1]) / 2 - 30),
              "直线距离 |t| = √(x²+y²+z²)", font(22), RED)

    # 垂足到 Tag 中心的竖线，说明“同一深度”
    d.line([foot, tag_c], fill=GRAY, width=2)
    label_box(d, (foot[0] + 14, (foot[1] + tag_c[1]) / 2), "同一深度", font(19), GRAY,
              anchor="lm")

    d.text((x0 + 40, 810), "注意：直线距离与 Z 深度不是一回事，两个都要输出并区分",
           font=font(23), fill=RED)
    d.text((x0 + 40, 848), "t 三个分量 = Tag 中心在相机系中的位置，可带负号；有效目标 Z > 0",
           font=font(21), fill=BLACK)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    panel_tag(d, img)
    d.line([(860, 220), (860, 860)], fill=(220, 220, 220), width=2)
    panel_camera(d, img)
    d.text((60, 890), "由 tools/make_docs_figures.py 生成 —— 角点次序经实测确定（见 spike/RESULTS.md）",
           font=font(20), fill=GRAY)
    img.save(OUT)
    print(f"[完成] 示意图已生成 {OUT}（{img.width}x{img.height}）")
    return 0


if __name__ == "__main__":
    _code = main()
    sys.stdout.flush()
    os._exit(_code)
