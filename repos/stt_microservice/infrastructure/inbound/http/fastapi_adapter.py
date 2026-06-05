import base64
import json
import time
from typing import AsyncIterator, Any, Awaitable, Callable

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.types import Receive, Scope, Send

from application.ports.adapter_inbound_port import AdapterInboundPort
from application.ports.service_port import ServicePort
from application.dtos.audio_stream_items import CompletedAudioSegment

from application.dtos.adapter_inbound_dtos import (
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    SetStreamRequestDto,
    SetStreamResponseDto,
    GetStreamRequestDto,
    GetStreamResponseDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    STTAvailabilityRequestDto,
    STTAvailabilityResponseDto,
    InitInboundAdapterDto,
)

from infrastructure.inbound.http.voice_stream_autoloader import VoiceStreamAutoloader
from infrastructure.inbound.http.stream_events import (
    ndjson_stream_event,
    sse_stream_event,
    text_event_stream,
)

from application.dtos.mapper.adapter_inbound_to_service import (
    map_inbound_to_service_stream_request,
    map_inbound_to_service_set_stream_request,
    map_inbound_to_service_get_stream_request,
    map_inbound_to_service_batch_request,
    map_inbound_to_service_availability_request,
)

from application.dtos.mapper.service_to_adapter_inbound import (
    map_service_to_inbound_stream_response,
    map_service_to_inbound_set_stream_response,
    map_service_to_inbound_get_stream_response,
    map_service_to_inbound_batch_response,
    map_service_to_inbound_availability_response,
)
from runtime.logger import get_logger


logger = get_logger(__name__)


class InputStreamResponse(Response):
    def __init__(
        self,
        runner: Callable[[], Awaitable[Any]],
        *,
        formatter: Callable[[str, int, dict[str, Any]], str] = sse_stream_event,
        media_type: str = "text/event-stream",
        status_code: int = status.HTTP_200_OK,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(content=b"", status_code=status_code, headers=headers, media_type=media_type)
        self.formatter = formatter
        self.runner = runner
        self.raw_headers = [
            (name, value)
            for name, value in self.raw_headers
            if name.lower() != b"content-length"
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": self.formatter("stream_started", 1, {}).encode("utf-8"),
                "more_body": True,
            }
        )

        try:
            await self.runner()
        except Exception as exc:
            logger.exception("Input stream response runner failed after response start.")
            body = self.formatter(
                "error",
                2,
                {
                    "code": "stream_failed",
                    "message": str(exc),
                    "recoverable": True,
                },
            )
        else:
            body = self.formatter(
                "completed",
                2,
                {
                    "reason": "completed",
                    "output": "accepted",
                },
            )

        await send(
            {
                "type": "http.response.body",
                "body": body.encode("utf-8"),
                "more_body": False,
            }
        )


def _wants_ndjson(request: Request) -> bool:
    return "application/x-ndjson" in request.headers.get("accept", "").lower()


def _is_ndjson_request(request: Request) -> bool:
    return "application/x-ndjson" in request.headers.get("content-type", "").lower()


def _decode_base64_audio(value: Any, *, event_type: str, field_name: str, sequence: Any) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{event_type} event sequence {sequence} payload.{field_name} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError(f"{event_type} event sequence {sequence} payload.{field_name} is not valid base64") from exc


def _audio_format_hint(audio: bytes) -> str:
    if audio.startswith(b"RIFF"):
        return "wav"
    if audio.startswith(b"OggS"):
        return "ogg"
    if audio.startswith(b"ID3"):
        return "mp3"
    return "pcm_s16le"


def _silence_boundary_chunks(
    *,
    sample_rate: int,
    chunk_size: int,
    silence_limit_seconds: float,
) -> list[bytes]:
    silence_limit_chunks = int((sample_rate / chunk_size) * silence_limit_seconds)
    chunk_count = max(1, silence_limit_chunks)
    silence_chunk = b"\x00\x00" * chunk_size
    return [silence_chunk] * chunk_count


async def _ndjson_audio_stream(
    source: AsyncIterator[bytes],
    *,
    sample_rate: int,
    chunk_size: int,
    silence_limit_seconds: float,
) -> AsyncIterator[bytes | CompletedAudioSegment]:
    buffer = ""
    boundary_chunks = _silence_boundary_chunks(
        sample_rate=sample_rate,
        chunk_size=chunk_size,
        silence_limit_seconds=silence_limit_seconds,
    )

    async for chunk in source:
        if not chunk:
            continue
        buffer += chunk.decode("utf-8")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            event_type, audio = _audio_from_ndjson_line(line)
            if audio is not None:
                yield audio
            if event_type == "completed":
                if not isinstance(audio, CompletedAudioSegment):
                    for silence_chunk in boundary_chunks:
                        yield silence_chunk

    if buffer.strip():
        event_type, audio = _audio_from_ndjson_line(buffer)
        if audio is not None:
            yield audio
        if event_type == "completed":
            if not isinstance(audio, CompletedAudioSegment):
                for silence_chunk in boundary_chunks:
                    yield silence_chunk


