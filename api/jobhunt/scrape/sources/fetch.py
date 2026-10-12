"""JSON fetch that never puts request URLs into the partial-run message.

API keys travel in the query string or the path. ``httpx`` includes that URL
in ``HTTPStatusError``, so callers raise ``RunPartial`` with the status only.
"""

from typing import Any

import httpx
from tenacity import RetryError

from jobhunt.core.http import SourceBlocked
from jobhunt.scrape.sources.base import FetchContext, RunPartial


def read_json(
    ctx: FetchContext,
    source_id: str,
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    json: Any = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
) -> Any:
    try:
        response = ctx.http.request(
            method,
            url,
            source_id,
            params=params,
            json=json,
            headers=headers,
            auth=auth,
        )
    except SourceBlocked:
        raise
    except (httpx.HTTPError, RetryError) as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        detail = f"HTTP {status}" if status else "request failed"
        raise RunPartial(source_id, detail) from exc
    try:
        return response.json()
    except ValueError as exc:
        raise RunPartial(source_id, "response was not JSON") from exc
