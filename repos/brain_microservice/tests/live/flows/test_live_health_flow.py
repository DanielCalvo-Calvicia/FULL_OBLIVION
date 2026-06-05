import os

import pytest

from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real microphone/STT/TTS/speaker services.",
)


@pytest.mark.asyncio
async def test_live_health_for_each_microservice() -> None:
    live = LiveMicroservices()
    try:
        response = await live.service.check_integrations()
    finally:
        await live.close()

    statuses = {status.name: status for status in response.services}
    assert statuses["microphone"].is_available, statuses["microphone"].detail
    assert statuses["stt"].is_available, statuses["stt"].detail
    assert statuses["tts"].is_available, statuses["tts"].detail
    assert statuses["speaker"].is_available, statuses["speaker"].detail
