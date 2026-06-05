import asyncio
import base64
import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, AsyncIterator, Literal, Optional

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import ClientDisconnect

from application.ports.adapter_inbound_port import AdapterInboundPort
from application.ports.service_port import ServicePort
from application.dtos.stream_items import AudioSegmentEnd, AudioStreamError

from application.dtos.adapter_inbound_dtos import (
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    TTSAvailabilityRequestDto,
    TTSAvailabilityResponseDto,
    InitInboundAdapterDto,
    SetStreamRequestDto,
    GetStreamRequestDto,
    GetStreamResponseDto,
)

from application.dtos.mapper.adapter_inbound_to_service import (
    map_inbound_to_service_stream_request,
    map_inbound_to_service_batch_request,
    map_inbound_to_service_availability_request,
    map_inbound_to_service_set_stream_request,
    map_inbound_to_service_get_stream_request,
)

from application.dtos.mapper.service_to_adapter_inbound import (
    map_service_to_inbound_stream_response,
    map_service_to_inbound_batch_response,
    map_service_to_inbound_availability_response,
    map_service_to_inbound_get_stream_response,
)
from infrastructure.logger import get_logger


logger = get_logger(__name__)

STREAM_MEDIA_TYPE = "application/x-ndjson"
SSE_MEDIA_TYPE = "text/event-stream"
STREAM_EVENT_TYPES = {"stream_started", "partial", "completed", "heartbeat", "error"}
StreamPayloadKind = Literal["text", "audio"]
StreamResponseFormat = Literal["ndjson", "sse"]


class _DuplexStreamingResponse(StreamingResponse):
    """StreamingResponse variant that does not concurrently consume ASGI receive.

    Starlette's default StreamingResponse listens for disconnects by reading from
    the ASGI receive channel. For /process/stream/set, the response body iterator
    must read the request body stream, so the default disconnect listener can
    compete with request.stream().
    """

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        async for chunk in self.body_iterator:
            if not isinstance(chunk, bytes):
                chunk = chunk.encode(self.charset)
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        if self.background is not None:
            await self.background()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class _StreamEventEncoder:
    def __init__(self, response_format: StreamResponseFormat = "ndjson") -> None:
        self.sequence = 0
        self.response_format = response_format

    def encode(self, event_type: str, payload: dict[str, Any]) -> bytes:
        if event_type not in STREAM_EVENT_TYPES:
            raise ValueError(f"Unknown stream event type: {event_type}")
        if not isinstance(payload, dict):
            raise ValueError("Stream event payload must be an object")
        self.sequence += 1
        event = {
            "type": event_type,
            "sequence": self.sequence,
            "timestamp": _utc_timestamp(),
            "payload": payload,
        }
        event_json = json.dumps(event, separators=(",", ":"))
        if self.response_format == "sse":
            return f"event: {event_type}\ndata: {event_json}\n\n".encode("utf-8")
        return (event_json + "\n").encode("utf-8")


def _stream_response_format(request: Request) -> StreamResponseFormat:
    accept = request.headers.get("accept", "")
    if STREAM_MEDIA_TYPE in accept:
        return "ndjson"
    return "sse"


def _stream_media_type(response_format: StreamResponseFormat) -> str:
    if response_format == "sse":
        return SSE_MEDIA_TYPE
    return STREAM_MEDIA_TYPE


def _validate_utc_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be a UTC ISO-8601 string ending with Z")
    datetime.fromisoformat(value[:-1] + "+00:00")


