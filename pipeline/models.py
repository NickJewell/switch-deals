"""Source-agnostic dataclasses. Nothing here knows a Nintendo field name."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

ATL_CONFIRM_DAYS = 90


def to_pence(value: str | float | int | None) -> int | None:
    """'7.2' -> 720, 64.99 -> 6499. Floats go via str() so 9.74 never becomes 973."""
    if value is None or value == "":
        return None
    d = Decimal(str(value)) * 100
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def fmt_gbp(pence: int | None) -> str:
    return "—" if pence is None else f"£{pence // 100}.{pence % 100:02d}"


@dataclass(frozen=True)
class Title:
    fs_id: str
    title: str
    nsuids: tuple[str, ...]
    primary_nsuid: str | None
    is_switch2: bool
    publisher: str | None = None
    developer: str | None = None
    categories: tuple[str, ...] = ()
    released: date | None = None
    downloads_rank: int | None = None  # lower = more popular; None = unranked
    index_regular_p: int | None = None  # Solr hints only: may mix nsuids
    index_sale_p: int | None = None
    index_cheapest_p: int | None = None  # cheapest CURRENT price across nsuids — not an ATL
    image_square: str | None = None
    image_wide: str | None = None
    url: str | None = None
    excerpt: str | None = None


@dataclass(frozen=True)
class PriceInfo:
    nsuid: str
    country: str
    status: str  # e.g. onsale, not_found, unreleased
    currency: str | None
    regular_p: int | None
    sale_p: int | None
    sale_start: datetime | None
    sale_end: datetime | None

    @property
    def on_sale(self) -> bool:
        return self.sale_p is not None and self.regular_p is not None


@dataclass(frozen=True)
class Deal:
    title: Title
    nsuid: str
    country: str
    fetched_at: datetime
    regular_p: int
    sale_p: int
    sale_start: datetime | None
    sale_end: datetime | None
    history_min_p: int | None  # lowest sale price we have ever recorded for this nsuid
    history_days: float  # span of our own snapshot history

    @property
    def pct_off(self) -> int:
        return round(100 * (self.regular_p - self.sale_p) / self.regular_p) if self.regular_p else 0

    @property
    def is_atl(self) -> bool:
        """Sale price <= the lowest sale price in our own history.

        Nintendo exposes no lowest-ever field (`price_lowest_f` is the cheapest *current*
        price across a doc's nsuids), so our snapshot history is the only ATL source.
        """
        return self.history_min_p is not None and self.sale_p <= self.history_min_p

    @property
    def atl_confirmed(self) -> bool:
        """ATL backed by enough history to have seen previous sales (eShop sales recur ~quarterly)."""
        return self.is_atl and self.history_days >= ATL_CONFIRM_DAYS

    def days_left(self, now: datetime) -> float | None:
        if self.sale_end is None:
            return None
        return (self.sale_end - now).total_seconds() / 86400
