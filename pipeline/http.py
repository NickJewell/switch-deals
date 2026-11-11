"""The single place network calls happen: a polite, cached httpx wrapper."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

USER_AGENT = "switch-deals-uk/0.1 (personal research script)"
DEFAULT_CACHE = Path("data/cache")


@dataclass(frozen=True)
class CachedResponse:
    url: str
    fetched_at: datetime  # when the HTTP response was actually received (UTC)
    data: object
    from_cache: bool


class CachedClient:
    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE,
        min_interval: float = 1.0,
        retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self.retries = retries
        self._last_request = 0.0
        self.network_calls = 0
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30.0,
            transport=transport,
        )

    @staticmethod
    def build_url(base: str, params: list[tuple[str, str]] | dict[str, str]) -> str:
        items = params.items() if isinstance(params, dict) else params
        return f"{base}?{urlencode(list(items))}"

    def _cache_path(self, url: str) -> Path:
        host = urlsplit(url).hostname or "unknown"
        return self.cache_dir / host / f"{hashlib.sha256(url.encode()).hexdigest()}.json"

    def get_json(self, url: str, ttl: float) -> CachedResponse:
        """GET url as JSON; serve from disk cache if younger than ttl seconds (ttl=0 forces)."""
        path = self._cache_path(url)
        if ttl > 0 and path.exists():
            entry = json.loads(path.read_text())
            fetched_at = datetime.fromisoformat(entry["fetched_at"])
            if (datetime.now(UTC) - fetched_at).total_seconds() < ttl:
                return CachedResponse(url, fetched_at, entry["data"], True)

        data = self._fetch(url)
        fetched_at = datetime.now(UTC).replace(microsecond=0)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"url": url, "fetched_at": fetched_at.isoformat(), "data": data}))
        tmp.replace(path)
        return CachedResponse(url, fetched_at, data, False)

    def _fetch(self, url: str) -> object:
        delay = 2.0
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            self.network_calls += 1
            try:
                resp = self._http.get(url)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
            else:
                if resp.status_code < 400:
                    return resp.json()
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    resp.raise_for_status()
            time.sleep(delay)
            delay *= 2
        raise RuntimeError("unreachable")

    def close(self) -> None:
        self._http.close()
