"""SQLite 持久化层。"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS grids (
    grid_id   TEXT PRIMARY KEY,
    rows      INTEGER NOT NULL,
    cols      INTEGER NOT NULL,
    timezone  TEXT NOT NULL,
    defaults  TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS promotions (
    grid_id      TEXT NOT NULL REFERENCES grids(grid_id),
    promotion_id TEXT NOT NULL,
    row          INTEGER NOT NULL,
    col          INTEGER NOT NULL,
    product_id   TEXT NOT NULL,
    start_utc    INTEGER NOT NULL,  -- epoch 秒
    end_utc      INTEGER NOT NULL,  -- epoch 秒，开区间端
    status       TEXT NOT NULL DEFAULT 'active',  -- active / cancelled
    PRIMARY KEY (grid_id, promotion_id)
);
CREATE INDEX IF NOT EXISTS idx_promotions_grid_active
    ON promotions (grid_id, status);
"""


class Store:
    """封装 grids / promotions 两张表的读写。时间统一存 epoch 秒。"""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """检查+写入放在同一事务里，失败整体回滚。"""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    # ---- grids ----

    def create_grid(
        self,
        grid_id: str,
        rows: int,
        cols: int,
        timezone: str,
        defaults: dict[tuple[int, int], str],
    ) -> None:
        defaults_json = json.dumps({f"{r},{c}": p for (r, c), p in defaults.items()})
        with self.transaction():
            self._conn.execute(
                "INSERT INTO grids (grid_id, rows, cols, timezone, defaults) VALUES (?,?,?,?,?)",
                (grid_id, rows, cols, timezone, defaults_json),
            )

    def get_grid(self, grid_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM grids WHERE grid_id = ?", (grid_id,)
        ).fetchone()
        if row is None:
            return None
        defaults = {tuple(map(int, k.split(","))): v for k, v in json.loads(row["defaults"]).items()}
        return {
            "grid_id": row["grid_id"],
            "rows": row["rows"],
            "cols": row["cols"],
            "timezone": row["timezone"],
            "defaults": defaults,
        }

    # ---- promotions ----

    def insert_promotion(
        self,
        grid_id: str,
        promotion_id: str,
        row: int,
        col: int,
        product_id: str,
        start_utc: int,
        end_utc: int,
    ) -> None:
        self._conn.execute(
            "INSERT INTO promotions"
            " (grid_id, promotion_id, row, col, product_id, start_utc, end_utc, status)"
            " VALUES (?,?,?,?,?,?,?, 'active')",
            (grid_id, promotion_id, row, col, product_id, start_utc, end_utc),
        )

    def get_promotion(self, grid_id: str, promotion_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM promotions WHERE grid_id = ? AND promotion_id = ?",
            (grid_id, promotion_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def update_promotion_times(
        self, grid_id: str, promotion_id: str, start_utc: int, end_utc: int
    ) -> None:
        self._conn.execute(
            "UPDATE promotions SET start_utc = ?, end_utc = ?"
            " WHERE grid_id = ? AND promotion_id = ?",
            (start_utc, end_utc, grid_id, promotion_id),
        )

    def cancel_promotion(self, grid_id: str, promotion_id: str) -> None:
        self._conn.execute(
            "UPDATE promotions SET status = 'cancelled'"
            " WHERE grid_id = ? AND promotion_id = ?",
            (grid_id, promotion_id),
        )

    def active_promotions(self, grid_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM promotions WHERE grid_id = ? AND status = 'active'",
            (grid_id,),
        ).fetchall()
        return [dict(r) for r in rows]
