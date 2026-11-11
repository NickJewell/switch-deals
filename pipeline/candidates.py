"""`make candidates WEEK=…`: rank live deals → episodes/<WEEK>/candidates.md."""

from __future__ import annotations

import argparse
import math
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from pipeline import history, shortlist
from pipeline.models import ATL_CONFIRM_DAYS, Deal, fmt_gbp
from pipeline.store import DEFAULT_DB, Store

LONDON = ZoneInfo("Europe/London")
TOP_N = 40
RANK_FLOOR = 3000  # downloads_rank at/after which popularity counts for nothing
WEIGHTS = {
    "discount": 0.40,  # pct_off / 100
    "popularity": 0.30,  # 1 - rank percentile among ranked deals; unranked = 0
    "atl": 0.15,  # all-time low, only when confirmed by >= ATL_CONFIRM_DAYS of our history
    "switch2": 0.10,
    "ending_soon": 0.05,  # ends within 7 days of now
}


def week_folder(week: str) -> Path:
    return Path("episodes") / week


def publish_date_for(week: str, picks_path: Path) -> date:
    if picks_path.exists():
        data = yaml.safe_load(picks_path.read_text()) or {}
        if data.get("publish_date"):
            d = data["publish_date"]
            return d if isinstance(d, date) else date.fromisoformat(str(d))
    year, wk = week.split("-W")
    return date.fromisocalendar(int(year), int(wk), 5)  # Friday


def cutoff_utc(publish: date) -> datetime:
    """Deals must still be live 24h after publish_date 00:00 Europe/London."""
    return (datetime.combine(publish, time(0), LONDON) + timedelta(hours=24)).astimezone(UTC)


def eligible(deals: list[Deal], cutoff: datetime) -> list[Deal]:
    return [d for d in deals if d.sale_end is not None and d.sale_end >= cutoff]


def score(deals: list[Deal], now: datetime) -> list[tuple[float, Deal]]:
    def pop(d: Deal) -> float:
        """Log-scaled download rank: #1 → 1.0, #40 → ~0.54, #RANK_FLOOR+ / unranked → 0."""
        r = d.title.downloads_rank
        return 0.0 if r is None else max(0.0, 1 - math.log(max(r, 1)) / math.log(RANK_FLOOR))

    out = []
    for d in deals:
        left = d.days_left(now)
        s = (
            WEIGHTS["discount"] * d.pct_off / 100
            + WEIGHTS["popularity"] * pop(d)
            + WEIGHTS["atl"] * d.atl_confirmed
            + WEIGHTS["switch2"] * d.title.is_switch2
            + WEIGHTS["ending_soon"] * (left is not None and left <= 7)
        )
        out.append((round(s, 3), d))
    out.sort(key=lambda sd: (-sd[0], sd[1].title.title))
    return out


def _ends(dt: datetime | None) -> str:
    return dt.astimezone(LONDON).strftime("%a %d %b %H:%M") if dt else "—"


def render(
    week: str,
    publish: date,
    cutoff: datetime,
    ranked,
    total_live: int,
    now,
    covered: dict[str, str] | None = None,
) -> str:
    covered = covered or {}
    lines = [
        f"# Candidates — {week}",
        "",
        f"_Generated {now.astimezone(LONDON):%Y-%m-%d %H:%M} London. Prices from the GB price API "
        f"(latest snapshot). Publish {publish:%a %d %b %Y}; deals ending before "
        f"{_ends(cutoff)} London are excluded ({total_live - len(ranked)} of {total_live} live "
        f"deals dropped)._",
        "",
        f"Weights: {', '.join(f'{k} {v}' for k, v in WEIGHTS.items())}. "
        f"ATL `✓` = lowest price in our own history, once that covers ≥ {ATL_CONFIRM_DAYS} days "
        "(Nintendo exposes no lowest-ever price, so ATL stays blank until then). "
        f"Popularity = log-scaled `downloads_rank` (#1 → 1, #{RANK_FLOOR}+ or unranked → 0). "
        f"`↺` = covered by another episode within {history.WINDOW_DAYS} days "
        f"({len(covered)} games) — never shortlisted.",
        "",
        "| # | title | price | % | ends (London) | ATL | S2 | rank | score | nsuid |",
        "|---:|---|---|---:|---|:-:|:-:|---:|---:|---|",
    ]
    for i, (s, d) in enumerate(ranked[:TOP_N], 1):
        atl = "✓" if d.atl_confirmed else ""
        title = f"[{d.title.title}]({d.title.url})" if d.title.url else d.title.title
        if d.title.fs_id in covered:
            title = f"↺ {covered[d.title.fs_id]} · ~~{title}~~"
        lines.append(
            f"| {i} | {title} | {fmt_gbp(d.regular_p)} → **{fmt_gbp(d.sale_p)}** | {d.pct_off}% | "
            f"{_ends(d.sale_end)} | {atl} | {'✓' if d.title.is_switch2 else ''} | "
            f"{d.title.downloads_rank or ''} | {s:.3f} | `{d.nsuid}` |"
        )
    lines += ["", "## picks.yaml snippets (any candidate)", "", "```yaml"]
    for _, d in ranked[:TOP_N]:
        lines += _snippet(d, "rapid_fire")
    lines += ["```", ""]
    table = next(i for i, line in enumerate(lines) if line.startswith("| # |"))
    return "\n".join(lines[:table] + _shortlist_section(ranked, covered) + lines[table:])


