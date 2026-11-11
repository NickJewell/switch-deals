import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.models import fmt_gbp, to_pence
from pipeline.nintendo.catalog import doc_to_title, primary_nsuid
from pipeline.nintendo.prices import batches, parse_price

FX = Path(__file__).parent / "fixtures"
DOCS = json.loads((FX / "solr_page.json").read_text())["response"]["docs"]
PRICES = json.loads((FX / "prices_gb.json").read_text())["prices"]


def by_title(prefix):
    return next(d for d in DOCS if d["title"].startswith(prefix))


def test_to_pence_is_exact():
    assert to_pence("7.2") == 720
    assert to_pence("7.49") == 749
    assert to_pence(9.74) == 974  # float 9.74 must not become 973
    assert to_pence(64.99) == 6499
    assert to_pence(None) is None
    assert fmt_gbp(749) == "£7.49" and fmt_gbp(720) == "£7.20"


def test_multi_nsuid_doc_prefers_base_game():
    t = doc_to_title(by_title("FINAL FANTASY VII REBIRTH"))
    assert t.nsuids == ("70010000112478", "70070000032076")
    assert t.primary_nsuid == "70010000112478"
    assert t.is_switch2
    assert t.index_lowest_p == 749
    assert t.url.startswith("https://www.nintendo.com/en-gb/")


def test_doc_without_nsuid():
    t = doc_to_title(by_title("Cannon Fodder"))
    assert t.nsuids == () and t.primary_nsuid is None


def test_primary_nsuid_falls_back_to_bundle():
    assert primary_nsuid(["70070000000002", "70070000000001"]) == "70070000000001"
    assert primary_nsuid([]) is None


def test_switch1_doc_not_flagged():
    t = doc_to_title({"fs_id": "1", "title": "x", "playable_on_txt": ["HAC"]})
    assert not t.is_switch2


def test_unranked_rank_is_none():
    assert (
        doc_to_title({"fs_id": "1", "title": "x", "downloads_rank_i": 999999}).downloads_rank
        is None
    )


def test_parse_price_on_sale():
    entry = next(p for p in PRICES if p["title_id"] == 70010000112478)
    p = parse_price(entry, "GB")
    assert (p.regular_p, p.sale_p, p.currency) == (4999, 749, "GBP")
    assert p.sale_end == datetime(2026, 11, 16, 23, 59, 59, tzinfo=UTC)
    assert p.on_sale


def test_parse_price_without_discount_and_not_found():
    p = parse_price(
        {"title_id": 1, "sales_status": "onsale",
         "regular_price": {"currency": "GBP", "raw_value": "9.99"}}, "GB"
    )  # fmt: skip
    assert p.regular_p == 999 and p.sale_p is None and not p.on_sale
    nf = parse_price({"title_id": 2, "sales_status": "not_found"}, "GB")
    assert nf.status == "not_found" and nf.regular_p is None and not nf.on_sale


def test_batches_dedupe_sort_and_chunk():
    ids = [str(70010000000000 + i) for i in range(120, 0, -1)] + ["70010000000005"]
    bs = batches(ids)
    assert [len(b) for b in bs] == [50, 50, 20]
    assert bs[0][0] == "70010000000001" and sum(bs, []) == sorted(set(ids))
