import pytest

from application.dtos.outbound_dtos import STTBatchRequestDto
from application.dtos.service_dtos import (
    BatchTranscriptionServiceRequestDto,
    MicrophoneTranscriptionServiceRequestDto,
    TextToSpeechPlaybackServiceRequestDto,
    VoicePipelineServiceRequestDto,
)
from tests.shared.fakes import (
    DiagnosticMicrophone,
    DiagnosticSTT,
    DiagnosticSpeaker,
    DiagnosticTTS,
    build_brain_service,
)


@pytest.mark.asyncio
async def test_transcribe_batch_delegates_to_stt() -> None:
    stt = DiagnosticSTT()
    service = build_brain_service(stt=stt)

    response = await service.transcribe_batch(
        BatchTranscriptionServiceRequestDto(audio_data=b"pcm", sample_rate=8000)
    )

    assert response.text == "batch text"
    assert stt.last_batch_request == STTBatchRequestDto(audio_data=b"pcm", sample_rate=8000)


@pytest.mark.asyncio
async def test_transcribe_microphone_collects_limited_segments() -> None:
    microphone = DiagnosticMicrophone()
    stt = DiagnosticSTT()
    service = build_brain_service(microphone=microphone, stt=stt)

    response = await service.transcribe_microphone(
        MicrophoneTranscriptionServiceRequestDto(max_segments=1)
    )

    assert response.segments == ("hello",)
    assert microphone.started is True
    assert microphone.stopped is False
    assert stt.last_stream_request is not None


@pytest.mark.asyncio
async def test_play_text_sends_tts_audio_to_speaker() -> None:
    tts = DiagnosticTTS(audio_chunks=(b"wav",))
    speaker = DiagnosticSpeaker()
    service = build_brain_service(tts=tts, speaker=speaker)

    response = await service.play_text(
        TextToSpeechPlaybackServiceRequestDto(text="Say this", sample_rate=24000, channels=1)
    )

    assert response.success is True
    assert response.message == "played"
    assert tts.set_requests == []
    assert tts.text_received == ["Say this"]
    assert speaker.audio_received == b"wav"


@pytest.mark.asyncio
async def test_voice_pipeline_connects_mic_to_stt_to_tts_to_speaker() -> None:
    microphone = DiagnosticMicrophone()
    stt = DiagnosticSTT()
    tts = DiagnosticTTS(audio_chunks=(b"wav",))
    speaker = DiagnosticSpeaker()
    service = build_brain_service(microphone=microphone, stt=stt, tts=tts, speaker=speaker)

    response = await service.run_voice_pipeline(VoicePipelineServiceRequestDto(max_text_segments=2))

    assert response.success is True
    assert response.text_segments_forwarded == 2
    assert microphone.started is True
    assert microphone.stopped is False
    assert stt.last_stream_request is not None
    assert tts.set_requests == []
    assert tts.text_received == ["hello", "world"]
    assert speaker.audio_received == b"wav"
