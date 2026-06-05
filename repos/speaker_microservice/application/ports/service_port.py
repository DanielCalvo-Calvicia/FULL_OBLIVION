from abc import ABC, abstractmethod
from application.dtos.services_dtos import PlaybackStreamRequestDto, PlaybackStreamResponseDto, SpeakerCleanupResponseDto

class SpeakerServicePort(ABC):
    @abstractmethod
    async def play(self, request: PlaybackStreamRequestDto) -> PlaybackStreamResponseDto:
        """Coordinate and validate audio stream playback through outbound adapter."""
        pass

    @abstractmethod
    async def stop_and_cleanup(self) -> SpeakerCleanupResponseDto:
        """Gracefully interrupt current playback and clean up hardware resources."""
        pass
