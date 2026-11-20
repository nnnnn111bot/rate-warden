"""规则：交换信息缺失。

具体比赛要求哪些交换项因赛事而异，所以全部做成开关。
"""

from rate_warden.rule_base import Rule, Param, Context, common_penalty_params


class MissingExchangeRule(Rule):
    id = "missing_exchange"
    name = "交换信息缺失"
    description = (
        "落库时检查关键交换字段是否为空（或序列号为 0）。"
        "按你当前比赛规则勾选需要的项。"
    )
    events = ("contact",)
    axis = "mistake"
    params_schema = [
        Param("check_rcvnr", "检查收到的序号", "bool", True,
              help="序列号类比赛必开：rcvnr 为空或 0 视为缺失。"),
        Param("check_sntnr", "检查发出的序号", "bool", False,
              help="检查 sntnr 是否为空。"),
        Param("check_power", "检查功率交换", "bool", False,
              help="功率交换类比赛（如 ARRL 大功率组）开启。"),
        Param("check_section", "检查 Section", "bool", False,
              help="Sweepstakes 等赛事开启。"),
        Param("check_zone", "检查 CQ Zone", "bool", False,
              help="CQ WW 等赛事开启。"),
        Param("check_grid", "检查网格", "bool", False,
              help="VHF / FT8 网格类比赛开启。"),
        *common_penalty_params(default_strength=45, default_duration=1.5),
    ]

    def on_contact(self, ctx: Context):
        contact = ctx.contact
        if contact is None:
            return None

        problems = []
        if self.get("check_rcvnr", True):
            if contact.rcvnr.strip() in ("", "0"):
                problems.append("收到序号为空/0")
        if self.get("check_sntnr", False):
            if contact.sntnr.strip() in ("", "0"):
                problems.append("发出序号为空/0")
        if self.get("check_power", False) and not contact.power.strip():
            problems.append("功率为空")
        if self.get("check_section", False) and not contact.section.strip():
            problems.append("Section 为空")
        if self.get("check_zone", False) and not contact.zone.strip():
            problems.append("Zone 为空")
        if self.get("check_grid", False) and not contact.gridsquare.strip():
            problems.append("网格为空")

        if not problems:
            return None
        return self.event(
            ctx,
            reason=f"{contact.call} 交换缺失: {'; '.join(problems)}",
        )
