import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import respx

from pipeline import candidates as cand
from pipeline.fetch import run as fetch_run
from pipeline.http import CachedClient
from pipeline.models import Deal, PriceInfo, Title
from pipeline.store import Store

FX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 11, 18, 0, tzinfo=UTC)


def title(fs_id="1", nsuid="70010000000001", rank=None, s2=False, name=None):
    return Title(
        fs_id=fs_id, title=name or f"Game {fs_id}", nsuids=(nsuid,), primary_nsuid=nsuid,
        is_switch2=s2, downloads_rank=rank,
    )  # fmt: skip


def price(nsuid, sale, regular=2000, end=NOW + timedelta(days=5)):
    return PriceInfo(nsuid, "GB", "onsale", "GBP", regular, sale, NOW - timedelta(days=2), end)


def deal(sale=500, regular=2000, hist_min=None, hist_days=0.0, end=None, **kw):
    return Deal(
        title=title(**kw), nsuid="7001", country="GB", fetched_at=NOW, regular_p=regular,
        sale_p=sale, sale_start=None, sale_end=end or NOW + timedelta(days=5),
        history_min_p=hist_min, history_days=hist_days,
    )  # fmt: skip


# --- ATL -----------------------------------------------------------------------------------


def test_atl_needs_long_history_to_be_confirmed():
    assert deal(sale=500, hist_min=500, hist_days=1).is_atl
    assert not deal(sale=500, hist_min=500, hist_days=1).atl_confirmed
    assert deal(sale=500, hist_min=500, hist_days=120).atl_confirmed
    assert not deal(sale=600, hist_min=500, hist_days=120).is_atl


def test_atl_ignores_index_cheapest_price():
    # index_cheapest_p is a *current* price; it must not make a deal an ATL on its own
    d = deal(sale=500, hist_min=None)
    assert not d.is_atl


# --- store ---------------------------------------------------------------------------------


def test_snapshots_are_idempotent_and_history_is_tracked(tmp_path):
    s = Store(tmp_path / "d.sqlite")
    s.upsert_titles([title()], NOW)
    assert s.insert_snapshots([(price("70010000000001", 900), NOW - timedelta(days=100))]) == 1
    rows = [(price("70010000000001", 700), NOW - timedelta(hours=1))]
    assert s.insert_snapshots(rows) == 1
    assert s.insert_snapshots(rows) == 0  # same fetched_at → ignored
    [d] = s.latest_deals("GB", NOW)
    assert (d.sale_p, d.history_min_p) == (700, 700)
    assert d.history_days > 99 and d.atl_confirmed


def test_latest_deals_drops_stale_and_ended(tmp_path):
    s = Store(tmp_path / "d.sqlite")
    s.upsert_titles([title("1", "70010000000001"), title("2", "70010000000002")], NOW)
    s.insert_snapshots(
        [
            (price("70010000000001", 700), NOW - timedelta(days=3)),  # stale snapshot
            (price("70010000000002", 700, end=NOW - timedelta(minutes=1)), NOW),  # ended
        ]
    )
    assert s.latest_deals("GB", NOW) == []


def test_latest_deals_uses_latest_snapshot_even_if_sale_over(tmp_path):
    s = Store(tmp_path / "d.sqlite")
    s.upsert_titles([title()], NOW)
    s.insert_snapshots([(price("70010000000001", 700), NOW - timedelta(hours=5))])
    off = PriceInfo("70010000000001", "GB", "onsale", "GBP", 2000, None, None, None)
    s.insert_snapshots([(off, NOW - timedelta(hours=1))])
    assert s.latest_deals("GB", NOW) == []


# --- candidates ----------------------------------------------------------------------------


def test_publish_date_default_is_friday_and_cutoff_is_london_midnight_plus_24h(tmp_path):
    assert cand.publish_date_for("2026-W46", tmp_path / "none.yaml") == date(2026, 11, 13)
    assert cand.cutoff_utc(date(2026, 11, 13)) == datetime(2026, 11, 14, 0, 0, tzinfo=UTC)
    # BST: London midnight is 23:00 UTC the previous day
    assert cand.cutoff_utc(date(2026, 7, 10)) == datetime(2026, 7, 10, 23, 0, tzinfo=UTC)


def test_publish_date_from_picks(tmp_path):
    p = tmp_path / "picks.yaml"
    p.write_text("publish_date: 2026-11-12\npicks: []\n")
    assert cand.publish_date_for("2026-W46", p) == date(2026, 11, 12)


def test_eligible_excludes_deals_ending_before_cutoff():
    cutoff = datetime(2026, 11, 14, tzinfo=UTC)
    keep = deal(end=datetime(2026, 11, 16, 23, 59, 59, tzinfo=UTC))
    drop = deal(end=datetime(2026, 11, 13, 23, 59, 59, tzinfo=UTC))
    assert cand.eligible([keep, drop], cutoff) == [keep]


def test_score_orders_by_discount_popularity_and_switch2():
    big_popular = deal(sale=200, fs_id="a", rank=10)
    big_obscure = deal(sale=200, fs_id="b", rank=None)
    small = deal(sale=1800, fs_id="c", rank=20)
    s2 = deal(sale=200, fs_id="d", rank=None, s2=True)
    order = [d.title.fs_id for _, d in cand.score([small, big_obscure, s2, big_popular], NOW)]
    assert order == ["a", "d", "b", "c"]


def test_candidates_run_writes_files_and_never_overwrites_picks(tmp_path):
    s = Store(tmp_path / "d.sqlite")
    s.upsert_titles([title(name="Keeper")], NOW)
    s.insert_snapshots([(price("70010000000001", 700), NOW - timedelta(hours=1))])
    out = cand.run("2026-W46", "GB", s, NOW, root=tmp_path)
    text = out.read_text()
    assert "Keeper" in text and "£20.00 → **£7.00**" in text
    picks = tmp_path / "episodes/2026-W46/picks.yaml"
    picks.write_text("publish_date: 2026-11-13\npicks: [mine]\n")
    cand.run("2026-W46", "GB", s, NOW, root=tmp_path)
    assert "mine" in picks.read_text()


# --- fetch (network mocked) ----------------------------------------------------------------


@respx.mock
def test_fetch_is_idempotent_and_second_run_makes_no_requests(tmp_path):
    solr = json.loads((FX / "solr_page.json").read_text())
    prices = json.loads((FX / "prices_gb.json").read_text())
    respx.get(url__startswith="https://searching.nintendo-europe.com/").mock(
        return_value=httpx.Response(200, json=solr)
    )
    respx.get(url__startswith="https://api.ec.nintendo.com/").mock(
        return_value=httpx.Response(200, json=prices)
    )
    store = Store(tmp_path / "d.sqlite")
    http = CachedClient(cache_dir=tmp_path / "cache", min_interval=0)
    first = fetch_run(http, store)
    assert first["titles"] == 5 and first["unpriceable"] == 1
    assert first["snapshots_inserted"] == first["prices"] > 0
    calls = http.network_calls
    second = fetch_run(http, store)
    assert http.network_calls == calls  # all served from cache
    assert second["snapshots_inserted"] == 0
    assert store.count("price_snapshots") == first["prices"]
