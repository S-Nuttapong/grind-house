import httpx
import pytest
import respx
from jobhunt.core.http import HttpClient, SourceBlocked


@respx.mock
def test_retries_server_error_then_succeeds() -> None:
    route = respx.get("https://example.com/jobs").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, text="ok"),
        ]
    )
    client = HttpClient(sleep=lambda _seconds: None, uniform=lambda _a, _b: 0)
    response = client.get("https://example.com/jobs", "greenhouse")
    assert response.text == "ok"
    assert route.call_count == 2


@respx.mock
def test_does_not_retry_429() -> None:
    route = respx.get("https://example.com/jobs").mock(return_value=httpx.Response(429))
    client = HttpClient(sleep=lambda _seconds: None, uniform=lambda _a, _b: 0)
    with pytest.raises(SourceBlocked) as caught:
        client.get("https://example.com/jobs", "greenhouse")
    assert caught.value.status_code == 429
    assert route.call_count == 1


def test_delay_between_requests_to_the_same_host() -> None:
    now = {"t": 0.0}
    slept: list[float] = []

    def clock() -> float:
        return now["t"]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now["t"] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=request.url.path)

    transport = httpx.MockTransport(handler)
    client = HttpClient(
        httpx.Client(transport=transport),
        clock=clock,
        sleep=sleep,
        uniform=lambda _low, _high: 1.5,
    )
    client.get("https://boards.example/a", "greenhouse")
    now["t"] = 0.2
    client.get("https://boards.example/b", "greenhouse")
    assert slept == [pytest.approx(1.3)]
    client.get("https://other.example/c", "lever")
    assert slept == [pytest.approx(1.3)]
