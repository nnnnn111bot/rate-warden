"""Rate Warden 规则契约层。

本模块只依赖标准库，不 import 任何其它 rate_warden 子模块，
这样用户规则文件可以安全地只依赖 rule_base。
"""

from __future__ import annotations

import time
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Optional

# 规则可订阅的事件名
EVENTS = ("contact", "lookup", "radio", "tick")


@dataclass
class Param:
    """一个规则的参数声明，GUI 据此自动生成控件。"""

    key: str
    label: str
    type: str  # int | float | bool | str | choice | waveform
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list] = None
    help: str = ""  # 悬停提示，会显示在 GUI 的状态栏
    group: str = "常规"


@dataclass
class PenaltyEvent:
    """一次惩罚请求。只描述"想怎么罚"，不负责发出去。"""

    rule_id: str
    strength_pct: int = 30  # 相对 baseline 的增量，0-100
    duration_s: float = 1.0
    preset: str = ""  # 波形预设名（DGHub 侧的名字）
    channel: str = "both"  # a / b / both
    action: str = "both"  # both | strength | waveform
    reason: str = ""

    def scaled(self, factor: float, cap: int) -> "PenaltyEvent":
        """返回按因子缩放后的副本，强度被夹在 [0, cap]。"""
        pct = int(round(self.strength_pct * factor))
        pct = max(0, min(pct, cap))
        return PenaltyEvent(
            rule_id=self.rule_id,
            strength_pct=pct,
            duration_s=self.duration_s,
            preset=self.preset,
            channel=self.channel,
            action=self.action,
            reason=self.reason,
        )


@dataclass
class Contact:
    """一条解析后的 ContactInfo / LookupInfo。"""

    call: str = ""
    band: str = ""
    mode: str = ""
    is_original: bool = True
    sntnr: str = ""
    rcvnr: str = ""
    power: str = ""
    section: str = ""
    zone: str = ""
    gridsquare: str = ""
    is_run_qso: Optional[bool] = None
    timestamp: float = field(default_factory=time.time)
    raw: dict = field(default_factory=dict)


@dataclass
class Context:
    """规则在每次回调时拿到的只读快照（state 除外）。"""

    now: float
    last_qso_time: float
    is_running: bool
    worked: set
    last_call: Optional[str]
    last_call_time: float
    pending_lookup_call: Optional[str]
    pending_lookup_time: float
    consecutive_mistakes: int
    strength_cap: int
    contact: Optional[Contact] = None
    lookup_call: Optional[str] = None
    radio: Optional[dict] = None
    state: dict = field(default_factory=dict)

    @property
    def idle_seconds(self) -> float:
        return self.now - self.last_qso_time


class Rule(ABC):
    """规则基类。每个 .py 文件定义一个 Rule 子类即可。"""

    # ---- 元数据（子类必须覆盖 id / name）----
    id: str = ""
    name: str = ""
    description: str = ""
    events: tuple = ()
    # axis: "rate" 表示节奏类（不参与连续失误递进）, "mistake" 表示操作失误类
    axis: str = "mistake"
    params_schema: list = []

    def __init__(self, params: Optional[dict] = None) -> None:
        self.params = self.default_params()
        if params:
            self.set_params(params)

    # ---- 参数 ----
    @classmethod
    def default_params(cls) -> dict:
        return {p.key: p.default for p in cls.params_schema}

    def set_params(self, params: dict) -> list:
        """写入参数并返回被忽略的非法项（用于 GUI 提示）。"""
        rejected = []
        known = {p.key: p for p in self.params_schema}
        for key, value in dict(params).items():
            spec = known.get(key)
            if spec is None:
                rejected.append(key)
                continue
            coerced = _coerce(spec, value)
            if coerced is _INVALID:
                rejected.append(key)
                continue
            self.params[key] = coerced
        return rejected

    def get(self, key: str, fallback: Any = None) -> Any:
        return self.params.get(key, fallback)

    # ---- 事件回调（子类按需重写，返回 PenaltyEvent 或 None）----
    def on_contact(self, ctx: Context) -> Optional[PenaltyEvent]:
        return None

    def on_lookup(self, ctx: Context) -> Optional[PenaltyEvent]:
        return None

    def on_radio(self, ctx: Context) -> Optional[PenaltyEvent]:
        return None

    def on_tick(self, ctx: Context) -> Optional[PenaltyEvent]:
        return None

    # ---- 便捷构造 ----
    def event(self, ctx: Context, reason: str, **overrides) -> PenaltyEvent:
        """用规则自身参数构造惩罚事件。"""
        data = {
            "rule_id": self.id,
            "strength_pct": int(self.get("strength", 30)),
            "duration_s": float(self.get("duration_s", 1.0)),
            "preset": str(self.get("waveform", "") or ""),
            "channel": str(self.get("channel", "both")),
            "action": str(self.get("action", "both")),
            "reason": reason,
        }
        preset_override = overrides.pop("preset", None)
        if preset_override:
            data["preset"] = str(preset_override)
        data.update(overrides)
        return PenaltyEvent(**data)


class _Invalid:
    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return "<invalid>"


_INVALID = _Invalid()


def _coerce(spec: Param, value: Any):
    """把 GUI 或 json 来的值转换成参数声明的类型，失败返回 _INVALID。"""
    try:
        if spec.type == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if spec.type == "int":
            number = int(float(value))
            return _clamp(spec, number)
        if spec.type == "float":
            number = float(value)
            return _clamp(spec, number)
        if spec.type == "choice":
            text = str(value)
            if spec.choices and text not in [str(c) for c in spec.choices]:
                return _INVALID
            return text
        return str(value)
    except (TypeError, ValueError):
        return _INVALID


def _clamp(spec: Param, number):
    if spec.min is not None:
        number = max(number, spec.min)
    if spec.max is not None:
        number = min(number, spec.max)
    return number


# 规则作者常用的共享参数片段
def common_penalty_params(default_strength: int = 40, default_duration: float = 1.0,
                          default_waveform: str = "") -> list:
    """生成一组标准的"强度/时长/波形/通道"参数声明。"""
    return [
        Param("strength", "惩罚强度(%)", "int", default_strength, 0, 100,
              help="相对 baseline 的强度增量。全局上限会在 config.strength_cap 处再夹一次。"),
        Param("duration_s", "持续时间(秒)", "float", default_duration, 0.1, 30.0,
              help="trigger 的 duration_s。rollback 模式下到期自动回到 baseline。"),
        Param("waveform", "波形预设", "waveform", default_waveform,
              help="从波形库选择的 DGHub 预设名。为空则用 strength 模式。"),
        Param("channel", "通道", "choice", "both", choices=["a", "b", "both"],
              help="惩罚作用在哪个通道。"),
    ]
