"""规则：磕台超时。

操作员按下 Tab/空格开始呼叫某个台（N1MM 发 LookupInfo），
若在 timeout_s 秒内没有落库，且期间没有转去呼叫别的台，则提醒。
"""

from rate_warden.rule_base import Rule, Param, Context, common_penalty_params


class LookupTimeoutRule(Rule):
    id = "lookup_timeout"
    name = "磕台超时"
    description = (
        "收到 LookupInfo 后 timeout_s 秒内该呼号仍未落库就提醒，"
        "促使操作员尽快决定「继续磕还是放弃」。"
    )
    events = ("tick",)
    axis = "mistake"
    params_schema = [
        Param("timeout_s", "超时阈值(秒)", "float", 90.0, 10.0, 600.0,
              help="从按下空格/Tab 到落库的最长容忍时间。"),
        *common_penalty_params(default_strength=55, default_duration=1.5),
    ]

    def on_tick(self, ctx: Context):
        pending = ctx.pending_lookup_call
        if not pending:
            return None

        # 同一个呼号只罚一次
        if ctx.state.get("fired_for") == pending:
            return None

        waited = ctx.now - ctx.pending_lookup_time
        if waited < float(self.get("timeout_s", 90.0)):
            return None

        ctx.state["fired_for"] = pending
        # 让引擎清掉待办，避免后续 tick 继续看着这个台
        ctx.state["request_clear_pending"] = True
        return self.event(
            ctx,
            reason=f"{pending} 已呼叫 {waited:.0f}s 仍未落库",
        )
