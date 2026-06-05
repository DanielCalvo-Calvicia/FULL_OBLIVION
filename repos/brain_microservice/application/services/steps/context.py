import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from application.dtos.outbound_dtos import (
    MicrophoneStreamResponseDto,
    SpeakerPlaybackRequestDto,
    SpeakerPlaybackResponseDto,
    STTSetStreamRequestDto,
    STTStreamResponseDto,
    TTSAudioStreamResponseDto,
    TTSTextStreamRequestDto,
)
from application.dtos.service_dtos import VoicePipelineServiceRequestDto
from domain.console import console_log

T = TypeVar("T")


class AsyncStreamPipe(Generic[T]):
    def __init__(self, name: str) -> None:
        self._name = name
        self._queue: asyncio.Queue[T | BaseException | None] = asyncio.Queue()
        self._closed = False

    @property
    def stream(self) -> AsyncIterator[T]:
        return self._iter()

    async def put(self, item: T) -> None:
        if self._closed:
            return
        await self._queue.put(item)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)

    async def fail(self, exc: BaseException) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(exc)

    async def _iter(self) -> AsyncIterator[T]:
        while True:
            item = await self._queue.get()
            if item is None:
                console_log("brain-service", "stream pipe closed", blank_lines=2, stream=self._name)
                break
            if isinstance(item, BaseException):
                console_log("brain-service", "stream pipe failed", level="error", blank_lines=2, stream=self._name, error=str(item))
                raise item
            yield item


class CountedTextStream:
    def __init__(self, text_stream: AsyncIterator[str], max_segments: int) -> None:
        self._source = text_stream
        self._max_segments = max_segments
        self.count = 0

    @property
    def text_stream(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        async for text in self._source:
            cleaned = text.strip()
            if not cleaned:
                console_log("brain-service", "skipping empty STT text segment")
                continue
            console_log("brain-service", "forwarding STT text segment to TTS", level="warn", segment=self.count + 1, chars=len(cleaned))
            yield cleaned
            self.count += 1
            if self._max_segments > 0 and self.count >= self._max_segments:
                console_log("brain-service", "text segment limit reached", max_segments=self._max_segments)
                break


def limit_and_count_text_stream(text_stream: AsyncIterator[str], max_segments: int) -> CountedTextStream:
    return CountedTextStream(text_stream, max_segments)


class AudioSegmentPipe:
    """Passes one TTS audio stream per segment to the speaker task.

    `produce(audio)` blocks until the speaker task signals it has finished
    playing the audio — this prevents TTS from calling SET(N+1) before the
    current synthesis is fully consumed, which would cancel it mid-play.
    """

    def __init__(self, name: str = "tts-to-speaker") -> None:
        self._name = name
        self._queue: asyncio.Queue[tuple | None] = asyncio.Queue()
        self._closed = False

    async def produce(self, audio_stream) -> None:
        """Put audio into the pipe and block until the speaker acks completion."""
        if self._closed:
            return
        ack: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put((audio_stream, ack))
        try:
            await ack  # blocks until speaker calls ack.set_result() or set_exception()
        except asyncio.CancelledError:
            if not ack.done():
                ack.cancel()
            raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)
        console_log("brain-service", "audio segment pipe closed", blank_lines=2, pipe=self._name)

    @property
    def stream(self):
        return self._iter()

    async def _iter(self):
        while True:
            item = await self._queue.get()
            if item is None:
                console_log("brain-service", "audio segment pipe stream ended", blank_lines=2, pipe=self._name)
                break
            yield item  # (audio_stream, ack_future)


def verify_microphone_output(output: MicrophoneStreamResponseDto) -> None:
    _verify_stream("microphone audio output", output.audio_stream)
    if output.sample_rate <= 0:
        raise RuntimeError("microphone output verification failed: sample_rate must be positive")
    console_log("flow4-verify", "microphone output verified", sample_rate=output.sample_rate)


def verify_stt_input(stt_input: STTSetStreamRequestDto) -> None:
    _verify_stream("STT audio input", stt_input.audio_stream)
    if stt_input.sample_rate <= 0:
        raise RuntimeError("STT input verification failed: sample_rate must be positive")
    if stt_input.chunk_size <= 0:
        raise RuntimeError("STT input verification failed: chunk_size must be positive")
    console_log("flow4-verify", "STT input verified", sample_rate=stt_input.sample_rate, chunk_size=stt_input.chunk_size)


def verify_stt_output(output: STTStreamResponseDto) -> None:
    _verify_stream("STT text output", output.text_stream)
    console_log("flow4-verify", "STT output verified")


def verify_tts_output(output: TTSAudioStreamResponseDto) -> None:
    _verify_stream("TTS audio output", output.audio_stream)
    console_log("flow4-verify", "TTS output verified")


def verify_speaker_input(speaker_input: SpeakerPlaybackRequestDto) -> None:
    _verify_stream("speaker audio input", speaker_input.audio_stream)
    if speaker_input.sample_rate <= 0:
        raise RuntimeError("speaker input verification failed: sample_rate must be positive")
    if speaker_input.channels <= 0:
        raise RuntimeError("speaker input verification failed: channels must be positive")
    console_log("flow4-verify", "speaker input verified", sample_rate=speaker_input.sample_rate, channels=speaker_input.channels)


def verify_speaker_response(response: SpeakerPlaybackResponseDto) -> None:
    if not isinstance(response.success, bool):
        raise RuntimeError("speaker response verification failed: success must be a bool")
    console_log("flow4-verify", "speaker response verified", success=response.success)


