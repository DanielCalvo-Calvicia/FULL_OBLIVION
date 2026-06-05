import pytest

from application.dtos.service_dtos import VoicePipelineServiceRequestDto
from tests.shared.fakes import DiagnosticMicrophone, DiagnosticSTT, DiagnosticSpeaker, DiagnosticTTS, build_brain_service


@pytest.mark.asyncio
async def test_full_voice_pipeline_connects_mic_to_stt_to_tts_to_speaker() -> None:
    microphone = DiagnosticMicrophone(chunks=(b"mic",))
    stt = DiagnosticSTT(text_chunks=("debug",))
    tts = DiagnosticTTS(audio_chunks=(b"spoken-debug",))
    speaker = DiagnosticSpeaker()
    service = build_brain_service(microphone=microphone, stt=stt, tts=tts, speaker=speaker)

    response = await service.run_voice_pipeline(
        VoicePipelineServiceRequestDto(
            microphone_sample_rate=16000,
            microphone_chunk_size=1024,
            max_text_segments=1,
            tts_sample_rate=24000,
            speaker_channels=1,
        )
    )

    assert response.success is True
    assert response.message == "played"
    assert response.text_segments_forwarded == 1
    assert microphone.stop_count == 0
    assert stt.audio_received == b"mic"
    assert tts.set_requests == []
    assert tts.text_received == ["debug"]
    assert speaker.audio_received == b"spoken-debug"
