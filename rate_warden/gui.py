"""Rate Warden 的 Qt（PySide6）界面。

四页：
  规则 —— 启用/调参/导入/新建/编辑/热重载
  波形 —— 导入预设名、预览试放、编辑别名备注
  说明 —— 规则写法、协议事实、N1MM 与 DGHub 配置步骤
  日志 —— 实时事件与惩罚记录
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import APP_NAME, APP_NAME_CN, __version__, config, loader, theme, waveforms
from .engine import Engine
from .eventlog import EventLog, LogRecord
from .n1mm import Listener
from .rule_base import EVENTS, Param, PenaltyEvent, Rule
from .sink import DghubSink, NullSink, Sink

MONO = theme.MONO_FAMILY


# --------------------------------------------------------------------------- #
# 规则表单
# --------------------------------------------------------------------------- #

class RuleForm(QWidget):
    """根据 params_schema 自动生成控件。"""

    changed = Signal()

    def __init__(self, wave_labels: list, parent=None) -> None:
        super().__init__(parent)
        self.wave_labels = wave_labels
        self.editors: dict = {}
        self.rule: Optional[Rule] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.header = QLabel("未选择规则")
        self.header.setWordWrap(True)
        self.header.setTextFormat(Qt.RichText)
        outer.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setLabelAlignment(Qt.AlignRight)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        scroll.setWidget(self.body)

        self.tip = QLabel("把鼠标停在参数上可以看到说明。")
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("color:#666;")
        outer.addWidget(self.tip)

    # -- 构建 --
    def load_rule(self, rule: Rule) -> None:
        self.rule = rule
        self.header.setText(
            f"<b>{rule.name}</b> <span style='color:#888'>[{rule.id}]</span><br>"
            f"<span style='color:#555'>{rule.description}</span><br>"
            f"<span style='color:#888'>订阅事件: {', '.join(rule.events) or '无'} · "
            f"类别: {'节奏' if getattr(rule, 'axis', 'mistake') == 'rate' else '失误'}</span>"
        )
        self._rebuild()

    def clear(self) -> None:
        self.rule = None
        self.editors.clear()
        while self.form.count():
            item = self.form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.header.setText("未选择规则")
        self.tip.setText("")

    def _rebuild(self) -> None:
        while self.form.count():
            item = self.form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.editors.clear()
        if self.rule is None:
            return

        groups: dict = {}
        for spec in self.rule.params_schema:
            groups.setdefault(spec.group or "常规", []).append(spec)

        for group_name, specs in groups.items():
            if len(groups) > 1 or group_name != "常规":
                self.form.addRow(_section_label(group_name))
            for spec in specs:
                editor = self._make_editor(spec)
                self.editors[spec.key] = editor
                holder = QWidget()
                row = QHBoxLayout(holder)
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(editor, 1)
                help_btn = QLabel("?")
                help_btn.setToolTip(spec.help or spec.label)
                help_btn.setFixedWidth(14)
                help_btn.setStyleSheet("color:#0a7;font-weight:bold;")
                help_btn.setCursor(Qt.WhatsThisCursor)
                help_btn.mousePressEvent = (  # type: ignore[method-assign]
                    lambda _e, s=spec: self.tip.setText(s.help or s.label)
                )
                row.addWidget(help_btn)
                self.form.addRow(spec.label, holder)

    def _make_editor(self, spec: Param):
        value = self.rule.params.get(spec.key, spec.default) if self.rule else spec.default
        if spec.type == "bool":
            editor = QCheckBox()
            editor.setChecked(bool(value))
            editor.toggled.connect(self.changed)
        elif spec.type == "int":
            editor = QSpinBox()
            editor.setRange(int(spec.min if spec.min is not None else -10**6),
                            int(spec.max if spec.max is not None else 10**6))
            editor.setValue(int(value))
            editor.valueChanged.connect(self.changed)
        elif spec.type == "float":
            editor = QDoubleSpinBox()
            editor.setDecimals(2)
            editor.setRange(float(spec.min if spec.min is not None else -10**6),
                            float(spec.max if spec.max is not None else 10**6))
            editor.setSingleStep(0.5)
            editor.setValue(float(value))
            editor.valueChanged.connect(self.changed)
        elif spec.type == "choice":
            editor = QComboBox()
            for choice in spec.choices or []:
                editor.addItem(str(choice))
            if str(value) in [str(c) for c in (spec.choices or [])]:
                editor.setCurrentText(str(value))
            editor.currentTextChanged.connect(self.changed)
        elif spec.type == "waveform":
            editor = QComboBox()
            editor.setEditable(True)
            editor.addItem("")
            for label in self.wave_labels:
                editor.addItem(label)
            editor.setCurrentText(str(value or ""))
            editor.currentTextChanged.connect(self.changed)
        else:
            editor = QLineEdit(str(value or ""))
            editor.textChanged.connect(self.changed)

        editor.setToolTip(spec.help or spec.label)
        if isinstance(editor, (QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit)):
            editor.setMinimumWidth(160)
        return editor

    # -- 取值 --
    def collect(self) -> dict:
        if self.rule is None:
            return {}
        values = {}
        for spec in self.rule.params_schema:
            editor = self.editors.get(spec.key)
            if editor is None:
                continue
            if isinstance(editor, QCheckBox):
                values[spec.key] = editor.isChecked()
            elif isinstance(editor, QSpinBox):
                values[spec.key] = editor.value()
            elif isinstance(editor, QDoubleSpinBox):
                values[spec.key] = editor.value()
            elif isinstance(editor, QComboBox):
                values[spec.key] = editor.currentText()
            else:
                values[spec.key] = editor.text()
        return values


def _section_label(text: str) -> QLabel:
    label = QLabel(f"<b>{text}</b>")
    label.setStyleSheet("color:#2b6cb0;margin-top:6px;")
    return label


class _StatCard(QFrame):
    """统计卡片：大数字 + 说明。"""

    def __init__(self, title: str, value: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:#ffffff;border:1px solid {theme.COLORS['border']};"
            f"border-radius:10px;}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color:{theme.COLORS['muted']};font-size:12px;border:none;background:transparent;")
        self.value = QLabel(value)
        self.value.setStyleSheet(
            f"color:{color};font-size:22px;font-weight:700;"
            f"border:none;background:transparent;")
        self.value.setWordWrap(False)
        layout.addWidget(title_label)
        layout.addWidget(self.value)


def _stat_card(title: str, value: str, color: str) -> _StatCard:
    return _StatCard(title, value, color)


# --------------------------------------------------------------------------- #
# 波形预览
# --------------------------------------------------------------------------- #

class WavePreview(QWidget):
    """因为协议只传预设名、没有帧数据，这里画的是"强度包络示意"。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.points: list = []
        self.caption = "选择一个波形查看示意"

    def set_shape(self, points: list, caption: str) -> None:
        self.points = points
        self.caption = caption
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfbfb"))

        margin = 24
        width = max(1, self.width() - margin * 2)
        height = max(1, self.height() - margin * 2)

        painter.setPen(QPen(QColor("#e2e2e2"), 1))
        for i in range(5):
            y = margin + height * i / 4
            painter.drawLine(margin, int(y), margin + width, int(y))

        painter.setPen(QPen(QColor("#666"), 1))
        painter.drawText(margin, self.height() - 6, self.caption)

        if len(self.points) < 2:
            painter.setPen(QPen(QColor("#999"), 1))
            painter.drawText(margin + 8, margin + 20, "（无示意数据）")
            return

        path = QPainterPath()
        for index, value in enumerate(self.points):
            x = margin + width * index / (len(self.points) - 1)
            y = margin + height * (1.0 - max(0.0, min(1.0, value)))
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(QColor("#c53030"), 2))
        painter.drawPath(path)


