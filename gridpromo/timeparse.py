"""本地时间解析与夏令时处理。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .errors import InvalidTimeError

FORMAT = "%m/%d/%Y %I:%M %p"
_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2} (AM|PM)$")
_UTC = timezone.utc


def _roundtrip_ok(naive: datetime, tz: ZoneInfo, fold: int) -> bool:
    """该 fold 下 naive 是否是真实存在的本地时间。"""
    aware = naive.replace(tzinfo=tz, fold=fold)
    back = aware.astimezone(_UTC).astimezone(tz)
    return back.replace(tzinfo=None) == naive and back.utcoffset() == aware.utcoffset()


def _gap_end_utc(naive: datetime, tz: ZoneInfo) -> datetime:
    """对空档中的本地时间，求空档结束那一刻的 UTC 时刻。

    fold=0 用跳变前偏移、fold=1 用跳变后偏移，二者夹住真实跳变点，
    在整数 epoch 秒上二分找到 utcoffset 切换的瞬间。
    """
    lo = int(naive.replace(tzinfo=tz, fold=1).astimezone(_UTC).timestamp())  # 跳变后偏移
    hi = int(naive.replace(tzinfo=tz, fold=0).astimezone(_UTC).timestamp())  # 跳变前偏移
    target = datetime.fromtimestamp(lo, _UTC).astimezone(tz).utcoffset()
    # 不变式：lo 处偏移 == target（跳变后），hi 处偏移 != target（跳变前）
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if datetime.fromtimestamp(mid, _UTC).astimezone(tz).utcoffset() == target:
            lo = mid
        else:
            hi = mid
    return datetime.fromtimestamp(hi, _UTC)


def parse_local(text: str, tz: ZoneInfo, *, is_end: bool) -> datetime:
    """把 "03/08/2026 02:30 PM" 这样的本地时间解析为带时区的实际时刻。

    - 空档（春季拨快）中不存在的时间：按空档结束时刻算。
    - 重复（秋季回拨）时间：开始取第一次出现，结束取第二次出现。
    """
    if not isinstance(text, str) or not _PATTERN.match(text.strip()):
        raise InvalidTimeError(f"无法解析时间: {text!r}，期望格式 MM/DD/YYYY HH:MM AM/PM")
    try:
        naive = datetime.strptime(text.strip(), FORMAT)
    except ValueError as exc:
        raise InvalidTimeError(f"无法解析时间: {text!r}，期望格式 MM/DD/YYYY HH:MM AM/PM") from exc

    first = naive.replace(tzinfo=tz, fold=0)
    second = naive.replace(tzinfo=tz, fold=1)
    ok_first = _roundtrip_ok(naive, tz, fold=0)
    ok_second = _roundtrip_ok(naive, tz, fold=1)

    if ok_first and ok_second and first.utcoffset() == second.utcoffset():
        return first  # 普通时间，唯一对应
    if ok_first and ok_second:
        # 秋季回拨重复时间：开始取第一次（UTC 早），结束取第二次
        return first if not is_end else second
    # 春季空档：按空档结束时刻算
    return _gap_end_utc(naive, tz).astimezone(tz)
