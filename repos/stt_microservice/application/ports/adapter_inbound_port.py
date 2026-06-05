from abc import ABC, abstractmethod
from typing import Any

from application.dtos.adapter_inbound_dtos import (
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    SetStreamRequestDto,
    SetStreamResponseDto,
    GetStreamRequestDto,
    GetStreamResponseDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    STTAvailabilityRequestDto,
    STTAvailabilityResponseDto,
)


class AdapterInboundPort(ABC):
    @abstractmethod
    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        """Process a real-time audio stream and return a text stream."""
        pass

    @abstractmethod
    async def set_stream(self, request: SetStreamRequestDto) -> SetStreamResponseDto:
        """Feed the shared decoupled audio stream."""
        pass

    @abstractmethod
    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        """Return the shared decoupled transcription stream."""
        pass

    @abstractmethod
    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        """Process a complete audio buffer and return transcribed text."""
        pass

    @abstractmethod
    async def is_available(self, request: STTAvailabilityRequestDto) -> STTAvailabilityResponseDto:
        """Check if the STT engine is ready to accept requests."""
        pass

    @property
    @abstractmethod
    def get_app(self) -> Any:
        """Return the underlying framework application instance (e.g., FastAPI app)."""
        pass

    @abstractmethod
    def start_autoload(self) -> None:
        """Start the background task that consumes the external stream."""
        pass

    @abstractmethod
    async def stop_autoload(self) -> None:
        """Gracefully stop the autoloading background task."""
        pass