def shape_for(name: str) -> tuple:
    """按预设名猜一个示意曲线（仅视觉参考）。"""
    lowered = (name or "").lower()
    if any(k in lowered for k in ("死亡", "death", "重", "strong")):
        return ([i / 20 for i in range(21)], "示意：持续高强度")
    if any(k in lowered for k in ("受伤", "hurt", "hit", "刺")):
        return ([1.0 if i in (6, 7, 14, 15) else 0.15 for i in range(21)],
                "示意：短促脉冲")
    if any(k in lowered for k in ("呼吸", "breath")):
        import math
        return ([0.5 + 0.45 * math.sin(i / 20 * 3.14159 * 2) for i in range(21)],
                "示意：缓变脉冲")
    if any(k in lowered for k in ("心跳", "heart")):
        seq = [0.1] * 21
        for index, value in ((3, 0.9), (4, 0.5), (9, 1.0), (10, 0.4)):
            seq[index] = value
        return (seq, "示意：心跳节拍")
    return ([0.25 + 0.6 * (i / 20) for i in range(21)], "示意：中频渐强")


# --------------------------------------------------------------------------- #
# 说明页
# --------------------------------------------------------------------------- #

GUIDE_RULES = """<h2>规则写作指南</h2>
<p>每条规则就是一个 <code>.py</code> 文件，放在 <code>rules_user/</code>。程序会在导入时
做静态检查，然后按需热加载。规则只允许依赖 <code>rate_warden.rule_base</code> 和标准库。</p>

<h3>最小骨架</h3>
<pre style="background:#f5f5f5;padding:8px;">from rate_warden.rule_base import Rule, Param, Context, common_penalty_params

class MyRule(Rule):
    id = "my_rule"           # 全局唯一
    name = "我的规则"
    description = "一句话说明触发条件"
    events = ("contact",)    # contact / tick / lookup / radio
    axis = "mistake"         # mistake = 参与连击递进; rate = 不参与
    params_schema = [
        Param("threshold", "阈值", "int", 3, 1, 10, help="悬停说明"),
        *common_penalty_params(default_strength=40, default_duration=1.0),
    ]

    def on_contact(self, ctx: Context):
        c = ctx.contact
        if c is None:
            return None
        if len(c.call) &lt; int(self.get("threshold", 3)):
            return self.event(ctx, reason=f"呼号太短: {c.call}")
        return None
</pre>

<h3>事件</h3>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>事件</th><th>时机</th><th>ctk 可用字段</th></tr>
<tr><td>on_contact</td><td>QSO 落库</td><td>ctx.contact（band/mode/call/sntnr/rcvnr/power/section/zone/gridsquare）</td></tr>
<tr><td>on_lookup</td><td>按 Tab/空格，准备呼号</td><td>ctx.lookup_call</td></tr>
<tr><td>on_radio</td><td>N1MM 广播运行状态</td><td>ctx.radio（is_running/freq/mode）、ctx.is_running</td></tr>
<tr><td>on_tick</td><td>心跳（默认 4Hz）</td><td>ctx.now、ctx.idle_seconds、ctx.pending_lookup_call</td></tr>
</table>

<h3>共享状态（只读）</h3>
<p><code>ctx.worked</code> 已通联集合 <code>{(band, mode, call)}</code>；
<code>ctx.last_call</code> / <code>ctx.last_call_time</code> 上一条 QSO；
<code>ctx.consecutive_mistakes</code> 当前连击数；
<code>ctx.strength_cap</code> 全局强度上限。</p>

<h3>私有状态</h3>
<p><code>ctx.state</code> 是每条规则自己的 dict，用来记住上次触发时间等，
跨回调保留。<code>ctx.state["request_clear_pending"] = True</code> 可以请求引擎清掉待办呼号。</p>

<h3>返回惩罚</h3>
<p>返回 <code>self.event(ctx, reason="...")</code> 就表示罚一次；返回 <code>None</code> 表示放过。
同一 QSO 命中多条规则时，引擎只发强度最高的一条。</p>

<h3>安全约定</h3>
<ul>
<li>规则文件之间禁止互相 <code>import</code>，保证可热重载。</li>
<li>惩罚强度会被 <code>config.json</code> 的 <code>strength_cap</code> 硬夹一次。</li>
<li>所有惩罚走 <code>rollback</code> 模式，到期自动回到 baseline。</li>
</ul>
"""

