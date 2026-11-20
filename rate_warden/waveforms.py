"""波形库。

重要协议事实：DGHub 的 trigger/pulse 只接受**预设名**（preset 字符串），
不支持下发任意 HEX 帧数据。所以这里的"波形库"管理的是
"预设名 + 用途别名 + 备注"，供 GUI 导入、选择和规则引用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from .config import WAVES_DIR, ensure_dirs

_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff \-_.+]{0,63}$")


@dataclass
class Wave:
    name: str                      # DGHub 里的预设名，必须逐字一致
    alias: str = ""                # 本地的用途别名
    note: str = ""
    source: str = "manual"
    tags: list = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.alias} ({self.name})" if self.alias else self.name


class WaveLibrary:
    def __init__(self, directory: Optional[Path] = None) -> None:
        self.dir = directory or WAVES_DIR
        ensure_dirs()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.waves: list = []
        self.errors: list = []

    # ---- 读写 ----
    def load(self) -> None:
        self.waves = []
        self.errors = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                self.errors.append(f"{path.name}: {exc}")
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if not name:
                    self.errors.append(f"{path.name}: 缺少 name 字段")
                    continue
                self.waves.append(Wave(
                    name=name,
                    alias=str(item.get("alias", "") or ""),
                    note=str(item.get("note", "") or ""),
                    source=str(item.get("source", path.stem)),
                    tags=list(item.get("tags") or []),
                ))

    def names(self) -> list:
        return [w.name for w in self.waves]

    def labels(self) -> list:
        return [w.label for w in self.waves]

    def find(self, token: str) -> Optional[Wave]:
        if not token:
            return None
        for wave in self.waves:
            if wave.name == token:
                return wave
        for wave in self.waves:
            if wave.alias and wave.alias == token:
                return wave
        for wave in self.waves:
            if wave.label == token:
                return wave
        return None

    # ---- 修改 ----
    def add(self, name: str, alias: str = "", note: str = "",
            source: str = "manual") -> tuple[bool, str]:
        name = (name or "").strip()
        if not name:
            return False, "预设名不能为空"
        if not _NAME_RE.match(name):
            return False, "预设名含非法字符或过长"
        if self.find(name) is not None:
            return False, f"波形已存在: {name}"
        self.waves.append(Wave(name=name, alias=alias.strip(), note=note.strip(),
                               source=source))
        self._persist()
        return True, f"已添加: {name}"

    def add_many(self, text: str, alias_prefix: str = "", source: str = "paste") -> dict:
        """按行导入预设名，返回 {added, skipped, errors}。"""
        added, skipped, errors = 0, 0, []
        for line in (text or "").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            # 支持 "预设名 | 别名 | 备注" 形式
            parts = [p.strip() for p in raw.split("|")]
            name = parts[0]
            alias = parts[1] if len(parts) > 1 else alias_prefix
            note = parts[2] if len(parts) > 2 else ""
            ok, message = self.add(name, alias=alias, note=note, source=source)
            if ok:
                added += 1
            elif "已存在" in message:
                skipped += 1
            else:
                errors.append(message)
        return {"added": added, "skipped": skipped, "errors": errors}

    def remove(self, name: str) -> tuple[bool, str]:
        before = len(self.waves)
        self.waves = [w for w in self.waves if w.name != name]
        if len(self.waves) == before:
            return False, f"未找到: {name}"
        self._persist()
        return True, f"已删除: {name}"

    def update(self, name: str, alias: str, note: str) -> tuple[bool, str]:
        wave = self.find(name)
        if wave is None:
            return False, f"未找到: {name}"
        wave.alias = alias.strip()
        wave.note = note.strip()
        self._persist()
        return True, "已保存"

    def _persist(self) -> None:
        target = self.dir / "library.json"
        payload = [asdict(w) for w in self.waves]
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- 导入 ----
    def import_file(self, path: str) -> dict:
        """从 .json / .txt 导入。json 支持波形库格式或 {frames:[...]} 的原样备份。"""
        p = Path(path)
        if not p.is_file():
            return {"added": 0, "skipped": 0, "errors": ["文件不存在"]}
        if p.suffix.lower() == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                return {"added": 0, "skipped": 0, "errors": [str(exc)]}
            items = data if isinstance(data, list) else [data]
            lines = []
            for item in items:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                    if not name:
                        continue
                    alias = str(item.get("alias", "") or "")
                    note = str(item.get("note", "") or "")
                    lines.append(f"{name} | {alias} | {note}")
                elif isinstance(item, str):
                    lines.append(item)
            return self.add_many("\n".join(lines), source=p.stem)
        text = p.read_text(encoding="utf-8", errors="ignore")
        return self.add_many(text, source=p.stem)


DEFAULT_SEED = """# DGHub 常见预设名参考（每行：预设名 | 别名 | 备注）
# 请把左侧预设名改成 DGHub 里实际显示的名字，逐字一致才会生效。
CS2-受伤 | 短促刺痛 | 高频短波形，适合提醒抄错呼号
CS2-死亡 | 重击 | 较长较强，适合重复通联
呼吸 | 缓脉冲 | 低频变化，适合空窗提醒
心跳 | 节拍 | 中频规律脉冲
脉冲 | 持续 | 中低频持续输出
"""
