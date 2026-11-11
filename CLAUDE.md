# Switch Deals UK

Local pipeline: Nintendo endpoints → deals DB → picks.yaml (manual) → script → ElevenLabs v3 audio → clips → Remotion render → MP4.

**Phase status:** 0–1 built (discovery, deals DB, candidates). Next: Phase 2 (tokens, normaliser, facts lint) after Nick confirms the Switch 2 rule and `docs/manual-check.md`.

## Conventions
- Python: uv, ruff, pytest. `uv run pytest`, `uv run ruff check`.
- All network calls go through `pipeline/http.py::CachedClient` (on-disk cache in `data/cache/`, ≥1 s between requests, generic User-Agent with no personal details).
- Tests never hit the network. They use recorded fixtures in `tests/fixtures/` (trimmed Nintendo responses only, never secrets: the repo is public).
- Raw Nintendo field names appear **only** in `pipeline/nintendo/*.py`. Everything else uses `pipeline/models.py` dataclasses.
- Money is integer pence (`int`). Never compare prices as floats. Datetimes are tz-aware UTC.
- The price API (`api.ec.nintendo.com`) is the source of truth for anything said on screen or in the voiceover. Solr index prices are hints only, and a Solr doc's price fields may mix several nsuids.
- Remotion: everything comes from props, with no data fetching inside components. Layouts go in `video/src/layouts/`.
- ElevenLabs: never call the API without passing the cache check, and print the character count before each run.
- Every `make` target is idempotent and works on one episode folder (`WEEK=2026-W46`).
- Never push to GitHub without asking.

## Layout
See `docs/data-dictionary.md` for the Nintendo field reference.
