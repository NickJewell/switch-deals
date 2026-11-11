"""Price API client: exact local prices and sale windows. Source of truth for on-screen prices."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

from pipeline.http import CachedClient
from pipeline.models import PriceInfo, to_pence

BASE = "https://api.ec.nintendo.com/v1/price"
BATCH = 50
TTL = 3600


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def parse_price(entry: dict, country: str) -> PriceInfo:
    regular = entry.get("regular_price") or {}
    discount = entry.get("discount_price") or {}
    return PriceInfo(
        nsuid=str(entry["title_id"]),
        country=country,
        status=entry.get("sales_status", "unknown"),
        currency=regular.get("currency"),
        regular_p=to_pence(regular.get("raw_value")),
        sale_p=to_pence(discount.get("raw_value")),
        sale_start=_dt(discount.get("start_datetime")),
        sale_end=_dt(discount.get("end_datetime")),
    )


def batches(nsuids: Iterable[str], size: int = BATCH) -> list[list[str]]:
    """Deduped, sorted, chunked — so cache keys are deterministic across runs."""
    ids = sorted(set(nsuids))
    return [ids[i : i + size] for i in range(0, len(ids), size)]


class PriceClient:
    def __init__(self, http: CachedClient) -> None:
        self.http = http

    def get(
        self, nsuids: Iterable[str], country: str = "GB", ttl: float = TTL
    ) -> Iterator[tuple[PriceInfo, datetime]]:
        for chunk in batches(nsuids):
            params = [("country", country), ("lang", "en"), ("ids", ",".join(chunk))]
            resp = self.http.get_json(self.http.build_url(BASE, params), ttl=ttl)
            for entry in resp.data.get("prices", []):
                yield parse_price(entry, country), resp.fetched_at
