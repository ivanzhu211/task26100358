"""容量与格位独占约束的验收测试。"""
from datetime import datetime, timezone

import pytest

from gridpromo import ConflictError, GridPromoService

UTC = timezone.utc


@pytest.fixture
def svc():
    s = GridPromoService(":memory:")
    s.create_grid("g", 6, 5, "America/New_York")  # 30 个格位
    yield s
    s.close()


def test_thirty_cells_exactly_twenty_accepted(svc):
    """30 个不同格位依次提交同一时段，恰好 20 个成功、10 个被拒。"""
    accepted, rejected = [], []
    for i in range(30):
        row, col = divmod(i, 5)
        try:
            svc.schedule("g", f"p{i}", row, col, f"P{i}",
                           "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
            accepted.append(i)
        except ConflictError:
            rejected.append(i)
    assert len(accepted) == 20
    assert len(rejected) == 10
    # 前 20 个成功，后 10 个因越界被拒
    assert accepted == list(range(20))
    assert rejected == list(range(20, 30))
    # 生效时刻网格上恰好 20 个促销
    board = svc.display_at("g", datetime(2026, 3, 10, 14, 30, tzinfo=UTC))
    shown = [board[r][c] for r in range(6) for c in range(5)]
    assert sum(1 for v in shown if v is not None) == 20


def test_cancel_frees_capacity(svc):
    for i in range(20):
        row, col = divmod(i, 5)
        svc.schedule("g", f"p{i}", row, col, "P", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
    svc.cancel("g", "p0")
    svc.schedule("g", "p20", 4, 0, "P20", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")


def test_capacity_counts_only_overlapping(svc):
    # 20 个占满 10:00–11:00
    for i in range(20):
        row, col = divmod(i, 5)
        svc.schedule("g", f"p{i}", row, col, "P", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
    # 第 21 个首尾相接（11:00 开始）→ 接受
    svc.schedule("g", "next", 5, 4, "N", "03/10/2026 11:00 AM", "03/10/2026 12:00 PM")
    # 第 21 个重叠 1 分钟（10:59 结束）→ 拒绝
    with pytest.raises(ConflictError):
        svc.schedule("g", "overlap", 5, 4, "O", "03/10/2026 09:30 AM", "03/10/2026 10:59 AM")


def test_same_cell_overlap_rejected_adjacent_ok(svc):
    svc.schedule("g", "a", 0, 0, "A", "03/10/2026 10:00 AM", "03/10/2026 11:00 AM")
    with pytest.raises(ConflictError):
        svc.schedule("g", "b", 0, 0, "B", "03/10/2026 10:30 AM", "03/10/2026 11:30 AM")
    svc.schedule("g", "c", 0, 0, "C", "03/10/2026 11:00 AM", "03/10/2026 12:00 PM")
