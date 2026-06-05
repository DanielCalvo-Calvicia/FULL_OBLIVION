import asyncio
import os
import tempfile
import wave
from typing import AsyncIterator

import numpy as np
from openai import OpenAI

from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.dtos.adapter_outbound_dtos import (
    InitOutboundAdapterDto,
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    STTAvailabilityRequestDto,
    STTAvailabilityResponseDto,
)
from runtime.logger import get_logger


# ─── Constants ────────────────────────────────────────────────────────
logger = get_logger(__name__)

_EMA_DECAY = 0.9
_EMA_ADAPT = 0.1
_WAV_CHANNELS = 1       # Always mono
_WAV_SAMPLE_WIDTH = 2   # 16-bit PCM = 2 bytes per sample
_WHISPER_MODEL = "whisper-1"


class _AsyncOpenAITextStream(AsyncIterator[str]):
    def __init__(self, request: ProcessStreamRequestDto, api_key: str, language: str = "en"):
        self.request = request
        self.client = OpenAI(api_key=api_key)
        self.language = language
        logger.info(
            "Initialized OpenAI async text stream: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s language=%s.",
            request.sample_rate,
            request.chunk_size,
            request.silence_threshold,
            request.silence_limit_seconds,
            self.language,
        )

        self.audio_buffer = bytearray()
        self.silent_chunks = 0
        self._chunks_seen = 0
        self._bytes_seen = 0
        self._last_volume = None
        self._pending_pcm_byte = b""

        chunks_per_second = self.request.sample_rate / self.request.chunk_size
        self.silence_limit_chunks = int(
            chunks_per_second * self.request.silence_limit_seconds
        )

        self._smoothed_volume = 0.0
        self._noise_floor = float("inf")
        self._noise_samples = 0
        self._is_speaking = False

    def __aiter__(self) -> "_AsyncOpenAITextStream":
        return self

    async def __anext__(self) -> str:
        while True:
            try:
                async for chunk in self.request.audio_stream:
                    self._chunks_seen += 1
                    self._bytes_seen += len(chunk)
                    logger.debug("OpenAI stream received audio chunk: bytes=%s.", len(chunk))
                    pcm_chunk = self._complete_pcm_chunk(chunk)
                    volume = self._compute_volume(pcm_chunk)
                    self._last_volume = volume
                    self._print_debug_status(volume)

                    if not self._is_speaking and volume >= self._start_threshold():
                        self._is_speaking = True
                        self.silent_chunks = 0
                        logger.info("OpenAI stream detected speech start: volume=%s.", volume)

                    if self._is_speaking:
                        self.audio_buffer.extend(pcm_chunk)

                    self._update_silence_counter(volume)

                    if self._is_speaking and self._is_utterance_complete():
                        logger.info("OpenAI stream detected utterance completion: buffered_bytes=%s.", len(self.audio_buffer))
                        text = await self._transcribe_utterance()
                        if text:
                            return text
                        continue
            except Exception:
                logger.exception(
                    "OpenAI audio stream failed while reading upstream audio iterator: chunks_seen=%s bytes_seen=%s buffered_bytes=%s is_speaking=%s silent_chunks=%s silence_limit_chunks=%s.",
                    self._chunks_seen,
                    self._bytes_seen,
                    len(self.audio_buffer),
                    self._is_speaking,
                    self.silent_chunks,
                    self.silence_limit_chunks,
                )
                raise

            logger.info(
                "OpenAI audio stream exhausted: cause=upstream_audio_iterator_completed chunks_seen=%s bytes_seen=%s buffered_bytes=%s is_speaking=%s silent_chunks=%s silence_limit_chunks=%s last_volume=%s start_threshold=%s effective_threshold=%s.",
                self._chunks_seen,
                self._bytes_seen,
                len(self.audio_buffer),
                self._is_speaking,
                self.silent_chunks,
                self.silence_limit_chunks,
                self._last_volume,
                self._start_threshold(),
                self._effective_threshold(),
            )
            if self._is_speaking and len(self.audio_buffer) > 0:
                if self._pending_pcm_byte:
                    logger.warning(
                        "OpenAI audio stream ended with one incomplete PCM byte; dropping trailing byte before final buffer handling."
                    )
                    self._pending_pcm_byte = b""
                logger.info(
                    "OpenAI audio stream ended with an unfinished utterance buffered; transcribing final buffered audio: buffered_bytes=%s silent_chunks=%s silence_limit_chunks=%s.",
                    len(self.audio_buffer),
                    self.silent_chunks,
                    self.silence_limit_chunks,
                )
                text = await self._transcribe_utterance()
                if text:
                    return text
            raise StopAsyncIteration

    def _complete_pcm_chunk(self, chunk: bytes) -> bytes:
        if self._pending_pcm_byte:
            chunk = self._pending_pcm_byte + chunk
            self._pending_pcm_byte = b""
        if len(chunk) % _WAV_SAMPLE_WIDTH == 0:
            return chunk
        self._pending_pcm_byte = chunk[-1:]
        complete_chunk = chunk[:-1]
        logger.debug(
            "OpenAI stream carried incomplete PCM byte to next chunk: input_bytes=%s complete_bytes=%s.",
            len(chunk),
            len(complete_chunk),
        )
        return complete_chunk

    def _compute_volume(self, chunk: bytes) -> int:
        if len(chunk) == 0:
            return 0
        data = np.frombuffer(chunk, dtype=np.int16)
        raw_volume = 0 if len(data) == 0 else int(np.sqrt(np.mean(np.square(data.astype(np.float64)))))
        self._track_noise_floor(raw_volume)
        return self._smooth_volume(raw_volume)

    def _track_noise_floor(self, raw_volume: float) -> None:
        if raw_volume == 0:
            return
        if raw_volume < self._noise_floor:
            self._noise_floor = raw_volume
        if self._noise_samples < 100:
            self._noise_samples += 1

    def _smooth_volume(self, raw_volume: float) -> int:
        self._smoothed_volume = (
            self._smoothed_volume * _EMA_DECAY + raw_volume * _EMA_ADAPT
        )
        return int(self._smoothed_volume)

    def _print_debug_status(self, volume: int) -> None:
        effective_threshold = self._effective_threshold()
        start_threshold = self._start_threshold()
        speaking_flag = "S" if self._is_speaking else " "
        logger.trace(
            "OpenAI stream status: volume=%s start_threshold=%s effective_threshold=%s silent_chunks=%s speaking=%s.",
            volume,
            start_threshold,
            effective_threshold,
            self.silent_chunks,
            speaking_flag == "S",
        )

    def _update_silence_counter(self, volume: int) -> None:
        if self._is_speaking and volume < self._effective_threshold():
            self.silent_chunks += 1
        else:
            self.silent_chunks = 0

    def _effective_threshold(self) -> int:
        if self._noise_floor == float("inf"):
            return self.request.silence_threshold
        noise_threshold = int(self._noise_floor * 2.0)
        return max(self.request.silence_threshold, noise_threshold)

    def _start_threshold(self) -> int:
        if self._noise_floor == float("inf"):
            return self.request.silence_threshold * 2
        return max(self.request.silence_threshold * 2, int(self._noise_floor * 3.0))

    def _is_utterance_complete(self) -> bool:
        return self.silent_chunks >= self.silence_limit_chunks

    async def _transcribe_utterance(self) -> str:
        if len(self.audio_buffer) == 0:
            logger.debug("OpenAI utterance transcription skipped because buffer is empty.")
            self.silent_chunks = 0
            return ""

        logger.info("Sending utterance to OpenAI Whisper: bytes=%s sample_rate=%s.", len(self.audio_buffer), self.request.sample_rate)
        text = await asyncio.to_thread(
            self._transcribe_with_openai,
            bytes(self.audio_buffer),
            self.request.sample_rate,
        )

        self._reset_buffers()

        if text:
            logger.info("OpenAI Whisper returned transcription: text_length=%s.", len(text))
            logger.info("OpenAI transcription result: %s", text)
        else:
            logger.info("OpenAI Whisper returned empty transcription.")

        return text

    def _reset_buffers(self) -> None:
        logger.debug("Resetting OpenAI stream buffers.")
        self.audio_buffer.clear()
        self.silent_chunks = 0
        self._is_speaking = False

    def _transcribe_with_openai(self, raw_pcm: bytes, sample_rate: int) -> str:
        logger.debug("Preparing OpenAI transcription request from raw PCM: bytes=%s sample_rate=%s.", len(raw_pcm), sample_rate)
        wav_path = self._write_wav_file(raw_pcm, sample_rate)
        try:
            return self._call_whisper_api(wav_path)
        finally:
            self._cleanup_temp_file(wav_path)

    @staticmethod
    def _write_wav_file(raw_pcm: bytes, sample_rate: int) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = wav_file.name
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(_WAV_CHANNELS)
            wf.setsampwidth(_WAV_SAMPLE_WIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(raw_pcm)
        logger.debug("Temporary WAV file created for OpenAI transcription: %s.", wav_path)
        return wav_path

    def _call_whisper_api(self, wav_path: str) -> str:
        logger.info(
            "Calling OpenAI audio transcription API with model '%s' and language '%s'.",
            _WHISPER_MODEL,
            self.language,
        )
        with open(wav_path, "rb") as audio_file:
            result = self.client.audio.transcriptions.create(
                model=_WHISPER_MODEL,
                file=audio_file,
                language=self.language,
                temperature=0.0,
                response_format="text",
        )
        logger.info("OpenAI audio transcription API call completed.")
        return result.strip() if isinstance(result, str) else str(result)

    @staticmethod
    def _cleanup_temp_file(path: str) -> None:
        try:
            os.remove(path)
            logger.debug("Temporary WAV file removed: %s.", path)
        except OSError:
            logger.warning("Failed to remove temporary WAV file: %s.", path)
            pass


class OpenAISTTAdapter(AdapterOutboundPort):
    def __init__(self, config: InitOutboundAdapterDto):
        self.api_key = config.api_key
        self.language = config.language or "en"
        logger.info(
            "OpenAI STT Adapter initialized with configured model name '%s' and language '%s'.",
            config.model_name,
            self.language,
        )

    async def process_stream(
        self, request: ProcessStreamRequestDto
    ) -> ProcessStreamResponseDto:
        logger.info("OpenAI STT Adapter processing stream request.")
        text_stream = _AsyncOpenAITextStream(request, self.api_key, self.language)
        return ProcessStreamResponseDto(text_stream=text_stream)

    async def process_batch(
        self, request: ProcessBatchRequestDto
    ) -> ProcessBatchResponseDto:
        logger.info("OpenAI STT Adapter processing batch request: bytes=%s sample_rate=%s.", len(request.audio_data), request.sample_rate)
        client = OpenAI(api_key=self.api_key)
        wav_path = _AsyncOpenAITextStream._write_wav_file(
            request.audio_data, request.sample_rate
        )
        try:
            with open(wav_path, "rb") as audio_file:
                logger.info(
                    "Calling OpenAI audio transcription API for batch request with model '%s' and language '%s'.",
                    _WHISPER_MODEL,
                    self.language,
                )
                result = await asyncio.to_thread(
                    client.audio.transcriptions.create,
                    model=_WHISPER_MODEL,
                    file=audio_file,
                    language=self.language,
                    temperature=0.0,
                    response_format="text",
                )
            text = result.strip() if isinstance(result, str) else str(result)
            logger.info("OpenAI batch transcription completed: text_length=%s.", len(text))
            return ProcessBatchResponseDto(text=text)
        finally:
            _AsyncOpenAITextStream._cleanup_temp_file(wav_path)

    async def is_available(
        self, request: STTAvailabilityRequestDto
    ) -> STTAvailabilityResponseDto:
        logger.info("OpenAI STT Adapter availability checked: api_key_present=%s.", bool(self.api_key))
        return STTAvailabilityResponseDto(is_available=bool(self.api_key))
