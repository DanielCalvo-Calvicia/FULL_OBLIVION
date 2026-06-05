import os
from contextlib import suppress

import pytest

from application.dtos.outbound_dtos import MicrophoneStreamRequestDto
from application.services.steps.stream_helpers import read_one_chunk
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real microphone service.",
)


@pytest.mark.asyncio
async def test_live_microphone_stream_can_open_and_emit_audio() -> None:
    live = LiveMicroservices()
    try:
        response = await live.microphone_adapter.start_stream(MicrophoneStreamRequestDto())
        await read_one_chunk("microphone", response.audio_stream, timeout_seconds=5)
    finally:
        with suppress(Exception):
            await live.microphone_adapter.stop_stream()
        await live.close()