def _audio_from_ndjson_line(line: str) -> tuple[str | None, bytes | CompletedAudioSegment | None]:
    stripped = line.strip()
    if not stripped:
        return None, None

    try:
        event = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid NDJSON stream event JSON") from exc

    if not isinstance(event, dict):
        raise ValueError("NDJSON stream event must be a JSON object")

    event_type = event.get("type")
    sequence = event.get("sequence")
    payload = event.get("payload")
    logger.info("STT input stream event received: type=%s sequence=%s.", event_type, sequence)
    if not isinstance(payload, dict):
        raise ValueError(f"{event_type or 'unknown'} event sequence {sequence} payload must be an object")

    if event_type in {"stream_started", "heartbeat"}:
        return event_type, None
    if event_type == "partial":
        audio = _decode_base64_audio(
            payload.get("bytes_base64"),
            event_type="partial",
            field_name="bytes_base64",
            sequence=sequence,
        )
        logger.info(
            "Decoded STT partial audio event: sequence=%s bytes=%s format_hint=%s first_bytes=%s.",
            sequence,
            len(audio),
            _audio_format_hint(audio),
            audio[:12].hex(),
        )
        return event_type, audio
    if event_type == "completed":
        output_audio = payload.get("output_bytes_base64")
        if output_audio is None:
            logger.info("Completed STT audio event has no output_bytes_base64: sequence=%s.", sequence)
            return event_type, None
        audio = _decode_base64_audio(
            output_audio,
            event_type="completed",
            field_name="output_bytes_base64",
            sequence=sequence,
        )
        logger.info(
            "Decoded STT completed audio event: sequence=%s bytes=%s format_hint=%s first_bytes=%s.",
            sequence,
            len(audio),
            _audio_format_hint(audio),
            audio[:12].hex(),
        )
        return event_type, CompletedAudioSegment(audio_data=audio, source_sequence=sequence)
    if event_type == "error":
        code = payload.get("code", "upstream_stream_error")
        message = payload.get("message", "Upstream audio stream reported an error")
        raise RuntimeError(f"{code}: {message}")

    raise ValueError(f"Unknown NDJSON stream event type: {event_type}")


