import asyncio

from application.dtos.outbound_dtos import (
    ExternalHealthResponseDto,
    MicrophoneStreamRequestDto,
    MicrophoneStreamResponseDto,
    SpeakerPlaybackRequestDto,
    SpeakerPlaybackResponseDto,
    STTBatchRequestDto,
    STTBatchResponseDto,
    STTSetStreamRequestDto,
    STTStreamResponseDto,
    STTTextStreamRequestDto,
    TTSAudioStreamRequestDto,
    TTSAudioStreamResponseDto,
    TTSSetStreamRequestDto,
    TTSTextStreamRequestDto,
)
from application.services.service import BrainService
from application.services.steps.stream_internal.external_events import (
    decode_completed_audio,
    decode_event_audio,
    ndjson_events,
    stream_event_bytes,
)
from tests.shared.streams import byte_stream, text_stream


SERVICE_NAMES = ("microphone", "stt", "tts", "speaker")


class DiagnosticMicrophone:
    def __init__(
        self,
        *,
        available: bool = True,
        chunks: tuple[bytes, ...] = (b"mic-audio-1", b"mic-audio-2"),
    ) -> None:
        self.available = available
        self.chunks = chunks
        self.start_requests: list[MicrophoneStreamRequestDto] = []
        self.stop_count = 0

    @property
    def started(self) -> bool:
        return bool(self.start_requests)

    @property
    def stopped(self) -> bool:
        return self.stop_count > 0

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(self.available, "ok" if self.available else "down")

    async def start_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        self.start_requests.append(request)
        return MicrophoneStreamResponseDto(audio_stream=_audio_ndjson_stream(self.chunks), sample_rate=request.sample_rate)

    async def get_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        return await self.start_stream(request)

    async def stop_stream(self) -> None:
        self.stop_count += 1


class DiagnosticSTT:
    def __init__(
        self,
        *,
        available: bool = True,
        text_chunks: tuple[str, ...] = ("hello", "world"),
    ) -> None:
        self.available = available
        self.text_chunks = text_chunks
        self.stream_requests: list[STTSetStreamRequestDto] = []
        self.get_requests: list[STTTextStreamRequestDto] = []
        self.batch_requests: list[STTBatchRequestDto] = []
        self.audio_received = b""
        self._audio_complete = asyncio.Event()

    @property
    def last_stream_request(self) -> STTSetStreamRequestDto | None:
        return self.stream_requests[-1] if self.stream_requests else None

    @property
    def last_batch_request(self) -> STTBatchRequestDto | None:
        return self.batch_requests[-1] if self.batch_requests else None

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(self.available, "ok" if self.available else "down")

    async def set_stream(self, request: STTSetStreamRequestDto) -> None:
        self.stream_requests.append(request)
        async for event in ndjson_events(request.audio_stream, service_name="stt-test"):
            if event.type == "partial":
                self.audio_received += decode_event_audio(event)
            if event.type == "completed" and not self.audio_received:
                self.audio_received += decode_completed_audio(event)
        self._audio_complete.set()

    async def get_stream(self, request: STTTextStreamRequestDto) -> STTStreamResponseDto:
        self.get_requests.append(request)
        return STTStreamResponseDto(text_stream=self._sse_text_after_audio())

    async def _sse_text_after_audio(self):
        await self._audio_complete.wait()
        yield b"data: " + stream_event_bytes("stream_started", 1, {}) + b"\n"
        sequence = 2
        async for text in text_stream(self.text_chunks):
            yield b"data: " + stream_event_bytes("completed", sequence, {"reason": "completed", "output": text}) + b"\n"
            sequence += 1

    async def process_batch(self, request: STTBatchRequestDto) -> STTBatchResponseDto:
        self.batch_requests.append(request)
        return STTBatchResponseDto(text="batch text")


class DiagnosticTTS:
    def __init__(
        self,
        *,
        available: bool = True,
        audio_chunks: tuple[bytes, ...] = (b"tts-audio-1", b"tts-audio-2"),
    ) -> None:
        self.available = available
        self.audio_chunks = audio_chunks
        self.set_requests: list[TTSSetStreamRequestDto] = []
        self.text_stream_requests: list[TTSTextStreamRequestDto] = []
        self.text_received: list[str] = []
        self.get_requests: list[TTSAudioStreamRequestDto] = []

    @property
    def last_set_request(self) -> TTSSetStreamRequestDto | None:
        return self.set_requests[-1] if self.set_requests else None

    @property
    def streamed_text(self) -> str:
        return "".join(self.text_received)

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(self.available, "ok" if self.available else "down")

    async def set_stream(self, request: TTSSetStreamRequestDto) -> None:
        self.set_requests.append(request)

    async def set_text_stream(self, request: TTSTextStreamRequestDto) -> None:
        self.text_stream_requests.append(request)
        async for event in ndjson_events(request.text_stream, service_name="tts-test"):
            if event.type == "partial":
                text = event.payload.get("text", "")
                if isinstance(text, str):
                    self.text_received.append(text)
            if event.type == "completed":
                output = event.payload.get("output", "")
                if isinstance(output, str):
                    self.text_received.append(output)

    async def get_stream(self, request: TTSAudioStreamRequestDto) -> TTSAudioStreamResponseDto:
        self.get_requests.append(request)
        return TTSAudioStreamResponseDto(audio_stream=_audio_ndjson_stream(self.audio_chunks, complete_each_chunk=False))


class DiagnosticSpeaker:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.play_requests: list[SpeakerPlaybackRequestDto] = []
        self.audio_received = b""

    @property
    def last_request(self) -> SpeakerPlaybackRequestDto | None:
        return self.play_requests[-1] if self.play_requests else None

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(self.available, "ok" if self.available else "down")

    async def play_stream(self, request: SpeakerPlaybackRequestDto) -> SpeakerPlaybackResponseDto:
        self.play_requests.append(request)
        async for event in ndjson_events(request.audio_stream, service_name="speaker-test"):
            if event.type == "partial":
                self.audio_received += decode_event_audio(event)
        return SpeakerPlaybackResponseDto(success=True, message="played")


def build_brain_service(
    microphone: DiagnosticMicrophone | None = None,
    stt: DiagnosticSTT | None = None,
    tts: DiagnosticTTS | None = None,
    speaker: DiagnosticSpeaker | None = None,
) -> BrainService:
    return BrainService(
        microphone or DiagnosticMicrophone(),
        stt or DiagnosticSTT(),
        tts or DiagnosticTTS(),
        speaker or DiagnosticSpeaker(),
    )


async def _audio_ndjson_stream(chunks: tuple[bytes, ...], *, complete_each_chunk: bool = True):
    yield stream_event_bytes("stream_started", 1, {})
    sequence = 2
    all_chunks: list[bytes] = []
    for chunk in chunks:
        all_chunks.append(chunk)
        yield stream_event_bytes("partial", sequence, {"bytes_base64": _base64_audio(chunk)})
        sequence += 1
        if complete_each_chunk:
            yield stream_event_bytes("completed", sequence, {"reason": "completed", "bytes_base64": _base64_audio(chunk)})
            sequence += 1
    if not complete_each_chunk:
        yield stream_event_bytes("completed", sequence, {"reason": "completed", "output_bytes_base64": _base64_audio(b"".join(all_chunks))})


def _base64_audio(chunk: bytes) -> str:
    import base64

    return base64.b64encode(chunk).decode("ascii")
