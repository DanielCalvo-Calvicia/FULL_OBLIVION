from typing import Protocol

from application.dtos.outbound_dtos import (
    ExternalHealthResponseDto,
    MicrophoneStreamRequestDto,
    MicrophoneStreamResponseDto,
    SpeakerPlaybackRequestDto,
    SpeakerPlaybackResponseDto,
    STTBatchRequestDto,
    STTBatchResponseDto,
    STTSetStreamRequestDto,
    STTTextStreamRequestDto,
    STTStreamResponseDto,
    TTSAudioStreamRequestDto,
    TTSAudioStreamResponseDto,
    TTSSetStreamRequestDto,
    TTSTextStreamRequestDto,
)


class HealthCheckPort(Protocol):
    async def check_health(self) -> ExternalHealthResponseDto:
        ...


class MicrophonePort(HealthCheckPort, Protocol):
    async def start_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        ...

    async def get_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        ...

    async def stop_stream(self) -> None:
        ...


class STTPort(HealthCheckPort, Protocol):
    async def set_stream(self, request: STTSetStreamRequestDto) -> None:
        ...

    async def get_stream(self, request: STTTextStreamRequestDto) -> STTStreamResponseDto:
        ...

    async def process_batch(self, request: STTBatchRequestDto) -> STTBatchResponseDto:
        ...


class TTSPort(HealthCheckPort, Protocol):
    async def set_stream(self, request: TTSSetStreamRequestDto) -> None:
        ...

    async def set_text_stream(self, request: TTSTextStreamRequestDto) -> None:
        ...

    async def get_stream(self, request: TTSAudioStreamRequestDto) -> TTSAudioStreamResponseDto:
        ...


class SpeakerPort(HealthCheckPort, Protocol):
    async def play_stream(self, request: SpeakerPlaybackRequestDto) -> SpeakerPlaybackResponseDto:
        ...
