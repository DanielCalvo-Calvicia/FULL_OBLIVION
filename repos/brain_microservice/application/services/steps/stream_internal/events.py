import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


STREAM_EVENT_TYPES = frozenset({"stream_started", "partial", "completed", "heartbeat", "error"})


@dataclass(frozen=True, slots=True)
class StandardStreamEvent:
    type: str
    sequence: int
    timestamp: str
    payload: dict[str, Any]


def stream_started_event(sequence: int) -> StandardStreamEvent:
    return _stream_event("stream_started", sequence, {})


def text_partial_event(sequence: int, text: str) -> StandardStreamEvent:
    return _stream_event("partial", sequence, {"text": text})


def audio_partial_event(sequence: int, chunk: bytes) -> StandardStreamEvent:
    return _stream_event("partial", sequence, {"bytes_base64": base64.b64encode(chunk).decode("ascii")})


def text_completed_event(sequence: int, output: str) -> StandardStreamEvent:
    return _stream_event("completed", sequence, {"reason": "completed", "output": output})


def audio_completed_event(sequence: int, output: bytes) -> StandardStreamEvent:
    return _stream_event(
        "completed",
        sequence,
        {"reason": "completed", "output_bytes_base64": base64.b64encode(output).decode("ascii")},
    )


def stream_error_event(sequence: int, message: str, *, code: str = "stream_error", recoverable: bool = True) -> StandardStreamEvent:
    return _stream_event("error", sequence, {"code": code, "message": message, "recoverable": recoverable})


def event_text(event: StandardStreamEvent) -> str:
    text = event.payload.get("text")
    if not isinstance(text, str):
        raise RuntimeError("text stream event payload missing text")
    return text


def event_completed_text(event: StandardStreamEvent) -> str:
    output = event.payload.get("output")
    if not isinstance(output, str):
        raise RuntimeError("text completion event payload missing output")
    return output


def event_audio(event: StandardStreamEvent, field_name: str = "bytes_base64") -> bytes:
    encoded = event.payload.get(field_name)
    if not isinstance(encoded, str):
        raise RuntimeError(f"audio stream event payload missing {field_name}")
    try:
        return base64.b64decode(encoded)
    except ValueError as exc:
        raise RuntimeError(f"audio stream event payload {field_name} was invalid base64") from exc


def validate_internal_stream_event(event: StandardStreamEvent, expected_sequence: int) -> None:
    if event.type not in STREAM_EVENT_TYPES:
        raise RuntimeError(f"internal stream event type was unknown: {event.type}")
    if event.sequence != expected_sequence:
        raise RuntimeError(f"internal stream event sequence must be {expected_sequence}, received {event.sequence}")
    if expected_sequence == 1 and event.type != "stream_started":
        raise RuntimeError("internal stream event sequence 1 must be stream_started")
    if not event.timestamp.endswith("Z"):
        raise RuntimeError("internal stream event timestamp must be UTC ISO-8601 ending in Z")
    try:
        datetime.fromisoformat(event.timestamp.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise RuntimeError("internal stream event timestamp was not valid ISO-8601") from exc
    if not isinstance(event.payload, dict):
        raise RuntimeError("internal stream event payload must be an object")


def _stream_event(event_type: str, sequence: int, payload: dict[str, Any]) -> StandardStreamEvent:
    if event_type not in STREAM_EVENT_TYPES:
        raise RuntimeError(f"unknown stream event type: {event_type}")
    if sequence < 1:
        raise RuntimeError("stream event sequence must be positive")
    return StandardStreamEvent(
        type=event_type,
        sequence=sequence,
        timestamp=datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        payload=payload,
    )
