"""配置读写：config.json 位于项目根目录。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
WAVES_DIR = ROOT / "waves"
RULES_USER_DIR = ROOT / "rules_user"
RULES_BUILTIN_DIR = Path(__file__).resolve().parent / "rules"
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
