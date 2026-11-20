"""惩罚执行后端。

DghubSink   —— 真实通路：dghub_sdk.Agent 走 WebSocket 连 DGHub 主程序。
NullSink    —— 离线通路：只记录，用于自检与无设备演示。

两者接口一致，引擎不关心谁在另一端。
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from .rule_base import PenaltyEvent


class Sink:
    name = "sink"

    def fire(self, event: PenaltyEvent) -> bool:
        raise NotImplementedError

    def emergency_stop(self) -> bool:
        raise NotImplementedError

    def status(self) -> tuple[str, bool]:
        """返回 (人话状态, 是否就绪)。"""
        raise NotImplementedError

    def close(self) -> None:
        pass


class NullSink(Sink):
    """不连接任何设备的 sink；把发出的指令记在 sent 里便于断言。"""

    name = "null"

    def __init__(self, on_log: Optional[Callable[[str], None]] = None) -> None:
        self.sent: list = []
        self.stops = 0
        self.on_log = on_log
        self._ready = True

    def fire(self, event: PenaltyEvent) -> bool:
        self.sent.append(event)
        if self.on_log:
            self.on_log(
                f"[null] 惩罚 {event.rule_id} 强度={event.strength_pct} "
                f"时长={event.duration_s}s 波形={event.preset or '-'}"
            )
        return True

    def emergency_stop(self) -> bool:
        self.stops += 1
        if self.on_log:
            self.on_log("[null] 急停：强度归零")
        return True

    def status(self) -> tuple[str, bool]:
        return ("未连接设备（惩罚只记录）", False)


class DghubSink(Sink):
    """通过 dghub_sdk.Agent 连 DGHub 主程序。

    DGHub 会把本插件作为外部插件管理：一条 trigger 同时覆盖
    强度 + 波形 + rollback（到期自动回正），这是官方推荐用法。
    """

    name = "dghub"

    def __init__(self, on_log: Optional[Callable[[str], None]] = None,
                 on_device: Optional[Callable[[bool, str, int, int], None]] = None,
                 on_config: Optional[Callable[[dict], None]] = None) -> None:
        self.on_log = on_log
        self.on_device = on_device
        self.on_config = on_config
        self.config: dict = {}
        self.device_connected = False
        self.device_type = ""
        self.max_a = 0
        self.max_b = 0
        self.ready = False
        self.last_error = ""
        self._agent = None

    # ---- 连接 ----
    def connect(self, timeout: float = 8.0) -> bool:
        try:
            from dghub_sdk import Agent  # 延迟导入：缺失时优雅降级
        except ImportError as exc:
            self.last_error = f"未安装 dghub_sdk: {exc}"
            self._log(self.last_error)
            return False

        try:
            self._agent = Agent(
                on_config=self._handle_config,
                on_device_info=self._handle_device,
                on_stop=self._handle_stop,
                on_config_changed=self._handle_config_changed,
            )
            self._agent.start()
            self._agent.wait_ready(timeout=timeout)
        except Exception as exc:  # 连不上是常态（DGHub 没开），不能崩
            self.last_error = f"连接 DGHub 失败: {exc}"
            self.ready = False
            self._log(self.last_error)
            return False

        self.ready = True
        self._log("已连接 DGHub")
        return True

    # ---- 回调 ----
    def _handle_config(self, config: dict) -> None:
        self.config = dict(config or {})
        if self.on_config:
            self.on_config(self.config)

    def _handle_config_changed(self, key: str, value) -> None:
        self.config[key] = value
        if self.on_config:
            self.on_config(self.config)

    def _handle_device(self, connected: bool, device_type, max_a: int, max_b: int) -> None:
        self.device_connected = bool(connected)
        self.device_type = str(getattr(device_type, "value", device_type) or "")
        self.max_a = int(max_a or 0)
        self.max_b = int(max_b or 0)
        if self.on_device:
            self.on_device(self.device_connected, self.device_type, self.max_a, self.max_b)

    def _handle_stop(self, reason: str) -> None:
        self.ready = False
        self._log(f"DGHub 要求插件停止: {reason}")

    # ---- 发送 ----
    def fire(self, event: PenaltyEvent) -> bool:
        if not self._agent or not self.ready:
            self._log("惩罚未发送：DGHub 未连接")
            return False
        action = event.action
        if action in ("both", "waveform") and not event.preset:
            action = "strength"
        try:
            self._agent.send_trigger(
                action=action,
                delta_pct=int(event.strength_pct),
                strength_mode="rollback",  # 到期自动回正，安全
                duration_s=float(event.duration_s),
                preset=event.preset if action in ("both", "waveform") else "",
                channel=event.channel,
                label="Rate Warden",
                username="Rate Warden",
                name=event.rule_id,
                cause=event.reason,
            )
        except Exception as exc:
            self._log(f"发送 trigger 失败: {exc}")
            return False
        self._log(
            f"已发送 {event.rule_id}: 强度+{event.strength_pct}% "
            f"{event.duration_s}s 波形={event.preset or '-'} ({event.reason})"
        )
        return True

    def emergency_stop(self) -> bool:
        """急停：把通道强度直接归零。不经过引擎和队列。"""
        if not self._agent or not self.ready:
            return False
        ok = True
        for channel in ("a", "b"):
            try:
                self._agent.send_set_strength(channel=channel, pct=0)
            except Exception as exc:
                self._log(f"急停发送失败({channel}): {exc}")
                ok = False
        self._log("急停：A/B 强度归零")
        return ok

    def status(self) -> tuple[str, bool]:
        if not self.ready:
            return (self.last_error or "未连接 DGHub", False)
        if not self.device_connected:
            return ("已连 DGHub，设备未连接", False)
        return (f"设备已连接 ({self.device_type or '?'})", True)

    def close(self) -> None:
        if self._agent is not None:
            try:
                self._agent.stop()
            except Exception:
                pass
            self._agent = None
        self.ready = False

    def _log(self, message: str) -> None:
        if self.on_log:
            self.on_log(message)


def build_sink(kind: str = "dghub", **kwargs) -> Sink:
    """按名字造 sink；dghub 连不上时由调用方决定是否换 NullSink。"""
    if kind == "null":
        return NullSink(on_log=kwargs.get("on_log"))
    return DghubSink(
        on_log=kwargs.get("on_log"),
        on_device=kwargs.get("on_device"),
        on_config=kwargs.get("on_config"),
    )
