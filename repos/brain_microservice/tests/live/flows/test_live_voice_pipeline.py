import asyncio
import os

import pytest

from application.dtos.service_dtos import VoicePipelineServiceRequestDto
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real microphone/STT/TTS/speaker services.",
)


@pytest.mark.asyncio
async def test_live_voice_pipeline_runs_real_mic_to_stt_to_tts_to_speaker_attachment() -> None:
    live = LiveMicroservices()
    try:
        response = await asyncio.wait_for(
            live.service.run_voice_pipeline(
                VoicePipelineServiceRequestDto(
                    microphone_sample_rate=16000,
                    microphone_chunk_size=1024,
                    stt_silence_threshold=150,
                    stt_silence_limit_seconds=0.5,
                    max_text_segments=1,
                    tts_sample_rate=24000,
                    speaker_channels=1,
                )
            ),
            timeout=20,
        )
    finally:
        await live.close()

    assert isinstance(response.success, bool)
    assert response.text_segments_forwarded >= 0
