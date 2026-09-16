"""Polite HTTP client for the Prozorro public API.

Verified against https://public-api.prozorro.gov.ua/api/2.5 on 2026-09-16:
listing endpoint `/tenders` is ordered by dateModified and paginated by an
opaque `next_page.offset` token; an ISO datetime is accepted as a seed offset.
"""

from __future__ import annotations

import itertools
import random
import threading
import time
from dataclasses import dataclass, field

import requests

BASE = "https://public-api.prozorro.gov.ua/api/2.5"
USER_AGENT = (
    "ThesisInstitute-procurement-research/0.1 "
    "(research backtest; contact max@maxghenis.com)"
)

# The brief caps us at four concurrent requests against the public API.
MAX_CONCURRENCY = 4

RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class RequestCounter:
    """Thread-safe tally of requests issued, for the report."""

    counts: dict[str, int] = field(default_factory=dict)
    retries: int = 0
    bytes_in: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, kind: str, nbytes: int = 0, retry: bool = False) -> None:
        with self._lock:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.bytes_in += nbytes
            if retry:
                self.retries += 1

    def total(self) -> int:
        with self._lock:
            return sum(self.counts.values())

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "by_kind": dict(self.counts),
                "total": sum(self.counts.values()),
                "retries": self.retries,
                "bytes_in": self.bytes_in,
            }


COUNTER = RequestCounter()


class Client:
    """One `requests.Session` per thread, with exponential backoff."""

    def __init__(self, counter: RequestCounter | None = None, max_tries: int = 7):
        self._local = threading.local()
        self.counter = counter if counter is not None else COUNTER
        self.max_tries = max_tries

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
            self._local.session = s
        return s

    def get(self, path: str, params: dict | None = None, kind: str = "other") -> dict:
        """GET a JSON document, retrying 429/5xx and transport errors.

        Raises `requests.HTTPError` on a non-retryable status and
        `RuntimeError` when the retry budget is exhausted.
        """
        url = path if path.startswith("http") else f"{BASE}{path}"
        delay = 1.0
        last: Exception | None = None
        for attempt in itertools.count(1):
            try:
                resp = self.session.get(url, params=params, timeout=90)
                if resp.status_code in RETRY_STATUS:
                    last = requests.HTTPError(f"{resp.status_code} for {url}")
                elif resp.status_code >= 400:
                    self.counter.record(kind, len(resp.content))
                    resp.raise_for_status()
                else:
                    self.counter.record(kind, len(resp.content), retry=attempt > 1)
                    return resp.json()
            except (requests.RequestException, ValueError) as exc:  # transport or JSON
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    if exc.response.status_code not in RETRY_STATUS:
                        raise
                last = exc
            if attempt >= self.max_tries:
                raise RuntimeError(f"giving up on {url} after {attempt} tries: {last}")
            time.sleep(delay * (1.0 + 0.25 * random.random()))
            delay = min(delay * 2, 60.0)
        raise AssertionError("unreachable")


CLIENT = Client()
