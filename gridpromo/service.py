"""排期服务：网格创建、促销新建/改期/取消、时刻展示查询。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .errors import (
    ConflictError,
    GridNotFoundError,
    InvalidCellError,
    InvalidTimeError,
    PromoNotFoundError,
)
from .timeutil import local_to_utc, parse_local

MAX_ACTIVE_PROMOS_PER_GRID = 20
_UTC = timezone.utc


@dataclass(frozen=True)
class CellView:
    """某一格位在某个时刻的展示结果。"""

    row: int
    col: int
    product: str | None
    is_promo: bool
    promo_id: int | None


class GridService:
    """网格促销位排期服务，供上层陈列服务调用。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _get_grid(self, grid_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT id, rows, cols, timezone FROM grids WHERE id = ?", (grid_id,)
        ).fetchone()
        if row is None:
            raise GridNotFoundError(f"网格不存在: {grid_id}")
        return row

    def _check_cell(self, grid: sqlite3.Row, row: int, col: int) -> None:
        if not (0 <= row < grid["rows"] and 0 <= col < grid["cols"]):
            raise InvalidCellError(f"格位越界: ({row}, {col})")

    @staticmethod
    def _resolve_times(tz: ZoneInfo, start_local: str, end_local: str) -> tuple[int, int]:
        try:
            start_naive = parse_local(start_local)
            end_naive = parse_local(end_local)
        except ValueError as exc:
            raise InvalidTimeError(f"时间格式非法: {exc}") from exc
        start_utc = local_to_utc(tz, start_naive, is_end=False)
        end_utc = local_to_utc(tz, end_naive, is_end=True)
        if not end_utc > start_utc:
            raise InvalidTimeError("结束时间必须晚于开始时间（按实际时间比较）")
        return int(start_utc.timestamp()), int(end_utc.timestamp())

    def _assert_no_conflict(
        self,
        grid_id: int,
        row: int,
        col: int,
        start_utc: int,
        end_utc: int,
        exclude_promo_id: int | None = None,
    ) -> None:
        sql = (
            "SELECT id, row, col, start_utc, end_utc FROM promos "
            "WHERE grid_id = ? AND active = 1 AND start_utc < ? AND end_utc > ?"
        )
        params: list[object] = [grid_id, end_utc, start_utc]
        if exclude_promo_id is not None:
            sql += " AND id != ?"
            params.append(exclude_promo_id)
        overlapping = self._conn.execute(sql, params).fetchall()
        for other in overlapping:
            if other["row"] == row and other["col"] == col:
                raise ConflictError(
                    f"格位 ({row}, {col}) 在该时段已有促销 {other['id']}"
                )
        events: list[tuple[int, int]] = [(start_utc, 1), (end_utc, -1)]
        for other in overlapping:
            events.append((other["start_utc"], 1))
            events.append((other["end_utc"], -1))
        events.sort(key=lambda event: (event[0], event[1]))
        running = 0
        for _, delta in events:
            running += delta
            if running > MAX_ACTIVE_PROMOS_PER_GRID:
                raise ConflictError(
                    f"同一网格同时生效的促销超过 {MAX_ACTIVE_PROMOS_PER_GRID} 个"
                )

    def create_grid(
        self,
        rows: int,
        cols: int,
        timezone: str,
        default_products: dict[tuple[int, int], str | None] | None = None,
    ) -> int:
        """创建网格，返回网格 id。时区为 IANA 名称，创建后不可改。"""
        if rows <= 0 or cols <= 0:
            raise InvalidCellError("行列数必须为正整数")
        try:
            ZoneInfo(timezone)
        except (KeyError, ValueError) as exc:
            raise InvalidTimeError(f"非法的 IANA 时区: {timezone}") from exc
        defaults = default_products or {}
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO grids (rows, cols, timezone) VALUES (?, ?, ?)",
                (rows, cols, timezone),
            )
            grid_id = int(cursor.lastrowid)
            self._conn.executemany(
                "INSERT INTO grid_cells (grid_id, row, col, default_product) "
                "VALUES (?, ?, ?, ?)",
                [
                    (grid_id, r, c, defaults.get((r, c)))
                    for r in range(rows)
                    for c in range(cols)
                ],
            )
        return grid_id

    def create_promo(
        self,
        grid_id: int,
        row: int,
        col: int,
        product: str,
        start_local: str,
        end_local: str,
    ) -> int:
        """新建促销，返回促销 id。越界则整单拒绝并抛 ConflictError。"""
        grid = self._get_grid(grid_id)
        self._check_cell(grid, row, col)
        tz = ZoneInfo(grid["timezone"])
        start_utc, end_utc = self._resolve_times(tz, start_local, end_local)
        with self._conn:
            self._assert_no_conflict(grid_id, row, col, start_utc, end_utc)
            cursor = self._conn.execute(
                "INSERT INTO promos (grid_id, row, col, product, start_utc, end_utc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (grid_id, row, col, product, start_utc, end_utc),
            )
        return int(cursor.lastrowid)

    def reschedule_promo(
        self,
        promo_id: int,
        start_local: str,
        end_local: str,
    ) -> None:
        """改期。被拒时抛 ConflictError，原排期保持不变。"""
        promo = self._conn.execute(
            "SELECT id, grid_id, row, col FROM promos WHERE id = ? AND active = 1",
            (promo_id,),
        ).fetchone()
        if promo is None:
            raise PromoNotFoundError(f"促销不存在或已取消: {promo_id}")
        grid = self._get_grid(promo["grid_id"])
        tz = ZoneInfo(grid["timezone"])
        start_utc, end_utc = self._resolve_times(tz, start_local, end_local)
        with self._conn:
            self._assert_no_conflict(
                promo["grid_id"],
                promo["row"],
                promo["col"],
                start_utc,
                end_utc,
                exclude_promo_id=promo_id,
            )
            self._conn.execute(
                "UPDATE promos SET start_utc = ?, end_utc = ? WHERE id = ?",
                (start_utc, end_utc, promo_id),
            )

    def cancel_promo(self, promo_id: int) -> None:
        """取消促销，名额立即释放。"""
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE promos SET active = 0 WHERE id = ? AND active = 1",
                (promo_id,),
            )
        if cursor.rowcount == 0:
            raise PromoNotFoundError(f"促销不存在或已取消: {promo_id}")

    def get_display(self, grid_id: int, at: datetime) -> list[list[CellView]]:
        """查询网格在某个实际时刻（aware datetime）的展示。"""
        if at.tzinfo is None:
            raise InvalidTimeError("at 必须是携带时区的实际时刻")
        grid = self._get_grid(grid_id)
        moment = int(at.astimezone(_UTC).timestamp())
        cells = self._conn.execute(
            "SELECT row, col, default_product FROM grid_cells WHERE grid_id = ?",
            (grid_id,),
        ).fetchall()
        promos = self._conn.execute(
            "SELECT id, row, col, product FROM promos "
            "WHERE grid_id = ? AND active = 1 AND start_utc <= ? AND end_utc > ?",
            (grid_id, moment, moment),
        ).fetchall()
        promo_by_cell = {(p["row"], p["col"]): p for p in promos}
        board: list[list[CellView]] = [
            [None] * grid["cols"] for _ in range(grid["rows"])  # type: ignore[list-item]
        ]
        for cell in cells:
            key = (cell["row"], cell["col"])
            promo = promo_by_cell.get(key)
            if promo is not None:
                view = CellView(
                    row=cell["row"],
                    col=cell["col"],
                    product=promo["product"],
                    is_promo=True,
                    promo_id=promo["id"],
                )
            else:
                view = CellView(
                    row=cell["row"],
                    col=cell["col"],
                    product=cell["default_product"],
                    is_promo=False,
                    promo_id=None,
                )
            board[cell["row"]][cell["col"]] = view
        return board
