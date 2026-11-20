"""规则：RUN 模式空窗。

只在 RUN（CQ）模式下生效：S&P 天然出 QSO 慢，空窗不该挨罚。
带冷却，避免接电话 / 修设备时被连续电击。
"""

from rate_warden.rule_base import Rule, Param, Context, common_penalty_params


class EmptyWindowRule(Rule):
    id = "empty_window"
    name = "RUN 空窗"
    description = (
        "RUN 模式下连续 window_s 秒没有新 QSO 就惩罚一次，之后进入冷却。"
        "S&P 模式自动豁免。"
    )
    events = ("tick",)
    axis = "rate"
    params_schema = [
        Param("window_s", "空窗阈值(秒)", "float", 30.0, 5.0, 600.0,
              help="多久没 QSO 判定为空窗。这就是你最初要的 30 秒。"),
        Param("cooldown_s", "冷却(秒)", "float", 60.0, 0.0, 1800.0,
              help="触发后多久内不再重复罚空窗。"),
        Param("require_run", "仅 RUN 模式", "bool", True,
              help="勾选后 S&P 模式完全不罚空窗。"),
        Param("require_radio", "需要收到 RadioInfo", "bool", True,
              help="勾选后，若 N1MM 从未广播运行状态，则空窗规则保持沉默（防止误罚）。"),
        *common_penalty_params(default_strength=40, default_duration=1.0),
    ]

    def __init__(self, params=None) -> None:
        super().__init__(params)
        # 首次 tick 时才开始计时，避免程序刚启动就罚
        self._armed_at = None

    def on_tick(self, ctx: Context):
        now = ctx.now
        if self._armed_at is None:
            self._armed_at = now

        if self.get("require_run", True) and not ctx.is_running:
            return None

        if self.get("require_radio", True):
            radio = ctx.radio or {}
            if radio.get("is_running") is None:
                return None

        window = float(self.get("window_s", 30.0))
        # 空闲起点取「最后一次 QSO」与「规则就绪时刻」中较晚者
        reference = max(ctx.last_qso_time, self._armed_at)
        idle = now - reference
        if idle < window:
            return None

        last_fire = ctx.state.get("last_fire", 0.0)
        if last_fire and now - last_fire < float(self.get("cooldown_s", 60.0)):
            return None

        ctx.state["last_fire"] = now
        ctx.state["last_idle"] = idle
        return self.event(
            ctx,
            reason=f"RUN 已 {idle:.0f}s 无新 QSO（阈值 {window:.0f}s）",
        )
