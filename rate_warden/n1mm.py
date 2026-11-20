"""N1MM Logger+ UDP 广播监听。后台线程收包，解析后交给回调。

N1MM 在 Config -> Configure Ports -> Broadcast Data 里向指定端口广播 XML。
本模块只消费 contactinfo / contactreplace / contactdelete / lookupinfo / radioinfo。
"""

from __future__ import annotations

import socket
import threading
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional

from .rule_base import Contact

RELEVANT = {"contactinfo", "contactreplace", "contactdelete", "lookupinfo", "radioinfo"}


def _text(node: ET.Element, tag: str) -> str:
    value = node.findtext(tag)
    return (value or "").strip()


def _bool_text(node: ET.Element, tag: str) -> Optional[bool]:
    value = _text(node, tag).lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return None


def parse(xml_text: str) -> tuple[str, Optional[Contact], Optional[dict]]:
    """解析一个包，返回 (kind, contact, radio)。无法解析时 kind 为空串。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "", None, None

    kind = (root.tag or "").lower()
    if kind not in RELEVANT:
        return "", None, None

    if kind == "radioinfo":
        radio = {
            "is_running": _bool_text(root, "IsRunning"),
            "freq": _text(root, "Freq"),
            "mode": _text(root, "Mode"),
        }
        return kind, None, radio

    contact = Contact(
        call=_text(root, "call").upper(),
        band=_text(root, "band"),
        mode=_text(root, "mode").upper(),
        is_original=_bool_text(root, "IsOriginal") is not False,
        sntnr=_text(root, "sntnr"),
        rcvnr=_text(root, "rcvnr"),
        power=_text(root, "power"),
        section=_text(root, "section"),
        zone=_text(root, "zone"),
        gridsquare=_text(root, "gridsquare"),
        is_run_qso=_bool_text(root, "IsRunQSO"),
        raw={child.tag: (child.text or "") for child in root},
    )
    return kind, contact, None


class Listener:
    """UDP 监听线程。on_event(kind, contact, radio) 在监听线程中被调用。"""

    def __init__(self, port: int, bind: str, on_event: Callable,
                 on_error: Optional[Callable[[str], None]] = None) -> None:
        self.port = port
        self.bind = bind
        self.on_event = on_event
        self.on_error = on_error
        self.last_packet_ts: float = 0.0
        self.last_error: str = ""
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---- 生命周期 ----
    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.bind, self.port))
        except OSError as exc:
            sock.close()
            self.last_error = f"绑定 UDP {self.bind}:{self.port} 失败: {exc}"
            if self.on_error:
                self.on_error(self.last_error)
            raise
        sock.settimeout(0.3)
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="n1mm-udp", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def seconds_since_packet(self) -> Optional[float]:
        if self.last_packet_ts <= 0:
            return None
        return time.monotonic() - self.last_packet_ts

    # ---- 线程体 ----
    def _run(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, _addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self.last_packet_ts = time.monotonic()
            kind, contact, radio = parse(data.decode("utf-8", errors="ignore"))
            if not kind:
                continue
            try:
                self.on_event(kind, contact, radio)
            except Exception as exc:  # 用户规则异常不能杀死监听线程
                if self.on_error:
                    self.on_error(f"处理 {kind} 包出错: {exc}")
