import os
import asyncio

import pytest

from application.dtos.outbound_dtos import STTSetStreamRequestDto, STTTextStreamRequestDto
from application.services.steps.stream_helpers import finite_silence_audio_stream
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real STT service.",
)


@pytest.mark.asyncio
async def test_live_stt_stream_accepts_audio_and_completes() -> None:
    live = LiveMicroservices()
    try:
        input_task = asyncio.create_task(
            live.stt_adapter.set_stream(
                STTSetStreamRequestDto(
                    audio_stream=finite_silence_audio_stream(sample_rate=16000, seconds=1),
                    sample_rate=16000,
                    chunk_size=1024,
                    silence_threshold=150,
                    silence_limit_seconds=0.2,
                )
            )
        )
        await asyncio.sleep(0.1)
        response = await live.stt_adapter.get_stream(STTTextStreamRequestDto(sample_rate=16000))
        texts = [text async for text in response.text_stream]
        await input_task
    finally:
        await live.close()

    assert isinstance(texts, list)
