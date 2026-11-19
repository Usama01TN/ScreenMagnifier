#!/usr/bin/env bash
# Runs INSIDE a Debian container (the build-container job of .github/workflows/build-release.yml) and builds the Linux
# release binaries for the CPUs that have no GitHub-hosted runner and no Qt wheels on PyPI: 32-bit x86 (i386),
# ARMv7 (armhf), ARMv5/v6 (armel), ppc64le, s390x, riscv64. Qt (PyQt5), NumPy and OpenCV come from the distribution's
# own packages, PyInstaller / ManyQt / pynput from PyPI (PyInstaller compiles its bootloader where it has no wheel).
# Environment: SM_VERSION (release version), SM_ARCH (archive name: x86, armv7 ...), HOST_UID / HOST_GID (owner of dist/).
# Usage:  docker run --rm --platform linux/arm/v7 -e SM_VERSION=1.2.3 -e SM_ARCH=armv7 -v "$PWD":/work -w /work \
#             debian:bookworm bash .github/packaging/build-in-container.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev build-essential zlib1g-dev binutils ca-certificates \
    python3-pyqt5 python3-numpy python3-six python3-xlib python3-evdev fonts-dejavu-core \
    libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libdbus-1-3 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libxcb-cursor0
# OpenCV is optional (the application degrades gracefully without it): a CPU without the package still gets a build.
apt-get install -y --no-install-recommends python3-opencv || echo "::warning::python3-opencv is not available on this CPU: building without OpenCV"

# --system-site-packages: PyQt5 / NumPy / OpenCV of the distribution are used as they are.
python3 -m venv --system-site-packages /opt/venv
/opt/venv/bin/python -m pip install --quiet ManyQt pynput pyinstaller
/opt/venv/bin/python -c "import PyQt5.QtCore as q; print('Qt', q.QT_VERSION_STR, 'PyQt', q.PYQT_VERSION_STR)"

status=0
/opt/venv/bin/python .github/packaging/build.py --version "${SM_VERSION:-dev}" --qt-api pyqt5 --arch "${SM_ARCH:?SM_ARCH is required}" || status=$?
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" dist build ScreenMagnifier/_buildinfo.py 2> /dev/null || true
exit $status
