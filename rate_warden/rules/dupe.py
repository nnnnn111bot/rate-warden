"""规则：重复通联（Dupe）。

N1MM 的 ContactInfo 不直接带 dupe 标志，所以由引擎侧维护 (band, mode, call) 历史集合。
"""

from rate_warden.rule_base import Rule, Param, Context, common_penalty_params


class DupeRule(Rule):
    id = "dupe"
    name = "重复通联"
    description = "同一波段、同一模式下重复记录同一个呼号。"
    events = ("contact",)
    axis = "mistake"
    params_schema = [
        Param("ignore_other_modes", "按波段+模式判重", "bool", True,
              help="勾选后只有波段和模式都相同才算 dupe；取消则同波段不同模式也算。"),
        *common_penalty_params(default_strength=60, default_duration=2.0),
    ]

    def on_contact(self, ctx: Context):
        contact = ctx.contact
        if contact is None or not contact.call:
            return None

        if self.get("ignore_other_modes", True):
            key = (contact.band, contact.mode, contact.call)
            hit = key in ctx.worked
        else:
            hit = any(
                k[0] == contact.band and k[2] == contact.call for k in ctx.worked
            )

        if not hit:
            return None
        return self.event(
            ctx,
            reason=f"Dupe: {contact.band}/{contact.mode}/{contact.call}",
        )
