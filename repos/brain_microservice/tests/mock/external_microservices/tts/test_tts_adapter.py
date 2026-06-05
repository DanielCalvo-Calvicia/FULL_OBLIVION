import json

import httpx
import pytest

from application.dtos.outbound_dtos import TTSAudioStreamRequestDto, TTSSetStreamRequestDto, TTSTextStreamRequestDto
from infrastructure.outbound.http.base import HttpServiceConfig
from infrastructure.outbound.http.tts.tts_adapter import HttpTTSAdapter
from application.services.steps.stream_internal.external_events import stream_event_bytes, text_stream_as_ndjson_events
from tests.shared.streams import byte_stream


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


def _ndjson_events(body: bytes) -> list[dict]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line]


def _assert_standard_event(event: dict, event_type: str, sequence: int) -> None:
    assert event["type"] == event_type
    assert event["sequence"] == sequence
    assert event["timestamp"].endswith("Z")
    assert isinstance(event["payload"], dict)


@pytest.mark.asyncio
async def test_tts_adapter_posts_single_text_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/process/stream/set"
        assert request.url.params["sample_rate"] == "24000"
        assert request.url.params["channels"] == "1"
        assert request.headers["content-type"] == "application/x-ndjson"
        assert await request.aread() == b"hello"
        return httpx.Response(200, json={"message": "accepted"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpTTSAdapter(
        HttpServiceConfig("tts", "http://tts.test"),
        set_stream_endpoint="/process/stream/set",
        client=client,
    )

    await adapter.set_stream(TTSSetStreamRequestDto(text="hello", sample_rate=24000, channels=1))

    await client.aclose()


@pytest.mark.asyncio
async def test_tts_adapter_posts_text_iterator_as_newline_chunks() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/stream/set"
        events = _ndjson_events(await request.aread())
        assert [event["type"] for event in events] == ["stream_started", "partial", "partial", "completed"]
        assert [event["sequence"] for event in events] == [1, 2, 3, 4]
        assert events[1]["payload"] == {"text": "hello"}
        assert events[2]["payload"] == {"text": "world"}
        assert events[3]["payload"] == {"reason": "completed", "output": "helloworld"}
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpTTSAdapter(
        HttpServiceConfig("tts", "http://tts.test"),
        set_stream_endpoint="/process/stream/set",
        client=client,
    )

    body = b"".join(
        [
            stream_event_bytes("stream_started", 1, {}),
            stream_event_bytes("partial", 2, {"text": "hello"}),
            stream_event_bytes("partial", 3, {"text": "world"}),
            stream_event_bytes("completed", 4, {"reason": "completed", "output": "helloworld"}),
        ]
    )
    await adapter.set_text_stream(
        TTSTextStreamRequestDto(text_stream=byte_stream((body,)), sample_rate=24000, channels=1)
    )

    await client.aclose()


@pytest.mark.asyncio
async def test_tts_text_stream_wrapper_completes_each_normal_text_segment() -> None:
    async def text_stream():
        yield "hello"
        yield "world"

    events = _ndjson_events(b"".join([event async for event in text_stream_as_ndjson_events(text_stream())]))

    assert [event["type"] for event in events] == ["stream_started", "completed", "completed"]
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert events[1]["payload"] == {"reason": "completed", "output": "hello"}
    assert events[2]["payload"] == {"reason": "completed", "output": "world"}


@pytest.mark.asyncio
async def test_tts_text_stream_wrapper_uses_partials_only_for_large_text() -> None:
    async def text_stream():
        yield "abcdef"

    events = _ndjson_events(
        b"".join([event async for event in text_stream_as_ndjson_events(text_stream(), partial_chunk_chars=3)])
    )

    assert [event["type"] for event in events] == ["stream_started", "partial", "partial", "completed"]
    assert events[1]["payload"] == {"text": "abc", "chunk_index": 1}
    assert events[2]["payload"] == {"text": "def", "chunk_index": 2}
    assert events[3]["payload"] == {"reason": "completed", "output": "abcdef"}


@pytest.mark.asyncio
async def test_tts_adapter_accepts_async_stream_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/stream/set"
        events = _ndjson_events(await request.aread())
        assert events[0]["payload"] == {"text": "hello"}
        return httpx.Response(202)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpTTSAdapter(
        HttpServiceConfig("tts", "http://tts.test"),
        set_stream_endpoint="/process/stream/set",
        client=client,
    )

    await adapter.set_text_stream(
        TTSTextStreamRequestDto(
            text_stream=byte_stream((stream_event_bytes("partial", 1, {"text": "hello"}),)),
            sample_rate=24000,
            channels=1,
        )
    )

    await client.aclose()


@pytest.mark.asyncio
async def test_tts_adapter_gets_audio_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/process/stream/get"
        assert request.url.params["sample_rate"] == "22050"
        assert request.url.params["channels"] == "2"
        assert request.url.params["keep_open_after_completed"] == "true"
        return httpx.Response(
            200,
            content=b"".join(
                [
                    _event("stream_started", 1, {}),
                    _event("partial", 2, {"bytes_base64": "dHRzLWF1ZGlv", "byte_count": 9, "chunk_index": 1}),
                    _event(
                        "completed",
                        3,
                        {"reason": "completed", "output_bytes_base64": "dHRzLWF1ZGlv", "total_bytes": 9},
                    ),
                ]
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpTTSAdapter(
        HttpServiceConfig("tts", "http://tts.test"),
        get_stream_endpoint="/process/stream/get",
        client=client,
    )

    response = await adapter.get_stream(TTSAudioStreamRequestDto(sample_rate=22050, channels=2))
    chunks = [chunk async for chunk in response.audio_stream]

    assert b"tts-audio" not in b"".join(chunks)
    assert b"dHRzLWF1ZGlv" in b"".join(chunks)
    await client.aclose()


@pytest.mark.asyncio
async def test_tts_adapter_stops_after_requested_completed_outputs() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/stream/get"
        assert request.url.params["keep_open_after_completed"] == "true"
        return httpx.Response(
            200,
            content=b"".join(
                [
                    _event("stream_started", 1, {}),
                    _event("partial", 2, {"bytes_base64": "Zmlyc3Q=", "byte_count": 5, "chunk_index": 1}),
                    _event("completed", 3, {"reason": "completed", "total_bytes": 5}),
                    _event("heartbeat", 4, {}),
                    _event("partial", 5, {"bytes_base64": "c2Vjb25k", "byte_count": 6, "chunk_index": 1}),
                    _event("completed", 6, {"reason": "completed", "total_bytes": 6}),
                ]
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpTTSAdapter(
        HttpServiceConfig("tts", "http://tts.test"),
        get_stream_endpoint="/process/stream/get",
        client=client,
    )

    response = await adapter.get_stream(
        TTSAudioStreamRequestDto(sample_rate=24000, channels=1, completed_outputs_to_read=1)
    )
    chunks = [chunk async for chunk in response.audio_stream]

    body = b"".join(chunks)
    assert b"Zmlyc3Q=" in body
    assert b"c2Vjb25k" in body
    await client.aclose()
