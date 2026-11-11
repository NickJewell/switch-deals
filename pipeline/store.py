"""SQLite snapshots + history. Money in integer pence, datetimes as ISO-8601 UTC strings."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pipeline.models import Deal, PriceInfo, Title

DEFAULT_DB = Path("data/deals.sqlite")
SCHEMA_VERSION = 1
STALE_AFTER = timedelta(hours=48)  # a "latest" snapshot older than this isn't a live deal

SCHEMA = """
CREATE TABLE IF NOT EXISTS titles (
    fs_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    primary_nsuid TEXT,
    is_switch2 INTEGER NOT NULL,
    publisher TEXT, developer TEXT, categories TEXT, released TEXT,
    downloads_rank INTEGER,
    index_regular_p INTEGER, index_sale_p INTEGER, index_cheapest_p INTEGER,
    image_square TEXT, image_wide TEXT, url TEXT, excerpt TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS title_nsuids (
    fs_id TEXT NOT NULL, nsuid TEXT NOT NULL, PRIMARY KEY (fs_id, nsuid)
);
CREATE INDEX IF NOT EXISTS ix_title_nsuids_nsuid ON title_nsuids(nsuid);
CREATE TABLE IF NOT EXISTS price_snapshots (
    nsuid TEXT NOT NULL,
    country TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    currency TEXT,
    regular_p INTEGER, sale_p INTEGER,
    sale_start TEXT, sale_end TEXT,
    UNIQUE (nsuid, country, fetched_at)
);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class Store:
    def __init__(self, path: Path = DEFAULT_DB) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"DB schema v{version} is newer than code (v{SCHEMA_VERSION})")
        self.db.executescript(SCHEMA)
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def upsert_titles(self, titles: Iterable[Title], now: datetime) -> int:
        n = 0
        with self.db:
            for t in titles:
                self.db.execute(
                    """INSERT INTO titles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(fs_id) DO UPDATE SET
                      title=excluded.title, primary_nsuid=excluded.primary_nsuid,
                      is_switch2=excluded.is_switch2, publisher=excluded.publisher,
                      developer=excluded.developer, categories=excluded.categories,
                      released=excluded.released, downloads_rank=excluded.downloads_rank,
                      index_regular_p=excluded.index_regular_p,
                      index_sale_p=excluded.index_sale_p,
                      index_cheapest_p=excluded.index_cheapest_p,
                      image_square=excluded.image_square, image_wide=excluded.image_wide,
                      url=excluded.url, excerpt=excluded.excerpt, updated_at=excluded.updated_at""",
                    (
                        t.fs_id, t.title, t.primary_nsuid, int(t.is_switch2), t.publisher,
                        t.developer, json.dumps(list(t.categories)),
                        t.released.isoformat() if t.released else None, t.downloads_rank,
                        t.index_regular_p, t.index_sale_p, t.index_cheapest_p,
                        t.image_square, t.image_wide, t.url, t.excerpt, _iso(now),
                    ),
                )  # fmt: skip
                self.db.executemany(
                    "INSERT OR IGNORE INTO title_nsuids VALUES (?,?)",
                    [(t.fs_id, n_) for n_ in t.nsuids],
                )
                n += 1
        return n

    def insert_snapshots(self, rows: Iterable[tuple[PriceInfo, datetime]]) -> int:
        """INSERT OR IGNORE on (nsuid, country, fetched_at): replaying a cached response is a no-op."""
        before = self.db.total_changes
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO price_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        p.nsuid, p.country, _iso(fetched_at), p.status, p.currency,
                        p.regular_p, p.sale_p, _iso(p.sale_start), _iso(p.sale_end),
                    )
                    for p, fetched_at in rows
                ],
            )  # fmt: skip
        return self.db.total_changes - before

    def count(self, table: str) -> int:
        assert table in {"titles", "title_nsuids", "price_snapshots"}
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def _title(self, r: sqlite3.Row) -> Title:
        nsuids = tuple(
            x[0]
            for x in self.db.execute(
                "SELECT nsuid FROM title_nsuids WHERE fs_id=? ORDER BY nsuid", (r["fs_id"],)
            )
        )
        return Title(
            fs_id=r["fs_id"], title=r["title"], nsuids=nsuids, primary_nsuid=r["primary_nsuid"],
            is_switch2=bool(r["is_switch2"]), publisher=r["publisher"], developer=r["developer"],
            categories=tuple(json.loads(r["categories"] or "[]")),
            released=date.fromisoformat(r["released"]) if r["released"] else None,
            downloads_rank=r["downloads_rank"], index_regular_p=r["index_regular_p"],
            index_sale_p=r["index_sale_p"], index_cheapest_p=r["index_cheapest_p"],
            image_square=r["image_square"], image_wide=r["image_wide"], url=r["url"],
            excerpt=r["excerpt"],
        )  # fmt: skip

    def latest_deals(self, country: str, now: datetime) -> list[Deal]:
        """One Deal per title (primary nsuid), from its latest snapshot, if live and fresh."""
        rows = self.db.execute(
            """
            WITH latest AS (
              SELECT s.*, ROW_NUMBER() OVER (PARTITION BY nsuid ORDER BY fetched_at DESC) AS rn
              FROM price_snapshots s WHERE country = ?
            ), hist AS (
              SELECT nsuid, MIN(sale_p) AS min_p, MIN(fetched_at) AS first_at,
                     MAX(fetched_at) AS last_at
              FROM price_snapshots WHERE country = ? AND sale_p IS NOT NULL GROUP BY nsuid
            )
            SELECT t.*, l.fetched_at AS s_fetched_at, l.regular_p AS s_regular_p,
                   l.sale_p AS s_sale_p, l.sale_start AS s_sale_start, l.sale_end AS s_sale_end,
                   h.min_p, h.first_at, h.last_at
            FROM titles t
            JOIN latest l ON l.nsuid = t.primary_nsuid AND l.rn = 1
            LEFT JOIN hist h ON h.nsuid = t.primary_nsuid
            WHERE l.sale_p IS NOT NULL AND l.regular_p IS NOT NULL
            """,
            (country, country),
        ).fetchall()
        deals = []
        for r in rows:
            fetched_at = _dt(r["s_fetched_at"])
            sale_end = _dt(r["s_sale_end"])
            if now - fetched_at > STALE_AFTER or (sale_end is not None and sale_end <= now):
                continue
            span = (_dt(r["last_at"]) - _dt(r["first_at"])).total_seconds() / 86400
            deals.append(
                Deal(
                    title=self._title(r),
                    nsuid=r["primary_nsuid"],
                    country=country,
                    fetched_at=fetched_at,
                    regular_p=r["s_regular_p"],
                    sale_p=r["s_sale_p"],
                    sale_start=_dt(r["s_sale_start"]),
                    sale_end=sale_end,
                    history_min_p=r["min_p"],
                    history_days=span,
                )  # fmt: skip
            )
        return deals

    def close(self) -> None:
        self.db.close()
