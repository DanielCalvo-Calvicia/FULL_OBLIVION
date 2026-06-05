import os

import pytest

from application.dtos.outbound_dtos import TTSAudioStreamRequestDto, TTSSetStreamRequestDto
from application.services.steps.stream_helpers import read_one_chunk
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real TTS service.",
)


@pytest.mark.asyncio
async def test_live_tts_stream_accepts_text_and_emits_audio() -> None:
    live = LiveMicroservices()
    try:
        await live.tts_adapter.set_stream(
            TTSSetStreamRequestDto(text="live diagnostics test", sample_rate=24000, channels=1)
        )
        response = await live.tts_adapter.get_stream(TTSAudioStreamRequestDto(sample_rate=24000, channels=1))
        await read_one_chunk("tts", response.audio_stream, timeout_seconds=5)
    finally:
        await live.close()
