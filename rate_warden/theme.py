"""Rate Warden 视觉主题（QSS）。

配色：深色顶栏 + 浅色工作区，强调色蓝 #2563eb，危险色红 #dc2626。
所有样式集中在这里，方便统一调整。
"""

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"

COLORS = {
    "bg": "#f5f6f8",
    "panel": "#ffffff",
    "border": "#dfe3e8",
    "text": "#1f2933",
    "muted": "#6b7280",
    "accent": "#2563eb",
    "accent_dark": "#1d4ed8",
    "ok": "#059669",
    "warn": "#d97706",
    "bad": "#dc2626",
    "header": "#1e293b",
}

APP_QSS = f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: 13px;
}}
QWidget {{
    background: {COLORS['bg']};
    color: {COLORS['text']};
}}

QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
    background: {COLORS['panel']};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {COLORS['muted']};
    padding: 9px 20px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {COLORS['accent']};
    background: #eef2ff;
}}
QTabBar::tab:selected {{
    background: {COLORS['panel']};
    color: {COLORS['accent']};
    border: 1px solid {COLORS['border']};
    border-bottom-color: {COLORS['panel']};
}}

QGroupBox {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: {COLORS['muted']};
}}

QPushButton {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 7px 16px;
    color: {COLORS['text']};
}}
QPushButton:hover {{
    background: #eef2ff;
    border-color: #c7d2fe;
    color: {COLORS['accent_dark']};
}}
QPushButton:pressed {{
    background: #dbe4ff;
}}
QPushButton:disabled {{
    color: #b6bcc6;
    background: #f2f3f5;
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {COLORS['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {COLORS['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #b8c0cc;
    background: {COLORS['panel']};
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border: 1px solid {COLORS['accent_dark']};
    image: none;
}}
QCheckBox::indicator:hover {{
    border: 1px solid {COLORS['accent']};
}}

/* 深色顶栏上的复选框：浅色描边 + 白色选中块 */
QFrame#topbar QCheckBox {{
    color: #e2e8f0;
    background: transparent;
}}
QFrame#topbar QCheckBox::indicator {{
    border: 1px solid #94a3b8;
    background: #334155;
}}
QFrame#topbar QCheckBox::indicator:checked {{
    background: #22c55e;
    border: 1px solid #16a34a;
}}

QTreeWidget::indicator, QListWidget::indicator {{
    width: 16px;
    height: 16px;
}}

QTreeWidget, QListWidget, QTableWidget {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 9px;
    alternate-background-color: #fafbfc;
    selection-background-color: #e3ecff;
    selection-color: {COLORS['text']};
    outline: none;
}}
QTreeWidget::item, QListWidget::item {{
    height: 30px;
    padding: 2px 4px;
}}
QTreeWidget::item:hover, QListWidget::item:hover {{
    background: #f0f4ff;
}}
QHeaderView::section {{
    background: #f7f8fa;
    color: {COLORS['muted']};
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    padding: 8px 8px;
    font-weight: 600;
}}

QPlainTextEdit, QTextBrowser {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 9px;
    padding: 6px;
}}

QSplitter::handle {{
    background: transparent;
    width: 8px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #c9ced6;
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #aeb5bf;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #c9ced6;
    border-radius: 5px;
    min-width: 30px;
}}

QStatusBar {{
    background: {COLORS['panel']};
    border-top: 1px solid {COLORS['border']};
    color: {COLORS['muted']};
}}
QToolTip {{
    background: #1e293b;
    color: #f8fafc;
    border: none;
    border-radius: 6px;
    padding: 6px 9px;
}}
"""

TOPBAR_QSS = f"""
QFrame#topbar {{
    background: {COLORS['header']};
    border-radius: 12px;
}}
QFrame#topbar QLabel {{
    color: #cbd5e1;
    background: transparent;
}}
QLabel#brand {{
    color: #ffffff;
    font-size: 17px;
    font-weight: 700;
}}
QLabel#brandSub {{
    color: #94a3b8;
    font-size: 11px;
}}
QFrame#pill {{
    background: #334155;
    border-radius: 11px;
}}
"""

STOP_QSS = f"""
QPushButton#stop {{
    background: {COLORS['bad']};
    color: #ffffff;
    border: none;
    border-radius: 10px;
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 2px;
}}
QPushButton#stop:hover {{
    background: #ef4444;
}}
QPushButton#stop:pressed {{
    background: #b91c1c;
}}
"""

PRIMARY_QSS = f"""
QPushButton#primary {{
    background: {COLORS['accent']};
    color: #ffffff;
    border: 1px solid {COLORS['accent_dark']};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {COLORS['accent_dark']};
}}
"""


def lamp_style(color: str, filled: bool = True) -> str:
    """状态灯：● 文字染色，配合深色顶栏。"""
    return f"color: {color}; font-weight: 600; background: transparent;"


def level_color(level: str) -> str:
    return {
        "info": "#334155",
        "warn": "#b45309",
        "error": "#b91c1c",
    }.get(level, "#334155")


def kind_color(kind: str) -> str:
    return {
        "penalty": "#1d4ed8",
        "blocked": "#b45309",
        "merged": "#6b7280",
        "rule": "#0f766e",
        "system": "#6b7280",
        "wave": "#7c3aed",
    }.get(kind, "#334155")
