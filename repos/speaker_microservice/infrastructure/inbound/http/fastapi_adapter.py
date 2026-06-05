import asyncio
import base64
import binascii
import json
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Any
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from application.ports.adapter_inbound_port import AdapterInboundPort
from application.ports.service_port import SpeakerServicePort

from application.dtos.adapter_inbound_dtos import (
    InitInboundAdapterDto,
    StartSpeakerStreamRequestDto,
    StartSpeakerStreamResponseDto,
)
from application.dtos.services_dtos import PlaybackStreamResponseDto

from application.dtos.mapper.adapter_inbound_to_service import map_inbound_to_service_playback_request
from application.dtos.mapper.service_to_adapter_inbound import map_service_to_inbound_playback_response
from infrastructure.inbound.http.audio_stream_autoloader import AudioStreamAutoloader
from runtime.logger import get_logger

logger = get_logger("infrastructure.inbound")


class NdjsonInputError(ValueError):
    """Raised when a streamed NDJSON playback request violates the input contract."""


class NdjsonEventStream:
    """Build newline-delimited JSON protocol events with stream-local sequencing."""

    def __init__(self) -> None:
        self._sequence = 0

    def line(self, event_type: str, payload: dict[str, Any]) -> str:
        self._sequence += 1
        event = {
            "type": event_type,
            "sequence": self._sequence,
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "payload": payload,
        }
        return json.dumps(event, separators=(",", ":")) + "\n"


class RequestBodySafeStreamingResponse(Response):
    """
    Stream response bytes without concurrently reading the ASGI receive channel.

    Starlette's StreamingResponse listens for disconnects by calling receive()
    while response chunks are produced. This endpoint also consumes request.stream()
    in a playback task, so a second receive() consumer can race the request body.
    """

    def __init__(
        self,
        content: AsyncGenerator[str, None],
        media_type: str,
        headers: dict[str, str] | None = None,
        status_code: int = status.HTTP_200_OK,
    ) -> None:
        super().__init__(content=None, status_code=status_code, headers=headers, media_type=media_type)
        self.body_iterator = content
        self.raw_headers = [
            (name, value)
            for name, value in self.raw_headers
            if name.lower() != b"content-length"
        ]

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        async for chunk in self.body_iterator:
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk.encode(self.charset),
                    "more_body": True,
                }
            )
        await send({"type": "http.response.body", "body": b"", "more_body": False})


