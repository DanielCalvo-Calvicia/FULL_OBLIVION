from abc import ABC, abstractmethod
from typing import Any

from application.dtos.adapter_inbound_dtos import (
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    TTSAvailabilityRequestDto,
    TTSAvailabilityResponseDto,
    SetStreamRequestDto,
    GetStreamRequestDto,
    GetStreamResponseDto,
)


class AdapterInboundPort(ABC):
    @abstractmethod
    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        """Process a real-time text stream and return synthesized audio stream."""
        pass

    @abstractmethod
    async def set_stream(self, request: SetStreamRequestDto) -> None:
        """Set the active input text stream to process in the background."""
        pass

    @abstractmethod
    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        """Retrieve the active synthesized audio response stream."""
        pass


    @abstractmethod
    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        """Process a complete text string and return synthesized audio buffer."""
        pass

    @abstractmethod
    async def is_available(self, request: TTSAvailabilityRequestDto) -> TTSAvailabilityResponseDto:
        """Check if the TTS engine is ready to accept requests."""
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
