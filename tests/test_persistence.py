"""排期数据持久化在本地 SQLite 文件中，重开后仍在。"""
from datetime import datetime, timezone

from gridpromo import GridPromoService, PromotionNotFoundError
import pytest

UTC = timezone.utc


def test_data_survives_reopen(tmp_path):
    db = str(tmp_path / "promo.db")
    svc = GridPromoService(db)
    svc.create_grid("g", 4, 4, "America/New_York", {(0, 0): "D0"})
    svc.schedule("g", "p1", 1, 1, "X", "03/08/2026 12:00 AM", "03/08/2026 04:00 AM")
    svc.schedule("g", "p2", 2, 2, "Y", "03/09/2026 10:00 AM", "03/09/2026 11:00 AM")
    svc.cancel("g", "p2")
    svc.close()

    svc2 = GridPromoService(db)
    board = svc2.display_at("g", datetime(2026, 3, 8, 6, 0, tzinfo=UTC))
    assert board[1][1] == "X"
    assert board[0][0] == "D0"
    # 已取消的促销保持取消状态
    with pytest.raises(PromotionNotFoundError):
        svc2.cancel("g", "p2")
    svc2.close()
