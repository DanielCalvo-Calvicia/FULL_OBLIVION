import os
from collections.abc import AsyncIterator

import pytest

from application.dtos.outbound_dtos import (
    SpeakerPlaybackRequestDto,
    TTSAudioStreamRequestDto,
    TTSSetStreamRequestDto,
    TTSTextStreamRequestDto,
)
from application.services.steps.stream_internal.external_events import text_stream_as_ndjson_events
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real TTS and speaker services.",
)


@pytest.mark.asyncio
async def test_live_tts_to_speaker_flow_forwards_real_tts_audio_to_speaker() -> None:
    live = LiveMicroservices()
    try:
        await live.tts_adapter.set_stream(
            TTSSetStreamRequestDto(text="live tts to speaker diagnostics", sample_rate=24000, channels=1)
        )
        tts_output = await live.tts_adapter.get_stream(TTSAudioStreamRequestDto(sample_rate=24000, channels=1))
        speaker_response = await live.speaker_adapter.play_stream(
            SpeakerPlaybackRequestDto(audio_stream=tts_output.audio_stream, sample_rate=24000, channels=1)
        )
    finally:
        await live.close()

    assert speaker_response.success is True, speaker_response.message


@pytest.mark.asyncio
async def test_live_debug_text_variable_streams_through_real_tts_to_speaker() -> None:
    debug_text = "Hello world, Hello world,Hello world,"
    live = LiveMicroservices()
    try:
        await live.tts_adapter.set_text_stream(
            TTSTextStreamRequestDto(
                text_stream=text_stream_as_ndjson_events(_text_variable_stream(debug_text)),
                sample_rate=24000,
                channels=1,
            )
        )
        tts_output = await live.tts_adapter.get_stream(TTSAudioStreamRequestDto(sample_rate=24000, channels=1))
        speaker_response = await live.speaker_adapter.play_stream(
            SpeakerPlaybackRequestDto(audio_stream=tts_output.audio_stream, sample_rate=24000, channels=1)
        )
    finally:
        await live.close()

    assert speaker_response.success is True, speaker_response.message


async def _text_variable_stream(text: str) -> AsyncIterator[str]:
    yield text
