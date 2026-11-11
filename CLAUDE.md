# Switch Deals UK

Local pipeline: Nintendo endpoints → deals DB → picks.yaml (manual) → script → ElevenLabs v3 audio → clips → Remotion render → MP4.

**Phase status:** 0–1 built (discovery, deals DB, candidates). Next: Phase 2 (tokens, normaliser, facts lint) after Nick confirms the Switch 2 rule and `docs/manual-check.md`.

## Conventions
- Python: uv, ruff, pytest. `uv run pytest`, `uv run ruff check`.
- All network calls go through `pipeline/http.py::CachedClient` (on-disk cache in `data/cache/`, ≥1 s between requests, generic User-Agent with no personal details).
- Tests never hit the network. They use recorded fixtures in `tests/fixtures/` (trimmed Nintendo responses only, never secrets: the repo is public).
- Raw Nintendo field names appear **only** in `pipeline/nintendo/*.py`. Everything else uses `pipeline/models.py` dataclasses.
- Money is integer pence (`int`). Never compare prices as floats. Datetimes are tz-aware UTC.
- ATL comes only from our own `price_snapshots` history (Nintendo has no lowest-ever field; `price_lowest_f` is the cheapest *current* price). Confirmed after 90 days of daily fetches.
- The price API (`api.ec.nintendo.com`) is the source of truth for anything said on screen or in the voiceover. Solr index prices are hints only, and a Solr doc's price fields may mix several nsuids.
- Remotion: everything comes from props, with no data fetching inside components. Layouts go in `video/src/layouts/`.
- ElevenLabs: never call the API without passing the cache check, and print the character count before each run.
- No repeats: a game (matched by fs_id, so bundles count) approved in any episode within 120 days of this one is never shortlisted, and `make check-picks` fails on it. The Phase 2 facts lint must call `history.check_picks`.
- Every `make` target is idempotent and works on one episode folder (`WEEK=2026-W46`).
- Never push to GitHub without asking.

## Script writing (Phase 2+)
`prompts/voiceover-script.md` is Nick's voiceover persona/style prompt — use it verbatim as the base when generating `script.md`. Keep it unedited; put pipeline-specific additions (segment headers, `{{GBP:…}}` tokens, ElevenLabs v3 audio tags, ~2,500-char segments, prices only via tokens) in a separate wrapper rather than modifying it.

## Layout
See `docs/data-dictionary.md` for the Nintendo field reference.
