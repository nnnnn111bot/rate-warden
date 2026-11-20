"""Rate Warden 入口。

    python main.py            启动 GUI（自动尝试连接 DGHub）
    python main.py --demo     启动 GUI，强制使用 NullSink（不连设备）
    python main.py --check    只跑离线自检，不开窗口
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---- 必须在任何 print 之前：修 stdio 的两个 Windows 坑 ----
# 1) PyInstaller --windowed：无控制台，sys.stdout/stderr 为 None，print 会 AttributeError
# 2) Windows CI / cmd.exe：默认 cp1252，打印中文抛 UnicodeEncodeError
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        # Python < 3.7 或非常规流：保持原样
        pass
# -----------------------------------------------------------

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from rate_warden import APP_NAME, __version__, config, selftest  # noqa: E402


def main(argv: list) -> int:
    args = set(argv[1:])

    if "--check" in args:
        return selftest.main(argv)

    if "--version" in args:
        print(f"{APP_NAME} {__version__}")
        return 0

    try:
        from rate_warden.gui import run
    except ImportError as exc:
        print("无法加载 GUI（缺少 PySide6）：", exc, file=sys.stderr)
        print("安装： python -m pip install --user PySide6", file=sys.stderr)
        print("或先跑离线自检： python main.py --check", file=sys.stderr)
        return 2

    cfg = config.load()
    demo = "--demo" in args
    return run(cfg, demo=demo)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
