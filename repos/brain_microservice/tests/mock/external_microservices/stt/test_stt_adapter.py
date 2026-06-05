import json

import httpx
import pytest

from application.dtos.outbound_dtos import STTBatchRequestDto, STTSetStreamRequestDto, STTTextStreamRequestDto
from domain.errors import ExternalServiceUnavailableError
from infrastructure.outbound.http.base import HttpServiceConfig
from infrastructure.outbound.http.stt.stt_adapter import HttpSTTAdapter
from application.services.steps.stream_internal.external_events import stream_event_bytes
from tests.shared.streams import byte_stream


class _BrokenChunkedStream(httpx.AsyncByteStream):
    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body (incomplete chunked read)"
        )


def _sse_event(event_type: str, sequence: int, payload: dict) -> bytes:
    return (
        "data: "
        + json.dumps(
            {
                "type": event_type,
                "sequence": sequence,
                "timestamp": "2026-05-24T12:00:00Z",
                "payload": payload,
            }
        )
        + "\n\n"
    ).encode("utf-8")


def _ndjson_events(body: bytes) -> list[dict]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line]


def _assert_standard_event(event: dict, event_type: str, sequence: int) -> None:
    assert event["type"] == event_type
    assert event["sequence"] == sequence
    assert event["timestamp"].endswith("Z")
    assert isinstance(event["payload"], dict)


