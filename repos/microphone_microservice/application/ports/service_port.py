from abc import ABC, abstractmethod

from application.dtos.services_dtos import (
    StartMicrophoneStreamRequestDto,
    StartMicrophoneStreamResponseDto,
    StopMicrophoneStreamRequestDto,
    StopMicrophoneStreamResponseDto,
    MicrophoneAvailabilityRequestDto,
    MicrophoneAvailabilityResponseDto,
)

class ServicePort(ABC):
    @abstractmethod
    async def start_stream(
        self,
        request: StartMicrophoneStreamRequestDto,
    ) -> StartMicrophoneStreamResponseDto:
        """
        Start continuous microphone streaming.

        Returns:
            StartMicrophoneStreamResponseDto containing the audio stream.
        """
        pass

    @abstractmethod
    async def stop_stream(self, request: StopMicrophoneStreamRequestDto) -> StopMicrophoneStreamResponseDto:
        """Stop active microphone stream."""
        pass

    @abstractmethod
    async def is_available(self, request: MicrophoneAvailabilityRequestDto) -> MicrophoneAvailabilityResponseDto:
        """Check if microphone is available."""
        pass
