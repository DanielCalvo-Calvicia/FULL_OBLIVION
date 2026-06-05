from abc import ABC, abstractmethod
from application.dtos.services_dtos import PlaybackStreamRequestDto, PlaybackStreamResponseDto, SpeakerCleanupResponseDto

class AdapterOutboundPort(ABC):
    @abstractmethod
    async def play_stream(self, request: PlaybackStreamRequestDto) -> PlaybackStreamResponseDto:
        """Stream raw audio chunks directly to hardware output buffers."""
        pass

    @abstractmethod
    async def cleanup(self) -> SpeakerCleanupResponseDto:
        """Release audio devices and terminate engine threads."""
        pass
