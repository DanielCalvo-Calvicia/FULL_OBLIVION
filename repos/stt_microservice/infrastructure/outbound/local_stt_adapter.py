import asyncio
import numpy as np
from typing import Any, AsyncIterator
from faster_whisper import WhisperModel

from application.ports.adapter_outbound_port import AdapterOutboundPort
from runtime.logger import get_logger
from application.dtos.adapter_outbound_dtos import (
    InitOutboundAdapterDto,
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    STTAvailabilityRequestDto,
    STTAvailabilityResponseDto,
)

logger = get_logger(__name__)


class AsyncTextStream(AsyncIterator[str]):
    def __init__(self, request: ProcessStreamRequestDto, model: Any, language: str = "en"):
        self.request = request
        self.model = model
        self.language = language
        logger.info(
            "Initialized local async text stream: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s language=%s.",
            request.sample_rate,
            request.chunk_size,
            request.silence_threshold,
            request.silence_limit_seconds,
            self.language,
        )
        self.audio_buffer = bytearray()
        self.silent_chunks = 0
        self._pending_pcm_byte = b""
        
        chunks_per_second = self.request.sample_rate / self.request.chunk_size
        self.silence_limit_chunks = int(chunks_per_second * self.request.silence_limit_seconds)

        self.transcription_queue = asyncio.Queue()
        self._vad_task = asyncio.create_task(self._continuous_vad())
        logger.info("Local continuous VAD task created.")

    async def _continuous_vad(self):
        smoothed_volume = 0.0
        dc_offset = 0.0
        logger.info("Local continuous VAD loop started.")
        try:
            async for chunk in self.request.audio_stream:
                logger.debug("Local VAD received audio chunk: bytes=%s.", len(chunk))
                chunk = self._complete_pcm_chunk(chunk)
                audio_array = np.frombuffer(chunk, dtype=np.int16)
                if len(audio_array) > 0:
                    audio_float = audio_array.astype(np.float32)
                    
                    chunk_mean = np.mean(audio_float)
                    dc_offset = (dc_offset * 0.95) + (chunk_mean * 0.05)
                    audio_float -= dc_offset
                    
                    raw_volume = np.sqrt(np.mean(np.square(audio_float)))
                    smoothed_volume = (smoothed_volume * 0.9) + (raw_volume * 0.1)
                    volume = int(smoothed_volume)
                else:
                    volume = 0

                logger.trace(
                    "Local VAD status: volume=%s threshold=%s silent_chunks=%s.",
                    volume,
                    self.request.silence_threshold,
                    self.silent_chunks,
                )

                if volume < self.request.silence_threshold:
                    self.silent_chunks += 1
                else:
                    self.silent_chunks = 0

                if volume >= self.request.silence_threshold or len(self.audio_buffer) > 0:
                    self.audio_buffer.extend(chunk)

                if self.silent_chunks >= self.silence_limit_chunks:
                    if len(self.audio_buffer) > 0:
                        logger.info("Local VAD queued utterance for transcription: buffered_bytes=%s.", len(self.audio_buffer))
                        await self.transcription_queue.put(bytearray(self.audio_buffer))
                        self.audio_buffer.clear()
                        self.silent_chunks = 0
                    else:
                        self.silent_chunks = 0
        finally:
            if self._pending_pcm_byte:
                logger.warning("Local VAD dropped one trailing incomplete PCM byte.")
                self._pending_pcm_byte = b""
            if len(self.audio_buffer) > 0:
                logger.info(
                    "Local VAD queued final buffered utterance after audio stream ended: buffered_bytes=%s.",
                    len(self.audio_buffer),
                )
                await self.transcription_queue.put(bytearray(self.audio_buffer))
                self.audio_buffer.clear()
            logger.info("Local continuous VAD loop completed.")
            await self.transcription_queue.put(None)

    def _complete_pcm_chunk(self, chunk: bytes) -> bytes:
        if self._pending_pcm_byte:
            chunk = self._pending_pcm_byte + chunk
            self._pending_pcm_byte = b""
        if len(chunk) % 2 == 0:
            return chunk
        self._pending_pcm_byte = chunk[-1:]
        logger.debug(
            "Local VAD carried incomplete PCM byte to next chunk: input_bytes=%s complete_bytes=%s.",
            len(chunk),
            len(chunk) - 1,
        )
        return chunk[:-1]

    def __aiter__(self):
        return self

    def _transcribe_sync(self, audio_buffer: bytearray, sample_rate: int) -> str:
        logger.info("Local synchronous transcription started: bytes=%s sample_rate=%s.", len(audio_buffer), sample_rate)
        audio_data = np.frombuffer(
            bytes(audio_buffer), np.int16
        ).flatten().astype(np.float32) / 32768.0

        target_sr = 16000
        if sample_rate != target_sr:
            logger.info("Resampling local audio from %s Hz to %s Hz.", sample_rate, target_sr)
            target_len = int(len(audio_data) * target_sr / sample_rate)
            original_indices = np.arange(len(audio_data))
            target_indices = np.linspace(0, len(audio_data) - 1, target_len)
            audio_data = np.interp(target_indices, original_indices, audio_data).astype(np.float32)

        segments, _info = self.model.transcribe(
            audio_data, 
            beam_size=5, 
            language=self.language,
            condition_on_previous_text=False,
            no_speech_threshold=0.65
        )

        text_output = ""
        for segment in segments:
            if segment.text.strip():
                text_output += segment.text
                
        logger.info("Local synchronous transcription completed: text_length=%s.", len(text_output.strip()))
        return text_output

    async def __anext__(self) -> str:
        while True:
            logger.debug("Waiting for local transcription queue item.")
            audio_buffer_to_transcribe = await self.transcription_queue.get()
            
            if audio_buffer_to_transcribe is None:
                logger.info("Local text stream received completion sentinel.")
                raise StopAsyncIteration
                
            logger.info("Local text stream dequeued utterance: bytes=%s.", len(audio_buffer_to_transcribe))
            logger.info("Processing audio locally.")
            
            text_output = await asyncio.to_thread(
                self._transcribe_sync,
                audio_buffer_to_transcribe,
                self.request.sample_rate
            )

            self.transcription_queue.task_done()

            if text_output.strip():
                logger.info("Local text stream returning transcription: text_length=%s.", len(text_output.strip()))
                logger.info("Local transcription result: %s", text_output.strip())
                return text_output.strip()
            else:
                logger.info("Local text stream discarded empty transcription.")


