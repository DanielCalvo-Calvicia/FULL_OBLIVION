import asyncio
import base64
import random
import string
from collections.abc import AsyncIterator

import pytest

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
from application.dtos.service_dtos import VoicePipelineServiceRequestDto
from application.services.service import BrainService
from application.services.steps.stream_internal.external_events import decode_event_audio, ndjson_events, stream_event_bytes


def _random_byte_chunks(rng: random.Random, count: int, *, min_size: int, max_size: int) -> tuple[bytes, ...]:
    return tuple(rng.randbytes(rng.randint(min_size, max_size)) for _ in range(count))


def _random_text_chunks(rng: random.Random, count: int) -> tuple[str, ...]:
    chunks = []
    for index in range(count):
        text = "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(4, 12)))
        chunks.append(f"  {text}-{index}  ")
    return ("", *chunks, "   ")


class AuditedMicrophone:
    def __init__(self, chunks: tuple[bytes, ...], events: list[str]) -> None:
        self.chunks = chunks
        self.events = events
        self.start_requests: list[MicrophoneStreamRequestDto] = []
        self.stop_count = 0

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(True, "ok")

    async def start_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        self.events.append("microphone:start")
        self.start_requests.append(request)
        return MicrophoneStreamResponseDto(audio_stream=self._stream_chunks(), sample_rate=request.sample_rate)

    async def get_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        return await self.start_stream(request)

    async def stop_stream(self) -> None:
        self.events.append("microphone:stop")
        self.stop_count += 1

    async def _stream_chunks(self) -> AsyncIterator[bytes]:
        yield stream_event_bytes("stream_started", 1, {})
        sequence = 2
        for index, chunk in enumerate(self.chunks):
            self.events.append(f"microphone:emit:{index}")
            encoded = base64.b64encode(chunk).decode("ascii")
            yield stream_event_bytes("partial", sequence, {"bytes_base64": encoded})
            sequence += 1
            yield stream_event_bytes("completed", sequence, {"reason": "completed", "bytes_base64": encoded})
            sequence += 1


class AuditedSTT:
    def __init__(self, text_chunks: tuple[str, ...], events: list[str]) -> None:
        self.text_chunks = text_chunks
        self.events = events
        self.stream_requests: list[STTSetStreamRequestDto] = []
        self.get_requests: list[STTTextStreamRequestDto] = []
        self.audio_chunks_received: list[bytes] = []
        self.batch_requests: list[STTBatchRequestDto] = []
        self._audio_complete = asyncio.Event()

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(True, "ok")

    async def set_stream(self, request: STTSetStreamRequestDto) -> None:
        self.events.append("stt:start")
        self.stream_requests.append(request)
        async for event in ndjson_events(request.audio_stream, service_name="stt-test"):
            if event.type != "partial":
                continue
            chunk = decode_event_audio(event)
            self.events.append(f"stt:receive_audio:{len(self.audio_chunks_received)}")
            self.audio_chunks_received.append(chunk)
        self.events.append("stt:audio_complete")
        self._audio_complete.set()

    async def get_stream(self, request: STTTextStreamRequestDto) -> STTStreamResponseDto:
        self.events.append("stt:get_text")
        self.get_requests.append(request)
        return STTStreamResponseDto(text_stream=self._stream_text_sse())

    async def process_batch(self, request: STTBatchRequestDto) -> STTBatchResponseDto:
        self.batch_requests.append(request)
        return STTBatchResponseDto(text="batch text")

    async def _stream_text_sse(self) -> AsyncIterator[bytes]:
        await self._audio_complete.wait()
        yield b"data: " + stream_event_bytes("stream_started", 1, {}) + b"\n"
        sequence = 2
        for index, text in enumerate(self.text_chunks):
            self.events.append(f"stt:emit_text:{index}")
            yield b"data: " + stream_event_bytes("completed", sequence, {"reason": "completed", "output": text}) + b"\n"
            sequence += 1


class AuditedTTS:
    def __init__(self, audio_chunks: tuple[bytes, ...], events: list[str]) -> None:
        self.audio_chunks = audio_chunks
        self.events = events
        self.set_requests: list[TTSSetStreamRequestDto] = []
        self.text_stream_requests: list[TTSTextStreamRequestDto] = []
        self.text_received: list[str] = []
        self.get_requests: list[TTSAudioStreamRequestDto] = []

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(True, "ok")

    async def set_stream(self, request: TTSSetStreamRequestDto) -> None:
        self.events.append("tts:set_full_text")
        self.set_requests.append(request)

    async def set_text_stream(self, request: TTSTextStreamRequestDto) -> None:
        self.events.append("tts:start_text_input")
        self.text_stream_requests.append(request)
        async for event in ndjson_events(request.text_stream, service_name="tts-test"):
            if event.type == "completed":
                text = event.payload.get("output", "")
                self.events.append(f"tts:receive_text:{len(self.text_received)}")
                self.text_received.append(text)
        self.events.append("tts:text_complete")

    async def get_stream(self, request: TTSAudioStreamRequestDto) -> TTSAudioStreamResponseDto:
        self.events.append("tts:get_audio")
        self.get_requests.append(request)
        return TTSAudioStreamResponseDto(audio_stream=self._stream_audio())

    async def _stream_audio(self) -> AsyncIterator[bytes]:
        yield stream_event_bytes("stream_started", 1, {})
        sequence = 2
        all_chunks: list[bytes] = []
        for index, chunk in enumerate(self.audio_chunks):
            self.events.append(f"tts:emit_audio:{index}")
            all_chunks.append(chunk)
            encoded = base64.b64encode(chunk).decode("ascii")
            yield stream_event_bytes("partial", sequence, {"bytes_base64": encoded})
            sequence += 1
        encoded_output = base64.b64encode(b"".join(all_chunks)).decode("ascii")
        yield stream_event_bytes("completed", sequence, {"reason": "completed", "output_bytes_base64": encoded_output})


