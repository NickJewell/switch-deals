"""Pick a varied running order of ~8 deals for a ~10-minute episode from the scored candidates.

Greedy, in score order, with variety rules:
  1. quotas first — big names, a Switch 2 title, impulse buys — each filled by its best scorer;
  2. then the best remaining scores;
  always subject to: download rank <= MAX_RANK, one title per publisher, one per series,
  max two per genre bucket.
If the rules leave slots empty, the genre cap and then the publisher cap are relaxed.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from pipeline.models import Deal

SIZE = 8
SPOTLIGHTS = 2
POOL = 60  # only consider the top-N scored candidates
MAX_PER_GENRE = 2
MAX_PER_PUBLISHER = 1
MAX_RANK = 3000  # unranked / deep-rank titles are mostly inflated-RRP shovelware; swap in by hand
QUOTAS = [  # (label, how many, predicate) — filled in this order
    ("big name", 2, lambda d: d.title.downloads_rank is not None and d.title.downloads_rank <= 300),
    ("Switch 2", 1, lambda d: d.title.is_switch2),
    ("under £5", 2, lambda d: d.sale_p <= 500),
]
GENERIC_GENRES = {"Action", "Adventure", "Arcade", "Other"}  # tagged on nearly everything

# ~145 spoken words/min. 2×265 + 6×120 + intro 110 + outro 75 ≈ 1,435 words ≈ 9.9 min.
WORDS = {"intro": 110, "spotlight": 265, "rapid_fire": 120, "outro": 75}
WPM = 145


def publisher_key(d: Deal) -> str:
    """'SQUARE ENIX' and 'Square Enix Europe Ltd' → 'square'."""
    words = re.findall(r"[a-z0-9]+", (d.title.publisher or "").lower())
    return words[0] if words else f"?{d.title.fs_id}"


def series_key(d: Deal) -> str:
    """'FINAL FANTASY VII REBIRTH' and 'FINAL FANTASY X/X-2' → 'final fantasy'."""
    base = re.split(r"[:–\-(]", d.title.title)[0]
    words = re.findall(r"[a-z0-9']+", base.lower())
    return " ".join(words[:2]) or d.title.fs_id


def genre_buckets(pool: list[Deal]) -> dict[str, str]:
    """Each title's bucket = its most common specific genre in the pool (else first generic)."""
    freq = Counter(g for d in pool for g in d.title.categories if g not in GENERIC_GENRES)

    def bucket(d: Deal) -> str:
        specific = [g for g in d.title.categories if g not in GENERIC_GENRES]
        if specific:
            return max(specific, key=lambda g: (freq[g], g))
        return d.title.categories[0] if d.title.categories else "Other"

    return {d.nsuid: bucket(d) for d in pool}


@dataclass
class Slot:
    deal: Deal
    score: float
    genre: str
    reason: str
    layout: str = "rapid_fire"


@dataclass
class Shortlist:
    slots: list[Slot]  # in running order
    alternates: list[tuple[Slot, str]]  # (slot, why it was left out)
    relaxed: list[str]

    @property
    def minutes(self) -> float:
        words = WORDS["intro"] + WORDS["outro"] + sum(WORDS[s.layout] for s in self.slots)
        return words / WPM


def build(ranked: list[tuple[float, Deal]], size: int = SIZE) -> Shortlist:
    pool = [(s, d) for s, d in ranked[:POOL]]
    genre = genre_buckets([d for _, d in pool])
    chosen: list[Slot] = []
    relaxed: list[str] = []
    caps = {"genre": MAX_PER_GENRE, "publisher": MAX_PER_PUBLISHER}

    def blocker(d: Deal) -> str | None:
        if any(c.deal.nsuid == d.nsuid for c in chosen):
            return "already in"
        rank = d.title.downloads_rank
        if rank is None or rank > MAX_RANK:
            return f"obscure ({'unranked' if rank is None else f'rank {rank}'})"
        if any(series_key(c.deal) == series_key(d) for c in chosen):
            return f"same series as {next(c.deal.title.title for c in chosen if series_key(c.deal) == series_key(d))}"
        if sum(publisher_key(c.deal) == publisher_key(d) for c in chosen) >= caps["publisher"]:
            return f"publisher cap ({d.title.publisher})"
        if sum(c.genre == genre[d.nsuid] for c in chosen) >= caps["genre"]:
            return f"genre cap ({genre[d.nsuid]})"
        return None

    def take(pred, reason: str) -> bool:
        for s, d in pool:
            if pred(d) and blocker(d) is None:
                chosen.append(Slot(d, s, genre[d.nsuid], reason))
                return True
        return False

    for label, n, pred in QUOTAS:
        while sum(pred(c.deal) for c in chosen) < n and len(chosen) < size and take(pred, label):
            pass
    for cap in (None, "genre", "publisher"):
        if cap:
            if len(chosen) >= size:
                break
            caps[cap] = 99
            relaxed.append(cap)
        while len(chosen) < size and take(lambda d: True, "top score"):
            pass

    # spotlights = the two most popular picks; running order: spotlight, 2 rapid, spotlight, rest
    by_pop = sorted(chosen, key=lambda c: c.deal.title.downloads_rank or 10**9)
    spots = by_pop[:SPOTLIGHTS]
    for c in spots:
        c.layout = "spotlight"
    rest = sorted((c for c in chosen if c not in spots), key=lambda c: -c.score)
    order = spots[:1] + rest[:2] + spots[1:] + rest[2:]

    alternates = []
    for s, d in pool:
        if any(c.deal.nsuid == d.nsuid for c in chosen):
            continue
        alternates.append((Slot(d, s, genre[d.nsuid], ""), blocker(d) or "outscored"))
        if len(alternates) == 6:
            break
    return Shortlist(order, alternates, relaxed)
