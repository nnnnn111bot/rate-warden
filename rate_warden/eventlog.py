"""持久化日志。

两条通路：
1. 磁盘 —— logs/YYYY-MM-DD.jsonl，一行一条记录，追加写入，重启不丢。
2. 内存 —— 最近 N 条的环形缓冲，供 GUI 的「记录」页与统计使用。

记录类型（kind）：
  penalty   真正下发的一次惩罚
  blocked   判定了但没下发（总开关关、强度 0、未连接等）
  merged    同一事件命中多条规则，只发了最强的一条
  rule      规则加载/启用/停用/参数变更
  system    启动、监听、连接状态
  wave      波形库变更
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from .config import LOGS_DIR

MAX_MEMORY = 5000


@dataclass
class LogRecord:
    ts: float
    kind: str
    level: str           # info | warn | error
    message: str
    rule_id: str = ""
    rule_name: str = ""
    strength: int = 0
    duration: float = 0.0
    preset: str = ""
    channel: str = ""
    reason: str = ""
    context: dict = field(default_factory=dict)

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts))

    @property
    def clock(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.ts))

    def to_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_line(cls, line: str) -> Optional["LogRecord"]:
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class EventLog:
    """线程安全的事件日志。

    UDP 监听线程与 GUI 线程都会写，所以这里用锁保护。
    """

    def __init__(self, directory: Optional[Path] = None,
                 echo_to_stdout: bool = False) -> None:
        self.dir = directory or LOGS_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.records: deque = deque(maxlen=MAX_MEMORY)
        self._lock = threading.Lock()
        self.echo_to_stdout = echo_to_stdout
        self._listeners: list = []
        self._today: str = ""
        self._handle = None

    # ---- 写入 ----
    def add(self, kind: str, message: str, level: str = "info", **extra) -> LogRecord:
        record = LogRecord(ts=time.time(), kind=kind, level=level,
                           message=message, **extra)
        with self._lock:
            self.records.append(record)
            self._write(record)
        if self.echo_to_stdout:
            print(f"[{record.clock}] {record.message}")
        for callback in list(self._listeners):
            try:
                callback(record)
            except Exception:
                pass
        return record

    def subscribe(self, callback) -> None:
        self._listeners.append(callback)

    def _write(self, record: LogRecord) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(record.ts))
        try:
            if day != self._today or self._handle is None:
                if self._handle is not None:
                    self._handle.close()
                path = self.dir / f"{day}.jsonl"
                self._handle = path.open("a", encoding="utf-8")
                self._today = day
            self._handle.write(record.to_line() + "\n")
            self._handle.flush()
        except OSError:
            self._handle = None  # 磁盘不可写时静默降级为纯内存

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                try:
                    self._handle.close()
                finally:
                    self._handle = None

    # ---- 查询 ----
    def snapshot(self) -> list:
        with self._lock:
            return list(self.records)

    def since(self, seconds: float) -> list:
        cutoff = time.time() - seconds
        return [r for r in self.snapshot() if r.ts >= cutoff]

    def load_day(self, day: Optional[str] = None) -> list:
        """从磁盘读某一天的记录（默认今天），用于重启后回看。"""
        day = day or time.strftime("%Y-%m-%d")
        path = self.dir / f"{day}.jsonl"
        if not path.exists():
            return []
        records = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                record = LogRecord.from_line(line)
                if record is not None:
                    records.append(record)
        except OSError:
            pass
        return records

    def stats(self, seconds: Optional[float] = None) -> dict:
        """按规则聚合：触发次数、平均强度、最近一次时间。"""
        records = self.since(seconds) if seconds else self.snapshot()
        penalties = [r for r in records if r.kind == "penalty"]
        by_rule: dict = {}
        for record in penalties:
            entry = by_rule.setdefault(record.rule_id or "?", {
                "rule_id": record.rule_id or "?",
                "rule_name": record.rule_name or record.rule_id or "?",
                "count": 0,
                "strength_total": 0,
                "last_ts": 0.0,
            })
            entry["count"] += 1
            entry["strength_total"] += record.strength
            entry["last_ts"] = max(entry["last_ts"], record.ts)

        rows = []
        for entry in by_rule.values():
            rows.append({
                "rule_id": entry["rule_id"],
                "rule_name": entry["rule_name"],
                "count": entry["count"],
                "avg_strength": round(entry["strength_total"] / entry["count"], 1),
                "last": time.strftime("%H:%M:%S", time.localtime(entry["last_ts"]))
                if entry["last_ts"] else "-",
            })
        rows.sort(key=lambda row: row["count"], reverse=True)

        return {
            "total_records": len(records),
            "penalties": len(penalties),
            "by_rule": rows,
            "last_penalty": (penalties[-1].when if penalties else "-"),
        }

    def timeline(self, limit: int = 200, kind: Optional[str] = None) -> list:
        """最新的在前，供「记录」页表格使用。"""
        records = self.snapshot()
        if kind:
            records = [r for r in records if r.kind == kind]
        return list(reversed(records))[:limit]
