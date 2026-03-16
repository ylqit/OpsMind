"""
Nginx/Ingress access log 解析器。

默认解析 combined log，输出统一结构，供聚合层直接消费。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Optional

from engine.runtime.time_utils import utc_now_iso


COMBINED_LOG_PATTERN = re.compile(
    r'(?P<remote_addr>\S+)\s+\S+\s+\S+\s+\[(?P<time_local>[^\]]+)\]\s+'
    r'"(?P<method>[A-Z]+)\s+(?P<path>[^"]*?)\s+(?P<protocol>[^"]+)"\s+'
    r'(?P<status>\d{3})\s+(?P<body_bytes_sent>\d+|-)'
    r'(?:\s+"(?P<http_referer>[^"]*)"\s+"(?P<http_user_agent>[^"]*)")?'
    r'(?:\s+(?P<request_time>\S+))?'
)


class AccessLogParser:
    """访问日志解析器。"""

    def parse_line(self, line: str) -> Optional[Dict[str, object]]:
        """解析单行 access log。"""
        match = COMBINED_LOG_PATTERN.search(line.strip())
        if not match:
            return None

        groups = match.groupdict()
        request_time = self._parse_float(groups.get("request_time") or "0")
        path = groups.get("path") or "/"
        path_only = path.split("?", 1)[0] if path else "/"
        return {
            "remote_addr": groups.get("remote_addr", ""),
            "timestamp": self._parse_time(groups.get("time_local", "")),
            "method": groups.get("method") or "GET",
            "path": path_only or "/",
            "raw_path": path,
            "protocol": groups.get("protocol") or "HTTP/1.1",
            "status": int(groups.get("status") or 0),
            "bytes_sent": self._parse_int(groups.get("body_bytes_sent")),
            "referer": groups.get("http_referer") or "",
            "user_agent": groups.get("http_user_agent") or "",
            "request_time": request_time,
        }

    def _parse_int(self, value: Optional[str]) -> int:
        if not value or value == "-":
            return 0
        try:
            return int(value)
        except ValueError:
            return 0

    def _parse_float(self, value: Optional[str]) -> float:
        if not value or value == "-":
            return 0.0
        try:
            return float(value.strip('"'))
        except ValueError:
            return 0.0

    def _parse_time(self, value: str) -> str:
        if not value:
            return utc_now_iso()
        try:
            parsed = datetime.strptime(value, "%d/%b/%Y:%H:%M:%S %z")
            return parsed.isoformat()
        except ValueError:
            return utc_now_iso()
