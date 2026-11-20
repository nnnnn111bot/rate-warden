"""配置读写：config.json 位于项目根目录。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 打包成 exe（PyInstaller）后的路径布局：
#   - 可写目录（config / waves / rules_user / logs）落在 exe 同级目录
#   - 内置规则是 *.py 资源（loader 用文件路径扫描 + 静态检查），PyInstaller 默认
#     会把它们编进 PYZ 归档、磁盘上没有 .py 文件，因此必须用 --add-data 原样打包，
#     再通过 sys._MEIPASS（onedir 下 = _internal/）定位。
_FROZEN = bool(getattr(sys, "frozen", False))

if _FROZEN:
    ROOT = Path(sys.executable).resolve().parent
    _BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))
    RULES_BUILTIN_DIR = _BUNDLE / "rate_warden" / "rules"
    # 规则文件是运行期从磁盘动态加载的用户代码，可能 import 任何标准库；
    # PyInstaller 按静态分析打包，看不到这条隐式依赖，运行期会
    # ModuleNotFoundError。把纯 Python 标准库（python3XX.zip、
    # *_stdlib.zip 由构建时复制进 _internal）挂到 sys.path 末尾。
    for _name in sorted(_BUNDLE.glob("*.zip")):
        _p = str(_name)
        if _p not in sys.path:
            sys.path.append(_p)
else:
    ROOT = Path(__file__).resolve().parent.parent
    RULES_BUILTIN_DIR = Path(__file__).resolve().parent / "rules"

CONFIG_PATH = ROOT / "config.json"
WAVES_DIR = ROOT / "waves"
RULES_USER_DIR = ROOT / "rules_user"
LOGS_DIR = ROOT / "logs"

DEFAULTS = {
    "udp_port": 12060,
    "udp_bind": "0.0.0.0",
    "strength_cap": 70,
    "heartbeat_hz": 4,
    "default_channel": "both",
    "plugin_id": "rate_warden",
    "plugin_name": "Rate Warden",
    "master_enabled": True,
    "run_rules": {},  # {rule_id: {"enabled": bool, "params": {...}}}
}


def ensure_dirs() -> None:
    for path in (WAVES_DIR, RULES_USER_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    """读取配置；损坏或缺失时回落到默认值，并保证所有键存在。"""
    ensure_dirs()
    data = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS or k == "run_rules"})
    if not isinstance(merged.get("run_rules"), dict):
        merged["run_rules"] = {}
    return merged


def save(cfg: dict) -> None:
    ensure_dirs()
    payload = {k: cfg.get(k, DEFAULTS.get(k)) for k in DEFAULTS}
    payload["run_rules"] = cfg.get("run_rules", {})
    CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