def _snippet(d: Deal, layout: str) -> list[str]:
    return [
        f'  - nsuid: "{d.nsuid}"  # {d.title.title} — {fmt_gbp(d.sale_p)}, ends {_ends(d.sale_end)}',
        f"    layout: {layout}"
        + " " * (17 - len(layout))
        + "# spotlight | versus | rapid_fire | skip",
        '    take: ""',
        "    approved: false",
    ]


def _shortlist_section(ranked: list[tuple[float, Deal]], covered: dict[str, str]) -> list[str]:
    sl = shortlist.build(ranked, covered=covered)
    lines = [
        f"## Suggested running order — {len(sl.slots)} picks, ≈{sl.minutes:.1f} min of narration",
        "",
        f"_Rules: top {shortlist.POOL} by score; quotas first ("
        + ", ".join(f"{n}× {label}" for label, n, _ in shortlist.QUOTAS)
        + f"), then best score; download rank ≤ {shortlist.MAX_RANK}; max {shortlist.MAX_PER_PUBLISHER} per publisher, 1 per series, "
        f"{shortlist.MAX_PER_GENRE} per genre. Spotlights = the two most popular picks._"
        + (f" **Relaxed: {', '.join(sl.relaxed)} cap.**" if sl.relaxed else ""),
        "",
        "| # | layout | title | price | % | genre | rank | why | words |",
        "|---:|---|---|---|---:|---|---:|---|---:|",
    ]
    for i, s in enumerate(sl.slots, 1):
        d = s.deal
        lines.append(
            f"| {i} | {s.layout} | {d.title.title} | {fmt_gbp(d.regular_p)} → "
            f"**{fmt_gbp(d.sale_p)}** | {d.pct_off}% | {s.genre} | {d.title.downloads_rank or ''} | "
            f"{s.reason} | ~{shortlist.WORDS[s.layout]} |"
        )
    lines += [
        "",
        "**Swaps** (next best, and what kept them out):",
        "",
        *[
            f"- {s.deal.title.title} — {fmt_gbp(s.deal.sale_p)}, {s.deal.pct_off}% · {s.genre} · {why}"
            for s, why in sl.alternates
        ],
        "",
        "Paste into `picks.yaml`, write each `take`, then set `approved: true`:",
        "",
        "```yaml",
        "picks:",
    ]
    for s in sl.slots:
        lines += _snippet(s.deal, s.layout)
    return lines + ["```", "", "## All candidates", ""]


def picks_template(publish: date) -> str:
    return (
        f"publish_date: {publish.isoformat()}\n"
        "picks: []  # paste 5–8 snippets from candidates.md, write a take, set approved: true\n"
    )


def run(week: str, country: str, store: Store, now: datetime, root: Path = Path(".")) -> Path:
    folder = root / week_folder(week)
    folder.mkdir(parents=True, exist_ok=True)
    picks = folder / "picks.yaml"
    publish = publish_date_for(week, picks)
    cutoff = cutoff_utc(publish)
    live = store.latest_deals(country, now)
    ranked = score(eligible(live, cutoff), now)
    covered = {k: c.label() for k, c in history.coverage(root, store, week, publish).items()}
    out = folder / "candidates.md"
    out.write_text(render(week, publish, cutoff, ranked, len(live), now, covered))
    if not picks.exists():
        picks.write_text(picks_template(publish))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week", required=True, help="ISO week, e.g. 2026-W46")
    ap.add_argument("--country", default="GB")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    store = Store(args.db)
    try:
        out = run(args.week, args.country, store, datetime.now(UTC))
    finally:
        store.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
