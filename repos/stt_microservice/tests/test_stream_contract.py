import asyncio
import base64
import json
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

from application.dtos.adapter_inbound_dtos import InitInboundAdapterDto
from application.dtos.audio_stream_items import CompletedAudioSegment
from application.dtos.adapter_outbound_dtos import (
    ProcessBatchResponseDto as OutboundProcessBatchResponseDto,
    ProcessStreamResponseDto as OutboundProcessStreamResponseDto,
    STTAvailabilityResponseDto as OutboundSTTAvailabilityResponseDto,
)
from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.ports.service_port import ServicePort
from application.dtos.services_dtos import (
    GetStreamResponseDto,
    ProcessBatchResponseDto,
    ProcessStreamResponseDto,
    SetStreamResponseDto,
    STTAvailabilityResponseDto,
)
from application.services.service import STTService
from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter


def _parse_sse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
        elif line.strip():
            raise AssertionError(f"Unexpected raw stream line: {line!r}")
    return events


def _parse_ndjson_events(body: str) -> list[dict]:
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def _assert_event_shape(event: dict, expected_type: str, expected_sequence: int) -> None:
    assert set(event) == {"type", "sequence", "timestamp", "payload"}
    assert event["type"] == expected_type
    assert event["sequence"] == expected_sequence
    assert event["timestamp"].endswith("Z")
    assert isinstance(event["payload"], dict)


async def _text_stream(items: list[str]) -> AsyncIterator[str]:
    for item in items:
        yield item


async def _failing_text_stream() -> AsyncIterator[str]:
    raise RuntimeError("transcription backend unavailable")
    yield ""


async def _text_then_failing_stream() -> AsyncIterator[str]:
    yield "hello before failure"
    raise RuntimeError("transcription backend unavailable")


class FakeService(ServicePort):
    def __init__(
        self,
        *,
        process_items: list[str] | None = None,
        get_items: list[str] | None = None,
        fail_process_stream: bool = False,
        fail_process_stream_after_text: bool = False,
    ) -> None:
        self.process_items = process_items or []
        self.get_items = get_items or []
        self.fail_process_stream = fail_process_stream
        self.fail_process_stream_after_text = fail_process_stream_after_text

    async def process_stream(self, request) -> ProcessStreamResponseDto:
        if self.fail_process_stream:
            return ProcessStreamResponseDto(text_stream=_failing_text_stream())
        if self.fail_process_stream_after_text:
            return ProcessStreamResponseDto(text_stream=_text_then_failing_stream())
        return ProcessStreamResponseDto(text_stream=_text_stream(self.process_items))

    async def set_stream(self, request) -> SetStreamResponseDto:
        return SetStreamResponseDto(accepted=True)

    async def get_stream(self, request) -> GetStreamResponseDto:
        return GetStreamResponseDto(text_stream=_text_stream(self.get_items))

    async def stop_stream(self) -> None:
        return None

    async def process_batch(self, request) -> ProcessBatchResponseDto:
        return ProcessBatchResponseDto(text="")

    async def is_available(self, request) -> STTAvailabilityResponseDto:
        return STTAvailabilityResponseDto(is_available=True)