class FastApiAdapter(AdapterInboundPort):
    def __init__(self, service_port: ServicePort, app: FastAPI, config: InitInboundAdapterDto):
        self.service_port = service_port
        self.app = app
        logger.info("Initializing FastApiAdapter.")
        
        self.autoloader = None
        if config.autoload_voice_stream_url:
            logger.info("Configuring VoiceStreamAutoloader for %s.", config.autoload_voice_stream_url)
            self.autoloader = VoiceStreamAutoloader(config.autoload_voice_stream_url, self)
        else:
            logger.info("VoiceStreamAutoloader is disabled.")

        self.register_routes(self.app)

    def register_routes(self, app: FastAPI):
        logger.info("Registering FastAPI routes.")

        @app.get("/health", tags=["Health"])
        async def health_check():
            logger.info("HTTP GET /health received.")
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
            logger.info("HTTP GET /available received.")
            try:
                request_dto = STTAvailabilityRequestDto()
                response = await self.is_available(request_dto)
                logger.info("HTTP GET /available completed: is_available=%s.", response.is_available)
                http_response = JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "action": "check_availability",
                        "status": "success",
                        "status_code": status.HTTP_200_OK,
                        "message": "Availability checked successfully",
                        "timestamp": time.time(),
                        "data": response.is_available
                    }
                )
                return http_response
            except Exception as e:
                logger.exception("HTTP GET /available failed.")
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

        @app.post("/stop", status_code=status.HTTP_200_OK)
        async def handle_stop_stream():
            logger.info("HTTP POST /stop received.")
            try:
                await self.stop_stream()
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "action": "stop_stream",
                        "status": "success",
                        "status_code": status.HTTP_200_OK,
                        "message": "Stream stopped successfully",
                        "timestamp": time.time(),
                        "data": None,
                    },
                )
            except Exception as e:
                logger.exception("HTTP POST /stop failed.")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "stop_stream",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to stop stream: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e),
                    },
                )

        @app.post("/process/stream", status_code=status.HTTP_200_OK)
        async def handle_process_stream(
            request: Request,
            sample_rate: int = 16000,
            chunk_size: int = 1024,
            silence_threshold: int = 150,
            silence_limit_seconds: float = 2.0,
        ):
            logger.info(
                "HTTP POST /process/stream received: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s.",
                sample_rate,
                chunk_size,
                silence_threshold,
                silence_limit_seconds,
            )
            try:
                async def request_stream_generator() -> AsyncIterator[bytes]:
                    async for chunk in request.stream():
                        logger.debug("Received stream chunk: bytes=%s.", len(chunk))
                        yield chunk

                request_dto = ProcessStreamRequestDto(
                    audio_stream=request_stream_generator(),
                    sample_rate=sample_rate,
                    chunk_size=chunk_size,
                    silence_threshold=silence_threshold,
                    silence_limit_seconds=silence_limit_seconds,
                )

                response = await self.process_stream(request_dto)
                logger.info("HTTP POST /process/stream returning SSE response.")

                http_response = StreamingResponse(
                    text_event_stream(response.text_stream),
                    media_type="text/event-stream",
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
                return http_response
            except Exception as e:
                logger.exception("HTTP POST /process/stream failed.")
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

        @app.post("/process/stream/set", status_code=status.HTTP_200_OK)
        async def handle_set_stream(
            request: Request,
            sample_rate: int = 16000,
            chunk_size: int = 1024,
            silence_threshold: int = 150,
            silence_limit_seconds: float = 2.0,
        ):
            logger.info(
                "HTTP POST /process/stream/set received: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s.",
                sample_rate,
                chunk_size,
                silence_threshold,
                silence_limit_seconds,
            )
            try:
                async def request_stream_generator() -> AsyncIterator[bytes]:
                    async for chunk in request.stream():
                        logger.debug("Received decoupled stream chunk: bytes=%s.", len(chunk))
                        yield chunk

                audio_stream = request_stream_generator()
                if _is_ndjson_request(request):
                    logger.info("HTTP POST /process/stream/set using NDJSON audio event input.")
                    audio_stream = _ndjson_audio_stream(
                        audio_stream,
                        sample_rate=sample_rate,
                        chunk_size=chunk_size,
                        silence_limit_seconds=silence_limit_seconds,
                    )

                request_dto = SetStreamRequestDto(
                    audio_stream=audio_stream,
                    sample_rate=sample_rate,
                    chunk_size=chunk_size,
                    silence_threshold=silence_threshold,
                    silence_limit_seconds=silence_limit_seconds,
                )

                async def run_set_stream() -> None:
                    response = await self.set_stream(request_dto)
                    logger.info("HTTP POST /process/stream/set completed: accepted=%s.", response.accepted)

                return InputStreamResponse(
                    run_set_stream,
                    formatter=ndjson_stream_event if _wants_ndjson(request) else sse_stream_event,
                    media_type="application/x-ndjson" if _wants_ndjson(request) else "text/event-stream",
                    status_code=status.HTTP_200_OK,
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Action": "set_stream",
                        "X-Status": "accepted",
                        "X-Message": "Input stream connection established",
                        "X-Timestamp": str(time.time()),
                    }
                )
            except Exception as e:
                logger.exception("HTTP POST /process/stream/set failed.")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "set_stream",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to set stream: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )

        @app.get("/process/stream/get", status_code=status.HTTP_200_OK)
        async def handle_get_stream(request: Request):
            logger.info("HTTP GET /process/stream/get received.")
            try:
                request_dto = GetStreamRequestDto()
                response = await self.get_stream(request_dto)
                wants_ndjson = _wants_ndjson(request)
                formatter = ndjson_stream_event if wants_ndjson else sse_stream_event
                media_type = "application/x-ndjson" if wants_ndjson else "text/event-stream"
                logger.info("HTTP GET /process/stream/get returning %s response.", media_type)

                return StreamingResponse(
                    text_event_stream(
                        response.text_stream,
                        formatter=formatter,
                        emit_empty_completion_on_end=False,
                        heartbeat_interval_seconds=15.0,
                    ),
                    media_type=media_type,
                    status_code=status.HTTP_200_OK,
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Action": "get_stream",
                        "X-Status": "success",
                        "X-Message": "Stream retrieved successfully",
                        "X-Timestamp": str(time.time()),
                    }
                )
            except RuntimeError as e:
                logger.warning("HTTP GET /process/stream/get rejected: %s.", e)
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={
                        "action": "get_stream",
                        "status": "error",
                        "status_code": status.HTTP_404_NOT_FOUND,
                        "message": str(e),
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )
            except Exception as e:
                logger.exception("HTTP GET /process/stream/get failed.")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "get_stream",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to get stream: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )

        @app.post("/process/batch", status_code=status.HTTP_200_OK)
        async def handle_process_batch(
            request: Request,
            sample_rate: int = 16000,
        ):
            logger.info("HTTP POST /process/batch received: sample_rate=%s.", sample_rate)
            try:
                audio_data = await request.body()
                logger.info("HTTP POST /process/batch body read: bytes=%s.", len(audio_data))
                if not audio_data:
                    logger.warning("HTTP POST /process/batch rejected empty audio body.")
                    raise HTTPException(status_code=400, detail="No audio data provided")

                request_dto = ProcessBatchRequestDto(
                    audio_data=audio_data,
                    sample_rate=sample_rate,
                )

                response = await self.process_batch(request_dto)
                logger.info("HTTP POST /process/batch completed: text_length=%s.", len(response.text))

                http_response = JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "action": "process_batch",
                        "status": "success",
                        "status_code": status.HTTP_200_OK,
                        "message": "Audio processed successfully",
                        "timestamp": time.time(),
                        "data": {"text": response.text}
                    }
                )
                return http_response
            except Exception as e:
                logger.exception("HTTP POST /process/batch failed.")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "process_batch",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to process batch: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )

        # Routes are registered above
        logger.info("FastAPI routes registered.")

    def start_autoload(self) -> None:
        if self.autoloader:
            logger.info("Starting VoiceStreamAutoloader.")
            self.autoloader.start()
        else:
            logger.info("Autoload start requested, but autoloader is not configured.")

    async def stop_autoload(self) -> None:
        if self.autoloader:
            logger.info("Stopping VoiceStreamAutoloader.")
            await self.autoloader.stop()
        else:
            logger.info("Autoload stop requested, but autoloader is not configured.")

    @property
    def get_app(self) -> Any:
        logger.debug("Returning FastAPI app instance.")
        return self.app

    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        logger.info("Inbound adapter processing stream request.")
        service_request_dto = map_inbound_to_service_stream_request(request)
        service_response_dto = await self.service_port.process_stream(service_request_dto)
        adapter_response_dto = map_service_to_inbound_stream_response(service_response_dto)
        logger.info("Inbound adapter stream request mapped back to response.")
        return adapter_response_dto

    async def set_stream(self, request: SetStreamRequestDto) -> SetStreamResponseDto:
        logger.info("Inbound adapter setting shared stream.")
        service_request_dto = map_inbound_to_service_set_stream_request(request)
        service_response_dto = await self.service_port.set_stream(service_request_dto)
        adapter_response_dto = map_service_to_inbound_set_stream_response(service_response_dto)
        logger.info("Inbound adapter set stream completed: accepted=%s.", adapter_response_dto.accepted)
        return adapter_response_dto

    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        logger.info("Inbound adapter getting shared stream.")
        service_request_dto = map_inbound_to_service_get_stream_request(request)
        service_response_dto = await self.service_port.get_stream(service_request_dto)
        adapter_response_dto = map_service_to_inbound_get_stream_response(service_response_dto)
        logger.info("Inbound adapter get stream mapped back to response.")
        return adapter_response_dto

    async def stop_stream(self) -> None:
        logger.info("Inbound adapter stopping shared stream.")
        await self.service_port.stop_stream()

    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        logger.info("Inbound adapter processing batch request: bytes=%s sample_rate=%s.", len(request.audio_data), request.sample_rate)
        service_request_dto = map_inbound_to_service_batch_request(request)
        service_response_dto = await self.service_port.process_batch(service_request_dto)
        adapter_response_dto = map_service_to_inbound_batch_response(service_response_dto)
        logger.info("Inbound adapter batch request completed: text_length=%s.", len(adapter_response_dto.text))
        return adapter_response_dto

    async def is_available(self, request: STTAvailabilityRequestDto) -> STTAvailabilityResponseDto:
        logger.info("Inbound adapter checking availability.")
        service_request_dto = map_inbound_to_service_availability_request(request)
        service_response_dto = await self.service_port.is_available(service_request_dto)
        adapter_response_dto = map_service_to_inbound_availability_response(service_response_dto)
        logger.info("Inbound adapter availability result: %s.", adapter_response_dto.is_available)
        return adapter_response_dto