def _validate_stream_event_shape(
    event: Any,
    *,
    expected_sequence: int,
    payload_kind: StreamPayloadKind,
) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("each stream event must be a JSON object")

    event_type = event.get("type")
    if event_type not in STREAM_EVENT_TYPES:
        raise ValueError("unknown stream event type")
    if event.get("sequence") != expected_sequence:
        raise ValueError("stream event sequence must start at 1 and increment by 1")
    _validate_utc_timestamp(event.get("timestamp"))

    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("stream event payload must be an object")

    if event_type == "stream_started" and payload != {}:
        raise ValueError("stream_started payload must be an empty object")
    if event_type == "partial":
        if payload_kind == "text":
            if set(payload.keys()) != {"text"} or not isinstance(payload.get("text"), str):
                raise ValueError("text partial payload must contain only a text string")
        elif payload_kind == "audio":
            if set(payload.keys()) != {"bytes_base64"} or not isinstance(payload.get("bytes_base64"), str):
                raise ValueError("audio partial payload must contain only bytes_base64")
    if event_type == "completed":
        if payload_kind == "text":
            if set(payload.keys()) != {"reason", "output"}:
                raise ValueError("text completed payload must contain reason and output")
            if payload.get("reason") != "completed" or not isinstance(payload.get("output"), str):
                raise ValueError("text completed payload must use reason=completed and string output")
        elif payload_kind == "audio":
            if set(payload.keys()) != {"reason", "output_bytes_base64"}:
                raise ValueError("audio completed payload must contain reason and output_bytes_base64")
            if payload.get("reason") != "completed" or not isinstance(payload.get("output_bytes_base64"), str):
                raise ValueError("audio completed payload must use reason=completed and output_bytes_base64")
    if event_type == "error":
        if set(payload.keys()) != {"code", "message", "recoverable"}:
            raise ValueError("error payload must contain code, message, and recoverable")
        if (
            not isinstance(payload.get("code"), str)
            or not isinstance(payload.get("message"), str)
            or not isinstance(payload.get("recoverable"), bool)
        ):
            raise ValueError("error payload fields have invalid types")
    if event_type == "heartbeat" and payload != {}:
        raise ValueError("heartbeat payload must be an empty object")

    return event


