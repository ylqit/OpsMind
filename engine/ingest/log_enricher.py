"""
日志富化器。

提供轻量的 IP、UA、PV 和 service_key 推断，避免上层直接处理原始日志字段。
"""
from __future__ import annotations

import ipaddress
from typing import Dict
from urllib.parse import urlparse


class LogEnricher:
    """对结构化日志做轻量富化。"""

    def enrich(self, record: Dict[str, object], host_hint: str = "") -> Dict[str, object]:
        enriched = dict(record)
        remote_addr = str(enriched.get("remote_addr") or "")
        user_agent = str(enriched.get("user_agent") or "")
        path = str(enriched.get("path") or "/")
        host = host_hint or self._extract_host(str(enriched.get("referer") or ""))
        geo = self._build_geo(remote_addr)
        ua = self._parse_user_agent(user_agent)

        enriched["ip_scope"] = self._detect_ip_scope(remote_addr)
        enriched["geo"] = geo
        enriched["ua"] = ua
        enriched["geo_label"] = self._build_geo_label(geo)
        enriched["browser"] = ua["browser"]
        enriched["os"] = ua["os"]
        enriched["device"] = ua["device"]
        enriched["client_ip"] = remote_addr or "-"
        enriched["is_page_view"] = self._is_page_view(path)
        enriched["service_key"] = self._build_service_key(host, path)
        return enriched

    def fallback_enrich(self, record: Dict[str, object], host_hint: str = "") -> Dict[str, object]:
        """当富化过程异常时，返回最小可用字段，避免整批日志被丢弃。"""
        enriched = dict(record)
        path = str(enriched.get("path") or "/")
        remote_addr = str(enriched.get("remote_addr") or "")
        user_agent = str(enriched.get("user_agent") or "")
        host = host_hint or "unknown-host"
        geo = self._build_geo(remote_addr)
        ua = self._parse_user_agent(user_agent)

        enriched["ip_scope"] = self._detect_ip_scope(remote_addr)
        enriched["geo"] = geo
        enriched["ua"] = ua
        enriched["geo_label"] = self._build_geo_label(geo)
        enriched["browser"] = ua["browser"]
        enriched["os"] = ua["os"]
        enriched["device"] = ua["device"]
        enriched["client_ip"] = remote_addr or "-"
        enriched["is_page_view"] = self._is_page_view(path)
        enriched["service_key"] = self._build_service_key(host, path)
        enriched["enrich_fallback"] = True
        return enriched

    def _detect_ip_scope(self, ip_text: str) -> str:
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            return "unknown"
        if ip.is_loopback:
            return "loopback"
        if ip.is_private:
            return "private"
        return "public"

    def _build_geo(self, ip_text: str) -> Dict[str, str]:
        scope = self._detect_ip_scope(ip_text)
        if scope == "private":
            return {"country": "内网", "region": "私有网络", "city": "本地"}
        if scope == "loopback":
            return {"country": "本机", "region": "回环地址", "city": "localhost"}
        if scope == "public":
            return {"country": "公网", "region": "未知区域", "city": "未知城市"}
        return {"country": "未知", "region": "未知", "city": "未知"}

    def _build_geo_label(self, geo: Dict[str, str]) -> str:
        return "/".join(
            [str(part) for part in [geo.get("country"), geo.get("region"), geo.get("city")] if part],
        ) or "未知"

    def _parse_user_agent(self, user_agent: str) -> Dict[str, str]:
        ua = user_agent.lower()
        if "bot" in ua or "spider" in ua or "crawler" in ua:
            device = "bot"
        elif "mobile" in ua or "android" in ua or "iphone" in ua:
            device = "mobile"
        else:
            device = "desktop"

        if "chrome" in ua and "edg" not in ua:
            browser = "Chrome"
        elif "safari" in ua and "chrome" not in ua:
            browser = "Safari"
        elif "firefox" in ua:
            browser = "Firefox"
        elif "edg" in ua:
            browser = "Edge"
        else:
            browser = "Unknown"

        if "windows" in ua:
            os_name = "Windows"
        elif "mac os" in ua or "macintosh" in ua:
            os_name = "macOS"
        elif "linux" in ua:
            os_name = "Linux"
        elif "android" in ua:
            os_name = "Android"
        elif "iphone" in ua or "ios" in ua:
            os_name = "iOS"
        else:
            os_name = "Unknown"

        return {"browser": browser, "os": os_name, "device": device}

    def _is_page_view(self, path: str) -> bool:
        static_suffixes = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".map")
        return not path.lower().endswith(static_suffixes)

    def _build_service_key(self, host: str, path: str) -> str:
        clean_host = host or "unknown-host"
        prefix = path.split("/", 2)[1] if path.startswith("/") and len(path.split("/")) > 1 else "root"
        return f"{clean_host}/{prefix or 'root'}"

    def _extract_host(self, referer: str) -> str:
        if not referer:
            return ""
        try:
            return urlparse(referer).hostname or ""
        except ValueError:
            return ""