class LocalSTTAdapter(AdapterOutboundPort):
    def __init__(self, config: InitOutboundAdapterDto):
        model_name = config.model_name or "small.en"
        self.language = config.language or "en"
        logger.info("Loading local Whisper model '%s' on CPU with int8 compute.", model_name)
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=2)
        logger.info("Local Whisper model '%s' loaded with language '%s'.", model_name, self.language)

    async def process_stream(
        self, request: ProcessStreamRequestDto
    ) -> ProcessStreamResponseDto:
        logger.info("Local STT Adapter processing stream request.")
        text_stream = AsyncTextStream(request, self.model, self.language)
        return ProcessStreamResponseDto(text_stream=text_stream)

    async def process_batch(
        self, request: ProcessBatchRequestDto
    ) -> ProcessBatchResponseDto:
        logger.info("Local STT Adapter processing batch request: bytes=%s sample_rate=%s.", len(request.audio_data), request.sample_rate)
        
        audio_data = np.frombuffer(
            request.audio_data, np.int16
        ).flatten().astype(np.float32) / 32768.0

        target_sr = 16000
        if request.sample_rate != target_sr:
            logger.info("Resampling local batch audio from %s Hz to %s Hz.", request.sample_rate, target_sr)
            target_len = int(len(audio_data) * target_sr / request.sample_rate)
            original_indices = np.arange(len(audio_data))
            target_indices = np.linspace(0, len(audio_data) - 1, target_len)
            audio_data = np.interp(target_indices, original_indices, audio_data).astype(np.float32)

        segments, _info = await asyncio.to_thread(
            self.model.transcribe,
            audio_data, 
            beam_size=5, 
            language=self.language,
            condition_on_previous_text=False,
            no_speech_threshold=0.65
        )

        text_output = "".join([s.text for s in segments if s.text.strip()])
        logger.info("Local batch transcription completed: text_length=%s.", len(text_output))
        return ProcessBatchResponseDto(text=text_output)

    async def is_available(
        self, request: STTAvailabilityRequestDto
    ) -> STTAvailabilityResponseDto:
        logger.info("Local STT Adapter availability checked: model_loaded=%s.", self.model is not None)
        return STTAvailabilityResponseDto(is_available=self.model is not None)
