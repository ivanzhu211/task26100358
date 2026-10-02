"""纽约时区夏令时切换前后的新建/改期/取消，逐分钟核对。"""

from datetime import datetime, timedelta, timezone

import pytest

from gridpromo import (
    ConflictError,
    GridService,
    InvalidTimeError,
    connect,
)

UTC = timezone.utc
SPRING_DAY = datetime(2026, 3, 8, tzinfo=UTC)  # 纽约 02:00 跳到 03:00
FALL_DAY = datetime(2026, 11, 1, tzinfo=UTC)  # 纽约 02:00 回拨到 01:00


@pytest.fixture()
def svc():
    return GridService(connect(":memory:"))


def active_cells(svc, grid_id, moment):
    board = svc.get_display(grid_id, moment)
    return {
        (cell.row, cell.col): cell.product
        for row in board
        for cell in row
        if cell.is_promo
    }


def assert_minutes(svc, grid_id, day, expected):
    """expected: {UTC 分钟 datetime: {(row, col): product}}，逐分钟核对。"""
    moment = day
    while moment < day + timedelta(days=1):
        assert active_cells(svc, grid_id, moment) == expected.get(moment, {}), moment
        moment += timedelta(minutes=1)


def minute_map(intervals):
    """intervals: [(start_utc, end_utc, cell, product)] -> 逐分钟期望表。"""
    expected = {}
    for start, end, cell, product in intervals:
        moment = start
        while moment < end:
            expected.setdefault(moment, {})[cell] = product
            moment += timedelta(minutes=1)
    return expected


def utc(hour, minute=0, day=SPRING_DAY):
    return day.replace(hour=hour, minute=minute)


def test_spring_forward_create(svc):
    grid = svc.create_grid(1, 3, "America/New_York")
    # 01:00 EST -> 02:30 不存在按 03:00 EDT 算：实际 06:00-07:00 UTC，仅 1 小时
    svc.create_promo(grid, 0, 0, "A", "03/08/2026 01:00 AM", "03/08/2026 02:30 AM")
    # 首尾相接：03:00 EDT 开始，不与上面的 07:00 UTC 结束重叠
    svc.create_promo(grid, 0, 0, "B", "03/08/2026 03:00 AM", "03/08/2026 04:00 AM")
    expected = minute_map(
        [
            (utc(6), utc(7), (0, 0), "A"),
            (utc(7), utc(8), (0, 0), "B"),
        ]
    )
    assert_minutes(svc, grid, SPRING_DAY, expected)


def test_spring_forward_gap_start_equals_end_rejected(svc):
    grid = svc.create_grid(1, 1, "America/New_York")
    # 02:30 与 03:00 都按 07:00 UTC 算，结束不晚于开始
    with pytest.raises(InvalidTimeError):
        svc.create_promo(grid, 0, 0, "X", "03/08/2026 02:30 AM", "03/08/2026 03:00 AM")


def test_spring_forward_overlap_rejected(svc):
    grid = svc.create_grid(1, 2, "America/New_York")
    svc.create_promo(grid, 0, 0, "A", "03/08/2026 01:00 AM", "03/08/2026 02:30 AM")
    # 01:30-03:30 实际为 06:30-07:30 UTC，与 A 的 06:00-07:00 重叠
    with pytest.raises(ConflictError):
        svc.create_promo(grid, 0, 0, "C", "03/08/2026 01:30 AM", "03/08/2026 03:30 AM")
    # 换到空格位则必须接受
    svc.create_promo(grid, 0, 1, "C", "03/08/2026 01:30 AM", "03/08/2026 03:30 AM")


def test_spring_forward_reschedule_and_cancel(svc):
    grid = svc.create_grid(1, 2, "America/New_York")
    a = svc.create_promo(grid, 0, 0, "A", "03/08/2026 01:00 AM", "03/08/2026 02:30 AM")
    b = svc.create_promo(grid, 0, 1, "B", "03/08/2026 05:00 AM", "03/08/2026 06:00 AM")
    svc.create_promo(grid, 0, 1, "D", "03/08/2026 01:00 AM", "03/08/2026 02:30 AM")
    # 改期到与同格位的 D 重叠：拒绝，且原排期不变
    with pytest.raises(ConflictError):
        svc.reschedule_promo(b, "03/08/2026 01:30 AM", "03/08/2026 03:30 AM")
    expected = minute_map(
        [
            (utc(6), utc(7), (0, 0), "A"),
            (utc(6), utc(7), (0, 1), "D"),
            (utc(9), utc(10), (0, 1), "B"),
        ]
    )
    assert_minutes(svc, grid, SPRING_DAY, expected)
    # 改期到合法时段：接受
    svc.reschedule_promo(b, "03/08/2026 03:00 AM", "03/08/2026 04:00 AM")
    expected = minute_map(
        [
            (utc(6), utc(7), (0, 0), "A"),
            (utc(6), utc(7), (0, 1), "D"),
            (utc(7), utc(8), (0, 1), "B"),
        ]
    )
    assert_minutes(svc, grid, SPRING_DAY, expected)
    # 取消 A 后名额立即释放，原先冲突的排期现在可以建
    svc.cancel_promo(a)
    svc.create_promo(grid, 0, 0, "C", "03/08/2026 01:30 AM", "03/08/2026 03:30 AM")
    expected = minute_map(
        [
            (utc(6, 30), utc(7, 30), (0, 0), "C"),
            (utc(6), utc(7), (0, 1), "D"),
            (utc(7), utc(8), (0, 1), "B"),
        ]
    )
    assert_minutes(svc, grid, SPRING_DAY, expected)


def test_fall_back_ambiguous_start_and_end(svc):
    grid = svc.create_grid(1, 2, "America/New_York")
    # 01:30 出现两次：开始取第一次(EDT 05:30 UTC)，结束取第二次(EST 06:30 UTC)
    svc.create_promo(grid, 0, 0, "A", "11/01/2026 01:30 AM", "11/01/2026 01:30 AM")
    # 12:30 AM EDT = 04:30 UTC，结束 01:30 取第二次 = 06:30 UTC，实际 2 小时
    svc.create_promo(grid, 0, 1, "B", "11/01/2026 12:30 AM", "11/01/2026 01:30 AM")
    expected = minute_map(
        [
            (utc(5, 30, FALL_DAY), utc(6, 30, FALL_DAY), (0, 0), "A"),
            (utc(4, 30, FALL_DAY), utc(6, 30, FALL_DAY), (0, 1), "B"),
        ]
    )
    assert_minutes(svc, grid, FALL_DAY, expected)


def test_fall_back_overlap_across_repeat(svc):
    grid = svc.create_grid(1, 1, "America/New_York")
    svc.create_promo(grid, 0, 0, "A", "11/01/2026 01:30 AM", "11/01/2026 01:30 AM")
    # 01:00-02:00 实际覆盖 05:00-07:00 UTC 两个小时，与 A 的 05:30-06:30 重叠
    with pytest.raises(ConflictError):
        svc.create_promo(grid, 0, 0, "C", "11/01/2026 01:00 AM", "11/01/2026 02:00 AM")
