from abc import ABC, abstractmethod

from application.dtos.adapter_outbound_dtos import (
    ProcessStreamRequestDto,
    ProcessStreamResponseDto,
    ProcessBatchRequestDto,
    ProcessBatchResponseDto,
    STTAvailabilityRequestDto,
    STTAvailabilityResponseDto,
)


class AdapterOutboundPort(ABC):
    @abstractmethod
    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        """Send an audio stream to the STT engine and yield a text stream."""
        pass

    @abstractmethod
    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        """Send a complete audio buffer to the STT engine and return transcribed text."""
        pass

    @abstractmethod
    async def is_available(self, request: STTAvailabilityRequestDto) -> STTAvailabilityResponseDto:
        """Check if the STT engine is healthy and ready."""
        pass