class RecordingSetService(FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.audio_chunks: list[bytes] = []

    async def set_stream(self, request) -> SetStreamResponseDto:
        async for chunk in request.audio_stream:
            self.audio_chunks.append(chunk)
        return SetStreamResponseDto(accepted=True)


class FakeOutboundAdapter(AdapterOutboundPort):
    def __init__(self, items: list[str] | None = None) -> None:
        self.items = ["adapter text"] if items is None else items

    async def process_stream(self, request) -> OutboundProcessStreamResponseDto:
        return OutboundProcessStreamResponseDto(text_stream=_text_stream(self.items))

    async def process_batch(self, request) -> OutboundProcessBatchResponseDto:
        return OutboundProcessBatchResponseDto(text="")

    async def is_available(self, request) -> OutboundSTTAvailabilityResponseDto:
        return OutboundSTTAvailabilityResponseDto(is_available=True)


class AudioDrivenOutboundAdapter(AdapterOutboundPort):
    async def process_stream(self, request) -> OutboundProcessStreamResponseDto:
        async def text_stream() -> AsyncIterator[str]:
            async for chunk in request.audio_stream:
                if chunk:
                    yield "adapter text from live input"
                    return

        return OutboundProcessStreamResponseDto(text_stream=text_stream())

    async def process_batch(self, request) -> OutboundProcessBatchResponseDto:
        return OutboundProcessBatchResponseDto(text="")

    async def is_available(self, request) -> OutboundSTTAvailabilityResponseDto:
        return OutboundSTTAvailabilityResponseDto(is_available=True)


class MultiSegmentAudioDrivenOutboundAdapter(AdapterOutboundPort):
    def __init__(self) -> None:
        self.segment = 0

    async def process_stream(self, request) -> OutboundProcessStreamResponseDto:
        async def text_stream() -> AsyncIterator[str]:
            async for chunk in request.audio_stream:
                if chunk and any(chunk):
                    self.segment += 1
                    yield f"adapter text {self.segment}"

        return OutboundProcessStreamResponseDto(text_stream=text_stream())

    async def process_batch(self, request) -> OutboundProcessBatchResponseDto:
        self.segment += 1
        return OutboundProcessBatchResponseDto(text=f"adapter text {self.segment}")

    async def is_available(self, request) -> OutboundSTTAvailabilityResponseDto:
        return OutboundSTTAvailabilityResponseDto(is_available=True)


async def _request_events(app: FastAPI, method: str, path: str, content: bytes = b"audio") -> list[dict]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.request(method, path, content=content)
    assert response.status_code == 200
    return _parse_sse_events(response.text)


def _build_app(service: FakeService) -> FastAPI:
    app = FastAPI()
    FastApiAdapter(service, app, InitInboundAdapterDto())
    return app


async def _request_decoupled_events(app: FastAPI) -> list[dict]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        set_response = await client.post("/process/stream/set", content=b"audio")
        assert set_response.status_code == 200

        get_response = await client.get("/process/stream/get")
        assert get_response.status_code == 200

    return _parse_sse_events(get_response.text)


def test_process_stream_starts_with_stream_started() -> None:
    app = _build_app(FakeService(process_items=["hello world"]))

    events = asyncio.run(_request_events(app, "POST", "/process/stream"))

    _assert_event_shape(events[0], "stream_started", 1)
    assert events[0]["payload"] == {}


def test_process_stream_emits_no_chunks_when_no_text_is_parsed() -> None:
    app = _build_app(FakeService(process_items=[]))

    events = asyncio.run(_request_events(app, "POST", "/process/stream"))

    _assert_event_shape(events[0], "stream_started", 1)
    _assert_event_shape(events[1], "completed", 2)
    assert events[1]["payload"] == {"reason": "completed", "output": ""}


def test_process_stream_ignores_empty_adapter_text_chunks() -> None:
    app = _build_app(FakeService(process_items=["", "hello world", ""]))

    events = asyncio.run(_request_events(app, "POST", "/process/stream"))

    assert [event["type"] for event in events] == ["stream_started", "partial", "completed"]
    assert events[1]["payload"] == {"text": "hello world"}


def test_process_stream_emits_partial_and_completed_events() -> None:
    app = _build_app(FakeService(process_items=["hello world"]))

    events = asyncio.run(_request_events(app, "POST", "/process/stream"))

    _assert_event_shape(events[1], "partial", 2)
    assert events[1]["payload"] == {"text": "hello world"}
    _assert_event_shape(events[2], "completed", 3)
    assert events[2]["payload"] == {"reason": "completed", "output": "hello world"}


def test_stream_can_continue_after_completed_event() -> None:
    app = _build_app(FakeService(process_items=["first utterance", "second utterance"]))

    events = asyncio.run(_request_events(app, "POST", "/process/stream"))

    assert [event["type"] for event in events] == [
        "stream_started",
        "partial",
        "completed",
        "partial",
        "completed",
    ]
    assert events[2]["payload"]["output"] == "first utterance"
    assert events[3]["payload"]["text"] == "second utterance"


def test_get_stream_uses_same_event_contract() -> None:
    app = _build_app(FakeService(get_items=["queued utterance"]))

    events = asyncio.run(_request_events(app, "GET", "/process/stream/get", content=b""))

    _assert_event_shape(events[0], "stream_started", 1)
    _assert_event_shape(events[1], "partial", 2)
    _assert_event_shape(events[2], "completed", 3)
    assert events[2]["payload"]["output"] == "queued utterance"


def test_set_stream_returns_standard_stream_events() -> None:
    app = _build_app(FakeService())
    transport = httpx.ASGITransport(app=app)

    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/process/stream/set", content=b"audio")

    response = asyncio.run(run())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-action"] == "set_stream"
    assert response.headers["x-status"] == "accepted"
    events = _parse_sse_events(response.text)
    _assert_event_shape(events[0], "stream_started", 1)
    _assert_event_shape(events[1], "completed", 2)
    assert events[1]["payload"] == {"reason": "completed", "output": "accepted"}


def test_set_stream_decodes_ndjson_partial_audio_events() -> None:
    service = RecordingSetService()
    app = _build_app(service)
    transport = httpx.ASGITransport(app=app)
    first_chunk = b"\x01\x02\x03\x04"
    second_chunk = b"\x05\x06"
    events = [
        {"type": "stream_started", "sequence": 1, "timestamp": "2026-05-24T12:00:00Z", "payload": {}},
        {
            "type": "partial",
            "sequence": 2,
            "timestamp": "2026-05-24T12:00:01Z",
            "payload": {"bytes_base64": base64.b64encode(first_chunk).decode("ascii")},
        },
        {"type": "heartbeat", "sequence": 3, "timestamp": "2026-05-24T12:00:02Z", "payload": {}},
        {
            "type": "partial",
            "sequence": 4,
            "timestamp": "2026-05-24T12:00:03Z",
            "payload": {"bytes_base64": base64.b64encode(second_chunk).decode("ascii")},
        },
        {
            "type": "completed",
            "sequence": 5,
            "timestamp": "2026-05-24T12:00:04Z",
            "payload": {"reason": "completed"},
        },
    ]
    body = "\n".join(json.dumps(event) for event in events) + "\n"

    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/process/stream/set",
                content=body,
                headers={"Content-Type": "application/x-ndjson"},
            )

    response = asyncio.run(run())

    assert response.status_code == 200
    assert service.audio_chunks[:2] == [first_chunk, second_chunk]
    assert service.audio_chunks[2:]
    assert all(chunk == b"\x00\x00" * 1024 for chunk in service.audio_chunks[2:])


