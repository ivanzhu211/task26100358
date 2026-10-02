"""本地时间解析与夏令时规则的单元测试。"""
from datetime import timedelta

import pytest
from zoneinfo import ZoneInfo

from gridpromo.errors import InvalidTimeError
from gridpromo.timeparse import parse_local

NY = ZoneInfo("America/New_York")
PHX = ZoneInfo("America/Phoenix")
EDT = timedelta(hours=-4)
EST = timedelta(hours=-5)


def test_normal_time():
    dt = parse_local("03/07/2026 02:30 PM", NY, is_end=False)
    assert (dt.hour, dt.minute, dt.utcoffset()) == (14, 30, EST)


def test_pm_hour():
    dt = parse_local("06/15/2026 12:05 PM", NY, is_end=False)
    assert (dt.hour, dt.minute) == (12, 5)
    dt = parse_local("06/15/2026 12:05 AM", NY, is_end=False)
    assert (dt.hour, dt.minute) == (0, 5)


def test_spring_gap_maps_to_gap_end():
    for text in ("03/08/2026 02:00 AM", "03/08/2026 02:30 AM", "03/08/2026 02:59 AM"):
        for is_end in (False, True):
            dt = parse_local(text, NY, is_end=is_end)
            assert (dt.hour, dt.minute, dt.utcoffset()) == (3, 0, EDT), text


def test_fall_back_start_first_occurrence():
    dt = parse_local("11/01/2026 01:30 AM", NY, is_end=False)
    assert (dt.hour, dt.minute, dt.utcoffset()) == (1, 30, EDT)


def test_fall_back_end_second_occurrence():
    dt = parse_local("11/01/2026 01:30 AM", NY, is_end=True)
    assert (dt.hour, dt.minute, dt.utcoffset()) == (1, 30, EST)


def test_fall_back_boundary_minutes():
    # 01:00 与 01:59 同样遵循开始取第一次、结束取第二次
    assert parse_local("11/01/2026 01:00 AM", NY, is_end=False).utcoffset() == EDT
    assert parse_local("11/01/2026 01:00 AM", NY, is_end=True).utcoffset() == EST
    assert parse_local("11/01/2026 01:59 AM", NY, is_end=False).utcoffset() == EDT
    assert parse_local("11/01/2026 01:59 AM", NY, is_end=True).utcoffset() == EST


def test_no_dst_timezone_unaffected():
    dt = parse_local("03/08/2026 02:30 AM", PHX, is_end=False)
    assert (dt.hour, dt.minute) == (2, 30)
    assert parse_local("03/08/2026 02:30 AM", PHX, is_end=True) == dt


def test_invalid_format():
    for bad in ("2026-03-08", "03/08/2026 14:30", "03/08/2026 2:30 PM", "", "abc"):
        with pytest.raises(InvalidTimeError):
            parse_local(bad, NY, is_end=False)
