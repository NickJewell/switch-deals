"""Coverage history: which games earlier (or later) episodes already covered.

Source of truth is every `episodes/<week>/picks.yaml` pick with `approved: true` (any layout,
including `skip`, since that's still airtime). Repeats are matched per *game* (catalogue
fs_id), so a bundle/edition nsuid of an already-covered game still counts.

`make check-picks WEEK=…` fails if this week's picks repeat a game covered within
WINDOW_DAYS of this episode's publish date, or list the same game twice.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from pipeline.store import DEFAULT_DB, Store

WINDOW_DAYS = 120  # ~4 months
WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


@dataclass(frozen=True)
class Covered:
    week: str
    publish_date: date
    nsuid: str
    game: str  # fs_id when known, else "nsuid:<id>"

    def label(self) -> str:
        return f"{self.week} ({self.publish_date:%d %b})"


def episode_publish_date(week: str, data: dict) -> date:
    d = data.get("publish_date")
    if d:
        return d if isinstance(d, date) else date.fromisoformat(str(d))
    year, wk = week.split("-W")
    return date.fromisocalendar(int(year), int(wk), 5)


def load_picks(path: Path) -> tuple[dict, list[dict]]:
    data = yaml.safe_load(path.read_text()) or {}
    picks = [p for p in data.get("picks") or [] if isinstance(p, dict) and p.get("nsuid")]
    return data, picks


def game_key(store: Store, nsuid: str) -> str:
    return store.fs_id_for_nsuid(str(nsuid)) or f"nsuid:{nsuid}"


def coverage(root: Path, store: Store, week: str, publish: date) -> dict[str, Covered]:
    """Games covered by *other* episodes published within WINDOW_DAYS of `publish`."""
    out: dict[str, Covered] = {}
    for path in sorted((root / "episodes").glob("*/picks.yaml")):
        other = path.parent.name
        if other == week or not WEEK_RE.match(other):
            continue
        data, picks = load_picks(path)
        when = episode_publish_date(other, data)
        if abs((publish - when).days) >= WINDOW_DAYS:
            continue
        for p in picks:
            if p.get("approved") is True:
                c = Covered(other, when, str(p["nsuid"]), game_key(store, p["nsuid"]))
                prev = out.get(c.game)
                if prev is None or c.publish_date > prev.publish_date:
                    out[c.game] = c  # keep the most recent coverage
    return out


def check_picks(root: Path, store: Store, week: str) -> list[str]:
    path = root / "episodes" / week / "picks.yaml"
    if not path.exists():
        return [f"{path} not found"]
    data, picks = load_picks(path)
    publish = episode_publish_date(week, data)
    covered = coverage(root, store, week, publish)
    problems, seen = [], {}
    for p in picks:
        nsuid = str(p["nsuid"])
        key = game_key(store, nsuid)
        name = store.title_name(key) or nsuid
        if key in seen:
            problems.append(f"{name}: listed twice (nsuids {seen[key]} and {nsuid})")
        seen[key] = nsuid
        if key in covered:
            c = covered[key]
            gap = abs((publish - c.publish_date).days)
            problems.append(
                f"{name}: already covered in {c.label()}, {gap} days from this episode "
                f"(window {WINDOW_DAYS})"
            )
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week", required=True)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    store = Store(args.db)
    try:
        problems = check_picks(Path("."), store, args.week)
    finally:
        store.close()
    if problems:
        print(f"check-picks {args.week}: {len(problems)} problem(s)")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)
    print(f"check-picks {args.week}: no repeats within {WINDOW_DAYS} days ✓")


if __name__ == "__main__":
    main()
