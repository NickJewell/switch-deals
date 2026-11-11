from datetime import UTC, datetime, timedelta

from pipeline import shortlist
from pipeline.models import Deal, Title

NOW = datetime(2026, 11, 11, tzinfo=UTC)


def d(i, name, pub, genre, rank=100, sale=1000, s2=False):
    t = Title(
        fs_id=str(i), title=name, nsuids=(f"7001{i:010d}",), primary_nsuid=f"7001{i:010d}",
        is_switch2=s2, publisher=pub, categories=(genre,), downloads_rank=rank,
    )  # fmt: skip
    return Deal(t, t.primary_nsuid, "GB", NOW, 4000, sale, None, NOW + timedelta(days=5), None, 0)


def ranked(deals):
    return [(1 - i / 100, x) for i, x in enumerate(deals)]


def test_variety_rules_and_quotas():
    deals = [
        d(1, "FINAL FANTASY VII REBIRTH", "SQUARE ENIX", "RPG", rank=28, s2=True),
        d(2, "FINAL FANTASY VII REMAKE", "Square Enix Europe", "RPG", rank=39),
        d(3, "Dragon Quest XI", "SQUARE ENIX", "RPG", rank=50),
        d(4, "Shovelware 96%", "Panda", "Racing", rank=None, sale=149),
        d(5, "Puzzle A", "StudioA Ltd", "Puzzle", rank=900),
        d(6, "Puzzle B", "StudioB Ltd", "Puzzle", rank=950),
        d(7, "Puzzle C", "StudioC Ltd", "Puzzle", rank=990),
        d(8, "GTA Trilogy", "ROCKSTAR", "Action", rank=40),
        d(9, "Cheap Indie", "StudioD Ltd", "Platformer", rank=1500, sale=299),
        d(10, "Budget Gem", "StudioE Ltd", "Strategy", rank=1600, sale=399),
        d(11, "Racer", "StudioF Ltd", "Racing", rank=500),
        d(12, "Sim", "StudioG Ltd", "Simulation", rank=700),
        d(13, "Fighter", "StudioH Ltd", "Fighting", rank=800),
    ]
    sl = shortlist.build(ranked(deals), size=8)
    names = [s.deal.title.title for s in sl.slots]
    assert len(names) == 8 and sl.relaxed == []
    assert "Shovelware 96%" not in names  # unranked
    assert "FINAL FANTASY VII REMAKE" not in names and "Dragon Quest XI" not in names
    assert sum(s.genre == "Puzzle" for s in sl.slots) == 2
    assert {"Cheap Indie", "Budget Gem"} <= set(names)  # under-£5 quota
    assert [s.layout for s in sl.slots].count("spotlight") == 2
    assert sl.slots[0].deal.title.title == "FINAL FANTASY VII REBIRTH"  # most popular opens
    assert 9 <= sl.minutes <= 11
    why = dict((s.deal.title.title, w) for s, w in sl.alternates)
    assert why["FINAL FANTASY VII REMAKE"].startswith("same series")
    assert why["Shovelware 96%"] == "obscure (unranked)"


def test_relaxes_caps_when_pool_too_narrow():
    deals = [d(i, f"Game {i}", "Same Pub", "RPG", rank=100 + i) for i in range(10)]
    sl = shortlist.build(ranked(deals), size=8)
    assert len(sl.slots) == 8 and sl.relaxed == ["genre", "publisher"]
