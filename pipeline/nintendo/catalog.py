"""EU catalogue search (Solr) client. Discovery + metadata; prices here are hints only.

See docs/data-dictionary.md. Key facts:
- `/en/` index prices are GBP but a doc's price fields can come from *different* nsuids.
- `nsuid_txt` is a list: 7001… = base game, 7007… = bundle/edition, 7005… = add-on.
- Switch 2: `playable_on_txt` contains "BEE" (agrees 100% with system_names_txt).
- There is no `popularity` field; `downloads_rank_i` (lower = better, 999999 = unranked).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

from pipeline.http import CachedClient
from pipeline.models import Title, to_pence

BASE = "https://searching.nintendo-europe.com/en/select"
SITE = "https://www.nintendo.com"
PAGE_ROWS = 1000
TTL = 12 * 3600
UNRANKED = 999999


def primary_nsuid(nsuids: list[str]) -> str | None:
    """Prefer the base-game (7001…) id; fall back to the lowest id (e.g. bundle-only docs)."""
    if not nsuids:
        return None
    ordered = sorted(nsuids)
    base = [n for n in ordered if n.startswith("7001")]
    return (base or ordered)[0]


def _date(values: list[str] | None) -> date | None:
    if not values:
        return None
    try:
        return datetime.fromisoformat(values[0].replace("Z", "+00:00")).date()
    except ValueError:
        return None


def doc_to_title(doc: dict) -> Title:
    nsuids = sorted(set(doc.get("nsuid_txt") or []))
    rank = doc.get("downloads_rank_i")
    url = doc.get("url")
    return Title(
        fs_id=str(doc["fs_id"]),
        title=(doc.get("title") or "").strip(),
        nsuids=tuple(nsuids),
        primary_nsuid=primary_nsuid(nsuids),
        is_switch2="BEE" in (doc.get("playable_on_txt") or [])
        or "Nintendo Switch 2" in (doc.get("system_names_txt") or []),
        publisher=doc.get("publisher"),
        developer=doc.get("developer"),
        categories=tuple(doc.get("pretty_game_categories_txt") or ()),
        released=_date(doc.get("dates_released_dts")),
        downloads_rank=None if rank in (None, UNRANKED) else int(rank),
        index_regular_p=to_pence(doc.get("price_regular_f")),
        index_sale_p=to_pence(doc.get("price_discounted_f")),
        index_lowest_p=to_pence(doc.get("price_lowest_f")),
        image_square=doc.get("image_url_sq_s"),
        image_wide=doc.get("image_url_h16x9_s"),
        url=(SITE + url) if url and url.startswith("/") else url,
        excerpt=doc.get("excerpt"),
    )


class CatalogClient:
    def __init__(self, http: CachedClient) -> None:
        self.http = http
        self.last_fetched_at: datetime | None = None

    def search(
        self, fq: list[str], start: int = 0, rows: int = PAGE_ROWS, ttl: float = TTL
    ) -> dict:
        params = [("q", "*"), ("fq", "type:GAME")] + [("fq", f) for f in fq]
        params += [
            ("sort", "fs_id asc"),
            ("rows", str(rows)),
            ("start", str(start)),
            ("wt", "json"),
        ]
        resp = self.http.get_json(self.http.build_url(BASE, params), ttl=ttl)
        if self.last_fetched_at is None or resp.fetched_at > self.last_fetched_at:
            self.last_fetched_at = resp.fetched_at
        return resp.data["response"]

    def iter_docs(self, fq: list[str], ttl: float = TTL) -> Iterator[dict]:
        """All docs for a filter, paged on a stable sort; asserts nothing was skipped/duplicated."""
        seen: set[str] = set()
        start, total = 0, None
        while total is None or start < total:
            page = self.search(fq, start=start, ttl=ttl)
            total = page["numFound"]
            if not page["docs"]:
                break
            for doc in page["docs"]:
                if doc["fs_id"] not in seen:
                    seen.add(doc["fs_id"])
                    yield doc
            start += len(page["docs"])
        if len(seen) != total:
            raise RuntimeError(f"Solr paging drift: got {len(seen)} unique docs, numFound={total}")

    def iter_on_sale(self, ttl: float = TTL) -> Iterator[Title]:
        for doc in self.iter_docs(["price_has_discount_b:true"], ttl=ttl):
            yield doc_to_title(doc)