def _verify_stream(name: str, stream: AsyncIterator[Any]) -> None:
    if stream is None:
        raise RuntimeError(f"{name} verification failed: stream is missing")
    if not hasattr(stream, "__anext__"):
        raise RuntimeError(f"{name} verification failed: stream is not an async iterator")


@dataclass(slots=True)
class VoicePipelineContext:
    request: VoicePipelineServiceRequestDto
    tasks: list[asyncio.Task] = field(default_factory=list)
    microphone_output: MicrophoneStreamResponseDto | None = None
    stt_stream_in_pipe: AsyncStreamPipe[bytes] | None = None
    stt_input: STTSetStreamRequestDto | None = None
    stt_input_task: asyncio.Task | None = None
    stt_output: STTStreamResponseDto | None = None
    counted_text_stream: CountedTextStream | None = None
    stt_to_tts_task: asyncio.Task | None = None
    tts_stream_in_pipe: AsyncStreamPipe[str] | None = None
    tts_input: TTSTextStreamRequestDto | None = None
    tts_input_task: asyncio.Task | None = None
    tts_output: TTSAudioStreamResponseDto | None = None
    tts_to_speaker_task: asyncio.Task | None = None
    speaker_stream_in_pipe: AsyncStreamPipe[bytes] | None = None
    speaker_input: SpeakerPlaybackRequestDto | None = None
    speaker_task: asyncio.Task | None = None
    mic_to_stt_bridge: Any | None = None
    stt_to_tts_bridge: Any | None = None
    tts_to_speaker_bridge: Any | None = None

    @classmethod
    def create(cls, request: VoicePipelineServiceRequestDto) -> "VoicePipelineContext":
        return cls(
            request=request,
        )

    def create_task(self, coroutine, name: str) -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.append(task)
        return task

    async def cancel_pending_tasks(self) -> None:
        pending = [task for task in self.tasks if not task.done()]
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                console_log("flow4-attach", "pending stream task cancelled", task=task.get_name())
        await self.close_internal_streams()

    async def close_internal_streams(self) -> None:
        for bridge in (self.mic_to_stt_bridge, self.stt_to_tts_bridge, self.tts_to_speaker_bridge):
            internal_stream = getattr(bridge, "internal_stream", None)
            if internal_stream is not None:
                await internal_stream.close()

    def require_microphone_output(self) -> MicrophoneStreamResponseDto:
        if self.microphone_output is None:
            raise RuntimeError("voice pipeline context missing microphone_output")
        return self.microphone_output

    def require_stt_input_task(self) -> asyncio.Task:
        if self.stt_input_task is None:
            raise RuntimeError("voice pipeline context missing stt_input_task")
        return self.stt_input_task

    def require_stt_input(self) -> STTSetStreamRequestDto:
        if self.stt_input is None:
            raise RuntimeError("voice pipeline context missing stt_input")
        return self.stt_input

    def require_stt_output(self) -> STTStreamResponseDto:
        if self.stt_output is None:
            raise RuntimeError("voice pipeline context missing stt_output")
        return self.stt_output

    def require_stt_stream_in_pipe(self) -> AsyncStreamPipe[bytes]:
        if self.stt_stream_in_pipe is None:
            raise RuntimeError("voice pipeline context missing stt_stream_in_pipe")
        return self.stt_stream_in_pipe

    def require_counted_text_stream(self) -> CountedTextStream:
        if self.counted_text_stream is None:
            raise RuntimeError("voice pipeline context missing counted_text_stream")
        return self.counted_text_stream

    def require_tts_stream_in_pipe(self) -> AsyncStreamPipe[str]:
        if self.tts_stream_in_pipe is None:
            raise RuntimeError("voice pipeline context missing tts_stream_in_pipe")
        return self.tts_stream_in_pipe

    def require_speaker_stream_in_pipe(self) -> AsyncStreamPipe[bytes]:
        if self.speaker_stream_in_pipe is None:
            raise RuntimeError("voice pipeline context missing speaker_stream_in_pipe")
        return self.speaker_stream_in_pipe

    def require_mic_to_stt_bridge(self) -> Any:
        if self.mic_to_stt_bridge is None:
            raise RuntimeError("voice pipeline context missing mic_to_stt_bridge")
        return self.mic_to_stt_bridge

    def require_stt_to_tts_bridge(self) -> Any:
        if self.stt_to_tts_bridge is None:
            raise RuntimeError("voice pipeline context missing stt_to_tts_bridge")
        return self.stt_to_tts_bridge

    def require_tts_to_speaker_bridge(self) -> Any:
        if self.tts_to_speaker_bridge is None:
            raise RuntimeError("voice pipeline context missing tts_to_speaker_bridge")
        return self.tts_to_speaker_bridge

    def require_tts_input_task(self) -> asyncio.Task:
        if self.tts_input_task is None:
            raise RuntimeError("voice pipeline context missing tts_input_task")
        return self.tts_input_task

    def require_tts_output(self) -> TTSAudioStreamResponseDto:
        if self.tts_output is None:
            raise RuntimeError("voice pipeline context missing tts_output")
        return self.tts_output

    def require_speaker_task(self) -> asyncio.Task:
        if self.speaker_task is None:
            raise RuntimeError("voice pipeline context missing speaker_task")
        return self.speaker_task
