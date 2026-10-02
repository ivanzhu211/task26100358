"""SQLite 持久化层：建表与连接管理。"""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS grids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    timezone TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grid_cells (
    grid_id INTEGER NOT NULL REFERENCES grids(id),
    row INTEGER NOT NULL,
    col INTEGER NOT NULL,
    default_product TEXT,
    PRIMARY KEY (grid_id, row, col)
);

CREATE TABLE IF NOT EXISTS promos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grid_id INTEGER NOT NULL REFERENCES grids(id),
    row INTEGER NOT NULL,
    col INTEGER NOT NULL,
    product TEXT NOT NULL,
    start_utc INTEGER NOT NULL,
    end_utc INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_promos_grid ON promos(grid_id, active);
"""


def connect(path: str) -> sqlite3.Connection:
    """打开（必要时创建）SQLite 数据库并初始化表结构。"""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