def test_set_stream_decodes_completed_audio_as_utterance_boundary() -> None:
    service = RecordingSetService()
    app = _build_app(service)
    transport = httpx.ASGITransport(app=app)
    audio = b"\x01\x02\x03\x04"
    final_audio = b"\x05\x06"
    later_audio = b"\x07\x08"
    events = [
        {
            "type": "partial",
            "sequence": 1,
            "timestamp": "2026-05-24T12:00:00Z",
            "payload": {"bytes_base64": base64.b64encode(audio).decode("ascii")},
        },
        {
            "type": "completed",
            "sequence": 2,
            "timestamp": "2026-05-24T12:00:01Z",
            "payload": {
                "reason": "completed",
                "output_bytes_base64": base64.b64encode(final_audio).decode("ascii"),
            },
        },
        {
            "type": "partial",
            "sequence": 3,
            "timestamp": "2026-05-24T12:00:02Z",
            "payload": {"bytes_base64": base64.b64encode(later_audio).decode("ascii")},
        },
    ]
    body = "\n".join(json.dumps(event) for event in events) + "\n"

    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/process/stream/set",
                content=body,
                headers={"Content-Type": "application/x-ndjson"},
            )

    response = asyncio.run(run())

    assert response.status_code == 200
    assert service.audio_chunks[0] == audio
    assert isinstance(service.audio_chunks[1], CompletedAudioSegment)
    assert service.audio_chunks[1].audio_data == final_audio
    assert service.audio_chunks[1].source_sequence == 2
    assert service.audio_chunks[-1] == later_audio
    assert service.audio_chunks[2:-1] == []


def test_get_stream_can_return_ndjson_events() -> None:
    app = _build_app(FakeService(get_items=["queued utterance"]))
    transport = httpx.ASGITransport(app=app)

    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(
                "/process/stream/get",
                headers={"Accept": "application/x-ndjson"},
            )

    response = asyncio.run(run())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = _parse_ndjson_events(response.text)
    _assert_event_shape(events[0], "stream_started", 1)
    _assert_event_shape(events[1], "partial", 2)
    _assert_event_shape(events[2], "completed", 3)
    assert events[1]["payload"] == {"text": "queued utterance"}


def test_decoupled_stream_returns_text_from_outbound_adapter_to_get_stream() -> None:
    app = FastAPI()
    service = STTService("test", FakeOutboundAdapter())
    FastApiAdapter(service, app, InitInboundAdapterDto())

    events = asyncio.run(_request_decoupled_events(app))

    assert [event["type"] for event in events] == ["stream_started", "partial", "completed"]
    assert events[1]["payload"] == {"text": "adapter text"}
    assert events[2]["payload"] == {"reason": "completed", "output": "adapter text"}


def test_decoupled_get_receives_adapter_text_while_set_connection_is_open() -> None:
    async def run() -> list[dict]:
        app = FastAPI()
        service = STTService("test", AudioDrivenOutboundAdapter())
        FastApiAdapter(service, app, InitInboundAdapterDto())
        transport = httpx.ASGITransport(app=app)

        async def audio_stream() -> AsyncIterator[bytes]:
            yield b"audio"

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as set_client:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as get_client:
                async with set_client.stream("POST", "/process/stream/set", content=audio_stream()) as set_response:
                    assert set_response.status_code == 200
                    assert set_response.headers["x-status"] == "accepted"
                    first_event = (await set_response.aiter_bytes().__anext__()).decode()
                    assert _parse_sse_events(first_event)[0]["type"] == "stream_started"

                    get_response = await get_client.get("/process/stream/get")
                    assert get_response.status_code == 200
                    return _parse_sse_events(get_response.text)

    events = asyncio.run(asyncio.wait_for(run(), timeout=5.0))

    assert [event["type"] for event in events] == ["stream_started", "partial", "completed"]
    assert events[1]["payload"] == {"text": "adapter text from live input"}


