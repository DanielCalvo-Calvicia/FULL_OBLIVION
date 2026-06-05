import asyncio
import os
import random
import string
from collections.abc import AsyncIterator

import pytest

from application.dtos.outbound_dtos import (
    ExternalHealthResponseDto,
    MicrophoneStreamRequestDto,
    MicrophoneStreamResponseDto,
    SpeakerPlaybackRequestDto,
    STTSetStreamRequestDto,
    STTTextStreamRequestDto,
    TTSAudioStreamRequestDto,
    TTSSetStreamRequestDto,
    TTSTextStreamRequestDto,
)
from application.services.steps.stream_internal.external_events import sse_events, text_stream_as_ndjson_events
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real STT/TTS/speaker services.",
)


def _seeded_phrase() -> str:
    rng = random.Random(20260524)
    words = []
    for _ in range(4):
        words.append("".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(4, 8))))
    return "live pipeline " + " ".join(words)


async def _collect_audio_chunks(audio_stream: AsyncIterator[bytes]) -> tuple[bytes, ...]:
    chunks: list[bytes] = []
    async for chunk in audio_stream:
        if chunk:
            chunks.append(chunk)
    return tuple(chunks)


async def _collect_text_chunks(text_stream: AsyncIterator[bytes]) -> tuple[str, ...]:
    chunks: list[str] = []
    async for event in sse_events(text_stream, service_name="stt"):
        if event.type != "completed":
            continue
        text = event.payload.get("output", event.payload.get("text", ""))
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return tuple(chunks)


async def _text_stream(chunks: tuple[str, ...]) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk


async def _observed_audio_stream(chunks: tuple[bytes, ...], observed: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        observed.append(chunk)
        yield chunk


class GeneratedMicrophone:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.start_requests: list[MicrophoneStreamRequestDto] = []
        self.emitted_chunks: list[bytes] = []
        self.stop_count = 0

    async def check_health(self) -> ExternalHealthResponseDto:
        return ExternalHealthResponseDto(True, "generated")

    async def start_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        self.start_requests.append(request)
        return MicrophoneStreamResponseDto(audio_stream=self._audio_stream(), sample_rate=request.sample_rate)

    async def get_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        return await self.start_stream(request)

    async def stop_stream(self) -> None:
        self.stop_count += 1

    async def _audio_stream(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.emitted_chunks.append(chunk)
            yield chunk


@pytest.mark.asyncio
async def test_live_voice_pipeline_flow_by_flow_with_seeded_generated_chunks() -> None:
    phrase = _seeded_phrase()
    live = LiveMicroservices()
    microphone = None
    speaker_chunks_sent: list[bytes] = []
    try:
        await live.tts_adapter.set_stream(TTSSetStreamRequestDto(text=phrase, sample_rate=16000, channels=1))
        tts_output = await live.tts_adapter.get_stream(TTSAudioStreamRequestDto(sample_rate=16000, channels=1))
        microphone_chunks = await asyncio.wait_for(_collect_audio_chunks(tts_output.audio_stream), timeout=10)
        assert microphone_chunks

        microphone = GeneratedMicrophone(microphone_chunks)
        microphone_output = await microphone.start_stream(MicrophoneStreamRequestDto(sample_rate=16000, chunk_size=1024))
        stt_output = await live.stt_adapter.get_stream(
            STTTextStreamRequestDto(
                sample_rate=microphone_output.sample_rate,
                chunk_size=1024,
                silence_threshold=150,
                silence_limit_seconds=0.5,
            )
        )
        stt_input_task = asyncio.create_task(
            live.stt_adapter.set_stream(
                STTSetStreamRequestDto(
                    audio_stream=microphone_output.audio_stream,
                    sample_rate=microphone_output.sample_rate,
                    chunk_size=1024,
                    silence_threshold=150,
                    silence_limit_seconds=0.5,
                )
            )
        )
        stt_text_chunks = await asyncio.wait_for(_collect_text_chunks(stt_output.text_stream), timeout=15)
        await stt_input_task
        await microphone.stop_stream()

        tts_input_chunks = stt_text_chunks or (phrase,)
        await live.tts_adapter.set_text_stream(
            TTSTextStreamRequestDto(
                text_stream=text_stream_as_ndjson_events(_text_stream(tts_input_chunks)),
                sample_rate=24000,
                channels=1,
            )
        )
        final_tts_output = await live.tts_adapter.get_stream(TTSAudioStreamRequestDto(sample_rate=24000, channels=1))
        final_tts_chunks = await asyncio.wait_for(_collect_audio_chunks(final_tts_output.audio_stream), timeout=10)
        assert final_tts_chunks

        speaker_response = await live.speaker_adapter.play_stream(
            SpeakerPlaybackRequestDto(
                audio_stream=_observed_audio_stream(final_tts_chunks, speaker_chunks_sent),
                sample_rate=24000,
                channels=1,
            )
        )
    finally:
        if microphone is not None and microphone.stop_count == 0:
            await microphone.stop_stream()
        await live.close()

    assert microphone is not None
    assert speaker_response.success is True, speaker_response.message
    assert microphone.start_requests == [MicrophoneStreamRequestDto(sample_rate=16000, chunk_size=1024)]
    assert microphone.emitted_chunks == list(microphone_chunks)
    assert microphone.stop_count == 1
    assert speaker_chunks_sent == list(final_tts_chunks)
    assert tts_input_chunks == stt_text_chunks or tts_input_chunks == (phrase,)
