"""动态加载规则文件。

约束（导入时会静态校验）：
1. 必须是能被 ast 解析的 Python 文件；
2. 必须定义至少一个 Rule 子类，且有非空 id；
3. 不允许 import 其它 rate_warden.rules.* 模块（避免规则间耦合，保证可热重载）。
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import shutil
import sys
import traceback
from pathlib import Path
from typing import Optional

from .config import RULES_BUILTIN_DIR, RULES_USER_DIR, ensure_dirs
from .rule_base import EVENTS, Rule


class RuleLoadError(Exception):
    pass


def _iter_rule_files(dirs) -> list:
    files = []
    for directory in dirs:
        if not directory.exists():
            continue
        files.extend(sorted(p for p in directory.glob("*.py") if not p.name.startswith("_")))
    return files


def _module_name(path: Path) -> str:
    return f"_rate_warden_rule_{path.stem}"


def load_module(path: Path):
    name = _module_name(path)
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuleLoadError(f"无法为 {path.name} 创建模块 spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def find_rule_classes(module) -> list:
    found = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj is Rule or not issubclass(obj, Rule):
            continue
        if not getattr(obj, "id", ""):
            continue
        found.append(obj)
    return found


def inspect_file(path: Path) -> dict:
    """对规则文件做静态检查，返回 {ok, error, rules:[{id,name}]}。不执行任何用户代码。"""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"读取失败: {exc}", "rules": []}

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return {"ok": False, "error": f"语法错误 第{exc.lineno}行: {exc.msg}", "rules": []}

    # 规则之间禁止互相 import
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("rate_warden.rules"):
                    return {"ok": False,
                            "error": f"第{node.lineno}行: 规则文件之间禁止互相 import",
                            "rules": []}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("rate_warden.rules") or module in ("rules", ".rules"):
                return {"ok": False,
                        "error": f"第{node.lineno}行: 规则文件之间禁止互相 import",
                        "rules": []}

    try:
        module = load_module(path)
    except Exception:
        detail = traceback.format_exc(limit=3).strip().splitlines()[-1]
        return {"ok": False, "error": f"导入失败: {detail}", "rules": []}

    classes = find_rule_classes(module)
    if not classes:
        return {"ok": False, "error": "文件中没有找到带 id 的 Rule 子类", "rules": []}

    bad_events = [c.id for c in classes if any(e not in EVENTS for e in c.events)]
    if bad_events:
        return {"ok": False,
                "error": f"events 含有不支持的值（可选 {EVENTS}）: {bad_events}",
                "rules": []}

    return {
        "ok": True,
        "error": "",
        "rules": [{"id": c.id, "name": c.name or c.id, "class": c} for c in classes],
    }


def discover() -> tuple[list, list]:
    """扫描内置与用户目录，返回 (找到的 [{id,name,class,path,builtin}], 错误列表)。"""
    ensure_dirs()
    found, errors = [], []
    seen = {}
    for directory, builtin in ((RULES_BUILTIN_DIR, True), (RULES_USER_DIR, False)):
        for path in _iter_rule_files([directory]):
            info = inspect_file(path)
            if not info["ok"]:
                errors.append(f"{path.name}: {info['error']}")
                continue
            for entry in info["rules"]:
                rule_id = entry["id"]
                if rule_id in seen:
                    errors.append(
                        f"{path.name}: 规则 id '{rule_id}' 与 {seen[rule_id]} 重复，已跳过"
                    )
                    continue
                seen[rule_id] = path.name
                found.append({**entry, "path": path, "builtin": builtin})
    return found, errors


def import_file(src: str) -> tuple[bool, str, Optional[Path]]:
    """GUI 的『导入规则』。复制到 rules_user/ 并返回结果。"""
    ensure_dirs()
    source = Path(src)
    if not source.is_file() or source.suffix.lower() != ".py":
        return False, "请选择一个 .py 规则文件", None

    info = inspect_file(source)
    if not info["ok"]:
        return False, info["error"], None

    target = RULES_USER_DIR / source.name
    if target.exists() and target.resolve() != source.resolve():
        return False, f"rules_user/ 下已存在同名文件: {source.name}", None
    if not target.exists():
        shutil.copy2(source, target)
    names = ", ".join(r["name"] for r in info["rules"])
    return True, f"已导入: {names}", target


RULE_TEMPLATE = '''"""自定义规则模板 —— 复制后修改即可。

可用事件：
  on_tick(ctx)     每个心跳（默认 4Hz）
  on_contact(ctx)  一条 QSO 落库时
  on_lookup(ctx)   操作员按下 Tab/空格、准备呼叫时
  on_radio(ctx)    N1MM 广播运行状态变化时

返回 PenaltyEvent 表示惩罚，返回 None 表示放过。
"""

from rate_warden.rule_base import Rule, Param, PenaltyEvent, Context, common_penalty_params


class MyRule(Rule):
    id = "my_rule"              # 全局唯一，配置按此 id 存储
    name = "我的规则"
    description = "说明这条规则在什么情况下触发。"
    events = ("contact",)       # 只订阅需要的事件
    axis = "mistake"            # "mistake" 参与连续失误递进；"rate" 不参与
    params_schema = [
        Param("threshold", "阈值", "int", 1, 1, 10, help="示例参数"),
        *common_penalty_params(default_strength=40, default_duration=1.0),
    ]

    def on_contact(self, ctx: Context):
        c = ctx.contact
        if c is None:
            return None
        if not c.call.startswith("K"):
            return None
        return self.event(ctx, reason=f"呼号以 K 开头: {c.call}")
'''


def write_new_rule(stem: str) -> Path:
    """在 rules_user/ 下写一个模板规则文件，供 GUI 的『新建规则』使用。"""
    ensure_dirs()
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in "-_") or "my_rule"
    path = RULES_USER_DIR / f"{safe}.py"
    if path.exists():
        raise RuleLoadError(f"已存在: {path.name}")
    content = RULE_TEMPLATE.replace('id = "my_rule"', f'id = "{safe}"')
    content = content.replace('name = "我的规则"', f'name = "{safe}"')
    path.write_text(content, encoding="utf-8")
    return path
