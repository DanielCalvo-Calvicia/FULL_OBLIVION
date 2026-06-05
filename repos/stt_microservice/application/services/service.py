import asyncio
from typing import AsyncIterator, Optional

from application.ports.service_port import ServicePort
from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.dtos.audio_stream_items import CompletedAudioSegment
from runtime.logger import get_logger

from application.dtos.services_dtos import (
    ProcessStreamRequestDto as ServiceStreamRequest,
    ProcessStreamResponseDto as ServiceStreamResponse,
    SetStreamRequestDto as ServiceSetStreamRequest,
    SetStreamResponseDto as ServiceSetStreamResponse,
    GetStreamRequestDto as ServiceGetStreamRequest,
    GetStreamResponseDto as ServiceGetStreamResponse,
    ProcessBatchRequestDto as ServiceBatchRequest,
    ProcessBatchResponseDto as ServiceBatchResponse,
    STTAvailabilityRequestDto as ServiceAvailabilityRequest,
    STTAvailabilityResponseDto as ServiceAvailabilityResponse,
)

from application.dtos.mapper.service_to_adapter_outbound import (
    map_service_to_outbound_stream_request,
    map_service_to_outbound_batch_request,
    map_service_to_outbound_availability_request,
)
from application.dtos.mapper.adapter_outbound_to_service import (
    map_outbound_to_service_stream_response,
    map_outbound_to_service_batch_response,
    map_outbound_to_service_availability_response,
)

logger = get_logger(__name__)


class SharedStreamForwardingError(Exception):
    pass


