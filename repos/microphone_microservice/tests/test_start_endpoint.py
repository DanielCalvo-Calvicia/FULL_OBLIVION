import base64
import json
import struct
from collections.abc import AsyncIterator, Callable, Iterable
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from application.dtos.services_dtos import (
    MicrophoneAvailabilityRequestDto,
    MicrophoneAvailabilityResponseDto,
    StartMicrophoneStreamRequestDto,
    StartMicrophoneStreamResponseDto,
    StopMicrophoneStreamRequestDto,
    StopMicrophoneStreamResponseDto,
)
from application.ports.service_port import ServicePort
from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter

STANDARD_EVENT_TYPES = {"stream_started", "partial", "completed", "heartbeat", "error"}


async def _fake_audio_stream(chunks: Iterable[bytes] | None = None) -> AsyncIterator[bytes]:
    for chunk in chunks or [b"pcm-bytes"]:
        yield chunk


async def _failing_audio_stream() -> AsyncIterator[bytes]:
    yield b"before-error"
    raise RuntimeError("simulated stream failure")


def _pcm16(*samples: int) -> bytes:
    return struct.pack("<" + ("h" * len(samples)), *samples)


class FakeMicrophoneService(ServicePort):
    def __init__(
        self,
        chunks: Iterable[bytes] | None = None,
        stream_factory: Callable[[], AsyncIterator[bytes]] | None = None,
    ) -> None:
        self.chunks = chunks
        self.stream_factory = stream_factory

    def _stream(self) -> AsyncIterator[bytes]:
        if self.stream_factory is not None:
            return self.stream_factory()
        return _fake_audio_stream(self.chunks)

    async def start_stream(
        self,
        request: StartMicrophoneStreamRequestDto,
    ) -> StartMicrophoneStreamResponseDto:
        return StartMicrophoneStreamResponseDto(
            stream=self._stream(),
            sample_rate=request.sample_rate,
        )

    async def stop_stream(
        self,
        request: StopMicrophoneStreamRequestDto,
    ) -> StopMicrophoneStreamResponseDto:
        return StopMicrophoneStreamResponseDto(success=True)

    async def is_available(
        self,
        request: MicrophoneAvailabilityRequestDto,
    ) -> MicrophoneAvailabilityResponseDto:
        return MicrophoneAvailabilityResponseDto(is_available=True)

def test_start_endpoint_stream_starts_with_stream_started():
    events, response = _read_start_events(FakeMicrophoneService())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["x-action"] == "start_stream"
    assert response.headers["x-sample-rate"] == "16000"
    assert events[0]["type"] == "stream_started"
    assert events[0]["sequence"] == 1
    assert events[0]["payload"] == {}


def test_start_endpoint_emits_partial_audio_output_events():
    chunk = _pcm16(1000, 1200)
    events, _ = _read_start_events(FakeMicrophoneService(chunks=[chunk]))

    partial = _event_of_type(events, "partial")
    assert partial["payload"] == {
        "bytes_base64": base64.b64encode(chunk).decode("ascii")
    }


def test_start_endpoint_emits_completed_after_two_seconds_of_silence():
    speech = _pcm16(1000, 1200, 1000, 1200)
    one_second_silence = _pcm16(0, 0, 0, 0)
    chunks = [speech, one_second_silence, one_second_silence]

    events, _ = _read_start_events(
        FakeMicrophoneService(chunks=chunks),
        sample_rate=4,
    )
    completed_events = [event for event in events if event["type"] == "completed"]

    assert len(completed_events) == 1
    assert completed_events[0]["payload"] == {
        "reason": "completed",
        "output_bytes_base64": base64.b64encode(speech).decode("ascii"),
    }


def test_start_endpoint_does_not_emit_partial_events_for_silence():
    speech = _pcm16(1000, 1200, 1000, 1200)
    one_second_silence = _pcm16(0, 0, 0, 0)
    events, _ = _read_start_events(
        FakeMicrophoneService(chunks=[speech, one_second_silence, one_second_silence]),
        sample_rate=4,
    )
    event_types = [event["type"] for event in events]

    assert event_types == ["stream_started", "partial", "completed"]


def test_start_endpoint_treats_quiet_spikes_as_silence_for_completion():
    speech = _pcm16(1000, 1200, 1000, 1200)
    quiet_with_spike = _pcm16(0, 0, 0, 600)
    chunks = [speech, quiet_with_spike, quiet_with_spike]

    events, _ = _read_start_events(
        FakeMicrophoneService(chunks=chunks),
        sample_rate=4,
    )

    assert [event["type"] for event in events] == ["stream_started", "partial", "completed"]
    assert _event_of_type(events, "completed")["payload"] == {
        "reason": "completed",
        "output_bytes_base64": base64.b64encode(speech).decode("ascii"),
    }


def test_start_endpoint_does_not_complete_when_only_silence_is_received():
    one_second_silence = _pcm16(0, 0, 0, 0)
    events, _ = _read_start_events(
        FakeMicrophoneService(chunks=[one_second_silence, one_second_silence]),
        sample_rate=4,
    )

    assert [event["type"] for event in events] == ["stream_started"]


