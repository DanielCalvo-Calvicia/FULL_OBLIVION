import pytest

from application.dtos.outbound_dtos import TTSAudioStreamRequestDto
from application.dtos.service_dtos import TextToSpeechPlaybackServiceRequestDto
from tests.shared.fakes import DiagnosticSpeaker, DiagnosticTTS, build_brain_service


@pytest.mark.asyncio
async def test_tts_to_speaker_flow_forwards_tts_audio_and_playback_settings() -> None:
    tts = DiagnosticTTS(audio_chunks=(b"audio-a", b"audio-b"))
    speaker = DiagnosticSpeaker()
    service = build_brain_service(tts=tts, speaker=speaker)

    response = await service.play_text(
        TextToSpeechPlaybackServiceRequestDto(text="debug this path", sample_rate=22050, channels=2)
    )

    assert response.success is True
    assert response.message == "played"
    assert tts.set_requests == []
    assert tts.text_received == ["debug this path"]
    assert tts.text_stream_requests[0].sample_rate == 22050
    assert tts.text_stream_requests[0].channels == 2
    assert tts.get_requests == [
        TTSAudioStreamRequestDto(sample_rate=22050, channels=2, completed_outputs_to_read=1)
    ]
    assert speaker.audio_received == b"audio-aaudio-b"
    assert speaker.play_requests[0].sample_rate == 22050
    assert speaker.play_requests[0].channels == 2
