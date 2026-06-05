from abc import ABC, abstractmethod

from application.dtos.service_dtos import (
    BatchTranscriptionServiceRequestDto,
    BatchTranscriptionServiceResponseDto,
    HealthCheckServiceResponseDto,
    MicrophoneTranscriptionServiceRequestDto,
    MicrophoneTranscriptionServiceResponseDto,
    TextToSpeechPlaybackServiceRequestDto,
    TextToSpeechPlaybackServiceResponseDto,
    VoicePipelineServiceRequestDto,
    VoicePipelineServiceResponseDto,
)


class BrainServicePort(ABC):
    @abstractmethod
    async def check_integrations(self) -> HealthCheckServiceResponseDto:
        pass

    @abstractmethod
    async def transcribe_batch(
        self, request: BatchTranscriptionServiceRequestDto
    ) -> BatchTranscriptionServiceResponseDto:
        pass

    @abstractmethod
    async def transcribe_microphone(
        self, request: MicrophoneTranscriptionServiceRequestDto
    ) -> MicrophoneTranscriptionServiceResponseDto:
        pass

    @abstractmethod
    async def play_text(
        self, request: TextToSpeechPlaybackServiceRequestDto
    ) -> TextToSpeechPlaybackServiceResponseDto:
        pass

    @abstractmethod
    async def run_voice_pipeline(
        self, request: VoicePipelineServiceRequestDto
    ) -> VoicePipelineServiceResponseDto:
        pass
