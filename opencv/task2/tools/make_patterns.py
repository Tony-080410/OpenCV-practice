"""生成打印级标定素材（尺寸精确，打印后可直接量）

产物（默认参数）：
  assets/patterns/tag36h11_00000_official.png           官方图案原件（10x10 单元，含 1 单元白边）
  assets/patterns/apriltag_36h11_id0_100mm.pdf[/.png]   tag 页，黑框外边精确 100.0 mm
  assets/patterns/chessboard_9x6_20mm.pdf[/.png]        棋盘格页，9x6 内角点，方格 20.0 mm
  assets/patterns/apriltag_36h11_id0_phone_screen.png   手机全屏显示用（不打印也能先试检测）

常用参数：
  --tag-mm 100        改 tag 黑框外边（手册建议 80~120 mm）
  --square-mm 25 --page a3    大方格需换 A3；25 mm 方格在 A4 上放不下页眉+校验尺
  --screen            只生成手机屏幕测试图

要点：
  * 图案取自 AprilTag 官方仓库 AprilRobotics/apriltag-imgs（手册要求“使用官方图案”），
    不是自己画的，也不是别的库重排过的（官方图案与 OpenCV aruco 生成的差了 180°）。
  * 位姿解算用的边长是“黑框外边”，官方图案为 8x8 单元，故 8 x 单元边长。
  * 每个 PDF 内都印了一把 100 mm 校验尺：打印后量一下，误差超过约 1% 说明被缩放，
    必须选“实际大小 / 100%”，不要用“适合页面”。
  * 页面四周留白远大于 1 个单元的静默区，方向标记也放在静默区之外，不影响检测。

运行：python tools/make_patterns.py
"""
import argparse
import os
import pathlib
import sys
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OFFICIAL_URL = ("https://raw.githubusercontent.com/AprilRobotics/apriltag-imgs/"
                "master/tag36h11/tag36_11_{id:05d}.png")
A4_MM = {"portrait": (210, 297), "landscape": (297, 210)}
A3_MM = {"portrait": (297, 420), "landscape": (420, 297)}
PAGES = {"a4": A4_MM, "a3": A3_MM}
PPMM = 12.0                                  # 像素/毫米 → 304.8 dpi
CJK_FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
QUIET_MM = 25.0                              # 图案与任何印刷标记的最小距离

# 保活表：实测 OpenCV 5.0.x + apriltag 在释放 main() 局部变量/解释器退出时会随机段错误
# （exit 139，且重定向输出时可能整段丢失）。把重对象挂在这里活到 os._exit 避开该清理。
_KEEP_ALIVE: list = []


def font(size_mm):
    px = max(8, int(size_mm * PPMM))
    for p in CJK_FONTS:
        if pathlib.Path(p).exists():
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


def text_block(draw, x_mm, y_mm, lines):
    """按固定行距排一组文字，避免中文字挤在一起。lines: [(文字, 字号mm), ...]"""
    y = y_mm
    for s, size in lines:
        draw.text((x_mm * PPMM, y * PPMM), s, font=font(size), fill=0)
        y += size * 1.75
    return y


