import asyncio
import tempfile
import os
import sys
import wave
from typing import Any, AsyncIterator, Optional

from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.dtos.stream_items import AudioSegmentEnd, AudioStreamError
from application.dtos.adapter_outbound_dtos import (
    InitOutboundAdapterDto,
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    TTSAvailabilityRequestDto,
    TTSAvailabilityResponseDto,
    SetStreamRequestDto,
    GetStreamRequestDto,
    GetStreamResponseDto,
)
from infrastructure.logger import get_logger


logger = get_logger(__name__)


async def _run_tts_subprocess(text: str, file_path: str, speech_rate: int, voice_name_pref: str) -> None:
    """
    Spawns pyttsx3 in an isolated process using the current python executable.
    This completely isolates SAPI5/COM thread execution to a fresh OS process,
    preventing any STA/MTA COM apartment conflicts or event loop hangs on Windows.
    """
    try:
        logger.info(
            "TTS subprocess preparation started text_length=%s file_path=%s speech_rate=%s voice_name_pref=%s",
            len(text),
            file_path,
            speech_rate,
            voice_name_pref,
        )
        script = (
            "import pyttsx3\n"
            "engine = pyttsx3.init()\n"
            f"engine.setProperty('rate', {speech_rate})\n"
            "voices = engine.getProperty('voices')\n"
            "selected_voice = None\n"
            "for voice in voices:\n"
            # Look for a safer identifier or default to the first one found
            f"    if {repr(voice_name_pref)} in voice.name or 'en' in voice.id:\n"
            "        selected_voice = voice.id\n"
            "        break\n"
            "if selected_voice:\n"
            "    engine.setProperty('voice', selected_voice)\n"
            f"engine.save_to_file({repr(text)}, {repr(file_path)})\n"
            "engine.runAndWait()\n"
        )

        logger.info("TTS subprocess script generated length=%s", len(script))
        logger.debug("TTS subprocess script contents: %s", script)

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        logger.info("TTS subprocess started pid=%s", process.pid)

        stdout, stderr = await process.communicate()

        stdout_text = stdout.decode('utf-8', errors='ignore')
        stderr_text = stderr.decode("utf-8", errors="ignore")
        logger.info(
            "TTS subprocess finished pid=%s returncode=%s stdout_length=%s stderr_length=%s",
            process.pid,
            process.returncode,
            len(stdout_text),
            len(stderr_text),
        )
        if stdout_text:
            logger.debug("TTS subprocess stdout: %s", stdout_text)

        if process.returncode != 0:
            raise RuntimeError(f"TTS Subprocess synthesis failed: {stderr_text}")
        logger.info("TTS subprocess synthesis succeeded file_path=%s", file_path)
    except Exception:
        logger.exception("Unexpected error in TTS subprocess")
        raise


class AsyncAudioStream(AsyncIterator[bytes]):
    def __init__(self, request: ProcessStreamRequestDto, config: InitOutboundAdapterDto):
        self.request = request
        self.config = config
        self.chunk_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue[Optional[bytes]]()
        logger.info(
            "AsyncAudioStream initialized sample_rate=%s channels=%s speech_rate=%s voice=%s",
            request.sample_rate,
            request.channels,
            config.speech_rate,
            config.voice_name_preference,
        )
        self._generator_task: asyncio.Task[None] = asyncio.create_task(self._generate_audio())

    async def _generate_audio(self) -> None:
        logger.info("AsyncAudioStream generation task started")
        try:
            text_count = 0
            chunk_count = 0
            total_bytes = 0
            async for text in self.request.text_stream:
                if not text.strip():
                    logger.info("AsyncAudioStream skipped blank text item")
                    continue

                text_count += 1
                logger.info("AsyncAudioStream synthesizing text_index=%s text_length=%s", text_count, len(text))
                temp_path = ""
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                    temp_path = temp_wav.name
                logger.info("AsyncAudioStream temporary WAV created path=%s", temp_path)

                try:
                    # Run pyttsx3 in a fully isolated subprocess to prevent thread block / COM STA deadlock
                    await _run_tts_subprocess(
                        text=text,
                        file_path=temp_path,
                        speech_rate=self.config.speech_rate,
                        voice_name_pref=self.config.voice_name_preference
                    )

                    # Stream PCM chunks from the generated Wave file
                    with wave.open(temp_path, 'rb') as wf:
                        chunk_size = 1024
                        data = wf.readframes(chunk_size)
                        while data:
                            await self.chunk_queue.put(data)
                            chunk_count += 1
                            total_bytes += len(data)
                            logger.info(
                                "AsyncAudioStream queued chunk text_index=%s chunk_count=%s chunk_bytes=%s total_bytes=%s",
                                text_count,
                                chunk_count,
                                len(data),
                                total_bytes,
                            )
                            await asyncio.sleep(0.001)  # Yield control to prevent starvation
                            data = wf.readframes(chunk_size)
                finally:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                            logger.info("AsyncAudioStream temporary WAV removed path=%s", temp_path)
                        except OSError:
                            logger.exception("AsyncAudioStream failed to remove temporary WAV path=%s", temp_path)
            logger.info(
                "AsyncAudioStream generation completed text_count=%s chunk_count=%s total_bytes=%s",
                text_count,
                chunk_count,
                total_bytes,
            )
        except asyncio.CancelledError:
            logger.info("AsyncAudioStream generation task cancelled")
            pass
        finally:
            logger.info("AsyncAudioStream enqueueing end-of-stream sentinel")
            await self.chunk_queue.put(None)  # Sentinel to stop consumer

    def __aiter__(self) -> "AsyncAudioStream":
        return self

    async def __anext__(self) -> bytes:
        chunk = await self.chunk_queue.get()
        if chunk is None:
            logger.info("AsyncAudioStream consumer reached end-of-stream sentinel")
            raise StopAsyncIteration
        logger.info("AsyncAudioStream consumer returning chunk_bytes=%s", len(chunk))
        return chunk


