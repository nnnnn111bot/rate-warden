"""规则引擎：持有共享状态，把 N1MM 事件分发给规则，并决定实际惩罚。

设计要点
- 一个 QSO 可能同时命中多条规则 -> 只发强度最高的一条，避免波形排队叠加。
- 连续失误（axis="mistake"）会递进放大强度，倍数封顶 2x，并夹到 strength_cap。
- 空窗类（axis="rate"）不参与递进，触发后重置连击计数。
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from .rule_base import Contact, Context, PenaltyEvent, Rule


class Engine:
    def __init__(self, sink, strength_cap: int = 70,
                 on_log: Optional[Callable[[str], None]] = None,
                 on_penalty: Optional[Callable[[PenaltyEvent, Rule], None]] = None,
                 event_log=None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.sink = sink
        self.strength_cap = int(strength_cap)
        self.on_log = on_log or (lambda _m: None)
        self.on_penalty = on_penalty
        self.event_log = event_log
        self.clock = clock

        # 共享状态
        self.last_qso_time = clock()
        self.worked: set = set()
        self.last_call: Optional[str] = None
        self.last_call_time: float = 0.0
        self.pending_lookup_call: Optional[str] = None
        self.pending_lookup_time: float = 0.0
        self.is_running = False
        self.radio: dict = {}
        self.consecutive_mistakes = 0

        # 规则与每规则私有状态
        self.rules: list = []
        self._state: dict = {}
        self.last_contact_had_penalty = False

    # ---------- 规则管理 ----------
    def set_rules(self, rules: list) -> None:
        self.rules = list(rules)
        for rule in self.rules:
            self._state.setdefault(rule.id, {})

    def reset_state(self, rule_id: str) -> None:
        self._state[rule_id] = {}

    def clear_history(self) -> None:
        self.worked.clear()
        self.last_call = None
        self.pending_lookup_call = None
        self.consecutive_mistakes = 0

    # ---------- 事件入口 ----------
    def dispatch_radio(self, radio: dict) -> None:
        if not radio:
            return
        self.radio = radio
        if radio.get("is_running") is not None:
            self.is_running = bool(radio["is_running"])
        self._run("radio")

    def dispatch_lookup(self, contact: Contact) -> None:
        if not contact or not contact.call:
            return
        self.pending_lookup_call = contact.call
        self.pending_lookup_time = self.clock()
        self._run("lookup", contact=contact, lookup_call=contact.call)

    def dispatch_contact(self, contact: Contact, deleted: bool = False) -> None:
        if not contact or not contact.call:
            return
        key = (contact.band, contact.mode, contact.call)

        if deleted:
            self.worked.discard(key)
            self.on_log(f"撤回记录: {contact.band}/{contact.mode}/{contact.call}")
            return

        if not contact.is_original:
            return  # 多机联动的转发包，跳过

        # 先分发，让 dupe 规则还能看到该记录尚未入集
        events = self._run("contact", contact=contact)
        self.last_contact_had_penalty = bool(events)

        self.worked.add(key)
        self.last_qso_time = self.clock()
        self.last_call = contact.call
        self.last_call_time = self.clock()
        if self.pending_lookup_call == contact.call:
            self.pending_lookup_call = None

        if events:
            self.consecutive_mistakes += 1
        else:
            self.consecutive_mistakes = 0

    def tick(self) -> None:
        self._run("tick")

    # ---------- 分发与裁决 ----------
    def _context(self, **kwargs) -> Context:
        return Context(
            now=self.clock(),
            last_qso_time=self.last_qso_time,
            is_running=self.is_running,
            worked=self.worked,
            last_call=self.last_call,
            last_call_time=self.last_call_time,
            pending_lookup_call=self.pending_lookup_call,
            pending_lookup_time=self.pending_lookup_time,
            consecutive_mistakes=self.consecutive_mistakes,
            strength_cap=self.strength_cap,
            radio=self.radio,
            **kwargs,
        )

    def _run(self, event_name: str, **kwargs) -> list:
        base = self._context(**kwargs)
        fired: list = []
        for rule in self.rules:
            if event_name not in rule.events:
                continue
            ctx = Context(**{**base.__dict__, "state": self._state.setdefault(rule.id, {})})
            handler = getattr(rule, f"on_{event_name}", None)
            if handler is None:
                continue
            try:
                event = handler(ctx)
            except Exception as exc:
                self.on_log(f"规则 {rule.id} 抛异常: {exc}")
                continue
            if isinstance(event, PenaltyEvent):
                fired.append((event, rule))

        if not fired:
            return []

        if event_name == "contact":
            chosen = self._pick_strongest(fired)
            self._emit(chosen[0], chosen[1], fired)
            return [chosen[0]]

        # tick / lookup / radio 逐条处理
        results = []
        for event, rule in fired:
            self._emit(event, rule, fired)
            results.append(event)

        if event_name == "tick":
            if results:
                self.consecutive_mistakes = 0
            # 规则可以通过 state["request_clear_pending"] 请求清掉待办呼号
            for _event, rule in fired:
                state = self._state.get(rule.id, {})
                if state.pop("request_clear_pending", False):
                    self.pending_lookup_call = None
        return results

    @staticmethod
    def _pick_strongest(fired: list) -> tuple:
        return max(fired, key=lambda pair: (pair[0].strength_pct, pair[0].duration_s))

    def _emit(self, event: PenaltyEvent, rule: Rule, all_fired: list) -> None:
        final = event
        multiplier = 1.0
        if getattr(rule, "axis", "mistake") == "mistake":
            multiplier = min(1.0 + 0.25 * self.consecutive_mistakes, 2.0)
            if multiplier > 1.0:
                final = event.scaled(multiplier, self.strength_cap)
                self.on_log(
                    f"连击 x{self.consecutive_mistakes} -> 强度 {event.strength_pct}% "
                    f"放大到 {final.strength_pct}%"
                )
        else:
            final = event.scaled(1.0, self.strength_cap)

        merged_with = ""
        if len(all_fired) > 1:
            merged_with = ", ".join(
                f"{r.name}[{r.id}]" for e, r in all_fired if e is not event
            )

        if final.strength_pct <= 0 and final.action != "waveform":
            self.on_log(f"规则 {rule.id} 强度为 0，跳过发送")
            self._record("blocked", f"跳过 {rule.name}: 强度为 0", level="warn",
                         rule=rule, event=final, merged_with=merged_with)
            return

        self.on_log(
            f"惩罚 {rule.name} [{rule.id}]: {final.reason} | "
            f"强度+{final.strength_pct}% {final.duration_s}s "
            f"波形={final.preset or '-'} 通道={final.channel}"
        )
        if self.on_penalty:
            self.on_penalty(final, rule)

        delivered = self.sink.fire(final)
        self._record(
            "penalty" if delivered else "blocked",
            (f"{rule.name} 触发：{final.reason}" if delivered
             else f"{rule.name} 判定命中但未送达：{final.reason}"),
            level="info" if delivered else "warn",
            rule=rule, event=final, merged_with=merged_with,
            extra={"delivered": delivered, "multiplier": round(multiplier, 2),
                   "combo": self.consecutive_mistakes},
        )

        if merged_with:
            self.on_log(f"同一次事件还有 {merged_with} 也命中，已合并为一次输出")

    def _record(self, kind: str, message: str, level: str = "info",
                rule: Optional[Rule] = None, event: Optional[PenaltyEvent] = None,
                merged_with: str = "", extra: Optional[dict] = None) -> None:
        """写结构化日志（磁盘 + 内存）。没有 event_log 时静默跳过。"""
        if self.event_log is None:
            return
        context = {"merged_with": merged_with} if merged_with else {}
        if extra:
            context.update(extra)
        self.event_log.add(
            kind=kind,
            message=message,
            level=level,
            rule_id=getattr(rule, "id", "") or (event.rule_id if event else ""),
            rule_name=getattr(rule, "name", "") or "",
            strength=event.strength_pct if event else 0,
            duration=event.duration_s if event else 0.0,
            preset=event.preset if event else "",
            channel=event.channel if event else "",
            reason=event.reason if event else "",
            context=context,
        )