def draw_ruler(draw, x_mm, y_mm, length_mm, note):
    """画一把校验尺：主线 + 每 10 mm 刻度。y_mm 是主线的纵坐标。"""
    x0, y0 = x_mm * PPMM, y_mm * PPMM
    x1 = x0 + length_mm * PPMM
    draw.line([(x0, y0), (x1, y0)], fill=0, width=max(1, int(0.4 * PPMM)))
    for i in range(int(length_mm // 10) + 1):
        xx = x0 + i * 10 * PPMM
        h = (5 * PPMM if i % 5 == 0 else 3 * PPMM)
        draw.line([(xx, y0 - h / 2), (xx, y0 + h / 2)], fill=0, width=max(1, int(0.3 * PPMM)))
    draw.text((x0, y0 + 3 * PPMM), note, font=font(3.4), fill=0)


def fetch_official(dest: pathlib.Path, tag_id: int = 0) -> np.ndarray:
    """取官方 tag36h11 指定 ID 的图案；已存在（且合法）则直接用本地副本。"""
    if dest.exists():
        img = cv2.imread(str(dest), cv2.IMREAD_GRAYSCALE)
        if img is not None and img.shape == (10, 10):
            return img
    url = OFFICIAL_URL.format(id=tag_id)
    req = urllib.request.Request(url, headers={"User-Agent": "rm-task2"})
    dest.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    img = cv2.imread(str(dest), cv2.IMREAD_GRAYSCALE)
    assert img is not None and img.shape == (10, 10), f"官方图案异常: {img.shape}"
    return img


def make_tag_page(tag: np.ndarray, edge_mm: float, out: pathlib.Path,
                  page_key: str = "a4"):
    """tag 页：黑框外边 = edge_mm；官方图案自带 1 单元白边，四周再留静默区。"""
    cells = tag.shape[0]                        # 10
    cell_mm = edge_mm / 8.0                     # 黑框外边跨 8 个单元
    cell_px = int(round(cell_mm * PPMM))
    tag_px = cell_px * cells
    big = np.kron(tag, np.ones((cell_px, cell_px), np.uint8))
    assert big.shape == (tag_px, tag_px)
    page_w, page_h = [int(v * PPMM) for v in PAGES[page_key]["portrait"]]
    page = Image.new("L", (page_w, page_h), 255)
    ox, oy = (page_w - tag_px) // 2, int(page_h * 0.52) - tag_px // 2
    page.paste(Image.fromarray(big), (ox, oy))
    d = ImageDraw.Draw(page)
    fx0, fy0 = ox + cell_px, oy + cell_px
    fx1, fy1 = ox + tag_px - cell_px, oy + tag_px - cell_px
    # 四周留白都要够（图案自带 1 单元白边之外再留静默区），任何一边贴边都会影响检测
    assert min(fx0, fy0, page_w - fx1, page_h - fy1) / PPMM >= QUIET_MM

    text_block(d, 15, 14, [
        ("AprilTag  tag36h11  ID 0（官方图案，AprilRobotics/apriltag-imgs）", 5.0),
        (f"黑框外边 = {edge_mm:.1f} mm —— 位姿解算用的就是这个边长", 3.6),
        (f"含白边整张 = {cell_mm * cells:.1f} mm，四周留白别裁掉", 3.2),
        ("打印选「实际大小 / 100%」，不要缩放；打印后用页脚校验尺复核", 3.2),
    ])

    # 方向标记：放在静默区之外，只指示“这一边朝上”
    mid = (fx0 + fx1) // 2
    ty = fy0 - int(18 * PPMM)
    d.line([(mid, ty - int(5 * PPMM)), (mid, ty)], fill=0, width=int(0.5 * PPMM))
    d.polygon([(mid, ty - int(6 * PPMM)), (mid - int(1.5 * PPMM), ty - int(3 * PPMM)),
               (mid + int(1.5 * PPMM), ty - int(3 * PPMM))], fill=0)
    d.text((mid + int(3 * PPMM), ty - int(6 * PPMM)), "这一边朝上（方向标记）", font=font(3.2), fill=0)

    draw_ruler(d, 15, page_h / PPMM - 32, 100.0, "校验尺 100.0 mm：量出偏差 > 1 mm 就重新打印")
    text_block(d, 15, page_h / PPMM - 22, [
        ("打印裁剪后请实测黑框外边，把实测值填进 config.py（程序用的是实测值，不是标称值）", 3.2),
    ])

    page.save(out, "PDF", resolution=PPMM * 25.4)
    page.save(out.with_suffix(".png"), "PNG", resolution=PPMM * 25.4)
    return dict(page=page, frame_mm=((fx1 - fx0) / PPMM, (fy1 - fy0) / PPMM),
                cell_px=cell_px, tag_mm=cell_mm * cells, edge_mm=edge_mm)


def make_chessboard_page(cols, rows, square_mm, out, page_key="a4"):
    """棋盘格页：cols x rows 为内角点数，方格数 = cols+1 x rows+1。
    页眉与校验尺共需约 58 mm 纵向空间，放不下时换 A3 或减小方格边长。"""
    sq = int(round(square_mm * PPMM))
    n_r, n_c = rows + 1, cols + 1
    rr = np.arange(n_r).repeat(sq)[:, None]
    cc = np.arange(n_c).repeat(sq)[None, :]
    board = np.where(((rr + cc) % 2 == 1), 255, 0).astype(np.uint8)   # (0,0) 为黑
    bh, bw = board.shape
    assert (bw, bh) == (n_c * sq, n_r * sq)

    pages = PAGES[page_key]
    if bw > bh:
        page_mm, orient = pages["landscape"], "landscape"
    else:
        page_mm, orient = pages["portrait"], "portrait"
    page_w, page_h = [int(v * PPMM) for v in page_mm]
    need_w, need_h = bw + 25 * PPMM, bh + 58 * PPMM
    assert need_w < page_w and need_h < page_h, (
        f"棋盘格 {bw/PPMM:.0f}x{bh/PPMM:.0f} mm 连页眉校验尺放不下 {page_key.upper()}{orient}："
        f"需要 {need_w/PPMM:.0f}x{need_h/PPMM:.0f} mm，页面只有 {page_w/PPMM:.0f}x{page_h/PPMM:.0f} mm。"
        f"请改 --page a3 或减小 --square-mm")

    page = Image.new("L", (page_w, page_h), 255)
    ox, oy = (page_w - bw) // 2, int(page_h * 0.56) - bh // 2
    page.paste(Image.fromarray(board), (ox, oy))
    d = ImageDraw.Draw(page)
    text_block(d, 15, 14, [
        (f"棋盘格：{cols} x {rows} 个内角点（{cols + 1} x {rows + 1} 个方格）", 5.0),
        (f"方格边长 = {square_mm:.1f} mm；打印务必选「实际大小 / 100%」", 3.6),
        (f"棋盘整体 {bw / PPMM:.1f} x {bh / PPMM:.1f} mm，整张贴平在硬板上，不要折",
         3.2),
        ("标定用棋盘格；AprilTag 另配一张（两者职责不同，不要混用）", 3.2),
    ])
    draw_ruler(d, 15, page_h / PPMM - 22, 100.0, "校验尺 100.0 mm：量出偏差 > 1 mm 就重新打印")
    page.save(out, "PDF", resolution=PPMM * 25.4)
    page.save(out.with_suffix(".png"), "PNG", resolution=PPMM * 25.4)
    return dict(page=page, orient=orient, board_mm=(bw / PPMM, bh / PPMM),
                square_mm=square_mm, inner=(cols, rows))


def make_screen_image(tag: np.ndarray, out: pathlib.Path, tag_id: int = 0,
                      canvas: int = 1200, fill: float = 0.86) -> dict:
    """手机/平板全屏显示用：白底、tag 居中放大，屏幕上的实际尺寸由设备决定，必须实测。

    用途：还没打印 Tag 时，把这张图传到手机上全屏显示，举到摄像头前就能先试通
    「检测 + 位姿 + 显示」这条路；量出屏幕上黑框外边的实际毫米数后，用
    `main.py demo --tag-mm <实测值>` 跑，位姿数值才有意义。
    """
    cells = tag.shape[0]
    cell_px = int(canvas * fill / cells)        # 每单元像素（整数，避免边缘不齐）
    tag_px = cell_px * cells
    big = np.kron(tag, np.ones((cell_px, cell_px), np.uint8))
    page = Image.new("L", (canvas, canvas + int(canvas * 0.14)), 255)
    ox, oy = (page.width - tag_px) // 2, int(page.height * 0.42) - tag_px // 2
    page.paste(Image.fromarray(big), (ox, oy))
    d = ImageDraw.Draw(page)
    d.text((canvas * 0.05, page.height - canvas * 0.10),
           f"tag36h11 ID {tag_id} —— 全屏显示，屏幕亮度调高、别开护眼/夜览模式",
           font=font(1.0), fill=0)
    d.text((canvas * 0.05, page.height - canvas * 0.06),
           "举到摄像头前 30~80 cm；先量出屏幕上黑框外边的毫米数，再跑 "
           "main.py demo --tag-mm <实测值>",
           font=font(1.0), fill=0)
    page.save(out, "PNG")
    return dict(path=out, tag_px=tag_px, cell_px=cell_px)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag-mm", type=float, default=100.0, help="tag 黑框外边边长（mm，手册建议 80~120）")
    ap.add_argument("--square-mm", type=float, default=20.0,
                    help="棋盘格方格边长（mm）；A4 上 20 比较稳，25 需要 --page a3")
    ap.add_argument("--page", choices=["a4", "a3"], default="a4", help="打印纸张（默认 a4）")
    ap.add_argument("--inner-cols", type=int, default=9)
    ap.add_argument("--inner-rows", type=int, default=6)
    ap.add_argument("--tag-id", type=int, default=0, help="官方 tag36h11 的 ID（默认 0，可多打几个练手）")
    ap.add_argument("--outdir", default="assets/patterns")
    ap.add_argument("--screen", action="store_true",
                    help="只生成手机屏幕测试图（不打印也能先试检测）")
    a = ap.parse_args()
    if a.tag_mm <= 0 or a.square_mm <= 0:
        print("[错误] --tag-mm 与 --square-mm 必须为正数")
        return 1
    if not 80.0 <= a.tag_mm <= 120.0:
        print(f"[警告] --tag-mm={a.tag_mm:g} 超出手册建议的 80~120 mm"
              f"（位姿按实测值算，尺寸偏差会直接放大成距离偏差）")

    outdir = pathlib.Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    tag = fetch_official(outdir / f"tag36h11_{a.tag_id:05d}_official.png", a.tag_id)
    print(f"[1] 官方图案就位 id={a.tag_id} {tag.shape}（10x10 单元，含 1 单元白边）")

    if a.screen:
        spec = make_screen_image(tag, outdir / f"apriltag_36h11_id{a.tag_id}_phone_screen.png",
                                 a.tag_id)
        print(f"[2] 屏幕测试图 {spec['path'].name}（tag {spec['tag_px']}px ≈ {spec['cell_px']}px/单元）")
        print("    传到手机全屏显示 -> 量出屏幕上的黑框外边长 -> "
              "python main.py demo --no-calib --tag-mm <实测值>")
        return 0

    tag_pdf = outdir / f"apriltag_36h11_id{a.tag_id}_{a.tag_mm:g}mm.pdf"
    t = make_tag_page(tag, a.tag_mm, tag_pdf, a.page)
    print(f"[2] tag 页 {tag_pdf.name}：黑框外边 {t['frame_mm'][0]:.2f} x {t['frame_mm'][1]:.2f} mm"
          f"（{t['cell_px']}px/单元），整张 {t['tag_mm']:.1f} mm，页面 {a.page.upper()} 竖版")

    screen_png = outdir / f"apriltag_36h11_id{a.tag_id}_phone_screen.png"
    make_screen_image(tag, screen_png, a.tag_id)
    print(f"[3] 屏幕测试图 {screen_png.name}：传到手机/平板全屏显示，可用于不打印就试检测")

    chess_pdf = outdir / f"chessboard_{a.inner_cols}x{a.inner_rows}_{a.square_mm:g}mm.pdf"
    c = make_chessboard_page(a.inner_cols, a.inner_rows, a.square_mm, chess_pdf, a.page)
    print(f"[4] 棋盘格页 {chess_pdf.name}：{c['inner'][0]}x{c['inner'][1]} 内角点，"
          f"方格 {c['square_mm']:.1f} mm，整体 {c['board_mm'][0]:.1f} x {c['board_mm'][1]:.1f} mm，"
          f"页面 {a.page.upper()}{c['orient']}")

    # 自检顺序：先 OpenCV，再 apriltag 检测——OpenCV 5.0 与该库的调用顺序会引发退出时段错误
    chess = cv2.cvtColor(np.array(c["page"]), cv2.COLOR_GRAY2BGR)
    gray = cv2.cvtColor(chess, cv2.COLOR_BGR2GRAY)
    ok, corners = cv2.findChessboardCorners(gray, (a.inner_cols, a.inner_rows), None)
    print(f"[5] 自检：棋盘格页 findChessboardCorners({a.inner_cols}x{a.inner_rows}) = {ok}"
          + (f"，首个内角点 {np.round(corners[0, 0], 1)}" if ok else ""))

    from pupil_apriltags import Detector
    det = Detector(families="tag36h11", nthreads=2)
    _KEEP_ALIVE.extend([t, c, det])      # 见文件末尾 os._exit 处的说明
    res = det.detect(np.array(t["page"]))
    if res:
        d0 = res[0]
        sides = [np.linalg.norm(d0.corners[i] - d0.corners[(i + 1) % 4]) for i in range(4)]
        print(f"[6] 自检：生成页检出 id={d0.tag_id} hamming={d0.hamming}；"
              f"四边长 {[f'{s / PPMM:.2f}' for s in sides]} mm（应为 {a.tag_mm:.1f}）")
    else:
        print("[6] 自检失败：生成页未检出 tag")
    return 0


if __name__ == "__main__":
    _code = main()
    # 见文件顶部 _KEEP_ALIVE 的说明：解释器清理阶段会随机段错误，直接带退出码退出。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code)
