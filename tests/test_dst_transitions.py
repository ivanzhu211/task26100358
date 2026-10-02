"""夏令时切换日的端到端验收测试（纽约时区，2026 年）。

- 春季拨快：03/08 02:00 跳转到 03:00（02:00–03:00 不存在）
- 秋季回拨：11/01 02:00 回到 01:00（01:00–02:00 出现两次）

每个用例都把排期结果与逐分钟推算的实际生效分钟逐一比对。
"""
from datetime import datetime, timedelta, timezone

import pytest

from gridpromo import (
    ConflictError,
    GridPromoService,
    InvalidTimeError,
    PromotionNotFoundError,
)

UTC = timezone.utc


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


@pytest.fixture
def svc():
    s = GridPromoService(":memory:")
    s.create_grid("g", 8, 8, "America/New_York", {(0, 0): "DEFAULT"})
    yield s
    s.close()


def active_minutes(svc, grid_id, row, col, t_from, t_to):
    """逐分钟推算：返回 [t_from, t_to) 内该格位每分钟展示的商品。"""
    result = {}
    t = t_from
    while t < t_to:
        result[t] = svc.display_at(grid_id, t)[row][col]
        t += timedelta(minutes=1)
    return result


def assert_active_exactly(svc, grid_id, row, col, product, start_utc, end_utc):
    """断言该格位恰好在 [start_utc, end_utc) 的每一分钟展示 product，前后一分钟不展示。"""
    pad = timedelta(hours=1)
    minutes = active_minutes(svc, grid_id, row, col, start_utc - pad, end_utc + pad)
    for t, shown in minutes.items():
        expect = product if start_utc <= t < end_utc else None
        assert shown == expect, f"{t.isoformat()} 期望 {expect}，实际 {shown}"


# ---------- 春季拨快（03/08/2026） ----------

def test_spring_forward_create_minute_by_minute(svc):
    # 本地 12:00 AM–04:00 AM 跨空档，实际只有 3 小时：05:00–08:00 UTC
    svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 12:00 AM", "03/08/2026 04:00 AM")
    assert_active_exactly(svc, "g", 1, 1, "X", utc(2026, 3, 8, 5), utc(2026, 3, 8, 8))


def test_spring_forward_gap_start_snaps_to_gap_end(svc):
    # 02:30 AM 不存在，按空档结束 03:00 EDT（07:00 UTC）算
    svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 02:30 AM", "03/08/2026 03:30 AM")
    assert_active_exactly(svc, "g", 1, 1, "X", utc(2026, 3, 8, 7), utc(2026, 3, 8, 7, 30))


def test_spring_forward_window_fully_inside_gap_rejected(svc):
    # 02:15–02:45 都落在空档里，实际时长为 0，结束不晚于开始
    with pytest.raises(InvalidTimeError):
        svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 02:15 AM", "03/08/2026 02:45 AM")


def test_spring_forward_gap_to_gap_end_rejected(svc):
    # 02:00–03:00 本地看似一小时，实际两端都映射到 07:00 UTC
    with pytest.raises(InvalidTimeError):
        svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 02:00 AM", "03/08/2026 03:00 AM")


def test_spring_forward_reschedule_and_cancel(svc):
    svc.schedule("g", "p1", 1, 1, "X", "03/07/2026 10:00 PM", "03/08/2026 01:00 AM")
    # 改期跨过空档：01:30 AM – 03:30 AM → 06:30–07:30 UTC
    svc.reschedule("g", "p1", "03/08/2026 01:30 AM", "03/08/2026 03:30 AM")
    assert_active_exactly(svc, "g", 1, 1, "X", utc(2026, 3, 8, 6, 30), utc(2026, 3, 8, 7, 30))
    # 取消后名额立刻释放，格位回到无促销状态
    svc.cancel("g", "p1")
    minutes = active_minutes(svc, "g", 1, 1, utc(2026, 3, 8, 6), utc(2026, 3, 8, 9))
    assert all(v is None for v in minutes.values())
    # 取消后可以立刻在同一格位同一时段再排
    svc.schedule("g", "p2", 1, 1, "Y", "03/08/2026 01:30 AM", "03/08/2026 03:30 AM")
    assert_active_exactly(svc, "g", 1, 1, "Y", utc(2026, 3, 8, 6, 30), utc(2026, 3, 8, 7, 30))


def test_spring_forward_reschedule_rejected_keeps_original(svc):
    svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 12:00 AM", "03/08/2026 01:00 AM")
    svc.schedule("g", "p2", 1, 1, "Y", "03/08/2026 03:00 AM", "03/08/2026 04:00 AM")
    # 试图把 p1 改到与 p2 重叠 → 拒绝，p1 保持原排期
    with pytest.raises(ConflictError):
        svc.reschedule("g", "p1", "03/08/2026 03:30 AM", "03/08/2026 05:00 AM")
    assert_active_exactly(svc, "g", 1, 1, "X", utc(2026, 3, 8, 5), utc(2026, 3, 8, 6))