def test_decoupled_get_receives_adapter_text_after_set_connection_finishes() -> None:
    async def run() -> list[dict]:
        app = FastAPI()
        service = STTService("test", AudioDrivenOutboundAdapter())
        FastApiAdapter(service, app, InitInboundAdapterDto())
        transport = httpx.ASGITransport(app=app)

        async def audio_stream() -> AsyncIterator[bytes]:
            yield b"audio"

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with client.stream("POST", "/process/stream/set", content=audio_stream()) as set_response:
                assert set_response.status_code == 200
                assert set_response.headers["x-status"] == "accepted"
                first_event = (await set_response.aiter_bytes().__anext__()).decode()
                assert _parse_sse_events(first_event)[0]["type"] == "stream_started"

                get_response = await client.get("/process/stream/get")
                assert get_response.status_code == 200
                return _parse_sse_events(get_response.text)

    events = asyncio.run(asyncio.wait_for(run(), timeout=5.0))

    assert [event["type"] for event in events] == ["stream_started", "partial", "completed"]
    assert events[1]["payload"] == {"text": "adapter text from live input"}


def test_decoupled_get_stream_after_empty_adapter_output_does_not_emit_empty_completed() -> None:
    app = FastAPI()
    service = STTService("test", FakeOutboundAdapter(items=[]))
    FastApiAdapter(service, app, InitInboundAdapterDto())

    events = asyncio.run(_request_decoupled_events(app))

    _assert_event_shape(events[0], "stream_started", 1)
    assert len(events) == 1


def test_decoupled_get_stream_receives_two_completed_text_events_without_reconnecting() -> None:
    async def run() -> list[dict]:
        app = FastAPI()
        service = STTService("test", MultiSegmentAudioDrivenOutboundAdapter())
        FastApiAdapter(service, app, InitInboundAdapterDto())
        transport = httpx.ASGITransport(app=app)
        first_audio = b"\x01\x02\x03\x04"
        second_audio = b"\x05\x06\x07\x08"

        def completed_audio_event(sequence: int, audio: bytes) -> str:
            event = {
                "type": "completed",
                "sequence": sequence,
                "timestamp": "2026-05-24T12:00:00Z",
                "payload": {
                    "reason": "completed",
                    "output_bytes_base64": base64.b64encode(audio).decode("ascii"),
                },
            }
            return json.dumps(event)

        body = "\n".join(
            [
                completed_audio_event(1, first_audio),
                completed_audio_event(2, second_audio),
            ]
        ) + "\n"

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            set_response = await client.post(
                "/process/stream/set",
                content=body,
                headers={"Content-Type": "application/x-ndjson"},
            )
            assert set_response.status_code == 200

            async with client.stream("GET", "/process/stream/get") as get_response:
                assert get_response.status_code == 200
                body = (await get_response.aread()).decode("utf-8")
                completed_events = [
                    event
                    for event in _parse_sse_events(body)
                    if event["type"] == "completed"
                ]
                return completed_events

        raise AssertionError("GET stream ended before two completed events were received")

    completed_events = asyncio.run(asyncio.wait_for(run(), timeout=5.0))

    assert [event["sequence"] for event in completed_events] == [3, 5]
    assert [event["payload"]["output"] for event in completed_events] == [
        "adapter text 1",
        "adapter text 2",
    ]
    assert all(event["payload"]["output"] for event in completed_events)


def test_stream_error_event_shape_is_valid() -> None:
    app = _build_app(FakeService(fail_process_stream_after_text=True))

    events = asyncio.run(_request_events(app, "POST", "/process/stream"))

    _assert_event_shape(events[0], "stream_started", 1)
    _assert_event_shape(events[3], "error", 4)
    assert events[3]["payload"] == {
        "code": "stream_failed",
        "message": "transcription backend unavailable",
        "recoverable": True,
    }


def test_stream_error_before_text_emits_no_chunks() -> None:
    app = _build_app(FakeService(fail_process_stream=True))

    events = asyncio.run(_request_events(app, "POST", "/process/stream"))

    _assert_event_shape(events[0], "stream_started", 1)
    _assert_event_shape(events[1], "error", 2)
    assert events[1]["payload"] == {
        "code": "stream_failed",
        "message": "transcription backend unavailable",
        "recoverable": True,
    }


def test_sequence_numbers_are_monotonic() -> None:
    app = _build_app(FakeService(process_items=["one", "two", "three"]))

    events = asyncio.run(_request_events(app, "POST", "/process/stream"))

    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
