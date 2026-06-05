import pytest

from application.dtos.service_dtos import (
    BatchTranscriptionServiceRequestDto,
    MicrophoneTranscriptionServiceRequestDto,
    VoicePipelineServiceRequestDto,
)
from tests.shared.fakes import (
    DiagnosticMicrophone,
    DiagnosticSTT,
    DiagnosticSpeaker,
    DiagnosticTTS,
    build_brain_service,
)
from application.services.steps.stream_internal.external_events import decode_event_audio, ndjson_events


class FailingStreamSTT(DiagnosticSTT):
    async def set_stream(self, request):
        self.stream_requests.append(request)
        async for event in ndjson_events(request.audio_stream, service_name="stt-test"):
            if event.type == "partial":
                self.audio_received += decode_event_audio(event)
        self._audio_complete.set()
        raise RuntimeError("stt stream failed")


@pytest.mark.asyncio
async def test_voice_pipeline_stops_before_tts_when_stt_produces_no_text() -> None:
    microphone = DiagnosticMicrophone(chunks=(b"audio",))
    stt = DiagnosticSTT(text_chunks=("", "   "))
    tts = DiagnosticTTS(audio_chunks=())
    speaker = DiagnosticSpeaker()
    service = build_brain_service(microphone=microphone, stt=stt, tts=tts, speaker=speaker)

    response = await service.run_voice_pipeline(VoicePipelineServiceRequestDto(max_text_segments=2))

    assert response.success is False
    assert response.message == "No speech was detected before the STT stream completed."
    assert response.text_segments_forwarded == 0
    assert microphone.stop_count == 0
    assert stt.audio_received == b"audio"
    assert tts.text_received == []
    assert tts.set_requests == []
    assert len(tts.text_stream_requests) == 1
    assert len(tts.get_requests) == 1
    assert len(speaker.play_requests) == 1
    assert speaker.audio_received == b""


@pytest.mark.asyncio
async def test_transcribe_microphone_attachment_stops_microphone_when_stt_fails() -> None:
    microphone = DiagnosticMicrophone(chunks=(b"partial-audio",))
    stt = FailingStreamSTT()
    service = build_brain_service(microphone=microphone, stt=stt)

    with pytest.raises(RuntimeError, match="stt stream failed"):
        await service.transcribe_microphone(MicrophoneTranscriptionServiceRequestDto())

    assert microphone.stop_count == 1
    assert stt.audio_received == b"partial-audio"


@pytest.mark.asyncio
async def test_batch_transcription_attachment_only_calls_stt_batch() -> None:
    microphone = DiagnosticMicrophone()
    stt = DiagnosticSTT()
    tts = DiagnosticTTS()
    speaker = DiagnosticSpeaker()
    service = build_brain_service(microphone=microphone, stt=stt, tts=tts, speaker=speaker)

    response = await service.transcribe_batch(
        BatchTranscriptionServiceRequestDto(audio_data=b"batch-audio", sample_rate=8000)
    )

    assert response.text == "batch text"
    assert stt.last_batch_request is not None
    assert stt.last_batch_request.audio_data == b"batch-audio"
    assert stt.last_batch_request.sample_rate == 8000
    assert microphone.start_requests == []
    assert microphone.stop_count == 0
    assert tts.set_requests == []
    assert tts.text_stream_requests == []
    assert speaker.play_requests == []
