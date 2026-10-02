"""容量上限与边界规则：20 个封顶、同格位互斥、首尾相接不算重叠。"""

from datetime import datetime, timezone

import pytest

from gridpromo import (
    ConflictError,
    GridService,
    InvalidCellError,
    InvalidTimeError,
    PromoNotFoundError,
    connect,
)

UTC = timezone.utc


@pytest.fixture()
def svc():
    return GridService(connect(":memory:"))


def test_grid_cap_exactly_twenty(svc):
    grid = svc.create_grid(5, 6, "America/Chicago")
    accepted = 0
    rejected = 0
    for index in range(30):
        row, col = divmod(index, 6)
        try:
            svc.create_promo(
                grid, row, col, f"P{index}", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM"
            )
            accepted += 1
        except ConflictError:
            rejected += 1
    assert accepted == 20
    assert rejected == 10
    # 取消一个后名额立即释放，可以再建一个
    svc.cancel_promo(1)
    svc.create_promo(grid, 0, 0, "P30", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")


def test_same_cell_overlap_rejected(svc):
    grid = svc.create_grid(2, 2, "America/Phoenix")
    svc.create_promo(grid, 0, 0, "A", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
    with pytest.raises(ConflictError):
        svc.create_promo(grid, 0, 0, "B", "03/10/2026 10:30 AM", "03/10/2026 11:30 AM")
    # 首尾相接不算重叠
    svc.create_promo(grid, 0, 0, "C", "03/10/2026 11:00 AM", "03/10/2026 12:00 PM")
    svc.create_promo(grid, 0, 0, "D", "03/10/2026 09:00 AM", "03/10/2026 10:00 AM")


def test_reschedule_rejection_keeps_original(svc):
    grid = svc.create_grid(1, 2, "America/Phoenix")
    svc.create_promo(grid, 0, 0, "A", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
    b = svc.create_promo(grid, 0, 1, "B", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
    svc.create_promo(grid, 0, 1, "C", "03/10/2026 02:00 PM", "03/10/2026 03:00 PM")
    with pytest.raises(ConflictError):
        svc.reschedule_promo(b, "03/10/2026 02:30 PM", "03/10/2026 04:00 PM")
    # 改期被拒，原排期保持不变
    board = svc.get_display(grid, datetime(2026, 3, 10, 17, 30, tzinfo=UTC))
    assert board[0][1].product == "B"
    assert board[0][1].is_promo


def test_reschedule_to_same_slot_allowed(svc):
    grid = svc.create_grid(1, 1, "America/Phoenix")
    a = svc.create_promo(grid, 0, 0, "A", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
    svc.reschedule_promo(a, "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")


def test_invalid_inputs(svc):
    grid = svc.create_grid(2, 2, "America/Phoenix")
    with pytest.raises(InvalidTimeError):
        svc.create_promo(grid, 0, 0, "A", "03/10/2026 11:00 AM", "03/10/2026 10:00 AM")
    with pytest.raises(InvalidTimeError):
        svc.create_promo(grid, 0, 0, "A", "not-a-time", "03/10/2026 10:00 AM")
    with pytest.raises(InvalidCellError):
        svc.create_promo(grid, 2, 0, "A", "03/10/2026 09:00 AM", "03/10/2026 10:00 AM")
    with pytest.raises(PromoNotFoundError):
        svc.cancel_promo(999)
    with pytest.raises(PromoNotFoundError):
        svc.reschedule_promo(999, "03/10/2026 09:00 AM", "03/10/2026 10:00 AM")


def test_display_falls_back_to_default(svc):
    grid = svc.create_grid(1, 2, "America/Phoenix", {(0, 0): "DEFAULT"})
    svc.create_promo(grid, 0, 1, "PROMO", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
    during = svc.get_display(grid, datetime(2026, 3, 10, 17, 30, tzinfo=UTC))
    assert during[0][0].product == "DEFAULT"
    assert not during[0][0].is_promo
    assert during[0][1].product == "PROMO"
    after = svc.get_display(grid, datetime(2026, 3, 10, 18, 0, tzinfo=UTC))
    assert after[0][1].product is None
    assert not after[0][1].is_promo


def test_persistence_roundtrip(tmp_path):
    db_file = str(tmp_path / "promo.db")
    svc = GridService(connect(db_file))
    grid = svc.create_grid(1, 1, "America/New_York", {(0, 0): "DEFAULT"})
    svc.create_promo(grid, 0, 0, "PROMO", "03/08/2026 02:30 AM", "03/08/2026 04:00 AM")
    svc2 = GridService(connect(db_file))
    board = svc2.get_display(grid, datetime(2026, 3, 8, 7, 30, tzinfo=UTC))
    assert board[0][0].product == "PROMO"
