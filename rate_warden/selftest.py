"""离线自检：不需要 N1MM / DGHub / 设备。

跑法：
    python -m rate_warden.selftest
    python main.py --check

返回码 0 = 全部通过。
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from . import loader, waveforms
from .engine import Engine
from .n1mm import parse
from .rule_base import Contact, PenaltyEvent
from .sink import NullSink


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


RESULTS: list = []


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as exc:
        RESULTS.append((False, name, str(exc)))
        print(f"[FAIL] {name}: {exc}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, name, f"{type(exc).__name__}: {exc}"))
        print(f"[ERROR] {name}: {type(exc).__name__}: {exc}")
    else:
        RESULTS.append((True, name, ""))
        print(f"[ OK ] {name}")


def make_engine(clock=None) -> tuple:
    sink = NullSink()
    engine = Engine(sink=sink, strength_cap=70, clock=clock or time.monotonic)
    return engine, sink


def enabled(rules: list, *ids: str) -> list:
    wanted = set(ids)
    return [r for r in rules if r.id in wanted]


# --------------------------------------------------------------------------- #
# 用例
# --------------------------------------------------------------------------- #

def test_rule_discovery() -> None:
    found, errors = loader.discover()
    assert not errors, f"加载错误: {errors}"
    ids = {entry["id"] for entry in found}
    for expected in ("empty_window", "dupe", "similar_call",
                     "missing_exchange", "lookup_timeout"):
        assert expected in ids, f"缺少内置规则 {expected}"
    assert len(ids) == len(found), "规则 id 有重复"


def test_param_coercion() -> None:
    found, _ = loader.discover()
    entry = next(e for e in found if e["id"] == "empty_window")
    rule = entry["class"]({"window_s": "999999", "strength": "abc", "bogus": 1})
    assert rule.get("window_s") == 600.0, "float 参数未夹到上限"
    assert rule.get("strength") == rule.default_params()["strength"], "非法值应保持默认"
    rejected = rule.set_params({"bogus": 1})
    assert "bogus" in rejected, "未知参数应被拒绝"


def test_import_validation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        bad_syntax = tmp_path / "bad_syntax.py"
        bad_syntax.write_text("class X(:\n", encoding="utf-8")
        ok, message, _ = loader.import_file(str(bad_syntax))
        assert not ok and "语法错误" in message, f"应拒绝语法错误: {message}"

        no_rule = tmp_path / "no_rule.py"
        no_rule.write_text("VALUE = 1\n", encoding="utf-8")
        ok, message, _ = loader.import_file(str(no_rule))
        assert not ok and "Rule" in message, f"应拒绝无规则文件: {message}"

        cross_import = tmp_path / "cross_import.py"
        cross_import.write_text(
            "from rate_warden.rules.dupe import DupeRule\n", encoding="utf-8")
        ok, message, _ = loader.import_file(str(cross_import))
        assert not ok and "import" in message, f"应拒绝互相 import: {message}"

        good = tmp_path / "good_rule.py"
        good.write_text(
            "from rate_warden.rule_base import Rule\n"
            "class GoodRule(Rule):\n"
            "    id = 'good_rule'\n"
            "    name = '好规则'\n"
            "    events = ('contact',)\n"
            "    params_schema = []\n",
            encoding="utf-8")
        info = loader.inspect_file(good)
        assert info["ok"], f"合法规则应通过: {info['error']}"


def test_empty_window() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    rule = next(e["class"]() for e in found if e["id"] == "empty_window")
    rule.set_params({"window_s": 30.0, "cooldown_s": 60.0,
                     "require_run": True, "require_radio": True})
    engine.set_rules([rule])

    engine.dispatch_radio({"is_running": True, "mode": "SSB"})
    engine.tick()  # 首次 tick 开始计时
    clock.advance(31.0)
    engine.tick()
    assert len(sink.sent) == 1, f"S&P 应触发 1 次，实际 {len(sink.sent)}"

    sink.sent.clear()
    clock.advance(31.0)
    engine.tick()
    assert not sink.sent, "冷却期内不应重复触发"

    # S&P 模式豁免
    engine2, sink2 = make_engine(FakeClock())
    rule2 = next(e["class"]() for e in found if e["id"] == "empty_window")
    rule2.set_params({"window_s": 30.0, "cooldown_s": 0.0, "require_run": True})
    engine2.set_rules([rule2])
    engine2.dispatch_radio({"is_running": False, "mode": "SSB"})
    engine2.tick()
    engine2.clock.advance(120.0)
    engine2.tick()
    assert not sink2.sent, "S&P 模式不应触发空窗惩罚"


def test_empty_window_needs_qso() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    rule = next(e["class"]() for e in found if e["id"] == "empty_window")
    rule.set_params({"window_s": 30.0, "cooldown_s": 0.0})
    engine.set_rules([rule])
    engine.dispatch_radio({"is_running": True, "mode": "SSB"})
    engine.tick()

    for _ in range(3):
        clock.advance(20.0)
        engine.dispatch_contact(Contact(call="W1AW", band="20m", mode="SSB",
                                        rcvnr="59"))
        engine.tick()
    assert not sink.sent, "每 20 秒出一个 QSO，不应触发空窗"


def test_dupe() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    rule = next(e["class"]() for e in found if e["id"] == "dupe")
    engine.set_rules([rule])

    first = Contact(call="K1ABC", band="20m", mode="SSB", rcvnr="59")
    engine.dispatch_contact(first)
    assert not sink.sent, "首次通联不应判 dupe"

    again = Contact(call="K1ABC", band="20m", mode="SSB", rcvnr="59")
    engine.dispatch_contact(again)
    assert len(sink.sent) == 1, "同波段同模式重复应触发"

    other_band = Contact(call="K1ABC", band="40m", mode="SSB", rcvnr="59")
    sink.sent.clear()
    engine.dispatch_contact(other_band)
    assert not sink.sent, "不同波段不应判 dupe"

    forwarded = Contact(call="K1ABC", band="20m", mode="SSB",
                        rcvnr="59", is_original=False)
    sink.sent.clear()
    engine.dispatch_contact(forwarded)
    assert not sink.sent, "转发包应被忽略"


def test_dupe_delete_clears() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    rule = next(e["class"]() for e in found if e["id"] == "dupe")
    engine.set_rules([rule])
    contact = Contact(call="K1ABC", band="20m", mode="SSB", rcvnr="59")
    engine.dispatch_contact(contact)
    engine.dispatch_contact(contact, deleted=True)
    sink.sent.clear()
    engine.dispatch_contact(contact)
    assert not sink.sent, "撤回后重新落库不应判 dupe"


def test_similar_call() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    rule = next(e["class"]() for e in found if e["id"] == "similar_call")
    rule.set_params({"similarity": 0.75, "gap_s": 15.0})
    engine.set_rules([rule])

    engine.dispatch_contact(Contact(call="K1ABC", band="20m", mode="SSB", rcvnr="59"))
    clock.advance(5.0)
    engine.dispatch_contact(Contact(call="K1ABD", band="20m", mode="SSB", rcvnr="59"))
    assert len(sink.sent) == 1, "相似呼号应触发"

    # 字母前缀不同 = 不同电台，不应触发
    sink.sent.clear()
    clock.advance(1.0)
    engine.dispatch_contact(Contact(call="W1ABD", band="20m", mode="SSB", rcvnr="59"))
    assert not sink.sent, "字母前缀不同不应触发"

    # 间隔过久不应触发
    sink.sent.clear()
    clock.advance(300.0)
    engine.dispatch_contact(Contact(call="K1ABX", band="20m", mode="SSB", rcvnr="59"))
    assert not sink.sent, "间隔过久不应触发"


def test_merge_single_output() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    dupe_rule = next(e["class"]({"strength": 60}) for e in found if e["id"] == "dupe")
    sim_rule = next(e["class"]({"strength": 45}) for e in found if e["id"] == "similar_call")
    engine.set_rules([dupe_rule, sim_rule])

    engine.dispatch_contact(Contact(call="K1ABC", band="20m", mode="SSB", rcvnr="59"))
    clock.advance(3.0)
    engine.dispatch_contact(Contact(call="K1ABC", band="20m", mode="SSB", rcvnr="59"))
    assert len(sink.sent) == 1, f"同时命中应只发一次，实际 {len(sink.sent)}"
    assert sink.sent[0].rule_id == "dupe", "应选择强度更高的 dupe"
    assert sink.sent[0].strength_pct == 60


def test_escalation_capped() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    dupe_rule = next(e["class"]({"strength": 60}) for e in found if e["id"] == "dupe")
    sim_rule = next(e["class"]({"strength": 50}) for e in found if e["id"] == "similar_call")
    engine.set_rules([dupe_rule, sim_rule])

    engine.dispatch_contact(Contact(call="K1ABC", band="20m", mode="SSB", rcvnr="59"))
    for index in range(6):
        clock.advance(1.0)
        engine.dispatch_contact(
            Contact(call="K1ABC", band="20m", mode="SSB", rcvnr="59"))
    assert engine.consecutive_mistakes >= 3, "连击计数应累积"
    assert all(e.strength_pct <= 70 for e in sink.sent), "强度必须被 strength_cap 夹住"
    assert sink.sent[-1].strength_pct >= sink.sent[0].strength_pct, "强度应递进不回退"


def test_lookup_timeout() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    rule = next(e["class"]({"timeout_s": 90.0}) for e in found
                if e["id"] == "lookup_timeout")
    engine.set_rules([rule])

    engine.dispatch_lookup(Contact(call="JA1XYZ", band="20m", mode="CW"))
    clock.advance(30.0)
    engine.tick()
    assert not sink.sent, "未到阈值不应触发"

    clock.advance(70.0)
    engine.tick()
    assert len(sink.sent) == 1, "超过阈值应触发一次"
    clock.advance(10.0)
    engine.tick()
    assert len(sink.sent) == 1, "同一呼号不应重复罚"


def test_missing_exchange() -> None:
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    rule = next(e["class"]({"check_rcvnr": True}) for e in found
                if e["id"] == "missing_exchange")
    engine.set_rules([rule])

    engine.dispatch_contact(Contact(call="K2BBB", band="20m", mode="CW", rcvnr=""))
    assert len(sink.sent) == 1, "rcvnr 为空应触发"

    sink.sent.clear()
    engine.dispatch_contact(Contact(call="K2BBC", band="20m", mode="CW", rcvnr="001"))
    assert not sink.sent, "rcvnr 正常不应触发"


def test_n1mm_parse() -> None:
    xml = (
        "<contactinfo>"
        "<app>N1MM</app><contestnr>1</contestnr><timestamp>2026-11-15 01:00:00</timestamp>"
        "<mycall>BG5XYZ</mycall><band>20m</band><mode>SSB</mode>"
        "<call>K1ABC</call><sntnr>001</sntnr><rcvnr>59</rcvnr>"
        "<IsOriginal>True</IsOriginal><IsRunQSO>1</IsRunQSO>"
        "</contactinfo>"
    )
    kind, contact, radio = parse(xml)
    assert kind == "contactinfo", f"解析类型错误: {kind}"
    assert contact is not None and contact.call == "K1ABC"
    assert contact.band == "20m" and contact.mode == "SSB"
    assert contact.is_original is True and contact.is_run_qso is True

    radio_xml = "<radioinfo><app>N1MM</app><IsRunning>True</IsRunning></radioinfo>"
    kind, contact, radio = parse(radio_xml)
    assert kind == "radioinfo" and radio and radio["is_running"] is True

    assert parse("not xml at all")[0] == ""
    assert parse("<otherinfo><call>X</call></otherinfo>")[0] == ""


def test_end_to_end_udp_event() -> None:
    """模拟真实 N1MM 包 -> 解析 -> 引擎 -> NullSink 收到 trigger。"""
    clock = FakeClock()
    engine, sink = make_engine(clock)
    found, _ = loader.discover()
    dupe_rule = next(e["class"]() for e in found if e["id"] == "dupe")
    engine.set_rules([dupe_rule])

    packet = (
        "<contactinfo><band>20m</band><mode>SSB</mode><call>K9Z</call>"
        "<rcvnr>59</rcvnr><IsOriginal>True</IsOriginal></contactinfo>"
    )
    for _ in range(2):
        kind, contact, _radio = parse(packet)
        assert kind == "contactinfo"
        engine.dispatch_contact(contact)
    assert len(sink.sent) == 1 and sink.sent[0].rule_id == "dupe"
    assert sink.sent[0].channel == "both"


def test_wave_library() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = waveforms.WaveLibrary(Path(tmp))
        lib.load()
        ok, _ = lib.add("CS2-受伤", alias="短刺激", note="高频")
        assert ok
        ok, message = lib.add("CS2-受伤")
        assert not ok and "已存在" in message

        result = lib.add_many("CS2-死亡 | 重击 | 长波形\n呼吸 | 缓脉冲\n# 注释\n")
        assert result["added"] == 2 and not result["errors"]

        lib2 = waveforms.WaveLibrary(Path(tmp))
        lib2.load()
        assert set(lib2.names()) == {"CS2-受伤", "CS2-死亡", "呼吸"}
        found_wave = lib2.find("重击")
        assert found_wave is not None and found_wave.name == "CS2-死亡"

        bad = Path(tmp) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        result = lib2.import_file(str(bad))
        assert result["errors"], "损坏的 json 应报错而不是崩溃"


def test_sink_emergency_stop() -> None:
    sink = NullSink()
    assert sink.emergency_stop() is True
    assert sink.stops == 1
    event = PenaltyEvent(rule_id="x", strength_pct=10)
    assert sink.fire(event) is True
    assert len(sink.sent) == 1


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

CASES = [
    ("内置规则可加载", test_rule_discovery),
    ("参数类型校验", test_param_coercion),
    ("规则导入校验", test_import_validation),
    ("空窗规则触发与冷却", test_empty_window),
    ("有空 QSO 时空窗不触发", test_empty_window_needs_qso),
    ("Dupe 判定", test_dupe),
    ("撤回后不判 Dupe", test_dupe_delete_clears),
    ("相似呼号", test_similar_call),
    ("同一 QSO 只输出一次", test_merge_single_output),
    ("连击递进并夹上限", test_escalation_capped),
    ("磕台超时", test_lookup_timeout),
    ("交换缺失", test_missing_exchange),
    ("N1MM XML 解析", test_n1mm_parse),
    ("端到端事件链", test_end_to_end_udp_event),
    ("波形库", test_wave_library),
    ("Sink 急停", test_sink_emergency_stop),
]


def main(argv: Optional[list] = None) -> int:
    print("Rate Warden 自检\n" + "-" * 46)
    for name, fn in CASES:
        check(name, fn)
    passed = sum(1 for ok, _n, _m in RESULTS if ok)
    total = len(RESULTS)
    print("-" * 46)
    print(f"通过 {passed}/{total}")
    failures = [(n, m) for ok, n, m in RESULTS if not ok]
    if failures:
        print("\n失败项：")
        for name, message in failures:
            print(f"  - {name}: {message}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
