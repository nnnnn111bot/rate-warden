"""DGHub 插件入口。

DGHub 拉起本插件时，会注入 DGHUB_HOST / DGHUB_PORT / DGHUB_TOKEN
并以插件根目录为工作目录。

本入口做两件事：
1. 启动 GUI（Rate Warden 主窗口）；
2. 启动时做一次 startup_check 上报，让 DGHub 的插件卡片能显示 N1MM 连接状态。

GIL 说明：GUI 用 PySide6 事件循环，DGHub 的 Agent 在自己的后台线程里跑 asyncio
并经由内置队列回调，两者不冲突。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 插件根 = manifest.json 所在目录（dghub_plugin/main.py 的上一级）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rate_warden import APP_NAME, __version__, config  # noqa: E402


def _report_startup_check(port: int) -> None:
    """若被 DGHub 拉起，则上报一次启动检查。

    注意：本插件的惩罚发送由 rate_warden.sink.DghubSink 自己建立连接，
    这里的 Agent 只用于上报状态，失败不影响主功能。
    """
    if not os.environ.get("DGHUB_TOKEN"):
        print("[rate_warden] 未检测到 DGHUB_TOKEN，按独立进程模式运行")
        return
    try:
        from dghub_sdk import Agent, CheckState, LogLevel
    except ImportError:
        print("[rate_warden] dghub_sdk 不可用，跳过启动检查上报")
        return

    try:
        agent = Agent()
        agent.start()
        agent.wait_ready(timeout=8)
        agent.set_startup_check_title("Rate Warden 启动检查")
        # 每个步骤单独上报，最后一步统一发送
        agent.send_startup_check(
            "gui", "启动界面", CheckState.OK,
            detail=f"v{__version__} 已启动", dont_send=True)
        agent.send_startup_check(
            "gateway", "DGHub 连接", CheckState.OK,
            detail="已握手", dont_send=True)
        agent.send_startup_check(
            "n1mm", "N1MM 数据源", CheckState.PENDING,
            detail=f"监听 UDP {port}",
            hint="在 N1MM 的 Broadcast Data 中勾选 Contacts 并填 127.0.0.1",
            display_status="运行中")
        agent.send_log(LogLevel.INFO, f"{APP_NAME} v{__version__} 插件入口已就绪")
        agent.stop()
    except Exception as exc:  # 上报失败绝不影响 GUI
        print(f"[rate_warden] 启动检查上报失败: {exc}")


def main() -> int:
    cfg = config.load()
    _report_startup_check(int(cfg.get("udp_port", 12060)))

    try:
        from rate_warden.gui import run
    except ImportError as exc:
        print(f"[rate_warden] 缺少 PySide6: {exc}", file=sys.stderr)
        return 2

    return run(cfg, demo=False)


if __name__ == "__main__":
    sys.exit(main())
