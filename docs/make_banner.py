# coding=utf-8
"""
Compose docs/banner.png (1280 x 640: README header and GitHub social preview) from the icon and the real screenshot
(developer tool: pip install cairosvg pillow NumPy; run make_screenshot.py first).
"""
from numpy import mgrid, float32, array, sqrt, clip, random, uint8
from PIL.Image import fromarray, new, open, LANCZOS
from PIL import ImageDraw, ImageFilter, ImageFont
from os.path import abspath, dirname, join
from cairosvg import svg2png
from io import BytesIO

HERE = dirname(abspath(__file__))  # type: str
W, H = 1280, 640  # type: int, int
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'  # type: str
BOOK = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'  # type: str


def background():
    """
    :return: (Image) Diagonal navy gradient with soft blue / violet glows (float maths: no banding).
    """
    y, x = mgrid[0:H, 0:W].astype(float32)
    t = (x / W * 0.35 + y / H * 0.65)[..., None]
    img = (1 - t) * array([29, 37, 80], float32) + t * array([11, 14, 31], float32)
    for cx, cy, r, color, a in ((260, 250, 420, (79, 107, 255), 0.30), (1120, 120, 380, (138, 92, 255), 0.22),
                                (980, 640, 360, (46, 197, 255), 0.12)):
        d = sqrt((x - cx) ** 2 + (y - cy) ** 2) / r
        img += (clip(1 - d, 0, 1) ** 2 * a)[..., None] * (array(color, float32) - img)
    rng = random.default_rng(1)  # Fine grain against banding on large screens.
    img += rng.normal(0, 0.8, img.shape).astype(float32)
    return fromarray(clip(img, 0, 255).astype(uint8)).convert('RGBA')


def rounded(img, radius):
    """
    :param img: Image
    :param radius: int
    :return: Image
    """
    mask = new('L', img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.size[0] - 1, img.size[1] - 1), radius, fill=255)
    out = img.convert('RGBA')
    out.putalpha(mask)
    return out


def shadow(size, radius, blur, alpha):
    """
    :param size: tuple
    :param radius: int
    :param blur: int
    :param alpha: int
    :return: Image
    """
    pad = blur * 3  # type: int
    sh = new('RGBA', (size[0] + 2 * pad, size[1] + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad, pad + size[0], pad + size[1]), radius, fill=(3, 5, 14, alpha))
    return sh.filter(ImageFilter.GaussianBlur(blur)), pad


def main():
    """
    :return:
    """
    banner = background()
    draw = ImageDraw.Draw(banner)
    shot = open(join(HERE, 'screenshot.png')).convert('RGB')  # The real application.
    shot = rounded(shot.resize((744, 419), LANCZOS), 16)
    sx, sy = 560, 148
    sh, pad = shadow(shot.size, 16, 18, 190)
    banner.alpha_composite(sh, (sx - pad + 6, sy - pad + 14))
    banner.alpha_composite(shot, (sx, sy))
    layer = new('RGBA', banner.size, (0, 0, 0, 0))  # Translucent shapes: drawn apart, then BLENDED
    ImageDraw.Draw(layer).rounded_rectangle((sx, sy, sx + shot.size[0] - 1, sy + shot.size[1] - 1), 16,
                                            outline=(255, 255, 255, 46), width=2)
    icon = open(BytesIO(svg2png(url=join(HERE, 'icon.svg'), output_width=148, output_height=148))).convert('RGBA')
    ish, ipad = shadow((128, 128), 30, 12, 150)
    banner.alpha_composite(ish, (72 - ipad + 10, 70 - ipad + 18))
    banner.alpha_composite(icon, (62, 60))
    draw = ImageDraw.Draw(banner)
    draw.text((64, 236), u'ScreenMagnifier', font=ImageFont.truetype(BOLD, 52), fill=(246, 248, 252))
    draw.text((66, 306), u'Real-time screen magnifier for Windows,', font=ImageFont.truetype(BOOK, 21),
              fill=(174, 183, 210))
    draw.text((66, 336), u'macOS and Linux - in Python, with Qt.', font=ImageFont.truetype(BOOK, 21),
              fill=(174, 183, 210))
    chips = [u'AI upscaling', u'In-game zoomer', u'Screen color picker', u'Color zones', u'Face detection',
             u'Analysis server', 'PyQt5 \u00b7 PyQt6 \u00b7 PySide']
    font = ImageFont.truetype(BOOK, 16)
    chipDraw = ImageDraw.Draw(layer)
    x, y = 64, 392
    for text in chips:
        tw = int(draw.textlength(text, font=font))
        if x + tw + 28 > 540:
            x, y = 64, y + 42
        chipDraw.rounded_rectangle((x, y, x + tw + 28, y + 32), 16, fill=(255, 255, 255, 18),
                                   outline=(126, 160, 255, 110), width=1)
        chipDraw.text((x + 14, y + 7), text, font=font, fill=(222, 228, 245, 255))
        x += tw + 38
    banner.alpha_composite(layer)
    draw = ImageDraw.Draw(banner)
    draw.text((66, 568), 'pip install "ScreenMagnifier[all]"', font=ImageFont.truetype(BOOK, 17), fill=(128, 170, 255))
    banner.convert('RGB').save(join(HERE, 'banner.png'), optimize=True)
    print(u'Banner written: ' + join(HERE, 'banner.png'))


if __name__ == '__main__':
    main()