class STTService(ServicePort):
    def __init__(self, name: str, outbound_port: AdapterOutboundPort):
        self.name = name
        self.outbound_port = outbound_port
        self._text_queue: Optional[asyncio.Queue[Optional[str | Exception]]] = None
        self._stream_task: Optional[asyncio.Task] = None
        logger.info("STTService '%s' initialized with outbound adapter %s.", name, type(outbound_port).__name__)

    async def process_stream(self, request: ServiceStreamRequest) -> ServiceStreamResponse:
        logger.info(
            "STTService '%s' processing stream: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s.",
            self.name,
            request.sample_rate,
            request.chunk_size,
            request.silence_threshold,
            request.silence_limit_seconds,
        )
        outbound_req = map_service_to_outbound_stream_request(request)
        outbound_res = await self.outbound_port.process_stream(outbound_req)
        logger.info("STTService '%s' received outbound stream response.", self.name)
        return map_outbound_to_service_stream_response(outbound_res)

    async def set_stream(self, request: ServiceSetStreamRequest) -> ServiceSetStreamResponse:
        logger.info(
            "STTService '%s' setting shared stream: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s.",
            self.name,
            request.sample_rate,
            request.chunk_size,
            request.silence_threshold,
            request.silence_limit_seconds,
        )

        if self._stream_task and not self._stream_task.done():
            logger.info("STTService '%s' cancelling previous shared stream task.", self.name)
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                logger.info("STTService '%s' previous shared stream task cancelled.", self.name)

        self._text_queue = asyncio.Queue()
        self._stream_task = asyncio.create_task(self._forward_stream_to_queue(request, self._text_queue))

        try:
            await self._stream_task
        except asyncio.CancelledError:
            logger.info("STTService '%s' shared stream set request cancelled.", self.name)
            raise

        logger.info("STTService '%s' shared stream completed.", self.name)
        return ServiceSetStreamResponse(accepted=True)

    async def get_stream(self, request: ServiceGetStreamRequest) -> ServiceGetStreamResponse:
        logger.info("STTService '%s' getting shared text stream.", self.name)
        if self._text_queue is None:
            raise RuntimeError("No active stream has been set")

        return ServiceGetStreamResponse(
            text_stream=self._queue_text_stream(self._text_queue),
        )

    async def stop_stream(self) -> None:
        logger.info("STTService '%s' stopping shared stream.", self.name)
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                logger.info("STTService '%s' shared stream task stopped.", self.name)
        elif self._text_queue is not None:
            await self._text_queue.put(None)
        self._stream_task = None

    async def _forward_stream_to_queue(
        self,
        request: ServiceSetStreamRequest,
        queue: asyncio.Queue[Optional[str | Exception]],
    ) -> None:
        async def live_audio_stream() -> AsyncIterator[bytes]:
            async for item in request.audio_stream:
                if isinstance(item, CompletedAudioSegment):
                    text = await self._transcribe_completed_audio_segment(item, request)
                    text = text.strip()
                    logger.info(
                        "STTService '%s' completed audio segment transcription finished: source_sequence=%s text_length=%s.",
                        self.name,
                        item.source_sequence,
                        len(text),
                    )
                    if text:
                        await queue.put(text)
                    continue

                yield item

        try:
            outbound_req = map_service_to_outbound_stream_request(
                ServiceStreamRequest(
                    audio_stream=live_audio_stream(),
                    sample_rate=request.sample_rate,
                    chunk_size=request.chunk_size,
                    silence_threshold=request.silence_threshold,
                    silence_limit_seconds=request.silence_limit_seconds,
                )
            )
            outbound_res = await self.outbound_port.process_stream(outbound_req)
            async for text in outbound_res.text_stream:
                if text:
                    logger.info("STTService '%s' queued shared transcription: text_length=%s.", self.name, len(text))
                    await queue.put(text)
                    logger.info(
                        "STTService '%s' sent chunked text to shared out stream: text_length=%s text=%r.",
                        self.name,
                        len(text),
                        text,
                    )
        except asyncio.CancelledError:
            logger.info("STTService '%s' shared stream forwarding task cancelled.", self.name)
            raise
        except Exception as exc:
            logger.exception("STTService '%s' shared stream forwarding failed.", self.name)
            await queue.put(SharedStreamForwardingError(str(exc)))
        finally:
            await queue.put(None)

    async def _transcribe_completed_audio_segment(
        self,
        segment: CompletedAudioSegment,
        request: ServiceSetStreamRequest,
    ) -> str:
        logger.info(
            "STTService '%s' invoking completed-audio transcription: source_sequence=%s bytes=%s sample_rate=%s.",
            self.name,
            segment.source_sequence,
            len(segment.audio_data),
            request.sample_rate,
        )
        outbound_req = map_service_to_outbound_batch_request(
            ServiceBatchRequest(
                audio_data=segment.audio_data,
                sample_rate=request.sample_rate,
            )
        )
        outbound_res = await self.outbound_port.process_batch(outbound_req)
        return outbound_res.text

    async def _queue_text_stream(
        self,
        queue: asyncio.Queue[Optional[str | Exception]],
    ) -> AsyncIterator[str]:
        while True:
            text = await queue.get()
            try:
                if text is None:
                    logger.info("STTService '%s' shared text stream reached completion sentinel.", self.name)
                    break
                if isinstance(text, Exception):
                    raise text
                yield text
            finally:
                queue.task_done()

    async def process_batch(self, request: ServiceBatchRequest) -> ServiceBatchResponse:
        logger.info(
            "STTService '%s' processing batch: bytes=%s sample_rate=%s.",
            self.name,
            len(request.audio_data),
            request.sample_rate,
        )
        outbound_req = map_service_to_outbound_batch_request(request)
        outbound_res = await self.outbound_port.process_batch(outbound_req)
        logger.info("STTService '%s' received outbound batch response: text_length=%s.", self.name, len(outbound_res.text))
        return map_outbound_to_service_batch_response(outbound_res)

    async def is_available(self, request: ServiceAvailabilityRequest) -> ServiceAvailabilityResponse:
        logger.info("STTService '%s' checking outbound adapter availability.", self.name)
        outbound_req = map_service_to_outbound_availability_request(request)
        outbound_res = await self.outbound_port.is_available(outbound_req)
        logger.info("STTService '%s' availability result: %s.", self.name, outbound_res.is_available)
        return map_outbound_to_service_availability_response(outbound_res)