def _parse_text_stream_events(body_bytes: bytes) -> list[str]:
    lines = [line for line in body_bytes.decode("utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError("stream body must contain NDJSON stream events")

    text_chunks: list[str] = []
    completed_seen = False
    started_seen = False

    for index, line in enumerate(lines, start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("stream body must be NDJSON with one complete JSON object per line") from exc

        event = _validate_stream_event_shape(event, expected_sequence=index, payload_kind="text")
        event_type = event["type"]

        if index == 1 and event_type != "stream_started":
            raise ValueError("first stream event must be stream_started")
        if index > 1 and not started_seen:
            raise ValueError("stream_started event is required")
        if completed_seen:
            raise ValueError("completed must be the final input stream event")

        if event_type == "stream_started":
            if started_seen:
                raise ValueError("stream_started may only be emitted once")
            started_seen = True
        elif event_type == "partial":
            text_chunks.append(event["payload"]["text"])
        elif event_type == "completed":
            completed_seen = True
        elif event_type in {"heartbeat", "error"}:
            raise ValueError(f"{event_type} events are not accepted in text stream input")

    if not completed_seen:
        raise ValueError("text stream input must end with a completed event")

    return text_chunks


class _TextStreamQueue(AsyncIterator[str]):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def put(self, text: str) -> None:
        await self._queue.put(text)

    async def close(self) -> None:
        await self._queue.put(None)

    def __aiter__(self) -> "_TextStreamQueue":
        return self

    async def __anext__(self) -> str:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


def _combine_text_parts(partials: list[str], completed_output: str) -> str:
    partial_text = "".join(partials)
    if not completed_output:
        return partial_text
    if not partial_text:
        return completed_output
    if completed_output == partial_text:
        return completed_output
    return partial_text + completed_output


def _stream_error_payload(code: str, message: str, recoverable: bool = True) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "recoverable": recoverable,
    }


async def _iter_ndjson_events(request: Request) -> AsyncIterator[dict[str, Any]]:
    buffer = ""
    expected_sequence = 1
    started_seen = False

    async for chunk in request.stream():
        if not chunk:
            continue
        buffer += chunk.decode("utf-8")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                raw_event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("stream body must be NDJSON with one complete JSON object per line") from exc

            event = _validate_stream_event_shape(
                raw_event,
                expected_sequence=expected_sequence,
                payload_kind="text",
            )
            event_type = event["type"]
            if expected_sequence == 1 and event_type != "stream_started":
                raise ValueError("first stream event must be stream_started")
            if expected_sequence > 1 and not started_seen:
                raise ValueError("stream_started event is required")
            if event_type == "stream_started":
                if started_seen:
                    raise ValueError("stream_started may only be emitted once")
                started_seen = True

            expected_sequence += 1
            yield event

    if buffer.strip():
        try:
            raw_event = json.loads(buffer.strip())
        except json.JSONDecodeError as exc:
            raise ValueError("stream body must be NDJSON with one complete JSON object per line") from exc

        event = _validate_stream_event_shape(
            raw_event,
            expected_sequence=expected_sequence,
            payload_kind="text",
        )
        event_type = event["type"]
        if expected_sequence == 1 and event_type != "stream_started":
            raise ValueError("first stream event must be stream_started")
        if expected_sequence > 1 and not started_seen:
            raise ValueError("stream_started event is required")
        if event_type == "stream_started" and started_seen:
            raise ValueError("stream_started may only be emitted once")
        if event_type == "stream_started":
            started_seen = True
        yield event

    if not started_seen:
        raise ValueError("stream_started event is required")


async def _audio_event_stream(
    audio_stream: AsyncIterator[Any],
    *,
    action: str,
    response_format: StreamResponseFormat = "ndjson",
    keep_open_after_completed: bool = False,
    heartbeat_interval_seconds: float = 15.0,
) -> AsyncGenerator[bytes, None]:
    encoder = _StreamEventEncoder(response_format)
    combined_audio = bytearray()
    chunk_index = 0
    terminal_error_sent = False

    yield encoder.encode("stream_started", {})

    try:
        iterator = audio_stream.__aiter__()
        pending_item: Optional[asyncio.Task[Any]] = None

        while True:
            if pending_item is None:
                pending_item = asyncio.create_task(iterator.__anext__())

            if keep_open_after_completed:
                done, _ = await asyncio.wait(
                    {pending_item},
                    timeout=heartbeat_interval_seconds if heartbeat_interval_seconds > 0 else None,
                )
                if not done:
                    yield encoder.encode("heartbeat", {})
                    continue
            else:
                done, _ = await asyncio.wait({pending_item})

            try:
                item = pending_item.result()
            except StopAsyncIteration:
                pending_item = None
                break
            pending_item = None

            if isinstance(item, AudioStreamError):
                yield encoder.encode(
                    "error",
                    {
                        "code": item.code,
                        "message": item.message,
                        "recoverable": item.recoverable,
                    },
                )
                terminal_error_sent = True
                break

            if isinstance(item, AudioSegmentEnd):
                yield encoder.encode(
                    "completed",
                    {
                        "reason": "completed",
                        "output_bytes_base64": base64.b64encode(bytes(combined_audio)).decode("ascii"),
                        "total_bytes": len(combined_audio),
                        "chunk_count": chunk_index,
                    },
                )
                combined_audio = bytearray()
                chunk_index = 0
                continue

            chunk = item
            combined_audio.extend(chunk)
            chunk_index += 1
            yield encoder.encode(
                "partial",
                {
                    "bytes_base64": base64.b64encode(chunk).decode("ascii"),
                    "byte_count": len(chunk),
                    "chunk_index": chunk_index,
                },
            )

        if not terminal_error_sent and (combined_audio or chunk_index):
            yield encoder.encode(
                "completed",
                {
                    "reason": "completed",
                    "output_bytes_base64": base64.b64encode(bytes(combined_audio)).decode("ascii"),
                    "total_bytes": len(combined_audio),
                    "chunk_count": chunk_index,
                },
            )

        while keep_open_after_completed:
            await asyncio.sleep(heartbeat_interval_seconds)
            yield encoder.encode("heartbeat", {})
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("HTTP %s event stream failed", action)
        yield encoder.encode(
            "error",
            _stream_error_payload("stream_failed", f"Failed to stream {action}: {str(exc)}"),
        )


async def _set_stream_response(
    request: Request,
    *,
    adapter: "FastApiAdapter",
    sample_rate: int,
    channels: int,
    response_format: StreamResponseFormat,
) -> AsyncGenerator[bytes, None]:
    encoder = _StreamEventEncoder(response_format)
    text_queue: Optional[_TextStreamQueue] = None
    partials: list[str] = []
    completed_count = 0
    stream_started_sent = False
    terminal_error_sent = False

    try:
        async for event in _iter_ndjson_events(request):
            event_type = event["type"]
            payload = event["payload"]

            if event_type == "stream_started":
                text_queue = _TextStreamQueue()
                request_dto = SetStreamRequestDto(
                    text_stream=text_queue,
                    sample_rate=sample_rate,
                    channels=channels,
                )
                await adapter.set_stream(request_dto)
                stream_started_sent = True
                logger.info("HTTP POST /process/stream/set initialized live stream queue")
                yield encoder.encode("stream_started", {})
            elif event_type == "heartbeat":
                logger.info("HTTP POST /process/stream/set received heartbeat")
            elif event_type == "error":
                logger.warning(
                    "HTTP POST /process/stream/set received upstream stream error code=%s message=%s recoverable=%s",
                    payload["code"],
                    payload["message"],
                    payload["recoverable"],
                )
                yield encoder.encode("error", payload)
                terminal_error_sent = True
                break
            elif event_type == "partial":
                partials.append(payload["text"])
                logger.info(
                    "HTTP POST /process/stream/set received partial text_length=%s buffered_partials=%s",
                    len(payload["text"]),
                    len(partials),
                )
            elif event_type == "completed":
                if text_queue is None:
                    raise ValueError("stream_started event is required")
                full_text = _combine_text_parts(partials, payload["output"])
                completed_count += 1
                logger.info(
                    "HTTP POST /process/stream/set received completed completed_count=%s partials=%s output_length=%s full_text_length=%s",
                    completed_count,
                    len(partials),
                    len(payload["output"]),
                    len(full_text),
                )
                if full_text:
                    await text_queue.put(full_text)
                    logger.info(
                        "HTTP POST /process/stream/set queued completed text full_text_length=%s",
                        len(full_text),
                    )
                partials = []

        logger.info(
            "HTTP POST /process/stream/set request body ended completed_count=%s",
            completed_count,
        )
        if stream_started_sent and not terminal_error_sent:
            yield encoder.encode("completed", {"reason": "completed", "output": "accepted"})
    except ClientDisconnect:
        logger.warning("HTTP POST /process/stream/set client disconnected while reading request body")
        if stream_started_sent:
            yield encoder.encode(
                "error",
                _stream_error_payload(
                    "client_disconnected",
                    "Client disconnected before the request could be completed.",
                    recoverable=True,
                ),
            )
    except ValueError as exc:
        logger.warning("HTTP POST /process/stream/set rejected invalid stream events: %s", exc)
        yield encoder.encode(
            "error",
            _stream_error_payload("protocol_error", str(exc), recoverable=False),
        )
    except Exception as exc:
        logger.exception("HTTP POST /process/stream/set failed")
        yield encoder.encode(
            "error",
            _stream_error_payload("stream_failed", f"Failed to set stream: {str(exc)}"),
        )
    finally:
        if text_queue is not None:
            await text_queue.close()


def _client_disconnect_response(action: str) -> JSONResponse:
    return JSONResponse(
        status_code=499,
        content={
            "action": action,
            "status": "client_disconnected",
            "status_code": 499,
            "message": "Client disconnected before the request could be completed.",
            "timestamp": time.time(),
            "data": None,
        },
    )


class FastApiAdapter(AdapterInboundPort):
    def __init__(self, service_port: ServicePort, app: FastAPI, config: InitInboundAdapterDto):
        self.service_port = service_port
        self.app = app
        self.config = config
        logger.info("FastApiAdapter initialized service_port=%s", type(service_port).__name__)
        self.register_routes(self.app)

    def register_routes(self, app: FastAPI) -> None:
        logger.info("Registering FastAPI routes")

        @app.get("/health", tags=["Health"])
        async def health_check():
            logger.info("HTTP GET /health received")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "action": "health_check",
                    "status": "success",
                    "status_code": status.HTTP_200_OK,
                    "message": "Service is healthy",
                    "timestamp": time.time(),
                    "data": None
                }
            )

        @app.get("/available", status_code=status.HTTP_200_OK)
        async def handle_check_availability():
            logger.info("HTTP GET /available received")
            try:
                request_dto = TTSAvailabilityRequestDto()
                response = await self.is_available(request_dto)
                logger.info("HTTP GET /available succeeded is_available=%s", response.is_available)
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "action": "check_availability",
                        "status": "success",
                        "status_code": status.HTTP_200_OK,
                        "message": "Availability checked successfully",
                        "timestamp": time.time(),
                        "data": {"is_available": response.is_available}
                    }
                )
            except Exception as e:
                logger.exception("HTTP GET /available failed")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "check_availability",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to check availability: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )

        @app.post("/process/stream", status_code=status.HTTP_200_OK)
        async def handle_process_stream(
            request: Request,
            sample_rate: int = 22050,
            channels: int = 1,
            keep_open_after_completed: bool = False,
            heartbeat_interval_seconds: float = 15.0,
        ):
            logger.info(
                "HTTP POST /process/stream received sample_rate=%s channels=%s",
                sample_rate,
                channels,
            )
            try:
                body_bytes = await request.body()
                lines = _parse_text_stream_events(body_bytes)
                logger.info(
                    "HTTP POST /process/stream parsed body_bytes=%s text_chunks=%s",
                    len(body_bytes),
                    len(lines),
                )

                async def text_stream_generator() -> AsyncIterator[str]:
                    for line in lines:
                        logger.info("HTTP /process/stream yielding text line length=%s", len(line))
                        yield line

                request_dto = ProcessStreamRequestDto(
                    text_stream=text_stream_generator(),
                    sample_rate=sample_rate,
                    channels=channels,
                )

                response = await self.process_stream(request_dto)

                return StreamingResponse(
                    _audio_event_stream(
                        response.audio_stream,
                        action="process_stream",
                        response_format=_stream_response_format(request),
                        keep_open_after_completed=keep_open_after_completed,
                        heartbeat_interval_seconds=heartbeat_interval_seconds,
                    ),
                    media_type=_stream_media_type(_stream_response_format(request)),
                    status_code=status.HTTP_200_OK,
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Action": "process_stream",
                        "X-Status": "success",
                        "X-Message": "Stream processed successfully",
                        "X-Timestamp": str(time.time()),
                    }
                )
            except ClientDisconnect:
                logger.warning("HTTP POST /process/stream client disconnected while reading request body")
                return _client_disconnect_response("process_stream")
            except ValueError as e:
                logger.warning("HTTP POST /process/stream rejected invalid stream events: %s", e)
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "action": "process_stream",
                        "status": "error",
                        "status_code": status.HTTP_400_BAD_REQUEST,
                        "message": str(e),
                        "timestamp": time.time(),
                        "data": None,
                    }
                )
            except Exception as e:
                logger.exception("HTTP POST /process/stream failed")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "process_stream",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to process stream: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )

        # ──────────────────────────────────────────────
        # DECOUPLED STREAM (Single Flow)
        # ──────────────────────────────────────────────

        @app.post("/process/stream/set", status_code=status.HTTP_200_OK)
        async def handle_set_stream(
            request: Request,
            sample_rate: int = 22050,
            channels: int = 1,
        ):
            logger.info(
                "HTTP POST /process/stream/set received sample_rate=%s channels=%s",
                sample_rate,
                channels,
            )
            response_format = _stream_response_format(request)
            return _DuplexStreamingResponse(
                _set_stream_response(
                    request,
                    adapter=self,
                    sample_rate=sample_rate,
                    channels=channels,
                    response_format=response_format,
                ),
                media_type=_stream_media_type(response_format),
                status_code=status.HTTP_200_OK,
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Action": "set_stream",
                    "X-Status": "accepted",
                    "X-Message": "Stream accepted. Background synthesis started.",
                    "X-Timestamp": str(time.time()),
                },
            )

        @app.get("/process/stream/get", status_code=status.HTTP_200_OK)
        async def handle_get_stream(
            request: Request,
            sample_rate: int = 22050,
            channels: int = 1,
            keep_open_after_completed: bool = False,
            heartbeat_interval_seconds: float = 15.0,
        ):
            logger.info(
                "HTTP GET /process/stream/get received sample_rate=%s channels=%s",
                sample_rate,
                channels,
            )
            try:
                request_dto = GetStreamRequestDto()
                response = await self.get_stream(request_dto)

                return StreamingResponse(
                    _audio_event_stream(
                        response.audio_stream,
                        action="get_stream",
                        response_format="ndjson",
                        keep_open_after_completed=keep_open_after_completed,
                        heartbeat_interval_seconds=heartbeat_interval_seconds,
                    ),
                    media_type=STREAM_MEDIA_TYPE,
                    status_code=status.HTTP_200_OK,
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Action": "get_stream",
                        "X-Status": "success",
                        "X-Message": "Decoupled stream retrieved successfully",
                        "X-Timestamp": str(time.time()),
                    }
                )
            except Exception as e:
                logger.exception("HTTP GET /process/stream/get failed")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "get_stream",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to get stream: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e),
                    }
                )

        @app.post("/process/batch", status_code=status.HTTP_200_OK)
        async def handle_process_batch(
            text: str = "",
            sample_rate: int = 22050,
            channels: int = 1,
        ):
            logger.info(
                "HTTP POST /process/batch received text_length=%s sample_rate=%s channels=%s",
                len(text),
                sample_rate,
                channels,
            )
            try:
                if not text or text.strip() == "":
                    logger.warning("HTTP POST /process/batch rejected empty text")
                    raise HTTPException(status_code=400, detail="No text provided")

                request_dto = ProcessBatchRequestDto(
                    text=text,
                    sample_rate=sample_rate,
                    channels=channels,
                )

                response = await self.process_batch(request_dto)

                # Return raw audio as standard attachment, or hex, or in data envelope.
                # In standard envelope, we can encode audio as base64 for easy transport,
                # or return raw binary with headers. Let's return StreamingResponse/audio/wav
                # directly for batch too, but standard response envelope can hold Base64.
                # To match STT format of response envelope:
                encoded_audio = base64.b64encode(response.audio_data).decode("utf-8")
                logger.info(
                    "HTTP POST /process/batch succeeded audio_bytes=%s encoded_length=%s",
                    len(response.audio_data),
                    len(encoded_audio),
                )

                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "action": "process_batch",
                        "status": "success",
                        "status_code": status.HTTP_200_OK,
                        "message": "Text synthesized successfully",
                        "timestamp": time.time(),
                        "data": {
                            "audio_data_base64": encoded_audio,
                            "sample_rate": sample_rate,
                            "channels": channels
                        }
                    }
                )
            except Exception as e:
                logger.exception("HTTP POST /process/batch failed")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "process_batch",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to process batch: {str(e)}\n" + e.__str__(),
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )
        logger.info("FastAPI routes registered")

    def start_autoload(self) -> None:
        logger.info("FastApiAdapter.start_autoload called; no autoload task configured")

    async def stop_autoload(self) -> None:
        logger.info("FastApiAdapter.stop_autoload called; no autoload task configured")

    @property
    def get_app(self) -> Any:
        logger.info("FastApiAdapter.get_app accessed")
        return self.app

    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        logger.info("FastApiAdapter.process_stream mapping inbound request to service request")
        service_request_dto = map_inbound_to_service_stream_request(request)
        service_response_dto = await self.service_port.process_stream(service_request_dto)
        adapter_response_dto = map_service_to_inbound_stream_response(service_response_dto)
        logger.info("FastApiAdapter.process_stream completed")
        return adapter_response_dto

    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        logger.info("FastApiAdapter.process_batch mapping inbound request to service request")
        service_request_dto = map_inbound_to_service_batch_request(request)
        service_response_dto = await self.service_port.process_batch(service_request_dto)
        adapter_response_dto = map_service_to_inbound_batch_response(service_response_dto)
        logger.info("FastApiAdapter.process_batch completed")
        return adapter_response_dto

    async def set_stream(self, request: SetStreamRequestDto) -> None:
        logger.info("FastApiAdapter.set_stream mapping inbound request to service request")
        service_request_dto = map_inbound_to_service_set_stream_request(request)
        await self.service_port.set_stream(service_request_dto)
        logger.info("FastApiAdapter.set_stream completed")

    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        logger.info("FastApiAdapter.get_stream mapping inbound request to service request")
        service_request_dto = map_inbound_to_service_get_stream_request(request)
        service_response_dto = await self.service_port.get_stream(service_request_dto)
        adapter_response_dto = map_service_to_inbound_get_stream_response(service_response_dto)
        logger.info("FastApiAdapter.get_stream completed")
        return adapter_response_dto

    async def is_available(self, request: TTSAvailabilityRequestDto) -> TTSAvailabilityResponseDto:
        logger.info("FastApiAdapter.is_available mapping inbound request to service request")
        service_request_dto = map_inbound_to_service_availability_request(request)
        service_response_dto = await self.service_port.is_available(service_request_dto)
        adapter_response_dto = map_service_to_inbound_availability_response(service_response_dto)
        logger.info("FastApiAdapter.is_available completed is_available=%s", adapter_response_dto.is_available)
        return adapter_response_dto
