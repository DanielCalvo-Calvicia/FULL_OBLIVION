import asyncio
from typing import Any, AsyncIterator, Optional

import httpx
from application.dtos.stream_items import AudioSegmentEnd, AudioStreamError

from application.dtos.adapter_outbound_dtos import (
    InitOutboundAdapterDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    SetStreamRequestDto,
    GetStreamRequestDto,
    GetStreamResponseDto,
    TTSAvailabilityRequestDto,
    TTSAvailabilityResponseDto,
)
from application.ports.adapter_outbound_port import AdapterOutboundPort
from infrastructure.logger import get_logger


logger = get_logger(__name__)

DEFAULT_CHUNK_SIZE = 8192
REQUEST_TIMEOUT_SECONDS = 120.0


class OpenAIAudioStream(AsyncIterator[bytes]):
    def __init__(self, request: ProcessStreamRequestDto, adapter: "OpenAITTSAdapter"):
        self.request = request
        self.adapter = adapter
        self.chunk_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue[Optional[bytes]]()
        self._generator_task: asyncio.Task[None] = asyncio.create_task(self._generate_audio())
        logger.info(
            "OpenAIAudioStream initialized sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )

    async def _generate_audio(self) -> None:
        logger.info("OpenAIAudioStream generation task started")
        try:
            async for text in self.request.text_stream:
                text = text.strip()
                if not text:
                    logger.info("OpenAIAudioStream skipped blank text item")
                    continue

                logger.info("OpenAIAudioStream synthesizing text_length=%s", len(text))
                async for chunk in self.adapter.iter_speech_chunks(text):
                    await self.chunk_queue.put(chunk)
        except asyncio.CancelledError:
            logger.info("OpenAIAudioStream generation task cancelled")
        finally:
            logger.info("OpenAIAudioStream enqueueing end-of-stream sentinel")
            await self.chunk_queue.put(None)

    def __aiter__(self) -> "OpenAIAudioStream":
        return self

    async def __anext__(self) -> bytes:
        chunk = await self.chunk_queue.get()
        if chunk is None:
            logger.info("OpenAIAudioStream consumer reached end-of-stream sentinel")
            raise StopAsyncIteration
        return chunk


class DecoupledOpenAIAudioStream(AsyncIterator[Any]):
    def __init__(self, queue: asyncio.Queue[Any]):
        self._queue = queue

    def __aiter__(self) -> "DecoupledOpenAIAudioStream":
        return self

    async def __anext__(self) -> Any:
        item = await self._queue.get()
        if item is None:
            logger.info("DecoupledOpenAIAudioStream consumer reached end-of-stream sentinel")
            raise StopAsyncIteration
        return item


class OpenAITTSAdapter(AdapterOutboundPort):
    def __init__(self, config: Optional[InitOutboundAdapterDto] = None):
        self.config = config
        self._audio_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._generator_task: Optional[asyncio.Task[None]] = None
        logger.info("OpenAITTSAdapter created initialized=%s", config is not None)

    async def init(self, config: InitOutboundAdapterDto) -> None:
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when TTS_ADAPTER=openai.")

        if config.openai_response_format not in {"mp3", "opus", "aac", "flac", "wav", "pcm"}:
            raise ValueError(
                "OPENAI_TTS_RESPONSE_FORMAT must be one of mp3, opus, aac, flac, wav, or pcm."
            )

        self.config = config
        logger.info(
            "OpenAITTSAdapter configured model=%s voice=%s response_format=%s base_url=%s",
            config.openai_model,
            config.openai_voice,
            config.openai_response_format,
            config.openai_base_url,
        )

    def _require_config(self) -> InitOutboundAdapterDto:
        if self.config is None:
            raise RuntimeError("OpenAITTSAdapter must be initialized before use.")
        return self.config

    def _headers(self) -> dict[str, str]:
        config = self._require_config()
        return {
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json",
        }

    def _speech_payload(self, text: str) -> dict[str, object]:
        config = self._require_config()
        payload: dict[str, object] = {
            "model": config.openai_model,
            "voice": config.openai_voice,
            "input": text,
            "response_format": config.openai_response_format,
        }
        if config.openai_instructions:
            payload["instructions"] = config.openai_instructions
        if config.openai_speed is not None:
            payload["speed"] = config.openai_speed
        return payload

    async def iter_speech_chunks(self, text: str) -> AsyncIterator[bytes]:
        config = self._require_config()
        speech_url = f"{config.openai_base_url.rstrip('/')}/audio/speech"
        timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                speech_url,
                headers=self._headers(),
                json=self._speech_payload(text),
            ) as response:
                if response.status_code >= 400:
                    error_body = await response.aread()
                    raise RuntimeError(
                        "OpenAI speech generation failed "
                        f"status_code={response.status_code} body={error_body.decode('utf-8', errors='ignore')}"
                    )

                async for chunk in response.aiter_bytes(chunk_size=DEFAULT_CHUNK_SIZE):
                    if chunk:
                        yield chunk

    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        logger.info(
            "OpenAITTSAdapter.process_stream started sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        self._require_config()
        return ProcessStreamResponseDto(audio_stream=OpenAIAudioStream(request, self))

    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        logger.info(
            "OpenAITTSAdapter.process_batch started text_length=%s sample_rate=%s channels=%s",
            len(request.text),
            request.sample_rate,
            request.channels,
        )
        audio = bytearray()
        async for chunk in self.iter_speech_chunks(request.text):
            audio.extend(chunk)
        logger.info("OpenAITTSAdapter.process_batch finished audio_bytes=%s", len(audio))
        return ProcessBatchResponseDto(audio_data=bytes(audio))

    async def set_stream(self, request: SetStreamRequestDto) -> None:
        logger.info(
            "OpenAITTSAdapter.set_stream started sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        if self._generator_task is not None and not self._generator_task.done():
            self._generator_task.cancel()
            try:
                await self._generator_task
            except asyncio.CancelledError:
                logger.info("OpenAITTSAdapter.set_stream previous generator task cancelled")

        self._audio_queue = asyncio.Queue()
        self._generator_task = asyncio.create_task(self._generate_decoupled_audio(request))

    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        logger.info("OpenAITTSAdapter.get_stream started")
        return GetStreamResponseDto(audio_stream=DecoupledOpenAIAudioStream(self._audio_queue))

    async def _generate_decoupled_audio(self, request: SetStreamRequestDto) -> None:
        logger.info("OpenAITTSAdapter decoupled generation task started")
        try:
            async for text in request.text_stream:
                text = text.strip()
                if not text:
                    logger.info("OpenAITTSAdapter decoupled generation skipped blank text item")
                    continue

                logger.info("OpenAITTSAdapter decoupled generation synthesizing text_length=%s", len(text))
                async for chunk in self.iter_speech_chunks(text):
                    await self._audio_queue.put(chunk)
                await self._audio_queue.put(AudioSegmentEnd())
                logger.info("OpenAITTSAdapter decoupled generation queued audio segment end")
        except asyncio.CancelledError:
            logger.info("OpenAITTSAdapter decoupled generation task cancelled")
        except Exception as exc:
            logger.exception("OpenAITTSAdapter decoupled generation failed")
            await self._audio_queue.put(
                AudioStreamError(
                    code="synthesis_failed",
                    message=f"Failed to synthesize speech: {str(exc)}",
                    recoverable=True,
                )
            )
        finally:
            logger.info("OpenAITTSAdapter decoupled generation enqueueing end-of-stream sentinel")
            await self._audio_queue.put(None)

    async def is_available(self, request: TTSAvailabilityRequestDto) -> TTSAvailabilityResponseDto:
        logger.info("OpenAITTSAdapter.is_available started")
        try:
            config = self._require_config()
            model_url = f"{config.openai_base_url.rstrip('/')}/models/{config.openai_model}"
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.get(model_url, headers=self._headers())
            is_available = response.status_code < 400
            logger.info(
                "OpenAITTSAdapter.is_available finished status_code=%s is_available=%s",
                response.status_code,
                is_available,
            )
            return TTSAvailabilityResponseDto(is_available=is_available)
        except Exception:
            logger.exception("OpenAITTSAdapter.is_available failed")
            return TTSAvailabilityResponseDto(is_available=False)
