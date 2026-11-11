WEEK ?= $(shell date +%G-W%V)
COUNTRY ?= GB
PY := uv run python -m

.PHONY: discover fetch candidates voice clips render publish test lint

discover:
	$(PY) pipeline.discover

fetch:
	$(PY) pipeline.fetch --country $(COUNTRY)

candidates:
	$(PY) pipeline.candidates --week $(WEEK) --country $(COUNTRY)

voice clips render publish:
	@echo "make $@: not yet implemented (see CLAUDE.md phase status)"; exit 1

test:
	uv run pytest -q

lint:
	uv run ruff check . && uv run ruff format --check .
