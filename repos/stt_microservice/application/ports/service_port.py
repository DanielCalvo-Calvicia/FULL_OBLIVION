from abc import ABC, abstractmethod

from application.dtos.services_dtos import (
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


class ServicePort(ABC):
    @abstractmethod
    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        """Orchestrate real-time stream processing."""
        pass

    @abstractmethod
    async def set_stream(self, request: SetStreamRequestDto) -> SetStreamResponseDto:
        """Orchestrate the shared decoupled inbound audio stream."""
        pass

    @abstractmethod
    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        """Return the shared decoupled outbound text stream."""
        pass

    @abstractmethod
    async def stop_stream(self) -> None:
        """Stop the active shared decoupled stream, if any."""
        pass

    @abstractmethod
    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        """Orchestrate batch audio processing."""
        pass

    @abstractmethod
    async def is_available(self, request: STTAvailabilityRequestDto) -> STTAvailabilityResponseDto:
        """Check STT service availability."""
        pass
