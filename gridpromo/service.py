"""业务逻辑层：网格与促销排期。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import (
    ConflictError,
    GridNotFoundError,
    GridPromoError,
    InvalidTimeError,
    PromotionNotFoundError,
)
from .store import Store
from .timeparse import parse_local

MAX_ACTIVE_PROMOTIONS = 20


class GridPromoService:
    """供上层陈列服务调用的排期库入口。"""

    def __init__(self, db_path: str) -> None:
        self._store = Store(db_path)

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "GridPromoService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- 网格 ----

    def create_grid(
        self,
        grid_id: str,
        rows: int,
        cols: int,
        timezone: str,
        default_products: Optional[dict[tuple[int, int], str]] = None,
    ) -> None:
        if rows <= 0 or cols <= 0:
            raise GridPromoError("行列数必须为正整数")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise GridPromoError(f"未知时区: {timezone!r}") from exc
        defaults = dict(default_products or {})
        for (r, c) in defaults:
            self._check_cell(rows, cols, r, c)
        try:
            self._store.create_grid(grid_id, rows, cols, timezone, defaults)
        except sqlite3.IntegrityError as exc:
            raise GridPromoError(f"网格已存在: {grid_id!r}") from exc

    # ---- 促销 ----

    def schedule(
        self,
        grid_id: str,
        promotion_id: str,
        row: int,
        col: int,
        product_id: str,
        start_local: str,
        end_local: str,
    ) -> None:
        grid = self._require_grid(grid_id)
        self._check_cell(grid["rows"], grid["cols"], row, col)
        start_utc, end_utc = self._parse_window(grid, start_local, end_local)
        with self._store.transaction():
            if self._store.get_promotion(grid_id, promotion_id) is not None:
                raise GridPromoError(f"促销已存在: {promotion_id!r}")
            existing = self._store.active_promotions(grid_id)
            candidate = {"row": row, "col": col, "start_utc": start_utc, "end_utc": end_utc}
            self._check_conflicts(existing, candidate)
            self._store.insert_promotion(
                grid_id, promotion_id, row, col, product_id, start_utc, end_utc
            )

    def reschedule(
        self,
        grid_id: str,
        promotion_id: str,
        start_local: str,
        end_local: str,
    ) -> None:
        grid = self._require_grid(grid_id)
        start_utc, end_utc = self._parse_window(grid, start_local, end_local)
        with self._store.transaction():
            promo = self._store.get_promotion(grid_id, promotion_id)
            if promo is None or promo["status"] != "active":
                raise PromotionNotFoundError(f"促销不存在或已取消: {promotion_id!r}")
            existing = [
                p for p in self._store.active_promotions(grid_id)
                if p["promotion_id"] != promotion_id
            ]
            candidate = {
                "row": promo["row"], "col": promo["col"],
                "start_utc": start_utc, "end_utc": end_utc,
            }
            self._check_conflicts(existing, candidate)  # 拒绝则回滚，原排期不变
            self._store.update_promotion_times(grid_id, promotion_id, start_utc, end_utc)

    def cancel(self, grid_id: str, promotion_id: str) -> None:
        self._require_grid(grid_id)
        with self._store.transaction():
            promo = self._store.get_promotion(grid_id, promotion_id)
            if promo is None or promo["status"] != "active":
                raise PromotionNotFoundError(f"促销不存在或已取消: {promotion_id!r}")
            self._store.cancel_promotion(grid_id, promotion_id)

    # ---- 查询 ----

    def display_at(self, grid_id: str, when: datetime) -> list[list[Optional[str]]]:
        """网格在实际时刻 `when` 的展示：促销格位显示促销商品，其余显示默认商品。"""
        grid = self._require_grid(grid_id)
        if when.tzinfo is None:
            raise InvalidTimeError("when 必须是带时区的实际时刻")
        t = int(when.astimezone(timezone.utc).timestamp())
        board: list[list[Optional[str]]] = [
            [grid["defaults"].get((r, c)) for c in range(grid["cols"])]
            for r in range(grid["rows"])
        ]
        for p in self._store.active_promotions(grid_id):
            if p["start_utc"] <= t < p["end_utc"]:
                board[p["row"]][p["col"]] = p["product_id"]
        return board

    # ---- 内部 ----

    def _require_grid(self, grid_id: str) -> dict:
        grid = self._store.get_grid(grid_id)
        if grid is None:
            raise GridNotFoundError(f"网格不存在: {grid_id!r}")
        return grid

    @staticmethod
    def _check_cell(rows: int, cols: int, row: int, col: int) -> None:
        if not (0 <= row < rows and 0 <= col < cols):
            raise GridPromoError(f"格位越界: ({row}, {col})，网格 {rows}x{cols}")

    @staticmethod
    def _parse_window(grid: dict, start_local: str, end_local: str) -> tuple[int, int]:
        tz = ZoneInfo(grid["timezone"])
        start = parse_local(start_local, tz, is_end=False)
        end = parse_local(end_local, tz, is_end=True)
        start_utc = int(start.astimezone(timezone.utc).timestamp())
        end_utc = int(end.astimezone(timezone.utc).timestamp())
        if end_utc <= start_utc:
            raise InvalidTimeError(
                f"结束必须晚于开始（按实际时间比较）: {start_local!r} ~ {end_local!r}"
            )
        return start_utc, end_utc

    @staticmethod
    def _check_conflicts(existing: list[dict], candidate: dict) -> None:
        # 格位独占：半开区间两两不重叠即可
        for p in existing:
            if (
                p["row"] == candidate["row"]
                and p["col"] == candidate["col"]
                and p["start_utc"] < candidate["end_utc"]
                and candidate["start_utc"] < p["end_utc"]
            ):
                raise ConflictError(
                    f"格位 ({candidate['row']}, {candidate['col']}) 在该时段已有促销"
                )
        # 容量：扫描线求加入候选后的最大同时生效数
        events: list[tuple[int, int]] = []
        for p in existing:
            events.append((p["start_utc"], 1))
            events.append((p["end_utc"], -1))
        events.append((candidate["start_utc"], 1))
        events.append((candidate["end_utc"], -1))
        # 半开区间：同一时刻先处理结束(-1)再处理开始(+1)，首尾相接不算重叠
        events.sort(key=lambda e: (e[0], e[1]))
        count = 0
        for _, delta in events:
            count += delta
            if count > MAX_ACTIVE_PROMOTIONS:
                raise ConflictError(
                    f"同一网格同时生效的促销超过 {MAX_ACTIVE_PROMOTIONS} 个"
                )
