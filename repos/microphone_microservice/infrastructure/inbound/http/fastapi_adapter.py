
import base64
import json
import math
import sys
from array import array
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.responses import StreamingResponse, JSONResponse

import time

from application.ports.adapter_inbound_port import AdapterInboundPort
from application.ports.service_port import ServicePort

from application.dtos.adapter_inbound_dtos import (
    StartMicrophoneStreamRequestDto,
    StartMicrophoneStreamResponseDto,
    StopMicrophoneStreamRequestDto,
    StopMicrophoneStreamResponseDto,
    MicrophoneAvailabilityRequestDto,
    MicrophoneAvailabilityResponseDto,
)

from application.dtos.mapper.adapter_inbound_to_service import (
    map_adapter_to_service_start_request,
    map_adapter_to_service_stop_request,
    map_adapter_to_service_availability_request,
)

from application.dtos.mapper.service_to_adapter_inbound import (
    map_service_to_adapter_start_response,
    map_service_to_adapter_stop_response,
    map_service_to_adapter_availability_response,
)
from composition_root.runtime.logger import get_logger


logger = get_logger("http")

NDJSON_MEDIA_TYPE = "application/x-ndjson"
SSE_MEDIA_TYPE = "text/event-stream"
STREAM_EVENT_TYPES = {"stream_started", "partial", "completed", "heartbeat", "error"}
PCM_SAMPLE_WIDTH_BYTES = 2
SILENCE_SECONDS_TO_COMPLETE = 2.0
SILENCE_RMS_THRESHOLD = 350.0


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _event_line(event_type: str, sequence: int, payload: dict[str, Any]) -> bytes:
    if event_type not in STREAM_EVENT_TYPES:
        raise ValueError(f"Unsupported stream event type: {event_type}")
    if not isinstance(payload, dict):
        raise TypeError("Stream event payload must be an object")

    event = {
        "type": event_type,
        "sequence": sequence,
        "timestamp": _utc_timestamp(),
        "payload": payload,
    }
    return (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")


def _chunk_duration_seconds(chunk: bytes, sample_rate: int) -> float:
    if sample_rate <= 0:
        return 0.0
    return (len(chunk) // PCM_SAMPLE_WIDTH_BYTES) / sample_rate


def _pcm16_rms(chunk: bytes) -> float:
    sample_bytes = chunk[: len(chunk) - (len(chunk) % PCM_SAMPLE_WIDTH_BYTES)]
    if not sample_bytes:
        return 0.0

    samples = array("h")
    samples.frombytes(sample_bytes)
    if sys.byteorder != "little":
        samples.byteswap()

    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _is_silent_pcm16(chunk: bytes) -> bool:
    return _pcm16_rms(chunk) <= SILENCE_RMS_THRESHOLD


async def event_stream_from_audio_bytes(stream: AsyncIterator[bytes], sample_rate: int) -> AsyncIterator[bytes]:
    sequence = 1
    output = bytearray()
    silent_seconds = 0.0
    yield _event_line("stream_started", sequence, {})

    try:
        async for chunk in stream:
            chunk_rms = _pcm16_rms(chunk)
            chunk_is_silent = chunk_rms <= SILENCE_RMS_THRESHOLD
            logger.trace(
                "Audio stream chunk classified",
                rms=round(chunk_rms, 2),
                silent=chunk_is_silent,
                has_recording=bool(output),
                silent_seconds=round(silent_seconds, 3),
            )
            if not chunk_is_silent:
                silent_seconds = 0.0
                output.extend(chunk)
                sequence += 1
                bytes_base64 = base64.b64encode(chunk).decode("ascii")
                yield _event_line("partial", sequence, {"bytes_base64": bytes_base64})
                continue

            if not output:
                continue

            silent_seconds += _chunk_duration_seconds(chunk, sample_rate)
            if silent_seconds >= SILENCE_SECONDS_TO_COMPLETE:
                sequence += 1
                output_bytes_base64 = base64.b64encode(bytes(output)).decode("ascii")
                yield _event_line(
                    "completed",
                    sequence,
                    {
                        "reason": "completed",
                        "output_bytes_base64": output_bytes_base64,
                    },
                )
                output = bytearray()
                silent_seconds = 0.0

        if output:
            sequence += 1
            output_bytes_base64 = base64.b64encode(bytes(output)).decode("ascii")
            yield _event_line(
                "completed",
                sequence,
                {
                    "reason": "completed",
                    "output_bytes_base64": output_bytes_base64,
                },
            )
    except Exception as error:
        sequence += 1
        logger.error("Audio event stream failed", error=repr(error))
        yield _event_line(
            "error",
            sequence,
            {
                "code": "audio_stream_failed",
                "message": "Audio stream failed while producing events.",
                "recoverable": True,
            },
        )


async def sse_stream_from_audio_bytes(stream: AsyncIterator[bytes], sample_rate: int) -> AsyncIterator[bytes]:
    async for event_line in event_stream_from_audio_bytes(stream, sample_rate):
        yield b"data:" + event_line.rstrip(b"\n") + b"\n\n"


def _stream_media_type(request: Request) -> str:
    accept = request.headers.get("accept", "")
    if SSE_MEDIA_TYPE in accept and NDJSON_MEDIA_TYPE not in accept:
        return SSE_MEDIA_TYPE
    return NDJSON_MEDIA_TYPE


def _stream_body(stream: AsyncIterator[bytes], media_type: str, sample_rate: int) -> AsyncIterator[bytes]:
    if media_type == SSE_MEDIA_TYPE:
        return sse_stream_from_audio_bytes(stream, sample_rate)
    return event_stream_from_audio_bytes(stream, sample_rate)


class FastApiAdapter(AdapterInboundPort):
    def __init__(self, service_port: ServicePort, app: FastAPI):
        self.service_port = service_port
        self.app = app

        logger.info("FastApiAdapter initialized")
        self.register_routes(self.app)

    def register_routes(self, app: FastAPI) -> None:
        logger.info("Registering HTTP routes")
        @app.post("/start", status_code=status.HTTP_200_OK)
        async def handle_start_stream(request: StartMicrophoneStreamRequestDto, http_request: Request):
            logger.info(
                "POST /start received",
                sample_rate=request.sample_rate,
                channels=request.channels,
                chunk_size=request.chunk_size,
            )
            try:
                response = await self.start_stream(request)
                logger.info("POST /start succeeded", sample_rate=response.sample_rate)
                media_type = _stream_media_type(http_request)

                http_response = StreamingResponse(
                    _stream_body(response.stream, media_type, response.sample_rate),
                    media_type=media_type,
                    status_code=status.HTTP_200_OK,
                    headers={
                        "X-Sample-Rate": str(response.sample_rate),
                        "X-Action": "start_stream",
                        "X-Status": "success",
                        "X-Message": "Microphone stream started successfully",
                        "X-Timestamp": str(time.time()),
                    }
                )
                return http_response
            except Exception as e:
                logger.error("POST /start failed", error=repr(e))
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "start_stream",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to start microphone stream: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )
            
            
        @app.post("/stop", status_code=status.HTTP_200_OK)
        async def handle_stop_stream(request: StopMicrophoneStreamRequestDto):
            logger.info("POST /stop received")
            try:
                response = await self.stop_stream(request)
                logger.info("POST /stop succeeded", success=response.success)
                http_response = JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "action": "stop_stream",
                        "status": "success",
                        "status_code": status.HTTP_200_OK,
                        "message": "Microphone stream stopped successfully",
                        "timestamp": time.time(),
                        "data": response.success
                    }
                )
                return http_response
            except Exception as e:
                logger.error("POST /stop failed", error=repr(e))
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "stop_stream",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to stop microphone stream: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )

        @app.get("/available", status_code=status.HTTP_200_OK)
        async def handle_check_availability():
            logger.info("GET /available received")
            try:
                request_dto = MicrophoneAvailabilityRequestDto()
                response = await self.is_available(request_dto)
                logger.info("GET /available succeeded", is_available=response.is_available)
                http_response = JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "action": "check_availability",
                        "status": "success",
                        "status_code": status.HTTP_200_OK,
                        "message": "Microphone availability checked successfully",
                        "timestamp": time.time(),
                        "data": response.is_available
                    }
                )
                return http_response
            except Exception as e:
                logger.error("GET /available failed", error=repr(e))
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "action": "check_availability",
                        "status": "error",
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "message": f"Failed to check microphone availability: {str(e)}",
                        "timestamp": time.time(),
                        "data": str(e)
                    }
                )
        @app.get("/health", tags=["Health"])
        async def health_check():
            logger.info("GET /health received")
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
    @property
    def get_app(self) -> FastAPI:
        logger.trace("get_app accessed")
        return self.app

    async def start_stream(self, request: StartMicrophoneStreamRequestDto) -> StartMicrophoneStreamResponseDto:
        logger.trace("Adapter start_stream mapping inbound DTO to service DTO")
        
        service_request_dto = map_adapter_to_service_start_request(request)
        
        logger.trace("Adapter start_stream calling service")
        service_response_dto = await self.service_port.start_stream(service_request_dto)

        logger.trace("Adapter start_stream mapping service response to inbound DTO")
        adapter_response_dto = map_service_to_adapter_start_response(service_response_dto)

        logger.info("Adapter start_stream completed")
        return adapter_response_dto
    

    async def stop_stream(self, request: StopMicrophoneStreamRequestDto) -> StopMicrophoneStreamResponseDto:
        logger.trace("Adapter stop_stream mapping inbound DTO to service DTO")
        service_request_dto = map_adapter_to_service_stop_request(request)
        logger.trace("Adapter stop_stream calling service")
        service_response_dto = await self.service_port.stop_stream(service_request_dto)
        logger.trace("Adapter stop_stream mapping service response to inbound DTO")
        adapter_response_dto = map_service_to_adapter_stop_response(service_response_dto)
        logger.info("Adapter stop_stream completed")
        return adapter_response_dto

    async def is_available(self, request: MicrophoneAvailabilityRequestDto) -> MicrophoneAvailabilityResponseDto:
        logger.trace("Adapter is_available mapping inbound DTO to service DTO")
        service_request_dto = map_adapter_to_service_availability_request(request)
        logger.trace("Adapter is_available calling service")
        service_response_dto = await self.service_port.is_available(service_request_dto)
        logger.trace("Adapter is_available mapping service response to inbound DTO")
        adapter_response_dto = map_service_to_adapter_availability_response(service_response_dto)
        logger.info("Adapter is_available completed")
        return adapter_response_dto
