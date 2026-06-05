import json

import httpx
import pytest

from application.dtos.outbound_dtos import MicrophoneStreamRequestDto
from domain.errors import ExternalServiceUnavailableError
from infrastructure.outbound.http.base import HttpServiceConfig
from infrastructure.outbound.http.microphone.microphone_adapter import HttpMicrophoneAdapter


def _event(event_type: str, sequence: int, payload: dict) -> bytes:
    return (
        json.dumps(
            {
                "type": event_type,
                "sequence": sequence,
                "timestamp": "2026-05-24T12:00:00Z",
                "payload": payload,
            }
        )
        + "\n"
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_microphone_adapter_starts_stream_and_posts_expected_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/start"
        assert json.loads((await request.aread()).decode("utf-8")) == {
            "sample_rate": 8000,
            "channels": 1,
            "chunk_size": 512,
        }
        return httpx.Response(
            200,
            content=b"".join(
                [
                    _event("stream_started", 1, {}),
                    _event("partial", 2, {"bytes_base64": "bWljLWF1ZGlv"}),
                    _event("completed", 3, {"reason": "completed", "output": "", "bytes_base64": "bWljLWF1ZGlv"}),
                ]
            ),
            headers={"X-Sample-Rate": "44100"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpMicrophoneAdapter(
        HttpServiceConfig("microphone", "http://microphone.test"),
        start_endpoint="/start",
        client=client,
    )

    response = await adapter.start_stream(MicrophoneStreamRequestDto(sample_rate=8000, chunk_size=512))
    chunks = [chunk async for chunk in response.audio_stream]

    assert response.sample_rate == 44100
    assert b"".join(chunks) == b"".join(
        [
            _event("stream_started", 1, {}),
            _event("partial", 2, {"bytes_base64": "bWljLWF1ZGlv"}),
            _event("completed", 3, {"reason": "completed", "output": "", "bytes_base64": "bWljLWF1ZGlv"}),
        ]
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_microphone_adapter_returns_completed_event_stream_without_decoding() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/start"
        return httpx.Response(
            200,
            content=b"".join(
                [
                    _event("stream_started", 1, {}),
                    _event("completed", 2, {"reason": "completed", "output": "", "bytes_base64": "bWljLWF1ZGlv"}),
                ]
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpMicrophoneAdapter(
        HttpServiceConfig("microphone", "http://microphone.test"),
        start_endpoint="/start",
        client=client,
    )

    response = await adapter.start_stream(MicrophoneStreamRequestDto(sample_rate=8000, chunk_size=512))
    chunks = [chunk async for chunk in response.audio_stream]

    assert b"completed" in b"".join(chunks)
    await client.aclose()


@pytest.mark.asyncio
async def test_microphone_adapter_returns_partial_and_completed_events_without_decoding() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/start"
        return httpx.Response(
            200,
            content=b"".join(
                [
                    _event("stream_started", 1, {}),
                    _event("partial", 2, {"bytes_base64": "bWljLWF1ZGlv"}),
                    _event("completed", 3, {"reason": "completed", "output": "", "bytes_base64": "bWljLWF1ZGlv"}),
                ]
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpMicrophoneAdapter(
        HttpServiceConfig("microphone", "http://microphone.test"),
        start_endpoint="/start",
        client=client,
    )

    response = await adapter.start_stream(MicrophoneStreamRequestDto(sample_rate=8000, chunk_size=512))
    chunks = [chunk async for chunk in response.audio_stream]

    body = b"".join(chunks)
    assert body.count(b"bWljLWF1ZGlv") == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_microphone_adapter_stops_stream_and_closes_active_stream() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/start":
            return httpx.Response(200, content=_event("stream_started", 1, {}))
        if request.url.path == "/stop":
            return httpx.Response(200, json={"message": "stopped"})
        raise AssertionError(f"Unexpected request {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpMicrophoneAdapter(
        HttpServiceConfig("microphone", "http://microphone.test"),
        start_endpoint="/start",
        stop_endpoint="/stop",
        client=client,
    )

    await adapter.start_stream(MicrophoneStreamRequestDto())
    await adapter.stop_stream()

    assert requests == [("POST", "/start"), ("POST", "/stop")]
    await client.aclose()


@pytest.mark.asyncio
async def test_microphone_adapter_requires_200_when_starting_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/start"
        return httpx.Response(202, json={"message": "accepted but not open"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpMicrophoneAdapter(
        HttpServiceConfig("microphone", "http://microphone.test"),
        start_endpoint="/start",
        client=client,
    )

    with pytest.raises(ExternalServiceUnavailableError, match="expected HTTP 200"):
        await adapter.start_stream(MicrophoneStreamRequestDto())

    await client.aclose()
