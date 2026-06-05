import json
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from runtime.logger import get_logger


logger = get_logger(__name__)

VALID_EVENT_TYPES = {"stream_started", "partial", "completed", "heartbeat", "error"}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def standard_stream_event(event_type: str, sequence: int, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unknown stream event type: {event_type}")

    return {
        "type": event_type,
        "sequence": sequence,
        "timestamp": _utc_timestamp(),
        "payload": payload,
    }


def sse_stream_event(event_type: str, sequence: int, payload: dict[str, Any]) -> str:
    event = standard_stream_event(event_type, sequence, payload)
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


def ndjson_stream_event(event_type: str, sequence: int, payload: dict[str, Any]) -> str:
    event = standard_stream_event(event_type, sequence, payload)
    return f"{json.dumps(event, separators=(',', ':'))}\n"


async def text_event_stream(
    text_stream: AsyncIterator[str],
    *,
    completion_reason: str = "completed",
    formatter=sse_stream_event,
    emit_empty_completion_on_end: bool = True,
    heartbeat_interval_seconds: float | None = None,
) -> AsyncIterator[str]:
    sequence = 1
    emitted_text = False
    body = formatter("stream_started", sequence, {})
    logger.info("Emitting STT stream event: bytes=%s body=%r.", len(body.encode("utf-8")), body)
    yield body

    iterator = text_stream.__aiter__()
    pending_text: asyncio.Task[str] | None = None

    try:
        pending_text = asyncio.create_task(iterator.__anext__())
        while True:
            if heartbeat_interval_seconds is None:
                done, _pending = await asyncio.wait({pending_text}, return_when=asyncio.FIRST_COMPLETED)
            else:
                done, _pending = await asyncio.wait(
                    {pending_text},
                    timeout=heartbeat_interval_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )

            if not done:
                sequence += 1
                body = formatter("heartbeat", sequence, {})
                logger.info("Emitting STT stream event: bytes=%s body=%r.", len(body.encode("utf-8")), body)
                yield body
                continue

            try:
                text = pending_text.result()
            except StopAsyncIteration:
                break

            if not text:
                logger.debug("Skipping empty transcription chunk from adapter.")
                pending_text = asyncio.create_task(iterator.__anext__())
                continue

            sequence += 1
            emitted_text = True
            logger.info("Streaming transcription partial event: text_length=%s.", len(text))
            body = formatter("partial", sequence, {"text": text})
            logger.info("Emitting STT stream event: bytes=%s body=%r.", len(body.encode("utf-8")), body)
            yield body

            sequence += 1
            body = formatter(
                "completed",
                sequence,
                {
                    "reason": completion_reason,
                    "output": text,
                },
            )
            logger.info("Emitting STT stream event: bytes=%s body=%r.", len(body.encode("utf-8")), body)
            yield body
            pending_text = asyncio.create_task(iterator.__anext__())

        if emit_empty_completion_on_end and not emitted_text:
            sequence += 1
            body = formatter(
                "completed",
                sequence,
                {
                    "reason": completion_reason,
                    "output": "",
                },
            )
            logger.info("Emitting STT stream event: bytes=%s body=%r.", len(body.encode("utf-8")), body)
            yield body
    except Exception as exc:
        logger.exception("Streaming transcription failed.")
        sequence += 1
        body = formatter(
            "error",
            sequence,
            {
                "code": "stream_failed",
                "message": str(exc),
                "recoverable": True,
            },
        )
        logger.info("Emitting STT stream event: bytes=%s body=%r.", len(body.encode("utf-8")), body)
        yield body
    finally:
        if pending_text is not None and not pending_text.done():
            pending_text.cancel()
            with suppress(asyncio.CancelledError):
                await pending_text