class AuditedSpeaker:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.play_requests: list[SpeakerPlaybackRequestDto] = []
        self.audio_chunks_received: list[bytes] = []

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(True, "ok")

    async def play_stream(self, request: SpeakerPlaybackRequestDto) -> SpeakerPlaybackResponseDto:
        self.events.append("speaker:start")
        self.play_requests.append(request)
        async for event in ndjson_events(request.audio_stream, service_name="speaker-test"):
            if event.type != "partial":
                continue
            chunk = decode_event_audio(event)
            self.events.append(f"speaker:receive_audio:{len(self.audio_chunks_received)}")
            self.audio_chunks_received.append(chunk)
        self.events.append("speaker:complete")
        return SpeakerPlaybackResponseDto(success=True, message="played")


@pytest.mark.asyncio
async def test_full_voice_pipeline_forwards_seeded_random_chunks_across_each_flow() -> None:
    rng = random.Random(20260524)
    microphone_chunks = _random_byte_chunks(rng, 7, min_size=16, max_size=128)
    stt_text_chunks = _random_text_chunks(rng, 5)
    tts_audio_chunks = _random_byte_chunks(rng, 4, min_size=32, max_size=256)
    expected_tts_text = tuple(text.strip() for text in stt_text_chunks if text.strip())[:3]
    events: list[str] = []

    microphone = AuditedMicrophone(microphone_chunks, events)
    stt = AuditedSTT(stt_text_chunks, events)
    tts = AuditedTTS(tts_audio_chunks, events)
    speaker = AuditedSpeaker(events)
    service = BrainService(microphone, stt, tts, speaker)

    response = await service.run_voice_pipeline(
        VoicePipelineServiceRequestDto(
            microphone_sample_rate=16000,
            microphone_chunk_size=1024,
            stt_silence_threshold=150,
            stt_silence_limit_seconds=0.5,
            max_text_segments=len(expected_tts_text),
            tts_sample_rate=24000,
            speaker_channels=1,
        )
    )

    assert response.success is True
    assert response.message == "played"
    assert response.text_segments_forwarded == len(expected_tts_text)

    assert microphone.start_requests == [MicrophoneStreamRequestDto(sample_rate=16000, chunk_size=1024)]
    assert microphone.stop_count == 0
    assert stt.stream_requests[0].sample_rate == 16000
    assert stt.stream_requests[0].chunk_size == 1024
    assert stt.stream_requests[0].silence_threshold == 150
    assert stt.stream_requests[0].silence_limit_seconds == 0.5
    assert tuple(stt.audio_chunks_received) == microphone_chunks

    assert tts.set_requests == []
    assert tuple(tts.text_received) == expected_tts_text
    assert len(tts.text_stream_requests) == 1
    assert tts.text_stream_requests[0].sample_rate == 24000
    assert tts.text_stream_requests[0].channels == 1
    assert tts.get_requests == [
        TTSAudioStreamRequestDto(
            sample_rate=24000,
            channels=1,
            keep_open_after_completed=True,
            completed_outputs_to_read=len(expected_tts_text),
        )
    ]
    assert tuple(speaker.audio_chunks_received) == tts_audio_chunks
    assert speaker.play_requests[0].sample_rate == 24000
    assert speaker.play_requests[0].channels == 1

    for index in range(len(microphone_chunks)):
        assert events.index(f"microphone:emit:{index}") < events.index(f"stt:receive_audio:{index}")
    assert events.index("microphone:start") < events.index("stt:start")
    assert events.index("stt:start") < events.index("stt:get_text")
    assert events.index("stt:start") < events.index("tts:start_text_input")
    assert events.index("tts:start_text_input") < events.index("tts:get_audio")
    assert events.index("tts:get_audio") < events.index("speaker:start")
    for index in range(len(tts_audio_chunks)):
        assert events.index(f"tts:emit_audio:{index}") < events.index(f"speaker:receive_audio:{index}")
    assert "microphone:stop" not in events