class FastApiAdapter(AdapterInboundPort):
    def __init__(self, service_port: SpeakerServicePort, app: FastAPI, config: InitInboundAdapterDto):
        self.service_port = service_port
        self.app = app
        self.config = config        
        logger.info(
            "Initializing FastApiAdapter: allow_origins=%s autoload_enabled=%s",
            config.allow_origins,
            bool(config.autoload_stream_url),
        )
        
        self.autoloader = None
        if config.autoload_stream_url:
            logger.info("Creating audio stream autoloader for URL: %s", config.autoload_stream_url)
            self.autoloader = AudioStreamAutoloader(config.autoload_stream_url, self)

        self.register_routes(self.app)
        logger.info("FastApiAdapter route registration complete.")

    def register_routes(self, app: FastAPI) -> None:
        logger.info("Registering FastAPI inbound routes.")

        @app.get("/health", tags=["Health"])
        async def health_check() -> JSONResponse:
            logger.info("Health check requested.")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "action": "health_check",
                    "status": "success",
                    "status_code": status.HTTP_200_OK,
                    "message": "Speaker microservice is healthy",
                    "timestamp": time.time(),
                    "data": {"timestamp": time.time()}
                }
            )

        @app.post("/process/stream/set", tags=["Playback"], response_model=None)
        async def set_stream_http(
            request: Request,
            sample_rate: int = 24000,
            channels: int = 1,
            keep_open_after_completed: bool = False,
            heartbeat_interval_seconds: float = 15.0,
            max_heartbeats_after_completed: int | None = None,
        ) -> Response:
            """
            Accepts raw audio bytes via HTTP Chunked Transfer-Encoding,
            waits only for speaker stream setup, emits stream_started on
            a live NDJSON response, and keeps consuming request audio.
            """
            logger.info(
                "HTTP playback stream request received: client=%s sample_rate=%s channels=%s",
                request.client,
                sample_rate,
                channels,
            )

            event_stream = NdjsonEventStream()
            chunk_count = 0
            total_bytes = 0
            request_read_error: Exception | None = None
            is_ndjson_input = "application/x-ndjson" in request.headers.get("content-type", "").lower()

            def validate_event_shape(event: Any, expected_sequence: int) -> tuple[str, dict[str, Any]]:
                if not isinstance(event, dict):
                    raise NdjsonInputError("NDJSON event must be a JSON object.")

                event_type = event.get("type")
                sequence = event.get("sequence")
                timestamp = event.get("timestamp")
                payload = event.get("payload")

                if not isinstance(event_type, str):
                    raise NdjsonInputError("NDJSON event field 'type' must be a string.")
                if not isinstance(sequence, int):
                    raise NdjsonInputError("NDJSON event field 'sequence' must be an integer.")
                if sequence != expected_sequence:
                    raise NdjsonInputError(
                        f"NDJSON event sequence must be {expected_sequence}; received {sequence}."
                    )
                if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
                    raise NdjsonInputError("NDJSON event field 'timestamp' must be a UTC ISO-8601 string ending in Z.")
                try:
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError as e:
                    raise NdjsonInputError("NDJSON event field 'timestamp' must be parseable ISO-8601.") from e
                if not isinstance(payload, dict):
                    raise NdjsonInputError("NDJSON event field 'payload' must be an object.")

                return event_type, payload

            async def http_stream_generator() -> AsyncGenerator[bytes, None]:
                nonlocal chunk_count, total_bytes, request_read_error
                try:
                    async for chunk in request.stream():
                        if not chunk:
                            continue
                        chunk_count += 1
                        total_bytes += len(chunk)
                        yield chunk
                except ClientDisconnect:
                    logger.info("HTTP raw request stream disconnected; finalizing playback stream.")
                    return
                except Exception as e:
                    request_read_error = e
                    logger.error(
                        "HTTP request stream failed while playback was active: type=%s message=%r",
                        type(e).__name__,
                        str(e),
                    )
                    raise

            async def ndjson_audio_stream_generator() -> AsyncGenerator[bytes, None]:
                nonlocal chunk_count, total_bytes, request_read_error
                buffer = b""
                expected_sequence = 1
                stream_started_seen = False

                async def handle_line(line: str) -> bytes | None:
                    nonlocal expected_sequence, stream_started_seen
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise NdjsonInputError(f"Malformed NDJSON event: {e.msg}.") from e

                    event_type, payload = validate_event_shape(event, expected_sequence)
                    expected_sequence += 1

                    if event_type == "stream_started":
                        if stream_started_seen:
                            raise NdjsonInputError("NDJSON stream_started event may only be sent once.")
                        stream_started_seen = True
                        return None

                    if event_type == "partial":
                        if not stream_started_seen:
                            raise NdjsonInputError("NDJSON stream_started event must be sent before audio events.")
                        encoded_audio = payload.get("bytes_base64")
                        if not isinstance(encoded_audio, str):
                            raise NdjsonInputError("NDJSON partial event payload.bytes_base64 must be a string.")
                        try:
                            return base64.b64decode(encoded_audio, validate=True)
                        except (binascii.Error, ValueError) as e:
                            raise NdjsonInputError("NDJSON partial event payload.bytes_base64 is not valid base64.") from e

                    if event_type == "completed":
                        if not stream_started_seen:
                            raise NdjsonInputError("NDJSON stream_started event must be sent before audio events.")
                        return None

                    raise NdjsonInputError(f"Unsupported NDJSON event type: {event_type}.")

                try:
                    async for chunk in request.stream():
                        if not chunk:
                            continue
                        buffer += chunk
                        while b"\n" in buffer:
                            line_bytes, buffer = buffer.split(b"\n", 1)
                            line = line_bytes.decode("utf-8").strip()
                            if not line:
                                continue
                            audio_bytes = await handle_line(line)
                            if audio_bytes:
                                chunk_count += 1
                                total_bytes += len(audio_bytes)
                                yield audio_bytes

                    trailing_line = buffer.decode("utf-8").strip()
                    if trailing_line:
                        audio_bytes = await handle_line(trailing_line)
                        if audio_bytes:
                            chunk_count += 1
                            total_bytes += len(audio_bytes)
                            yield audio_bytes
                except ClientDisconnect:
                    logger.info("HTTP NDJSON request stream disconnected; finalizing playback stream.")
                    return
                except UnicodeDecodeError as e:
                    request_read_error = NdjsonInputError("NDJSON request body must be valid UTF-8.")
                    logger.error("HTTP NDJSON request body failed validation: %s", request_read_error)
                    raise request_read_error from e
                except NdjsonInputError as e:
                    request_read_error = e
                    logger.error("HTTP NDJSON request body failed validation: %s", e)
                    raise

            setup_future: asyncio.Future[PlaybackStreamResponseDto] = asyncio.get_running_loop().create_future()
            inbound_request = StartSpeakerStreamRequestDto(
                audio_stream=ndjson_audio_stream_generator() if is_ndjson_input else http_stream_generator(),
                sample_rate=sample_rate,
                channels=channels,
                setup_future=setup_future,
            )
            play_task = asyncio.create_task(self.play(inbound_request))

            done, _ = await asyncio.wait(
                {setup_future, play_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if setup_future in done:
                setup_response = setup_future.result()
            else:
                try:
                    setup_response = await play_task
                except Exception as e:
                    logger.exception("HTTP playback setup failed before acknowledgement.")
                    return JSONResponse(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        content={
                            "action": "set_stream_http",
                            "status": "error",
                            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "message": f"Failed to set playback stream: {str(e)}",
                            "timestamp": time.time(),
                            "data": str(e),
                        },
                    )

            if not setup_response.success:
                logger.warning("HTTP playback setup failed: message=%s", setup_response.message)
                if not play_task.done():
                    play_task.cancel()
                    try:
                        await play_task
                    except asyncio.CancelledError:
                        logger.info("HTTP playback task cancelled after setup failure.")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "set_stream_http",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": setup_response.message,
                        "timestamp": time.time(),
                        "data": None,
                    },
                )

            async def response_stream() -> AsyncGenerator[str, None]:
                yield event_stream.line(
                    "stream_started",
                    {
                        "message": setup_response.message,
                    },
                )

                try:
                    while not play_task.done():
                        await asyncio.sleep(0.1)

                    response = await play_task

                    if request_read_error is not None:
                        yield event_stream.line(
                            "error",
                            {
                                "code": "request_stream_failed",
                                "message": f"Failed to read request stream: {str(request_read_error)}",
                                "recoverable": True,
                            },
                        )
                    elif not response.success:
                        logger.warning(
                            "HTTP playback failed: chunks=%s bytes=%s message=%s",
                            chunk_count,
                            total_bytes,
                            response.message,
                        )
                        yield event_stream.line(
                            "error",
                            {
                                "code": "playback_failed",
                                "message": response.message,
                                "recoverable": True,
                            },
                        )
                    else:
                        logger.info(
                            "HTTP playback completed successfully: chunks=%s bytes=%s message=%s",
                            chunk_count,
                            total_bytes,
                            response.message,
                        )
                        yield event_stream.line(
                            "completed",
                            {
                                "reason": "end_of_input",
                                "output": "",
                                "chunk_count": chunk_count,
                                "byte_count": total_bytes,
                                "message": response.message,
                            },
                        )

                        heartbeat_count = 0
                        while keep_open_after_completed:
                            if (
                                max_heartbeats_after_completed is not None
                                and heartbeat_count >= max_heartbeats_after_completed
                            ):
                                break
                            await asyncio.sleep(max(0.1, heartbeat_interval_seconds))
                            heartbeat_count += 1
                            yield event_stream.line("heartbeat", {})
                except Exception as e:
                    logger.exception(
                        "HTTP playback request failed with exception after chunks=%s bytes=%s",
                        chunk_count,
                        total_bytes,
                    )
                    yield event_stream.line(
                        "error",
                        {
                            "code": "stream_failed",
                            "message": f"Failed to play stream: {str(e)}",
                            "recoverable": True,
                        },
                    )
                finally:
                    if not play_task.done():
                        play_task.cancel()
                        try:
                            await play_task
                        except asyncio.CancelledError:
                            logger.info("HTTP playback task cancelled while closing response stream.")

            return RequestBodySafeStreamingResponse(
                response_stream(),
                media_type="application/x-ndjson",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Content-Type-Options": "nosniff",
                },
            )

    def start_autoload(self) -> None:
        if self.autoloader:
            logger.info("Starting configured audio stream autoloader.")
            self.autoloader.start()
        else:
            logger.info("Autoload start requested, but no autoload stream URL is configured.")

    async def stop_autoload(self) -> None:
        if self.autoloader:
            logger.info("Stopping configured audio stream autoloader.")
            await self.autoloader.stop()
        else:
            logger.info("Autoload stop requested, but no autoloader exists.")

    @property
    def get_app(self) -> Any:
        logger.trace("FastAPI app requested from inbound adapter.")
        return self.app

    async def play(self, request: StartSpeakerStreamRequestDto) -> StartSpeakerStreamResponseDto:
        logger.info(
            "Inbound adapter forwarding playback request to service: sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        service_request_dto = map_inbound_to_service_playback_request(request)
        service_response_dto = await self.service_port.play(service_request_dto)
        adapter_response_dto = map_service_to_inbound_playback_response(service_response_dto)
        logger.info(
            "Inbound adapter received service playback response: success=%s message=%s",
            adapter_response_dto.success,
            adapter_response_dto.message,
        )
        return adapter_response_dto
