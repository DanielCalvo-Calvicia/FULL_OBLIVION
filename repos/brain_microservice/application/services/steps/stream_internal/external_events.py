import base64
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from domain.console import console_log
from domain.errors import ExternalServiceInvalidResponseError, ExternalServiceUnavailableError

from .events import StandardStreamEvent, validate_internal_stream_event

TEXT_PARTIAL_CHUNK_CHARS = 4096


async def ndjson_events(byte_stream: AsyncIterator[bytes], *, service_name: str) -> AsyncIterator[StandardStreamEvent]:
    buffer = ""
    expected_sequence = 1
    try:
        async for chunk in byte_stream:
            buffer += chunk.decode("utf-8", errors="ignore")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                event = parse_external_stream_event(line, service_name=service_name)
                validate_external_stream_event(event, expected_sequence, service_name=service_name)
                expected_sequence += 1
                yield event
    finally:
        close = getattr(byte_stream, "aclose", None)
        if close is not None:
            await close()

    tail = buffer.strip()
    if tail:
        event = parse_external_stream_event(tail, service_name=service_name)
        validate_external_stream_event(event, expected_sequence, service_name=service_name)
        yield event


async def sse_events(byte_stream: AsyncIterator[bytes], *, service_name: str) -> AsyncIterator[StandardStreamEvent]:
    buffer = ""
    data_lines: list[str] = []
    expected_sequence = 1
    try:
        async for chunk in byte_stream:
            buffer += chunk.decode("utf-8", errors="ignore")
            while "\n" in buffer:
                raw_line, buffer = buffer.split("\n", 1)
                line = raw_line.rstrip("\r")
                if not line.strip():
                    if data_lines:
                        event = parse_external_stream_event("\n".join(data_lines), service_name=service_name)
                        validate_external_stream_event(event, expected_sequence, service_name=service_name)
                        expected_sequence += 1
                        yield event
                        data_lines.clear()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())
    except ExternalServiceUnavailableError as exc:
        if "incomplete chunked read" not in exc.message:
            raise
        console_log("stream-internal", "external SSE stream closed without final chunk", service=service_name)
    finally:
        close = getattr(byte_stream, "aclose", None)
        if close is not None:
            await close()

    tail = buffer.strip()
    if tail.startswith("data:"):
        data_lines.append(tail.removeprefix("data:").strip())
    if data_lines:
        event = parse_external_stream_event("\n".join(data_lines), service_name=service_name)
        validate_external_stream_event(event, expected_sequence, service_name=service_name)
        yield event


async def binary_stream_as_ndjson_events(byte_stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    sequence = 1
    chunks: list[bytes] = []
    yield stream_event_bytes("stream_started", sequence, {})
    sequence += 1
    async for chunk in byte_stream:
        if not chunk:
            continue
        chunks.append(chunk)
        yield stream_event_bytes("partial", sequence, {"bytes_base64": base64.b64encode(chunk).decode("ascii")})
        sequence += 1
    yield stream_event_bytes(
        "completed",
        sequence,
        {"reason": "completed", "output_bytes_base64": base64.b64encode(b"".join(chunks)).decode("ascii")},
    )


async def text_stream_as_ndjson_events(
    text_stream: AsyncIterator[str],
    *,
    partial_chunk_chars: int = TEXT_PARTIAL_CHUNK_CHARS,
) -> AsyncIterator[bytes]:
    sequence = 1
    yield stream_event_bytes("stream_started", sequence, {})
    sequence += 1
    async for text in text_stream:
        cleaned = text.strip()
        if not cleaned:
            continue
        if len(cleaned) > partial_chunk_chars:
            for index, chunk in enumerate(_text_chunks(cleaned, partial_chunk_chars), start=1):
                yield stream_event_bytes(
                    "partial",
                    sequence,
                    {"text": chunk, "chunk_index": index},
                )
                sequence += 1
        yield stream_event_bytes("completed", sequence, {"reason": "completed", "output": cleaned})
        sequence += 1


def _text_chunks(text: str, chunk_chars: int) -> list[str]:
    if chunk_chars <= 0:
        return [text]
    return [text[index : index + chunk_chars] for index in range(0, len(text), chunk_chars)]


def decode_event_audio(event: StandardStreamEvent, field_name: str = "bytes_base64") -> bytes:
    encoded = event.payload.get(field_name)
    if not isinstance(encoded, str):
        raise ExternalServiceInvalidResponseError(event.type, f"stream event payload missing {field_name}")
    try:
        return base64.b64decode(encoded)
    except ValueError as exc:
        raise ExternalServiceInvalidResponseError(event.type, f"stream event payload {field_name} was invalid base64") from exc


def decode_completed_audio(event: StandardStreamEvent) -> bytes:
    for field_name in ("bytes_base64", "output_bytes_base64"):
        if isinstance(event.payload.get(field_name), str):
            return decode_event_audio(event, field_name)
    return b""


def parse_external_stream_event(raw_event: str, *, service_name: str) -> StandardStreamEvent:
    try:
        data = json.loads(raw_event)
    except ValueError as exc:
        raise ExternalServiceInvalidResponseError(service_name, "stream event was not valid JSON") from exc

    if not isinstance(data, dict):
        raise ExternalServiceInvalidResponseError(service_name, "stream event was not a JSON object")

    event_type = data.get("type")
    sequence = data.get("sequence")
    timestamp = data.get("timestamp")
    payload = data.get("payload")
    if (
        not isinstance(event_type, str)
        or not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or not isinstance(timestamp, str)
        or not isinstance(payload, dict)
    ):
        raise ExternalServiceInvalidResponseError(
            service_name,
            "stream event missing required type, sequence, timestamp, or payload fields",
        )
    return StandardStreamEvent(event_type, sequence, timestamp, payload)


def validate_external_stream_event(event: StandardStreamEvent, expected_sequence: int, *, service_name: str) -> None:
    try:
        validate_internal_stream_event(event, expected_sequence)
    except RuntimeError as exc:
        raise ExternalServiceInvalidResponseError(service_name, str(exc)) from exc


def raise_for_stream_error(event: StandardStreamEvent, *, service_name: str) -> None:
    code = event.payload.get("code", "stream_error")
    message = event.payload.get("message", "stream returned an error event")
    raise ExternalServiceUnavailableError(service_name, f"{code}: {message}")


def stream_event_bytes(event_type: str, sequence: int, payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            {
                "type": event_type,
                "sequence": sequence,
                "timestamp": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "payload": payload,
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
