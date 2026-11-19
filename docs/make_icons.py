# coding=utf-8
"""
Render the application icon from its SVG sources (developer tool: pip install cairosvg pillow):
    icon.svg        detailed icon (48 px and larger)
    icon-small.svg  simplified icon for 16 - 32 px (fine detail turns to mush at those sizes)
Output, in ScreenMagnifier/resources/: icon-<size>.png (window / tray icon, any platform), icon.ico (Windows
executable), icon.icns (macOS application bundle).
"""
from os.path import abspath, dirname, join
from cairosvg import svg2png
from PIL.Image import open
from io import BytesIO

HERE = dirname(abspath(__file__))  # type: str
OUT = join(HERE, '..', 'ScreenMagnifier', 'resources')  # type: str
SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]  # type: list[int]


def render(size):
    """
    :param size: int
    :return: Image
    """
    source = join(HERE, 'icon-small.svg' if size <= 32 else 'icon.svg')  # type: str
    return open(BytesIO(svg2png(url=source, output_width=size, output_height=size))).convert('RGBA')


def main():
    """
    :return:
    """
    images = {s: render(s) for s in SIZES}  # type: dict
    for s in SIZES[:-1]:  # 1024 only feeds the .icns
        images[s].save(join(OUT, 'icon-{}.png'.format(s)), optimize=True)
    ico = [16, 24, 32, 48, 64, 128, 256]  # type: list
    images[256].save(join(OUT, 'icon.ico'), format='ICO', sizes=[
        (s, s) for s in ico], append_images=[images[s] for s in ico if s != 256])
    images[1024].save(
        join(OUT, 'icon.icns'), format='ICNS', append_images=[images[s] for s in (16, 32, 64, 128, 256, 512)])
    print('icons written to ' + abspath(OUT))


if __name__ == '__main__':
    main()
