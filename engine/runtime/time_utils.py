"""
统一的 UTC 时间工具。
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone


UTC = timezone.utc
UTC_MIN = datetime.min.replace(tzinfo=UTC)


def utc_now() -> datetime:
    """返回带时区信息的 UTC 时间。"""
    return datetime.now(UTC)


def utc_now_iso() -> str:
    """返回 ISO 8601 格式的 UTC 时间字符串。"""
    return utc_now().isoformat()


def ensure_utc_datetime(value: datetime) -> datetime:
    """把任意 datetime 归一化为 UTC，兼容历史无时区数据。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_utc_datetime(value: str) -> datetime:
    """解析 ISO 时间文本并统一转换为 UTC。"""
    return ensure_utc_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))


def parse_optional_utc_datetime(value: str | None) -> datetime | None:
    """解析可选时间文本，空值时返回 None。"""
    if not value:
        return None
    return parse_utc_datetime(value)


def utc_day_start(day_value: date) -> datetime:
    """返回指定日期在 UTC 下的起始时间。"""
    return datetime.combine(day_value, time.min, tzinfo=UTC)
