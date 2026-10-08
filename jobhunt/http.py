"""Shared HTTP client: one host at a time, backoff on 5xx, stop on 429 or 403."""

import os
import random
import ssl
import time
from collections.abc import Callable
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, retry_if_result, stop_after_attempt, wait_fixed

from jobhunt import __version__

USER_AGENT = f"jobhunt/{__version__} (personal job research)"


class SourceBlocked(Exception):
    def __init__(self, source_id: str, status_code: int) -> None:
        super().__init__(f"{source_id} returned HTTP {status_code}")
        self.source_id = source_id
        self.status_code = status_code


class HttpClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
    ) -> None:
        cafile = os.environ.get("SSL_CERT_FILE")
        verify: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=cafile) if cafile else True
        )
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(60.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            verify=verify,
        )
        self._clock = clock
        self._sleep = sleep
        self._uniform = uniform
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._last_by_host: dict[str, float] = {}

    def get(self, url: str, source_id: str) -> httpx.Response:
        self._wait_for_host(url)
        response = self._get_retrying(url)
        self._last_by_host[urlparse(url).netloc] = self._clock()
        if response.status_code in {429, 403}:
            raise SourceBlocked(source_id, response.status_code)
        response.raise_for_status()
        return response

    def _wait_for_host(self, url: str) -> None:
        host = urlparse(url).netloc
        previous = self._last_by_host.get(host)
        if previous is None:
            return
        gap = self._uniform(self._min_delay, self._max_delay)
        remaining = gap - (self._clock() - previous)
        if remaining > 0:
            self._sleep(remaining)

    def _get_retrying(self, url: str) -> httpx.Response:
        @retry(
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError))
            | retry_if_result(lambda response: response.status_code >= 500),
            stop=stop_after_attempt(3),
            wait=wait_fixed(0),
            reraise=True,
        )
        def attempt() -> httpx.Response:
            return self._client.get(url)

        return attempt()