GUIDE_WAVE = """<h2>波形与协议</h2>

<div style="background:#fff4e5;border-left:4px solid #d97706;padding:8px;">
<b>必须先澄清一个常见的误解：</b><br>
DGHub 的插件协议里，<code>trigger</code> / <code>pulse</code> <b>只接受波形"预设名"字符串</b>
（例如 <code>"CS2-受伤"</code>），<b>不支持</b>由插件下发任意 HEX 帧数据。
所谓"第三方程序可以下发波形"，指的正是"指定用哪个预设、播多久、强度加多少"，
而不是把自造的帧序列推给手机。
</div>

<h3>所以这里的"波形库"是什么</h3>
<p>它管的是<b>预设名 + 用途别名 + 备注</b>：把 DGHub 里的官方预设名逐字录入，
再给它起个比赛用途的别名（如「dupe 重击」），规则里直接引用别名即可。
预设名必须与 DGHub 里显示的名字<b>完全一致</b>，包括大小写与「-」「_」。</p>

<h3>导入方式</h3>
<ol>
<li><b>粘贴预设名</b>：一行一个，支持 <code>预设名 | 别名 | 备注</code>。</li>
<li><b>从文件导入</b>：<code>.txt</code>（每行一个名字）或 <code>.json</code>。</li>
<li><b>内置参考清单</b>：首次启动会在波形库中放入常见预设名，把左侧名字改成你的实际名字即可。</li>
</ol>

<h3>怎么拿到准确的预设名</h3>
<ul>
<li>打开 DGHub → 波形/预设页面，逐个抄写显示名。</li>
<li>或在 DGHub 的插件配置界面里，<code>preset</code> 类型字段的下拉框会自动从主程序拉取预设，
那里看到的就是权威名字。</li>
</ul>

<h3>建议的对应关系</h3>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>规则</th><th>波形特征</th><th>强度</th><th>时长</th></tr>
<tr><td>RUN 空窗</td><td>低频缓脉冲</td><td>40</td><td>1.0s</td></tr>
<tr><td>重复通联</td><td>中频较长</td><td>60</td><td>2.0s</td></tr>
<tr><td>相似呼号</td><td>高频短促</td><td>50</td><td>0.6s</td></tr>
<tr><td>交换缺失</td><td>低频中长</td><td>45</td><td>1.5s</td></tr>
<tr><td>磕台超时</td><td>中频中长</td><td>55</td><td>1.5s</td></tr>
</table>
"""

GUIDE_SETUP = """<h2>配置步骤</h2>

<h3>一、N1MM Logger+ 侧</h3>
<ol>
<li>菜单 <code>Config → Configure Ports → Broadcast Data</code>。</li>
<li>勾选 <b>Contacts</b>（ContactInfo 落库事件）并填入目标地址
<code>127.0.0.1</code>、端口 <code>12060</code>。同一台电脑时地址填 127.0.0.1 即可。</li>
<li><b>不需要</b>勾选 External Callsign Lookup —— 磕台超时规则需要 LookupInfo，
若你希望它工作，请勾选 <b>External Callsign Lookup</b> 一起广播。</li>
<li>点击 <b>OK</b>。<code>RadioInfo</code> 会在频率/模式变化时自动广播，
主要用于判断 RUN / S&amp;P。</li>
<li>Windows 防火墙首次可能拦截 UDP 入站，需要允许 Python 程序访问专用网络。</li>
</ol>
<p>本程序默认监听 <code>0.0.0.0:12060</code>。若端口被占用，可在顶栏点
<b>监听设置</b> 修改，改完重启监听。</p>

<h3>二、DGHub 侧</h3>
<ol>
<li>启动 DGHub 主程序（保持运行）。</li>
<li>打开「插件中心 → 外部插件」，准备导入本插件目录
<code>dghub_plugin/</code>（内含 <code>manifest.json</code> 与 <code>main.py</code>）。</li>
<li>DGHub 启动插件时会注入 <code>DGHUB_HOST / DGHUB_PORT / DGHUB_TOKEN</code>。
本程序既可以由 DGHub 拉起，也可以<b>手动启动</b>：手动启动时若拿不到 token，
会提示你从 DGHub 的 <code>GET /api/plugins/_session_token</code> 获取，
或直接以"未连接（只记录）"模式运行。</li>
<li>手机 DGHub APP 连上设备后，插件顶栏会显示设备型号与最大强度。</li>
</ol>

<h3>三、安全建议</h3>
<ul>
<li>全局强度上限 <code>strength_cap</code> 默认 70。比赛中惩罚频次高，建议先跑一小时再调高。</li>
<li>顶栏红色 <b>急停</b> 按钮随时把 A/B 强度归零，不经过规则引擎。</li>
<li>先勾掉全部规则，用 <b>模拟数据</b> 按钮确认事件链正常，再逐条启用规则。</li>
<li>S&amp;P 阶段不建议启用空窗规则，或把阈值调到 120 秒以上。</li>
</ul>
"""


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #

