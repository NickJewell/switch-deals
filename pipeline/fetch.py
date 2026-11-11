"""`make fetch`: catalogue sweep (on-sale) → titles; price API (all nsuids, batches of 50) → snapshots.

Idempotent: within the cache TTLs a re-run makes no HTTP requests and inserts no rows.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from pipeline.http import CachedClient
from pipeline.nintendo.catalog import CatalogClient
from pipeline.nintendo.prices import PriceClient
from pipeline.store import DEFAULT_DB, Store


def run(http: CachedClient, store: Store, country: str = "GB", force: bool = False) -> dict:
    t0 = time.monotonic()
    cat = CatalogClient(http)
    titles = list(cat.iter_on_sale(ttl=0 if force else 12 * 3600))
    n_titles = store.upsert_titles(titles, now=datetime.now(UTC))
    nsuids = {n for t in titles for n in t.nsuids}
    rows = list(PriceClient(http).get(nsuids, country, ttl=0 if force else 3600))
    inserted = store.insert_snapshots(rows)
    return {
        "titles": n_titles,
        "unpriceable": sum(1 for t in titles if not t.nsuids),
        "nsuids": len(nsuids),
        "prices": len(rows),
        "on_sale_in_api": sum(1 for p, _ in rows if p.on_sale),
        "snapshots_inserted": inserted,
        "network_calls": http.network_calls,
        "elapsed_s": round(time.monotonic() - t0, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--country", default="GB")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--force", action="store_true", help="ignore the cache")
    args = ap.parse_args()
    http, store = CachedClient(), Store(args.db)
    try:
        stats = run(http, store, args.country, args.force)
    finally:
        http.close()
        store.close()
    print("  ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
