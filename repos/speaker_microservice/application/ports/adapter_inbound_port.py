from abc import ABC, abstractmethod
from typing import Any

from application.dtos.adapter_inbound_dtos import (
    StartSpeakerStreamRequestDto,
    StartSpeakerStreamResponseDto,
)


class AdapterInboundPort(ABC):
    @abstractmethod
    async def play(self, request: StartSpeakerStreamRequestDto) -> StartSpeakerStreamResponseDto:
        """Coordinate and validate audio stream playback."""
        pass

    @property
    @abstractmethod
    def get_app(self) -> Any:
        """Return the underlying framework application instance (e.g., FastAPI app)."""
        pass

    @abstractmethod
    def start_autoload(self) -> None:
        """Start the background task that consumes the external stream (if any)."""
        pass

    @abstractmethod
    async def stop_autoload(self) -> None:
        """Gracefully stop any autoloading background task."""
        pass