class MainWindow(QMainWindow):
    log_line = Signal(str, str)  # (level, message)
    record_added = Signal(object)  # LogRecord

    def __init__(self, cfg: dict, sink: Sink, demo: bool = False) -> None:
        super().__init__()
        self.cfg = cfg
        self.sink = sink
        self.demo = demo
        self.rules: list = []
        self.rule_index: dict = {}
        self.enabled_by_default = False

        self.wave_lib = waveforms.WaveLibrary()
        self.wave_lib.load()

        self.event_log = EventLog()
        # 引擎在 UDP 线程里也会写日志，信号跨线程投递到 GUI
        self.event_log.subscribe(
            lambda record: self.record_added.emit(record))

        self.engine = Engine(
            sink=self.sink,
            strength_cap=int(cfg.get("strength_cap", 70)),
            on_log=lambda message: self.log_line.emit("info", message),
            event_log=self.event_log,
        )
        self.listener: Optional[Listener] = None

        self.setWindowTitle(f"{APP_NAME} · {APP_NAME_CN}  v{__version__}")
        self.resize(1240, 820)
        self._build_ui()
        self._load_rules()
        self.log_line.connect(self._append_log)
        self.record_added.connect(self._on_record)
        # 波形列表依赖 UI 已建好，必须在 _build_ui 之后
        self._seed_waves()

        # 心跳
        self._last_tick = time.monotonic()
        self.heartbeat = QTimer(self)
        self.heartbeat.timeout.connect(self._on_heartbeat)
        hz = max(1, int(cfg.get("heartbeat_hz", 4) or 4))
        self.heartbeat.start(int(1000 / hz))

        self._status_poll = QTimer(self)
        self._status_poll.timeout.connect(self._refresh_status_lights)
        self._status_poll.start(700)

        self.start_listener()
        self.event_log.add("system", f"{APP_NAME} v{__version__} 已启动"
                                    + ("（演示模式）" if demo else ""))

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 8)
        outer.setSpacing(10)

        outer.addWidget(self._build_topbar())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_rules_tab(), "规则")
        self.tabs.addTab(self._build_waves_tab(), "波形")
        self.tabs.addTab(self._build_timeline_tab(), "记录")
        self.tabs.addTab(self._build_guide_tab(), "说明")
        self.tabs.addTab(self._build_log_tab(), "日志")
        outer.addWidget(self.tabs, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setStyleSheet(theme.TOPBAR_QSS)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 12, 14, 12)
        layout.setSpacing(14)

        # 品牌
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel(f"{APP_NAME}")
        brand.setObjectName("brand")
        brand_sub = QLabel(f"{APP_NAME_CN} · v{__version__}")
        brand_sub.setObjectName("brandSub")
        brand_box.addWidget(brand)
        brand_box.addWidget(brand_sub)
        layout.addLayout(brand_box)

        layout.addSpacing(10)

        # 四个状态胶囊
        self.lamp_n1mm = QLabel("N1MM 等待数据")
        self.lamp_sink = QLabel("DGHub 未连接")
        self.lamp_mode = QLabel("模式 -")
        self.lamp_idle = QLabel("空闲 -")
        self.penalty_count = QLabel("已罚 0 次")
        for label in (self.lamp_n1mm, self.lamp_sink, self.lamp_mode,
                      self.lamp_idle, self.penalty_count):
            pill = QFrame()
            pill.setObjectName("pill")
            pill_layout = QHBoxLayout(pill)
            pill_layout.setContentsMargins(12, 5, 12, 5)
            label.setStyleSheet(theme.lamp_style("#cbd5e1"))
            pill_layout.addWidget(label)
            layout.addWidget(pill)

        layout.addStretch(1)

        # 操作区
        self.master = QCheckBox("启用惩罚")
        # 总开关每次启动都默认打开；持久化只用于"记住你上次关掉了"的提示，
        # 但为避免一次误关导致整场静默，这里强制以开启状态启动。
        self.master.setChecked(True)
        if self.cfg.get("master_enabled") is False:
            self._log("warn", "上次退出时惩罚处于关闭状态，本次已自动重置为开启")
        self.master.setStyleSheet("color:#e2e8f0;font-weight:600;background:transparent;")
        self.master.setToolTip("总开关：关闭后所有规则仍会判定并写日志，但不会下发惩罚")
        self.master.stateChanged.connect(self._on_master)
        layout.addWidget(self.master)

        demo_btn = QPushButton("模拟数据")
        demo_btn.setToolTip("灌入一条假 QSO，验证事件链（不会真的发包）")
        demo_btn.clicked.connect(self._inject_demo_qso)
        layout.addWidget(demo_btn)

        listen_btn = QPushButton("监听设置…")
        listen_btn.clicked.connect(self._change_port)
        layout.addWidget(listen_btn)

        self.stop_btn = QPushButton("急  停")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.setFixedSize(132, 58)
        self.stop_btn.setStyleSheet(theme.STOP_QSS)
        self.stop_btn.setToolTip("立即把 A/B 通道强度归零，不经过任何规则")
        self.stop_btn.clicked.connect(self._emergency_stop)
        layout.addWidget(self.stop_btn)

        return bar

    def _build_rules_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_tree = QTreeWidget()
        self.rule_tree.setHeaderLabels(["启用", "规则", "id"])
        self.rule_tree.setRootIsDecorated(False)
        self.rule_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.rule_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.rule_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.rule_tree.itemSelectionChanged.connect(self._on_rule_selected)
        self.rule_tree.itemChanged.connect(self._on_rule_checked)
        left_layout.addWidget(self.rule_tree, 1)

        buttons = QGridLayout()
        import_btn = QPushButton("导入规则…")
        import_btn.clicked.connect(self._import_rule)
        new_btn = QPushButton("新建规则")
        new_btn.clicked.connect(self._new_rule)
        edit_btn = QPushButton("编辑源码")
        edit_btn.clicked.connect(self._edit_rule_source)
        reload_btn = QPushButton("重新扫描")
        reload_btn.clicked.connect(self._reload_rules)
        for index, button in enumerate((import_btn, new_btn, edit_btn, reload_btn)):
            buttons.addWidget(button, index // 2, index % 2)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_form = RuleForm(self.wave_lib.labels())
        right_layout.addWidget(self.rule_form, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_params_btn = QPushButton("保存参数")
        self.save_params_btn.clicked.connect(self._save_params)
        actions.addWidget(self.save_params_btn)
        reset_btn = QPushButton("恢复默认参数")
        reset_btn.clicked.connect(self._reset_params)
        actions.addWidget(reset_btn)
        right_layout.addLayout(actions)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 740])
        return splitter

    def _build_waves_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.wave_list = QListWidget()
        self.wave_list.currentItemChanged.connect(self._on_wave_selected)
        left_layout.addWidget(self.wave_list, 1)

        buttons = QGridLayout()
        paste_btn = QPushButton("粘贴预设名…")
        paste_btn.clicked.connect(self._import_wave_paste)
        file_btn = QPushButton("从文件导入…")
        file_btn.clicked.connect(self._import_wave_file)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_wave)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._reload_waves)
        for index, button in enumerate((paste_btn, file_btn, del_btn, refresh_btn)):
            buttons.addWidget(button, index // 2, index % 2)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        form_box = QGroupBox("波形信息")
        form = QFormLayout(form_box)
        self.wave_name = QLineEdit()
        self.wave_name.setReadOnly(True)
        self.wave_alias = QLineEdit()
        self.wave_note = QLineEdit()
        self.wave_source = QLabel("-")
        form.addRow("预设名（DGHub 原名）", self.wave_name)
        form.addRow("用途别名", self.wave_alias)
        form.addRow("备注", self.wave_note)
        form.addRow("来源", self.wave_source)
        right_layout.addWidget(form_box)

        preview_box = QGroupBox("形状示意（协议只传预设名，无帧数据可绘）")
        preview_layout = QVBoxLayout(preview_box)
        self.wave_preview = WavePreview()
        preview_layout.addWidget(self.wave_preview)
        right_layout.addWidget(preview_box, 1)

        actions = QHBoxLayout()
        save_btn = QPushButton("保存别名/备注")
        save_btn.clicked.connect(self._save_wave_meta)
        actions.addWidget(save_btn)
        actions.addStretch(1)
        preview_btn = QPushButton("预览试放（低强度）")
        preview_btn.setToolTip("用极低强度播放一次，只感受波形形状")
        preview_btn.clicked.connect(self._preview_wave)
        actions.addWidget(preview_btn)
        right_layout.addLayout(actions)

        splitter.addWidget(right)
        splitter.setSizes([340, 820])
        return splitter

    def _build_timeline_tab(self) -> QWidget:
        """记录页：什么时候触发了什么，带统计。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 顶部统计卡片
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.stat_penalties = _stat_card("惩罚次数", "0", theme.COLORS["accent"])
        self.stat_records = _stat_card("日志条数", "0", theme.COLORS["muted"])
        self.stat_last = _stat_card("最近一次惩罚", "-", theme.COLORS["bad"])
        self.stat_top = _stat_card("触发最多的规则", "-", "#7c3aed")
        for card in (self.stat_penalties, self.stat_records,
                     self.stat_last, self.stat_top):
            cards.addWidget(card)
        layout.addLayout(cards)

        # 过滤条
        filters = QHBoxLayout()
        filters.addWidget(QLabel("时间范围"))
        self.range_box = QComboBox()
        for label, seconds in (("最近 5 分钟", 300), ("最近 30 分钟", 1800),
                               ("最近 1 小时", 3600), ("本次运行", None)):
            self.range_box.addItem(label, seconds)
        self.range_box.setCurrentIndex(3)
        self.range_box.currentIndexChanged.connect(self._refresh_timeline)
        filters.addWidget(self.range_box)

        filters.addWidget(QLabel("类型"))
        self.kind_box = QComboBox()
        self.kind_box.addItem("全部", None)
        self.kind_box.addItem("仅惩罚", "penalty")
        self.kind_box.addItem("未送达", "blocked")
        self.kind_box.addItem("规则变更", "rule")
        self.kind_box.addItem("系统", "system")
        self.kind_box.currentIndexChanged.connect(self._refresh_timeline)
        filters.addWidget(self.kind_box)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_timeline)
        filters.addWidget(refresh_btn)
        filters.addStretch(1)
        open_btn = QPushButton("打开日志目录")
        open_btn.clicked.connect(self._open_log_dir)
        filters.addWidget(open_btn)
        layout.addLayout(filters)

        # 时间线表格
        self.timeline = QTableWidget(0, 6)
        self.timeline.setHorizontalHeaderLabels(
            ["时间", "规则", "触发原因", "强度", "时长", "通道"])
        self.timeline.setAlternatingRowColors(True)
        self.timeline.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.timeline.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.timeline.verticalHeader().setVisible(False)
        header = self.timeline.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        for column in (3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.timeline, 1)

        hint = QLabel("每次惩罚都会写入 logs/日期.jsonl，重启后仍可用「最近 1 小时 / 本次运行」查看。")
        hint.setStyleSheet(f"color:{theme.COLORS['muted']};")
        layout.addWidget(hint)
        return widget

    def _build_guide_tab(self) -> QWidget:
        tabs = QTabWidget()
        for title, html in (("规则写法", GUIDE_RULES),
                            ("波形与协议", GUIDE_WAVE),
                            ("配置步骤", GUIDE_SETUP)):
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setHtml(html)
            tabs.addTab(browser, title)
        return tabs

    def _build_log_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("显示"))
        self.log_filter = QComboBox()
        self.log_filter.addItem("全部", "all")
        self.log_filter.addItem("警告与错误", "warn")
        self.log_filter.addItem("仅惩罚", "penalty")
        self.log_filter.currentIndexChanged.connect(self._replay_log)
        bar.addWidget(self.log_filter)
        bar.addStretch(1)

        self._raw_log: list = []  # 用于切换过滤时重放

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(6000)
        self.log_view.setFont(QFont(MONO, 9))

        clear_btn = QPushButton("清空显示")
        clear_btn.clicked.connect(self.log_view.clear)
        bar.addWidget(clear_btn)
        save_btn = QPushButton("导出日志…")
        save_btn.clicked.connect(self._export_log)
        bar.addWidget(save_btn)
        layout.addLayout(bar)
        layout.addWidget(self.log_view, 1)
        return widget

    # ---------------- 日志 ----------------
    def _log(self, level: str, message: str, persist: bool = False) -> None:
        """写界面的纯文本日志。

        persist=True 时同时落盘（用于规则加载、导出等非引擎事件）；
        引擎的惩罚日志已由 Engine 自己写入 event_log，传 False 避免重复。
        """
        self.log_line.emit(level, message)
        if persist:
            self.event_log.add("system" if level == "info" else level,
                               message, level=level)

    def _append_log(self, level: str, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._raw_log.append((level, message, stamp))
        if len(self._raw_log) > 6000:
            del self._raw_log[:1000]
        if not self._passes_filter(level, message):
            return
        self._write_one(level, message, stamp)
        if level in ("error", "warn"):
            self.statusBar().showMessage(message, 8000)

    def _passes_filter(self, level: str, message: str) -> bool:
        mode = self.log_filter.currentData() if hasattr(self, "log_filter") else "all"
        if mode == "warn":
            return level in ("warn", "error")
        if mode == "penalty":
            return "惩罚" in message or level == "penalty"
        return True

    def _write_one(self, level: str, message: str, stamp: str) -> None:
        color = theme.level_color(level)
        self.log_view.appendHtml(
            f'<span style="color:#9aa3af">[{stamp}]</span> '
            f'<span style="color:{color}">{_escape(message)}</span>'
        )

    def _replay_log(self) -> None:
        self.log_view.clear()
        for level, message, stamp in self._raw_log[-3000:]:
            if self._passes_filter(level, message):
                self._write_one(level, message, stamp)

    def _export_log(self) -> None:
        default = config.LOGS_DIR / time.strftime("rate_warden-%Y%m%d.log")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", str(default), "日志 (*.log *.txt)")
        if not path:
            return
        lines = [f"[{stamp}] {message}" for _lvl, message, stamp in self._raw_log]
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.statusBar().showMessage(f"已导出 {len(lines)} 条到 {path}", 6000)
        self.event_log.add("system", f"日志已导出到 {path}")

    # ---------------- 记录页 ----------------
    def _on_record(self, record: LogRecord) -> None:
        """日志记录到达（可能来自 UDP 线程，经信号转到 GUI 线程）。

        只负责刷新统计与时间线；纯文本日志由引擎自己的 on_log 输出，
        这里不再重复打印，避免同一条惩罚出现两遍。
        """
        self._refresh_stats()
        if record.kind in ("penalty", "blocked"):
            self._refresh_timeline()

    def _refresh_stats(self) -> None:
        stats = self.event_log.stats()
        self.stat_penalties.value.setText(str(stats["penalties"]))
        self.stat_records.value.setText(str(stats["total_records"]))
        self.stat_last.value.setText(
            stats["last_penalty"].split(" ")[-1] if stats["last_penalty"] != "-" else "-")
        top = stats["by_rule"][0] if stats["by_rule"] else None
        self.stat_top.value.setText(
            f"{top['rule_name']} ({top['count']})" if top else "-")
        self.penalty_count.setText(f"已罚 {stats['penalties']} 次")

    def _refresh_timeline(self) -> None:
        if not hasattr(self, "timeline"):
            return
        seconds = self.range_box.currentData()
        kind = self.kind_box.currentData()
        if seconds:
            records = [r for r in self.event_log.since(seconds)]
            records.reverse()
        else:
            records = self.event_log.timeline(limit=500)
        if kind:
            records = [r for r in records if r.kind == kind]

        self.timeline.setRowCount(0)
        for record in records:
            row = self.timeline.rowCount()
            self.timeline.insertRow(row)
            values = [
                record.clock if _fresh(record.ts) else record.when,
                record.rule_name or record.rule_id or "-",
                record.reason or record.message,
                f"{record.strength}%" if record.strength else "-",
                f"{record.duration:g}s" if record.duration else "-",
                record.channel or "-",
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if record.kind == "penalty":
                    item.setForeground(QColor(theme.COLORS["accent_dark"]))
                else:
                    item.setForeground(QColor(theme.COLORS["muted"]))
                if column == 2:
                    item.setToolTip(record.message)
                self.timeline.setItem(row, column, item)
        self._refresh_stats()

    def _open_log_dir(self) -> None:
        try:
            os.startfile(str(config.LOGS_DIR))  # type: ignore[attr-defined]
        except OSError as exc:
            self._log("error", f"打开日志目录失败: {exc}")

    # ---------------- N1MM 监听 ----------------
    def start_listener(self) -> None:
        self.stop_listener()
        port = int(self.cfg.get("udp_port", 12060))
        bind = str(self.cfg.get("udp_bind", "0.0.0.0"))
        listener = Listener(
            port=port, bind=bind,
            on_event=self._on_n1mm_event,
            on_error=lambda message: self._log("error", message),
        )
        try:
            listener.start()
        except OSError:
            self._log("error", f"UDP {port} 监听失败，请检查端口占用或改用其它端口")
            return
        self.listener = listener
        self.event_log.add("system", f"开始监听 UDP {bind}:{port}")

    def stop_listener(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            self.listener = None

    def _on_n1mm_event(self, kind: str, contact, radio) -> None:
        """运行在监听线程：只把事件投递给引擎，引擎内部无阻塞调用。"""
        if not self.master.isChecked():
            return
        if kind == "radioinfo":
            self.engine.dispatch_radio(radio)
        elif kind == "lookupinfo":
            self.engine.dispatch_lookup(contact)
        elif kind in ("contactinfo", "contactreplace"):
            self.engine.dispatch_contact(contact)
        elif kind == "contactdelete":
            self.engine.dispatch_contact(contact, deleted=True)

    def _change_port(self) -> None:
        port, ok = QInputDialog.getInt(
            self, "监听设置", "UDP 端口:", int(self.cfg.get("udp_port", 12060)),
            1, 65535, 1)
        if not ok:
            return
        self.cfg["udp_port"] = int(port)
        config.save(self.cfg)
        self.start_listener()

    # ---------------- 心跳 ----------------
    def _on_heartbeat(self) -> None:
        if self.master.isChecked():
            try:
                self.engine.tick()
            except Exception as exc:
                self._log("error", f"心跳处理异常: {exc}")
        idle = time.monotonic() - self.engine.last_qso_time
        self.lamp_idle.setText(f"空闲: {idle:,.0f}s")

    def _refresh_status_lights(self) -> None:
        if self.listener is not None and self.listener.running:
            since = self.listener.seconds_since_packet()
            if since is None:
                self.lamp_n1mm.setText("● N1MM 等待首个包")
                self.lamp_n1mm.setStyleSheet("color:#b7791f;")
            elif since < 30:
                self.lamp_n1mm.setText(f"● N1MM 正常 ({since:.1f}s 前)")
                self.lamp_n1mm.setStyleSheet("color:#2f855a;")
            else:
                self.lamp_n1mm.setText(f"● N1MM 静默 {since:.0f}s")
                self.lamp_n1mm.setStyleSheet("color:#b7791f;")
        else:
            self.lamp_n1mm.setText("● N1MM 未监听")
            self.lamp_n1mm.setStyleSheet("color:#c53030;")

        text, ready = self.sink.status()
        self.lamp_sink.setText(f"● {text}")
        self.lamp_sink.setStyleSheet("color:#2f855a;" if ready else "color:#b7791f;")

        mode = self.engine.radio.get("mode") or "-"
        run_text = ("RUN" if self.engine.is_running else "S&P") if self.engine.radio else "-"
        self.lamp_mode.setText(f"模式: {mode} · {run_text}")

    def _on_master(self, _state: int) -> None:
        # 总开关只对本次运行有效，不写回 config.json。
        # 否则一次误关会让下次启动静默失效，排障成本极高。
        enabled = self.master.isChecked()
        self._log("info", "惩罚总开关: " + ("开" if enabled else "关"))
        self.event_log.add("system", "惩罚总开关: " + ("开" if enabled else "关"))

    def _emergency_stop(self) -> None:
        self._log("warn", "急停被按下")
        ok = self.sink.emergency_stop()
        if not ok:
            self._log("warn", "急停未送达（未连接 DGHub），本机不做任何输出")

    # ---------------- 规则 ----------------
    def _load_rules(self) -> None:
        found, errors = loader.discover()
        for message in errors:
            self._log("error", f"规则加载失败 {message}")

        self.rules = []
        self.rule_index = {}
        enabled_map = self.cfg.get("run_rules", {}) or {}

        for entry in found:
            rule_id = entry["id"]
            saved = enabled_map.get(rule_id, {}) if isinstance(enabled_map, dict) else {}
            try:
                rule = entry["class"](saved.get("params") or {})
            except Exception as exc:
                self._log("error", f"规则 {rule_id} 实例化失败: {exc}")
                continue
            enabled = bool(saved.get("enabled", True))
            self.rules.append(rule)
            self.rule_index[rule_id] = {"rule": rule, "entry": entry, "enabled": enabled}

        self.engine.set_rules([r for r in self.rules])
        self._refresh_rule_tree()
        self._log("info", f"已加载 {len(self.rules)} 条规则"
                          + (f"，{len(errors)} 条失败" if errors else ""))
        self.event_log.add(
            "rule", f"加载规则 {len(self.rules)} 条"
                    + (f"，{len(errors)} 条失败" if errors else ""))
        # 默认选中第一条，避免右侧空白
        if self.rule_tree.topLevelItemCount() and not self.rule_tree.selectedItems():
            self.rule_tree.setCurrentItem(self.rule_tree.topLevelItem(0))

    def _enabled_rules(self) -> list:
        return [meta["rule"] for meta in self.rule_index.values() if meta["enabled"]]

    def _refresh_rule_tree(self) -> None:
        self.rule_tree.blockSignals(True)
        self.rule_tree.clear()
        for rule_id, meta in self.rule_index.items():
            rule = meta["rule"]
            item = QTreeWidgetItem([
                "", rule.name or rule_id, rule_id
            ])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if meta["enabled"] else Qt.Unchecked)
            item.setToolTip(1, rule.description)
            item.setToolTip(2, f"文件: {meta['entry']['path'].name}"
                               f"{'（内置）' if meta['entry']['builtin'] else '（用户）'}")
            item.setData(0, Qt.UserRole, rule_id)
            self.rule_tree.addTopLevelItem(item)
        self.rule_tree.blockSignals(False)
        self._apply_enabled()

    def _apply_enabled(self) -> None:
        self.engine.set_rules(self._enabled_rules())

    def _on_rule_checked(self, item: QTreeWidgetItem, _column: int) -> None:
        rule_id = item.data(0, Qt.UserRole)
        meta = self.rule_index.get(rule_id)
        if meta is None:
            return
        meta["enabled"] = item.checkState(0) == Qt.Checked
        self._persist_rule(rule_id)
        self._apply_enabled()
        state = "启用" if meta["enabled"] else "停用"
        self._log("info", f"规则 {rule_id} 已{state}")

    def _on_rule_selected(self) -> None:
        items = self.rule_tree.selectedItems()
        if not items:
            return
        rule_id = items[0].data(0, Qt.UserRole)
        meta = self.rule_index.get(rule_id)
        if meta is None:
            return
        self.rule_form.wave_labels = self.wave_lib.labels()
        self.rule_form.load_rule(meta["rule"])

    def _save_params(self) -> None:
        rule = self.rule_form.rule
        if rule is None:
            return
        values = self.rule_form.collect()
        rejected = rule.set_params(values)
        if rejected:
            self._log("warn", f"忽略非法参数: {', '.join(rejected)}")
        self._persist_rule(rule.id)
        self._apply_enabled()
        self._log("info", f"规则 {rule.id} 参数已保存")
        self.statusBar().showMessage("参数已保存", 4000)

    def _reset_params(self) -> None:
        rule = self.rule_form.rule
        if rule is None:
            return
        rule.params = rule.default_params()
        self.rule_form.load_rule(rule)
        self._persist_rule(rule.id)
        self._log("info", f"规则 {rule.id} 参数已恢复默认")

    def _persist_rule(self, rule_id: str) -> None:
        meta = self.rule_index.get(rule_id)
        if meta is None:
            return
        self.cfg.setdefault("run_rules", {})[rule_id] = {
            "enabled": meta["enabled"],
            "params": dict(meta["rule"].params),
        }
        config.save(self.cfg)

    def _import_rule(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入规则（仅导入可信的 .py 文件）", str(config.ROOT),
            "Python 规则 (*.py)")
        if not path:
            return
        ok, message, target = loader.import_file(path)
        if not ok:
            self._log("error", f"导入失败: {message}")
            QMessageBox.warning(self, "导入失败", message)
            return
        self._log("info", f"{message} -> {target.name}")
        self._reload_rules()

    def _new_rule(self) -> None:
        stem, ok = QInputDialog.getText(self, "新建规则", "文件名（英文）:")
        if not ok or not stem.strip():
            return
        try:
            path = loader.write_new_rule(stem.strip())
        except loader.RuleLoadError as exc:
            QMessageBox.warning(self, "新建失败", str(exc))
            return
        self._log("info", f"已创建模板: {path.name}")
        self._reload_rules()
        self._edit_rule_source(rule_id=path.stem)

    def _edit_rule_source(self, rule_id: Optional[str] = None) -> None:
        target = None
        if rule_id and rule_id in self.rule_index:
            target = self.rule_index[rule_id]["entry"]["path"]
        elif not rule_id:
            items = self.rule_tree.selectedItems()
            if items:
                rid = items[0].data(0, Qt.UserRole)
                if rid in self.rule_index:
                    target = self.rule_index[rid]["entry"]["path"]
        if target is None:
            return
        if self.rule_index and any(
            meta["entry"]["path"] == target and meta["entry"]["builtin"]
            for meta in self.rule_index.values()
        ):
            self._log("warn", "内置规则建议复制到 rules_user/ 后再改，已用编辑器打开只读副本")
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            self._log("error", f"打开编辑器失败: {exc}")

    def _reload_rules(self) -> None:
        selected = None
        items = self.rule_tree.selectedItems()
        if items:
            selected = items[0].data(0, Qt.UserRole)
        self._load_rules()
        if selected and selected in self.rule_index:
            for index in range(self.rule_tree.topLevelItemCount()):
                item = self.rule_tree.topLevelItem(index)
                if item.data(0, Qt.UserRole) == selected:
                    self.rule_tree.setCurrentItem(item)
                    break

    # ---------------- 波形 ----------------
    def _seed_waves(self) -> None:
        if not self.wave_lib.waves:
            self.wave_lib.add_many(waveforms.DEFAULT_SEED, source="seed")
        self._refresh_wave_list()

    def _refresh_wave_list(self) -> None:
        current = None
        if self.wave_list.currentItem() is not None:
            current = self.wave_list.currentItem().data(Qt.UserRole)
        self.wave_list.clear()
        for wave in self.wave_lib.waves:
            item = QListWidgetItem(wave.label)
            item.setData(Qt.UserRole, wave.name)
            item.setToolTip(wave.note or wave.name)
            self.wave_list.addItem(item)
        if current:
            for row in range(self.wave_list.count()):
                item = self.wave_list.item(row)
                if item.data(Qt.UserRole) == current:
                    self.wave_list.setCurrentItem(item)
                    break
        self.rule_form.wave_labels = self.wave_lib.labels()

    def _on_wave_selected(self, current, _previous) -> None:
        if current is None:
            return
        wave = self.wave_lib.find(current.data(Qt.UserRole))
        if wave is None:
            return
        self.wave_name.setText(wave.name)
        self.wave_alias.setText(wave.alias)
        self.wave_note.setText(wave.note)
        self.wave_source.setText(wave.source)
        points, caption = shape_for(wave.name)
        self.wave_preview.set_shape(points, f"{wave.name} · {caption}")

    def _save_wave_meta(self) -> None:
        name = self.wave_name.text().strip()
        if not name:
            return
        ok, message = self.wave_lib.update(name, self.wave_alias.text(),
                                           self.wave_note.text())
        self._log("info" if ok else "error", message)
        self._refresh_wave_list()

    def _import_wave_paste(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("粘贴预设名")
        dialog.resize(560, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "一行一个预设名。支持 <code>预设名 | 别名 | 备注</code>。"
            "名字必须与 DGHub 中显示的完全一致。"))
        text = QPlainTextEdit()
        text.setFont(QFont(MONO, 10))
        text.setPlaceholderText("CS2-受伤 | 短促刺痛 | 高频提醒\nCS2-死亡 | 重击")
        layout.addWidget(text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        result = self.wave_lib.add_many(text.toPlainText(), source="paste")
        self._report_import(result)
        self._refresh_wave_list()

    def _import_wave_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入波形清单", str(config.ROOT),
            "清单文件 (*.txt *.json);;所有文件 (*)")
        if not path:
            return
        result = self.wave_lib.import_file(path)
        self._report_import(result)
        self._refresh_wave_list()

    def _report_import(self, result: dict) -> None:
        message = (f"新增 {result.get('added', 0)} 条，"
                   f"跳过 {result.get('skipped', 0)} 条")
        errors = result.get("errors") or []
        if errors:
            message += f"，{len(errors)} 条失败"
            self._log("warn", "；".join(errors[:5]))
        self._log("info", message)
        self.statusBar().showMessage(message, 5000)

    def _delete_wave(self) -> None:
        item = self.wave_list.currentItem()
        if item is None:
            return
        name = item.data(Qt.UserRole)
        if QMessageBox.question(self, "删除波形",
                                f"从波形库移除 {name}？") != QMessageBox.Yes:
            return
        ok, message = self.wave_lib.remove(name)
        self._log("info" if ok else "error", message)
        self._refresh_wave_list()
        self.wave_preview.set_shape([], "")

    def _reload_waves(self) -> None:
        self.wave_lib.load()
        self._seed_waves()
        self._log("info", f"波形库已刷新，共 {len(self.wave_lib.waves)} 条")

    def _preview_wave(self) -> None:
        name = self.wave_name.text().strip()
        if not name:
            return
        event = PenaltyEvent(
            rule_id="preview",
            strength_pct=5,
            duration_s=0.8,
            preset=name,
            channel="both",
            action="both",
            reason=f"预览 {name}",
        )
        ok = self.sink.fire(event)
        if ok:
            self._log("info", f"预览已发送: {name}（强度 5%，0.8s）")
        else:
            self._log("warn", "预览未送达：DGHub 未连接")

    # ---------------- 演示 ----------------
    def _inject_demo_qso(self) -> None:
        from .rule_base import Contact
        stamp = int(time.time())
        demo = Contact(
            call=f"K{stamp % 1000}ABC",
            band="20m",
            mode="SSB",
            sntnr="001",
            rcvnr="59",
            is_original=True,
            is_run_qso=True,
        )
        self.engine.dispatch_radio({"is_running": True, "mode": "SSB", "freq": "14.030"})
        self.engine.dispatch_lookup(demo)
        self.engine.dispatch_contact(demo)
        self._log("info", f"已注入模拟 QSO: {demo.call}")

    # ---------------- 关闭 ----------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self.heartbeat.stop()
        self._status_poll.stop()
        self.stop_listener()
        try:
            self.sink.emergency_stop()
        except Exception:
            pass
        try:
            self.sink.close()
        except Exception:
            pass
        event.accept()


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fresh(ts: float) -> bool:
    """今天的时间只显示时分秒，跨天才显示完整日期。"""
    return time.strftime("%Y-%m-%d", time.localtime(ts)) == time.strftime("%Y-%m-%d")


def run(cfg: dict, demo: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

    logs: list = []

    def log(message: str) -> None:
        logs.append(message)
        print(message)

    sink: Sink
    if demo:
        sink = NullSink(on_log=log)
    else:
        candidate = DghubSink(on_log=log)
        if candidate.connect():
            sink = candidate
        else:
            print("[warn] DGHub 未连接，惩罚只记录（NullSink 模式）")
            sink = NullSink(on_log=log)

    window = MainWindow(cfg, sink=sink, demo=demo)
    window.show()
    return app.exec()