@pytest.mark.asyncio
async def test_stt_adapter_posts_audio_stream_input() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/process/stream/set"
        assert request.url.params["sample_rate"] == "16000"
        assert request.url.params["chunk_size"] == "1024"
        assert request.url.params["silence_threshold"] == "150"
        assert request.url.params["silence_limit_seconds"] == "2.0"
        assert request.headers["content-type"] == "application/x-ndjson"
        events = _ndjson_events(await request.aread())
        assert len(events) == 3
        _assert_standard_event(events[0], "stream_started", 1)
        _assert_standard_event(events[1], "partial", 2)
        assert events[1]["payload"] == {"bytes_base64": "cGNt"}
        _assert_standard_event(events[2], "completed", 3)
        assert events[2]["payload"] == {"reason": "completed", "output_bytes_base64": "cGNt"}
        return httpx.Response(200, json={"data": {"accepted": True}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        set_stream_endpoint="/process/stream/set",
        client=client,
    )

    body = b"".join(
        [
            stream_event_bytes("stream_started", 1, {}),
            stream_event_bytes("partial", 2, {"bytes_base64": "cGNt"}),
            stream_event_bytes("completed", 3, {"reason": "completed", "output_bytes_base64": "cGNt"}),
        ]
    )
    await adapter.set_stream(STTSetStreamRequestDto(audio_stream=byte_stream((body,)), sample_rate=16000))

    await client.aclose()


@pytest.mark.asyncio
async def test_stt_adapter_can_replace_decoupled_stream_with_second_set_request() -> None:
    bodies: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/process/stream/set"
        bodies.append(await request.aread())
        return httpx.Response(200, json={"data": {"accepted": True}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        set_stream_endpoint="/process/stream/set",
        client=client,
    )

    first = stream_event_bytes("partial", 1, {"bytes_base64": "Zmlyc3Q="})
    second = stream_event_bytes("partial", 1, {"bytes_base64": "c2Vjb25k"})
    await adapter.set_stream(STTSetStreamRequestDto(audio_stream=byte_stream((first,)), sample_rate=16000))
    await adapter.set_stream(STTSetStreamRequestDto(audio_stream=byte_stream((second,)), sample_rate=16000))

    assert [_ndjson_events(body)[0]["payload"] for body in bodies] == [
        {"bytes_base64": "Zmlyc3Q="},
        {"bytes_base64": "c2Vjb25k"},
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_stt_adapter_requires_200_when_setting_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/process/stream/set"
        await request.aread()
        return httpx.Response(202, json={"data": {"accepted": True}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        set_stream_endpoint="/process/stream/set",
        client=client,
    )

    with pytest.raises(ExternalServiceUnavailableError, match="expected HTTP 200"):
        await adapter.set_stream(STTSetStreamRequestDto(audio_stream=byte_stream((b"pcm",)), sample_rate=16000))

    await client.aclose()


@pytest.mark.asyncio
async def test_stt_adapter_gets_and_parses_sse_text_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/process/stream/get"
        assert request.url.params["sample_rate"] == "16000"
        assert request.url.params["chunk_size"] == "2048"
        assert request.url.params["silence_threshold"] == "200"
        assert request.url.params["silence_limit_seconds"] == "0.75"
        return httpx.Response(
            200,
            content=b"".join(
                [
                    _sse_event("stream_started", 1, {}),
                    _sse_event("partial", 2, {"text": "hel"}),
                    _sse_event("completed", 3, {"reason": "silence", "output": "hello"}),
                    _sse_event("completed", 4, {"reason": "silence", "output": "world"}),
                ]
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        get_stream_endpoint="/process/stream/get",
        client=client,
    )

    response = await adapter.get_stream(
        STTTextStreamRequestDto(
            sample_rate=16000,
            chunk_size=2048,
            silence_threshold=200,
            silence_limit_seconds=0.75,
        )
    )
    texts = [chunk async for chunk in response.text_stream]

    assert b"hello" in b"".join(texts)
    assert b"world" in b"".join(texts)
    await client.aclose()


@pytest.mark.asyncio
async def test_stt_adapter_rejects_legacy_raw_sse_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/stream/get"
        return httpx.Response(200, content=b"data: hello world\n\n")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        get_stream_endpoint="/process/stream/get",
        client=client,
    )

    response = await adapter.get_stream(STTTextStreamRequestDto())
    body = b"".join([chunk async for chunk in response.text_stream])
    assert body == b"data: hello world\n\n"

    await client.aclose()


@pytest.mark.asyncio
async def test_stt_adapter_rejects_non_sequential_sse_events() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/stream/get"
        return httpx.Response(
            200,
            content=b"".join(
                [
                    _sse_event("stream_started", 1, {}),
                    _sse_event("completed", 3, {"reason": "completed", "output": "skipped"}),
                ]
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        get_stream_endpoint="/process/stream/get",
        client=client,
    )

    response = await adapter.get_stream(STTTextStreamRequestDto())
    body = b"".join([chunk async for chunk in response.text_stream])
    assert b"skipped" in body

    await client.aclose()


@pytest.mark.asyncio
async def test_stt_adapter_get_stream_before_set_surfaces_endpoint_not_found() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/process/stream/get"
        return httpx.Response(404, json={"message": "stream has not been initialized"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        get_stream_endpoint="/process/stream/get",
        client=client,
    )

    with pytest.raises(ExternalServiceUnavailableError, match="endpoint not found"):
        await adapter.get_stream(STTTextStreamRequestDto())

    await client.aclose()


@pytest.mark.asyncio
async def test_stt_adapter_treats_incomplete_chunked_close_as_stream_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/stream/get"
        return httpx.Response(200, stream=_BrokenChunkedStream())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        get_stream_endpoint="/process/stream/get",
        client=client,
    )

    response = await adapter.get_stream(STTTextStreamRequestDto())
    with pytest.raises(ExternalServiceUnavailableError, match="incomplete chunked read"):
        [chunk async for chunk in response.text_stream]
    await client.aclose()


@pytest.mark.asyncio
async def test_stt_adapter_posts_batch_audio_and_parses_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/batch"
        assert request.url.params["sample_rate"] == "8000"
        assert await request.aread() == b"batch-pcm"
        return httpx.Response(200, json={"data": {"text": "batch text"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSTTAdapter(
        HttpServiceConfig("stt", "http://stt.test"),
        batch_endpoint="/process/batch",
        client=client,
    )

    response = await adapter.process_batch(STTBatchRequestDto(audio_data=b"batch-pcm", sample_rate=8000))

    assert response.text == "batch text"
    await client.aclose()
