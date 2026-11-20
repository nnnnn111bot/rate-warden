"""规则：相似呼号快速落库（抄错呼号风险）。

比赛里"抄错一个字母就回车"是 NIL / Busted 的主要来源。
这里用编辑相似度在落库瞬间提醒。
"""

from difflib import SequenceMatcher

from rate_warden.rule_base import Rule, Param, Context, common_penalty_params


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _call_prefix(call: str) -> str:
    """取呼号的字母前缀（K1ABC -> K, JA1XYZ -> JA）。"""
    letters = []
    for char in call or "":
        if char.isalpha():
            letters.append(char)
        else:
            break
    return "".join(letters)


class SimilarCallRule(Rule):
    id = "similar_call"
    name = "相似呼号风险"
    description = (
        "新落库的呼号与上一个呼号高度相似（如 K1ABC / K1ABD），"
        "且两条记录间隔很短时提醒，降低抄错字母的概率。"
    )
    events = ("contact",)
    axis = "mistake"
    params_schema = [
        Param("similarity", "相似度阈值", "float", 0.75, 0.5, 1.0,
              help="0.75 大致等于 5 位呼号里差 1 个字符（K1ABC vs K1ABD 即 0.8）。"),
        Param("gap_s", "间隔阈值(秒)", "float", 15.0, 1.0, 600.0,
              help="两条 QSO 间隔超过这个秒数就不再判定为连续手误。"),
        Param("ignore_prefix_len", "前缀保护长度", "int", 0,
              help="大于 0 时，前缀不同则直接放过（如前 N 个字符不同视为不同电台）。"
                   "呼号的字母前缀不同时总会放过。"),
        *common_penalty_params(default_strength=50, default_duration=0.6),
    ]

    def on_contact(self, ctx: Context):
        contact = ctx.contact
        if contact is None or not ctx.last_call:
            return None

        gap = float(self.get("gap_s", 15.0))
        if ctx.now - ctx.last_call_time > gap:
            return None

        previous, current = ctx.last_call, contact.call
        if previous == current:
            return None

        # 前缀（字母部分）不同 = 不同电台，直接放过。
        # 数字后同位置换一个字母的（K1ABC -> K1ABD）才属于抄错风险。
        guard = int(self.get("ignore_prefix_len", 0) or 0)
        if guard > 0 and previous[:guard] != current[:guard]:
            return None
        if _call_prefix(previous) != _call_prefix(current):
            return None

        if len(previous) != len(current):
            return None

        score = similarity(previous, current)
        if score < float(self.get("similarity", 0.75)):
            return None

        return self.event(
            ctx,
            reason=f"呼号相似度 {score:.2f}: {previous} -> {current}",
        )
