import asyncio
import os
from contextlib import suppress

import pytest

from application.dtos.outbound_dtos import MicrophoneStreamRequestDto, STTSetStreamRequestDto, STTTextStreamRequestDto
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1"
    or os.getenv("RUN_LIVE_MIC_STT_SPEECH_TEST") != "1",
    reason=(
        "Set RUN_LIVE_MICROSERVICE_TESTS=1 and RUN_LIVE_MIC_STT_SPEECH_TEST=1 "
        "to run the manual microphone -> STT speech test."
    ),
)


async def _read_first_non_empty_text(text_stream) -> str:
    async for text in text_stream:
        cleaned = text.strip()
        if cleaned:
            return cleaned
    raise AssertionError("STT stream completed without transcribing any microphone speech.")


@pytest.mark.asyncio
async def test_live_microphone_to_stt_transcribes_speech_from_real_microphone() -> None:
    timeout_seconds = float(os.getenv("LIVE_MIC_STT_SPEECH_TIMEOUT_SECONDS", "20"))
    live = LiveMicroservices()
    try:
        microphone_output = await live.microphone_adapter.start_stream(
            MicrophoneStreamRequestDto(sample_rate=16000, chunk_size=1024)
        )
        stt_input_task = asyncio.create_task(
            live.stt_adapter.set_stream(
                STTSetStreamRequestDto(
                    audio_stream=microphone_output.audio_stream,
                    sample_rate=microphone_output.sample_rate,
                    chunk_size=1024,
                    silence_threshold=150,
                    silence_limit_seconds=1.0,
                )
            )
        )
        await asyncio.sleep(0.1)
        stt_output = await live.stt_adapter.get_stream(
            STTTextStreamRequestDto(
                sample_rate=microphone_output.sample_rate,
                chunk_size=1024,
                silence_threshold=150,
                silence_limit_seconds=1.0,
            )
        )
        transcribed_text = await asyncio.wait_for(
            _read_first_non_empty_text(stt_output.text_stream),
            timeout=timeout_seconds,
        )
        stt_input_task.cancel()
        with suppress(asyncio.CancelledError):
            await stt_input_task
    finally:
        with suppress(Exception):
            await live.microphone_adapter.stop_stream()
        await live.close()

    assert transcribed_text
