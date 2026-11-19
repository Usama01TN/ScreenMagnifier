# encoding: utf-8
"""
Setup script for ScreenMagnifier.
"""
from setuptools import setup, find_packages
from os.path import join, dirname
from re import search
from io import open

HERE = dirname(__file__) or "."  # type: str
NAME = "ScreenMagnifier"  # type: str
with open(join(HERE, NAME, "__init__.py"), encoding="utf-8") as f:  # Single version source, read as text.
    VERSION = search(r"__version__ = '([^']+)'", f.read()).group(1)  # type: str
DEVELOPER = "UsamaTN"  # type: str
DEVELOPER_EMAIL = "ininou.oussematn@gmail.com"  # type: str
PACKAGES = find_packages(HERE, include=["ScreenMagnifier", "ScreenMagnifier.*"])  # type: list[str]
DESCRIPTION = ("Real-time screen magnifier with AI upscaling, an in-game zoomer, a screen color picker, color / face "
               "detection and an optional analysis server - PyQt5 / PyQt6 / PySide through ManyQt.")  # type: str
with open(join(HERE, "README.md"), encoding="utf-8") as f:
    README = f.read()  # type: str
CLASSIFIERS = [
    "Development Status :: 4 - Beta",
    "Environment :: X11 Applications :: Qt",
    "Environment :: Win32 (MS Windows)",
    "Environment :: MacOS X",
    "Intended Audience :: End Users/Desktop",
    "Intended Audience :: Developers",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: MacOS",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Topic :: Desktop Environment",
    "Topic :: Multimedia :: Graphics :: Viewers",
]  # type: list[str]
KEYWORDS = ["magnifier", "zoom", "screen", "color picker", "eyedropper", "super-resolution", "accessibility",
            "PyQt5", "PyQt6", "PySide6"]  # type: list[str]
INSTALL_REQUIRES = [
    "ManyQt>=0.5",  # one Qt API over PyQt5 / PyQt6 / PySide2 / PySide6: the binding is chosen with an extra
    "numpy>=1.19",  # color detection, pixel-art upscaler
    "pynput>=1.7",  # screen color picker click capture, global hotkeys on Linux / macOS
]  # type: list[str]
OPENCV = "opencv-contrib-python-headless>=4.8,<5"  # type: str  # Bicubic / Lanczos / AI upscaling, face detection
EXTRAS_REQUIRE = {
    "pyqt6": ["PyQt6"],
    "pyqt5": ["PyQt5"],
    "pyside6": ["PySide6"],
    "opencv": [OPENCV],
    "all": ["PyQt6", OPENCV],
}  # type: dict[str, list[str]]
ENTRY_POINTS = {
    "gui_scripts": ["ScreenMagnifier = ScreenMagnifier.main:run"],
    "console_scripts": ["ScreenMagnifierServer = ScreenMagnifier.server:run"],
}  # type: dict[str, list[str]]
PACKAGE_DATA = {"ScreenMagnifier.upscaler.models": ["*.pb", "LICENSE*"],
                "ScreenMagnifier": ["resources/*.png", "resources/*.ico", "resources/*.icns",
                                    "translations/*.json"]}  # type: dict
PROJECT_URLS = {  # The same links as .github/FUNDING.yml and ScreenMagnifier/support.py (checked by the workflow).
    "Donate (Ko-fi)": "https://ko-fi.com/usamatn",
    "Donate (ba9chich)": "https://ba9chich.com/fr/IninouUsama",
}  # type: dict[str, str]

if __name__ == "__main__":
    setup(name=NAME, version=VERSION, author=DEVELOPER, author_email=DEVELOPER_EMAIL, description=DESCRIPTION,
          long_description=README, long_description_content_type="text/markdown", keywords=KEYWORDS,
          classifiers=CLASSIFIERS, packages=PACKAGES, package_data=PACKAGE_DATA, python_requires=">=3.8",
          install_requires=INSTALL_REQUIRES, extras_require=EXTRAS_REQUIRE, entry_points=ENTRY_POINTS,
          project_urls=PROJECT_URLS)
