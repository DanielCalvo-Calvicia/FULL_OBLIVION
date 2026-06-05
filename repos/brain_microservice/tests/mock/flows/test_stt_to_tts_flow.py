import pytest

from application.dtos.service_dtos import VoicePipelineServiceRequestDto
from tests.shared.fakes import DiagnosticSTT, DiagnosticTTS, build_brain_service


@pytest.mark.asyncio
async def test_stt_to_tts_flow_forwards_clean_limited_text_segments() -> None:
    stt = DiagnosticSTT(text_chunks=(" first ", "", "second", "third"))
    tts = DiagnosticTTS()
    service = build_brain_service(stt=stt, tts=tts)

    response = await service.run_voice_pipeline(VoicePipelineServiceRequestDto(max_text_segments=2))

    assert response.success is True
    assert response.text_segments_forwarded == 2
    assert tts.set_requests == []
    assert tts.text_received == ["first", "second"]
    assert tts.text_stream_requests
    assert tts.text_stream_requests[-1].sample_rate == 24000
    assert tts.text_stream_requests[-1].channels == 1
