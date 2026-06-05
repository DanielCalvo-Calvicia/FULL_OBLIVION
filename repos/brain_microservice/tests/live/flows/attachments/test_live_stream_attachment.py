import os

import pytest

from application.dtos.service_dtos import BatchTranscriptionServiceRequestDto, TextToSpeechPlaybackServiceRequestDto
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real attachment services.",
)


@pytest.mark.asyncio
async def test_live_text_playback_attachment_uses_real_tts_and_speaker() -> None:
    live = LiveMicroservices()
    try:
        response = await live.service.play_text(
            TextToSpeechPlaybackServiceRequestDto(
                text="live text playback attachment diagnostics",
                sample_rate=24000,
                channels=1,
            )
        )
    finally:
        await live.close()

    assert response.success is True, response.message


@pytest.mark.asyncio
async def test_live_batch_transcription_attachment_uses_real_stt_batch() -> None:
    live = LiveMicroservices()
    try:
        response = await live.service.transcribe_batch(
            BatchTranscriptionServiceRequestDto(audio_data=b"\0" * 32000, sample_rate=16000)
        )
    finally:
        await live.close()

    assert isinstance(response.text, str)
