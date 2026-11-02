"""A polite HTTP client: one shared rate limit, retries with backoff, honest User-Agent."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RateLimiter:
    """Spaces calls at least 1/rps seconds apart (single-threaded, so this is enough)."""

    def __init__(
        self,
        requests_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            delay = self._last + self.interval - now
            if delay > 0:
                self._sleep(delay)
                now = self._clock()
        self._last = now


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    body: bytes
    attempts: int


class PoliteClient:
    def __init__(
        self,
        requests_per_second: float = 1.0,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        user_agent: str = "job-radar",
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limiter = RateLimiter(requests_per_second, sleep=sleep)
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def get(self, url: str, params: dict[str, str] | None = None) -> FetchResult:
        """GET with retries on 429/5xx and network errors. 4xx (e.g. 404) returns immediately."""
        attempt = 0
        while True:
            attempt += 1
            self.limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout_s)
            except requests.RequestException as exc:
                if attempt > self.max_retries:
                    raise
                backoff = 2 ** (attempt - 1)
                log.warning("network error on %s (%s); retry in %ss", url, exc, backoff)
                self._sleep(backoff)
                continue

            if resp.status_code in RETRYABLE_STATUS and attempt <= self.max_retries:
                backoff = _retry_after(resp) or 2 ** (attempt - 1)
                log.warning("HTTP %s on %s; retry in %ss", resp.status_code, url, backoff)
                self._sleep(backoff)
                continue

            return FetchResult(
                url=resp.url, status=resp.status_code, body=resp.content, attempts=attempt
            )


def _retry_after(resp: requests.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return min(float(value), 60.0)
    except ValueError:
        return None
