from datetime import UTC, datetime, timedelta

from pipeline import candidates as cand
from pipeline import history, shortlist
from pipeline.models import PriceInfo, Title
from pipeline.store import Store

NOW = datetime(2026, 11, 11, 18, 0, tzinfo=UTC)
FF7, FF7_BUNDLE, GTA = "70010000112478", "70070000032076", "70070000013132"


def store(tmp_path):
    s = Store(tmp_path / "d.sqlite")
    s.upsert_titles(
        [
            Title("ff7", "FINAL FANTASY VII REBIRTH", (FF7, FF7_BUNDLE), FF7, True,
                  publisher="SQUARE ENIX", categories=("RPG",), downloads_rank=28),
            Title("gta", "GTA Trilogy", (GTA,), GTA, False,
                  publisher="ROCKSTAR", categories=("Action",), downloads_rank=40),
        ],
        NOW,
    )  # fmt: skip
    return s


def write_picks(root, week, publish, picks):
    folder = root / "episodes" / week
    folder.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f'  - nsuid: "{n}"\n    layout: rapid_fire\n    take: "x"\n    approved: {str(a).lower()}\n'
        for n, a in picks
    )
    (folder / "picks.yaml").write_text(f"publish_date: {publish}\npicks:\n{body}")


def test_repeat_within_window_fails_including_bundle_nsuid(tmp_path):
    s = store(tmp_path)
    write_picks(tmp_path, "2026-W40", "2026-10-02", [(FF7, True)])
    write_picks(tmp_path, "2026-W46", "2026-11-13", [(FF7_BUNDLE, True), (GTA, True)])
    problems = history.check_picks(tmp_path, s, "2026-W46")
    assert len(problems) == 1
    assert "FINAL FANTASY VII REBIRTH" in problems[0] and "2026-W40" in problems[0]
    assert "42 days" in problems[0]


def test_outside_window_or_unapproved_is_fine(tmp_path):
    s = store(tmp_path)
    write_picks(tmp_path, "2026-W20", "2026-05-15", [(FF7, True)])  # 182 days earlier
    write_picks(tmp_path, "2026-W44", "2026-10-30", [(GTA, False)])  # never approved
    write_picks(tmp_path, "2026-W46", "2026-11-13", [(FF7, True), (GTA, True)])
    assert history.check_picks(tmp_path, s, "2026-W46") == []


def test_later_drafted_episode_also_counts(tmp_path):
    s = store(tmp_path)
    write_picks(tmp_path, "2026-W50", "2026-12-11", [(GTA, True)])
    write_picks(tmp_path, "2026-W46", "2026-11-13", [(GTA, True)])
    assert "2026-W50" in history.check_picks(tmp_path, s, "2026-W46")[0]


def test_duplicate_within_same_episode(tmp_path):
    s = store(tmp_path)
    write_picks(tmp_path, "2026-W46", "2026-11-13", [(FF7, True), (FF7_BUNDLE, True)])
    assert "listed twice" in history.check_picks(tmp_path, s, "2026-W46")[0]


def test_candidates_never_shortlist_covered_games(tmp_path):
    s = store(tmp_path)
    for n in (FF7, GTA):
        s.insert_snapshots(
            [(PriceInfo(n, "GB", "onsale", "GBP", 4999, 749, NOW, NOW + timedelta(days=5)), NOW)]
        )
    write_picks(tmp_path, "2026-W44", "2026-10-30", [(FF7, True)])
    out = cand.run("2026-W46", "GB", s, NOW, root=tmp_path).read_text()
    picks_block = out.split("```yaml\npicks:")[1].split("```")[0]
    assert GTA in picks_block and FF7 not in picks_block
    assert "covered in 2026-W44 (30 Oct)" in out
    assert "↺ 2026-W44 (30 Oct)" in out


def test_shortlist_never_relaxes_coverage():
    t = Title(
        "ff7", "FF7", (FF7,), FF7, True, publisher="SE", categories=("RPG",), downloads_rank=1
    )
    from pipeline.models import Deal

    d = Deal(t, FF7, "GB", NOW, 4999, 749, None, NOW + timedelta(days=5), None, 0)
    sl = shortlist.build([(1.0, d)], size=8, covered={"ff7": "2026-W44"})
    assert sl.slots == [] and sl.alternates[0][1] == "covered in 2026-W44"
