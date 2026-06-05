import pytest

from composition_root.setup.startup_pipeline import start_startup_pipeline
from tests.shared.fakes import DiagnosticMicrophone, DiagnosticSTT, DiagnosticSpeaker, DiagnosticTTS, build_brain_service


@pytest.mark.asyncio
async def test_startup_pipeline_starts_and_merges_all_streams() -> None:
    microphone = DiagnosticMicrophone(chunks=(b"mic",))
    stt = DiagnosticSTT(text_chunks=("startup",))
    tts = DiagnosticTTS(audio_chunks=(b"audio",))
    speaker = DiagnosticSpeaker()
    service = build_brain_service(microphone=microphone, stt=stt, tts=tts, speaker=speaker)

    task = start_startup_pipeline(service)
    await task

    assert microphone.started is True
    assert microphone.stopped is False
    assert stt.audio_received == b"mic"
    assert tts.set_requests == []
    assert tts.text_received == ["startup"]
    assert tts.get_requests
    assert speaker.audio_received == b"audio"