def test_spring_forward_cell_conflict_across_gap(svc):
    # p1: 01:00–02:30 AM → 06:00–07:00 UTC（02:30 映射到 03:00 EDT）
    svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 01:00 AM", "03/08/2026 02:30 AM")
    # p2: 03:00–04:00 AM → 07:00–08:00 UTC，与 p1 首尾相接，不算重叠
    svc.schedule("g", "p2", 1, 1, "Y", "03/08/2026 03:00 AM", "03/08/2026 04:00 AM")
    # p3: 02:45–03:15 AM → 07:00–07:15 UTC，与 p1/p2 都重叠 → 拒绝
    with pytest.raises(ConflictError):
        svc.schedule("g", "p3", 1, 1, "Z", "03/08/2026 02:45 AM", "03/08/2026 03:15 AM")


# ---------- 秋季回拨（11/01/2026） ----------

def test_fall_back_create_minute_by_minute(svc):
    # 本地 12:00 AM–02:00 AM 跨回拨，实际 3 小时：04:00–07:00 UTC
    svc.schedule("g", "p1", 1, 1, "X", "11/01/2026 12:00 AM", "11/01/2026 02:00 AM")
    assert_active_exactly(svc, "g", 1, 1, "X", utc(2026, 11, 1, 4), utc(2026, 11, 1, 7))


def test_fall_back_ambiguous_start_first_end_second(svc):
    # 同一个本地时间 01:30 AM：开始取第一次（EDT 05:30 UTC），结束取第二次（EST 06:30 UTC）
    svc.schedule("g", "p1", 1, 1, "X", "11/01/2026 01:30 AM", "11/01/2026 01:30 AM")
    assert_active_exactly(svc, "g", 1, 1, "X", utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 6, 30))


def test_fall_back_reschedule_and_cancel(svc):
    svc.schedule("g", "p1", 1, 1, "X", "10/31/2026 10:00 PM", "11/01/2026 12:30 AM")
    # 改期到 01:00 AM–02:00 AM：开始取第一次 01:00 EDT（05:00 UTC），
    # 结束取第二次 02:00 EST（07:00 UTC），实际 2 小时
    svc.reschedule("g", "p1", "11/01/2026 01:00 AM", "11/01/2026 02:00 AM")
    assert_active_exactly(svc, "g", 1, 1, "X", utc(2026, 11, 1, 5), utc(2026, 11, 1, 7))
    svc.cancel("g", "p1")
    minutes = active_minutes(svc, "g", 1, 1, utc(2026, 11, 1, 4), utc(2026, 11, 1, 8))
    assert all(v is None for v in minutes.values())


def test_fall_back_reschedule_rejected_keeps_original(svc):
    # p1: 12:00–12:30 AM → 04:00–04:30 UTC
    svc.schedule("g", "p1", 1, 1, "X", "11/01/2026 12:00 AM", "11/01/2026 12:30 AM")
    # p2: 01:30 AM(第一次, 05:30 UTC) – 03:00 AM(EST, 08:00 UTC)
    svc.schedule("g", "p2", 1, 1, "Y", "11/01/2026 01:30 AM", "11/01/2026 03:00 AM")
    # 把 p1 改到 01:45–02:30 AM（05:45–07:30 UTC），与 p2 重叠 → 拒绝
    with pytest.raises(ConflictError):
        svc.reschedule("g", "p1", "11/01/2026 01:45 AM", "11/01/2026 02:30 AM")
    # p1 保持原排期 04:00–04:30 UTC
    assert_active_exactly(svc, "g", 1, 1, "X", utc(2026, 11, 1, 4), utc(2026, 11, 1, 4, 30))


def test_fall_back_adjacent_in_repeated_hour(svc):
    # p1: 01:30 AM(第一次, 05:30 UTC) – 02:00 AM(EST, 07:00 UTC)
    svc.schedule("g", "p1", 1, 1, "X", "11/01/2026 01:30 AM", "11/01/2026 02:00 AM")
    # p2: 02:00–03:00 AM → 07:00–08:00 UTC，与 p1 首尾相接 → 接受
    svc.schedule("g", "p2", 1, 1, "Y", "11/01/2026 02:00 AM", "11/01/2026 03:00 AM")
    # 首尾相接：06:59 还是 p1，07:00 起换成 p2
    assert svc.display_at("g", utc(2026, 11, 1, 6, 59))[1][1] == "X"
    assert svc.display_at("g", utc(2026, 11, 1, 7, 0))[1][1] == "Y"
    assert svc.display_at("g", utc(2026, 11, 1, 5, 29))[1][1] is None
    # p3: 01:00 AM(第一次, 05:00 UTC) – 01:30 AM(第二次, 06:30 UTC)，与 p1 重叠 → 拒绝
    with pytest.raises(ConflictError):
        svc.schedule("g", "p3", 1, 1, "Z", "11/01/2026 01:00 AM", "11/01/2026 01:30 AM")


# ---------- 通用 ----------

def test_cancel_then_reschedule_raises(svc):
    svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 10:00 AM", "03/08/2026 11:00 AM")
    svc.cancel("g", "p1")
    with pytest.raises(PromotionNotFoundError):
        svc.reschedule("g", "p1", "03/08/2026 12:00 PM", "03/08/2026 01:00 PM")
    with pytest.raises(PromotionNotFoundError):
        svc.cancel("g", "p1")


def test_display_falls_back_to_default(svc):
    svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 10:00 AM", "03/08/2026 11:00 AM")
    board = svc.display_at("g", utc(2026, 3, 8, 14, 30))
    assert board[1][1] == "X"
    assert board[0][0] == "DEFAULT"
    assert board[2][2] is None
