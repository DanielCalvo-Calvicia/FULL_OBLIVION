import os

import pytest

from application.dtos.outbound_dtos import SpeakerPlaybackRequestDto
from application.services.steps.stream_helpers import finite_silence_audio_stream
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real speaker service.",
)


@pytest.mark.asyncio
async def test_live_speaker_stream_accepts_audio() -> None:
    live = LiveMicroservices()
    try:
        response = await live.speaker_adapter.play_stream(
            SpeakerPlaybackRequestDto(
                audio_stream=finite_silence_audio_stream(sample_rate=24000, seconds=1),
                sample_rate=24000,
                channels=1,
            )
        )
    finally:
        await live.close()

    assert response.success is True, response.message
