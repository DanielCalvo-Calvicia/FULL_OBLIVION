from itertools import product

import pytest

from tests.shared.fakes import (
    SERVICE_NAMES,
    DiagnosticMicrophone,
    DiagnosticSTT,
    DiagnosticSpeaker,
    DiagnosticTTS,
    build_brain_service,
)


HEALTH_COMBINATIONS = tuple(product((False, True), repeat=len(SERVICE_NAMES)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "availability",
    HEALTH_COMBINATIONS,
    ids=[
        ",".join(f"{name}={'up' if is_up else 'down'}" for name, is_up in zip(SERVICE_NAMES, values))
        for values in HEALTH_COMBINATIONS
    ],
)
async def test_health_reports_each_microservice_for_every_availability_combination(
    availability: tuple[bool, bool, bool, bool],
) -> None:
    microphone_up, stt_up, tts_up, speaker_up = availability
    service = build_brain_service(
        microphone=DiagnosticMicrophone(available=microphone_up),
        stt=DiagnosticSTT(available=stt_up),
        tts=DiagnosticTTS(available=tts_up),
        speaker=DiagnosticSpeaker(available=speaker_up),
    )

    response = await service.check_integrations()

    actual = {status.name: status.is_available for status in response.services}
    assert actual == dict(zip(SERVICE_NAMES, availability))
    assert tuple(status.name for status in response.services) == SERVICE_NAMES