class DecoupledAudioStream(AsyncIterator[Any]):
    """Async iterator that drains audio chunks from the shared single-flow queue."""

    def __init__(self, queue: asyncio.Queue[Any]):
        self._queue = queue

    def __aiter__(self) -> "DecoupledAudioStream":
        return self

    async def __anext__(self) -> Any:
        item = await self._queue.get()
        if item is None:
            logger.info("DecoupledAudioStream consumer reached end-of-stream sentinel")
            raise StopAsyncIteration
        if isinstance(item, AudioStreamError):
            logger.info("DecoupledAudioStream consumer returning audio stream error code=%s", item.code)
            return item
        if isinstance(item, AudioSegmentEnd):
            logger.info("DecoupledAudioStream consumer returning audio segment end")
            return item
        logger.info("DecoupledAudioStream consumer returning chunk_bytes=%s", len(item))
        return item


class PyTTSx3Adapter(AdapterOutboundPort):
    def __init__(self, config: Optional[InitOutboundAdapterDto] = None):
        self.config = config
        self._audio_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._generator_task: Optional[asyncio.Task[None]] = None
        logger.info("PyTTSx3Adapter created initialized=%s", config is not None)

    async def init(self, config: InitOutboundAdapterDto) -> None:
        self.config = config
        logger.info(
            "PyTTSx3Adapter configured speech_rate=%s voice_name_preference=%s",
            config.speech_rate,
            config.voice_name_preference,
        )

    def _require_config(self) -> InitOutboundAdapterDto:
        if self.config is None:
            raise RuntimeError("PyTTSx3Adapter must be initialized before use.")
        return self.config

    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        logger.info(
            "PyTTSx3Adapter.process_stream started sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        audio_stream = AsyncAudioStream(request, self._require_config())
        logger.info("PyTTSx3Adapter.process_stream returning AsyncAudioStream")
        return ProcessStreamResponseDto(audio_stream=audio_stream)

    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        logger.info(
            "PyTTSx3Adapter.process_batch started text_length=%s sample_rate=%s channels=%s",
            len(request.text),
            request.sample_rate,
            request.channels,
        )
        config = self._require_config()
        temp_path = ""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            temp_path = temp_wav.name
        logger.info("PyTTSx3Adapter.process_batch temporary WAV created path=%s", temp_path)

        try:
            await _run_tts_subprocess(
                text=request.text,
                file_path=temp_path,
                speech_rate=config.speech_rate,
                voice_name_pref=config.voice_name_preference,
            )

            audio_data = bytearray()
            with wave.open(temp_path, "rb") as wf:
                chunk_size = 1024
                data = wf.readframes(chunk_size)
                chunk_count = 0
                total_bytes = 0
                while data:
                    audio_data.extend(data)
                    chunk_count += 1
                    total_bytes += len(data)
                    logger.info(
                        "PyTTSx3Adapter.process_batch read chunk chunk_count=%s chunk_bytes=%s total_bytes=%s",
                        chunk_count,
                        len(data),
                        total_bytes,
                    )
                    await asyncio.sleep(0.001)
                    data = wf.readframes(chunk_size)

                logger.info(
                    "PyTTSx3Adapter.process_batch finished chunk_count=%s total_bytes=%s returned_audio_bytes=%s",
                    chunk_count,
                    total_bytes,
                    len(audio_data),
                )
                return ProcessBatchResponseDto(audio_data=bytes(audio_data))
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    logger.info("PyTTSx3Adapter.process_batch temporary WAV removed path=%s", temp_path)
                except OSError:
                    logger.exception("PyTTSx3Adapter.process_batch failed to remove temporary WAV path=%s", temp_path)


    # ──────────────────────────────────────────────
    # DECOUPLED STREAM (Single Flow)
    # ──────────────────────────────────────────────

    async def set_stream(self, request: SetStreamRequestDto) -> None:
        """Reset the single-flow queue and spawn a background task to generate audio."""
        logger.info(
            "PyTTSx3Adapter.set_stream started sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        # Cancel any previously running generator task
        if self._generator_task is not None and not self._generator_task.done():
            logger.info("PyTTSx3Adapter.set_stream cancelling previous generator task")
            self._generator_task.cancel()
            try:
                await self._generator_task
            except asyncio.CancelledError:
                logger.info("PyTTSx3Adapter.set_stream previous generator task cancelled")

        # Create a fresh queue, discarding any stale/unconsumed chunks
        self._audio_queue = asyncio.Queue()
        logger.info("PyTTSx3Adapter.set_stream replaced decoupled audio queue")

        # Launch background generation
        self._generator_task = asyncio.create_task(
            self._generate_decoupled_audio(request)
        )
        logger.info("PyTTSx3Adapter.set_stream launched generator task")

    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        """Return an async iterator wrapping the current single-flow audio queue."""
        logger.info("PyTTSx3Adapter.get_stream started")
        audio_stream = DecoupledAudioStream(self._audio_queue)
        logger.info("PyTTSx3Adapter.get_stream returning DecoupledAudioStream")
        return GetStreamResponseDto(audio_stream=audio_stream)

    async def _generate_decoupled_audio(self, request: SetStreamRequestDto) -> None:
        """Background coroutine: consume text_stream, synthesize WAV chunks, push to queue."""
        logger.info("PyTTSx3Adapter decoupled generation task started")
        config = self._require_config()
        try:
            text_count = 0
            chunk_count = 0
            total_bytes = 0
            async for text in request.text_stream:
                if not text.strip():
                    logger.info("PyTTSx3Adapter decoupled generation skipped blank text item")
                    continue

                text_count += 1
                logger.info(
                    "PyTTSx3Adapter decoupled generation synthesizing text_index=%s text_length=%s",
                    text_count,
                    len(text),
                )
                temp_path = ""
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                    temp_path = temp_wav.name
                logger.info("PyTTSx3Adapter decoupled generation temporary WAV created path=%s", temp_path)

                try:
                    await _run_tts_subprocess(
                        text=text,
                        file_path=temp_path,
                        speech_rate=config.speech_rate,
                        voice_name_pref=config.voice_name_preference,
                    )

                    with wave.open(temp_path, "rb") as wf:
                        chunk_size = 1024
                        data = wf.readframes(chunk_size)
                        while data:
                            await self._audio_queue.put(data)
                            chunk_count += 1
                            total_bytes += len(data)
                            logger.info(
                                "PyTTSx3Adapter decoupled generation queued chunk text_index=%s chunk_count=%s chunk_bytes=%s total_bytes=%s",
                                text_count,
                                chunk_count,
                                len(data),
                                total_bytes,
                            )
                            await asyncio.sleep(0.001)
                            data = wf.readframes(chunk_size)
                finally:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                            logger.info("PyTTSx3Adapter decoupled generation temporary WAV removed path=%s", temp_path)
                        except OSError:
                            logger.exception("PyTTSx3Adapter decoupled generation failed to remove temporary WAV path=%s", temp_path)
                await self._audio_queue.put(AudioSegmentEnd())
                logger.info(
                    "PyTTSx3Adapter decoupled generation queued audio segment end text_index=%s",
                    text_count,
                )
            logger.info(
                "PyTTSx3Adapter decoupled generation completed text_count=%s chunk_count=%s total_bytes=%s",
                text_count,
                chunk_count,
                total_bytes,
            )
        except asyncio.CancelledError:
            logger.info("PyTTSx3Adapter decoupled generation task cancelled")
            pass
        except Exception as exc:
            logger.exception("PyTTSx3Adapter decoupled generation failed")
            await self._audio_queue.put(
                AudioStreamError(
                    code="synthesis_failed",
                    message=f"Failed to synthesize speech: {str(exc)}",
                    recoverable=True,
                )
            )
        finally:
            # Sentinel signals end-of-stream to the consumer
            logger.info("PyTTSx3Adapter decoupled generation enqueueing end-of-stream sentinel")
            await self._audio_queue.put(None)

    async def is_available(self, request: TTSAvailabilityRequestDto) -> TTSAvailabilityResponseDto:
        logger.info("PyTTSx3Adapter.is_available started")
        try:
            script = "import pyttsx3; engine = pyttsx3.init(); del engine"
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.wait()
            is_available = process.returncode == 0
            logger.info(
                "PyTTSx3Adapter.is_available finished returncode=%s is_available=%s",
                process.returncode,
                is_available,
            )
            return TTSAvailabilityResponseDto(is_available=is_available)
        except Exception:
            logger.exception("PyTTSx3Adapter.is_available failed")
            return TTSAvailabilityResponseDto(is_available=False)
