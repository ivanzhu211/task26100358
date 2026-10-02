"""本地时间与 UTC 的转换，含夏令时跳变规则。

规则：
- 春季跳变空档里不存在的本地时间，一律按空档结束的那一刻算。
- 秋季回拨时重复出现的本地时间，作开始时间取第一次出现，
  作结束时间取第二次出现。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TIME_FORMAT = "%m/%d/%Y %I:%M %p"
_UTC = timezone.utc


def parse_local(text: str) -> datetime:
    """解析 "03/08/2026 02:30 PM" 这样的 12 小时制本地时间字符串。

    返回 naive datetime（不携带时区）。格式非法时抛 ValueError。
    """
    text = " ".join(text.split())
    return datetime.strptime(text, LOCAL_TIME_FORMAT)


def _roundtrip_valid(tz: ZoneInfo, aware: datetime, naive: datetime) -> bool:
    back = aware.astimezone(_UTC).astimezone(tz)
    return back.replace(tzinfo=None) == naive


def _find_transition(tz: ZoneInfo, lo: datetime, hi: datetime) -> datetime:
    """在 [lo, hi]（UTC，aware）内二分查找 utcoffset 跳变的那一刻。"""
    offset_lo = lo.astimezone(tz).utcoffset()
    while (hi - lo) > timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        if mid.astimezone(tz).utcoffset() == offset_lo:
            lo = mid
        else:
            hi = mid
    return hi.replace(microsecond=0)


def local_to_utc(tz: ZoneInfo, local: datetime, *, is_end: bool) -> datetime:
    """把网格时区的本地时间换算成 UTC（aware datetime）。

    - 不存在的本地时间（春季空档）：按空档结束时刻算。
    - 重复出现的本地时间（秋季回拨）：is_end=False 取第一次，
      is_end=True 取第二次。
    """
    if local.tzinfo is not None:
        raise ValueError("local 必须是 naive datetime")
    first = local.replace(tzinfo=tz, fold=0)
    second = local.replace(tzinfo=tz, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first.astimezone(_UTC)
    valid_first = _roundtrip_valid(tz, first, local)
    valid_second = _roundtrip_valid(tz, second, local)
    if valid_first and valid_second:
        chosen = second if is_end else first
        return chosen.astimezone(_UTC)
    # 空档：fold=0 用跳变前偏移，fold=1 用跳变后偏移，
    # 两者各自换算出的 UTC 把真正的跳变点夹在中间。
    lo = second.astimezone(_UTC)
    hi = first.astimezone(_UTC)
    if lo > hi:
        lo, hi = hi, lo
    return _find_transition(tz, lo, hi)


def utc_to_local(tz: ZoneInfo, moment: datetime) -> datetime:
    """把一个实际时刻（aware datetime）换算成网格时区的本地时间。"""
    if moment.tzinfo is None:
        raise ValueError("moment 必须是 aware datetime")
    return moment.astimezone(tz)
