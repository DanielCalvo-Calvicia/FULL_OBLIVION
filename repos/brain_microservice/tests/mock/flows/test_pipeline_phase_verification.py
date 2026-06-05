from collections.abc import AsyncIterator
from typing import cast

import pytest

from application.dtos.outbound_dtos import (
    MicrophoneStreamRequestDto,
    MicrophoneStreamResponseDto,
    TTSAudioStreamRequestDto,
    TTSAudioStreamResponseDto,
)
from application.dtos.service_dtos import TextToSpeechPlaybackServiceRequestDto, VoicePipelineServiceRequestDto
from tests.shared.fakes import DiagnosticMicrophone, DiagnosticSTT, DiagnosticSpeaker, DiagnosticTTS, build_brain_service


class BrokenMicrophoneOutput(DiagnosticMicrophone):
    async def start_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        self.start_requests.append(request)
        return MicrophoneStreamResponseDto(
            audio_stream=cast(AsyncIterator[bytes], None),
            sample_rate=request.sample_rate,
        )


class BrokenTTSOutput(DiagnosticTTS):
    async def get_stream(self, request: TTSAudioStreamRequestDto) -> TTSAudioStreamResponseDto:
        self.get_requests.append(request)
        return TTSAudioStreamResponseDto(audio_stream=cast(AsyncIterator[bytes], None))


@pytest.mark.asyncio
async def test_voice_pipeline_stops_before_stt_when_microphone_output_fails_verification() -> None:
    microphone = BrokenMicrophoneOutput()
    stt = DiagnosticSTT()
    service = build_brain_service(microphone=microphone, stt=stt)

    with pytest.raises(RuntimeError, match="microphone audio output verification failed"):
        await service.run_voice_pipeline(VoicePipelineServiceRequestDto())

    assert stt.stream_requests == []
    assert microphone.stop_count == 1


@pytest.mark.asyncio
async def test_text_playback_stops_before_speaker_when_tts_output_fails_verification() -> None:
    tts = BrokenTTSOutput()
    speaker = DiagnosticSpeaker()
    service = build_brain_service(tts=tts, speaker=speaker)

    with pytest.raises(RuntimeError, match="TTS audio output verification failed"):
        await service.play_text(TextToSpeechPlaybackServiceRequestDto(text="hello"))

    assert speaker.play_requests == []