def test_start_endpoint_resets_silence_timer_when_audio_resumes():
    speech_a = _pcm16(1000, 1200, 1000, 1200)
    speech_b = _pcm16(1300, 1400, 1300, 1400)
    one_second_silence = _pcm16(0, 0, 0, 0)
    chunks = [speech_a, one_second_silence, speech_b, one_second_silence, one_second_silence]

    events, _ = _read_start_events(
        FakeMicrophoneService(chunks=chunks),
        sample_rate=4,
    )
    completed = _event_of_type(events, "completed")

    assert completed["payload"]["output_bytes_base64"] == base64.b64encode(speech_a + speech_b).decode("ascii")


def test_start_endpoint_can_complete_multiple_recording_segments():
    speech_a = _pcm16(1000, 1200, 1000, 1200)
    speech_b = _pcm16(1300, 1400, 1300, 1400)
    one_second_silence = _pcm16(0, 0, 0, 0)
    chunks = [
        speech_a,
        one_second_silence,
        one_second_silence,
        speech_b,
        one_second_silence,
        one_second_silence,
    ]

    events, _ = _read_start_events(
        FakeMicrophoneService(chunks=chunks),
        sample_rate=4,
    )
    completed_events = [event for event in events if event["type"] == "completed"]

    assert [event["type"] for event in events] == [
        "stream_started",
        "partial",
        "completed",
        "partial",
        "completed",
    ]
    assert completed_events[0]["payload"]["output_bytes_base64"] == base64.b64encode(speech_a).decode("ascii")
    assert completed_events[1]["payload"]["output_bytes_base64"] == base64.b64encode(speech_b).decode("ascii")


def test_start_endpoint_error_event_shape_is_valid():
    events, _ = _read_start_events(FakeMicrophoneService(stream_factory=_failing_audio_stream))
    error = _event_of_type(events, "error")

    assert error["payload"] == {
        "code": "audio_stream_failed",
        "message": "Audio stream failed while producing events.",
        "recoverable": True,
    }


def test_start_endpoint_sequence_numbers_are_monotonic():
    events, _ = _read_start_events(
        FakeMicrophoneService(chunks=[_pcm16(1000), _pcm16(1200)])
    )

    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))


def test_start_endpoint_can_stream_sse_wrapped_standard_events():
    chunk = _pcm16(1000, 1200)
    app = FastAPI()
    FastApiAdapter(service_port=FakeMicrophoneService(chunks=[chunk]), app=app)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/start",
        headers={"Accept": "text/event-stream"},
        json={"sample_rate": 16000, "channels": 1, "chunk_size": 1024},
    ) as response:
        body = response.read()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(body)
    assert events[0]["type"] == "stream_started"
    assert events[1]["payload"] == {
        "bytes_base64": base64.b64encode(chunk).decode("ascii")
    }
    assert events[2]["payload"] == {
        "reason": "completed",
        "output_bytes_base64": base64.b64encode(chunk).decode("ascii"),
    }


def test_stream_endpoint_is_not_registered():
    app = FastAPI()
    FastApiAdapter(service_port=FakeMicrophoneService(), app=app)
    client = TestClient(app)

    response = client.get("/stream")

    assert response.status_code == 404


def _read_start_events(service, sample_rate: int = 16000):
    app = FastAPI()
    FastApiAdapter(service_port=service, app=app)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/start",
        json={"sample_rate": sample_rate, "channels": 1, "chunk_size": 1024},
    ) as response:
        body = response.read()

    return _parse_events(body), response


def _parse_events(body):
    events = [json.loads(line) for line in body.decode("utf-8").splitlines()]
    for event in events:
        assert set(event) == {"type", "sequence", "timestamp", "payload"}
        assert event["type"] in STANDARD_EVENT_TYPES
        assert isinstance(event["sequence"], int)
        assert event["timestamp"].endswith("Z")
        datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        assert isinstance(event["payload"], dict)
        _assert_payload_shape(event)
    return events


def _event_of_type(events, event_type):
    return next(event for event in events if event["type"] == event_type)


def _parse_sse_events(body):
    events = []
    frames = [frame for frame in body.decode("utf-8").split("\n\n") if frame]
    for frame in frames:
        lines = frame.splitlines()
        assert len(lines) == 1
        assert lines[0].startswith("data:")
        assert not lines[0].startswith("data: ")
        events.extend(_parse_events((lines[0][len("data:"):] + "\n").encode("utf-8")))
    return events


def _assert_payload_shape(event):
    payload = event["payload"]
    if event["type"] == "stream_started":
        assert payload == {}
    elif event["type"] == "partial":
        assert set(payload) == {"bytes_base64"}
        base64.b64decode(payload["bytes_base64"], validate=True)
    elif event["type"] == "completed":
        assert set(payload) == {"reason", "output_bytes_base64"}
        assert payload["reason"] == "completed"
        base64.b64decode(payload["output_bytes_base64"], validate=True)
    elif event["type"] == "error":
        assert set(payload) == {"code", "message", "recoverable"}
        assert isinstance(payload["code"], str)
        assert isinstance(payload["message"], str)
        assert isinstance(payload["recoverable"], bool)
    elif event["type"] == "heartbeat":
        assert payload == {}
