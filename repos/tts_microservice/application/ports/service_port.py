from abc import ABC, abstractmethod

from application.dtos.services_dtos import (
    InitServiceDto,
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


class ServicePort(ABC):
    @abstractmethod
    async def init(self, request: InitServiceDto) -> None:
        """Initialize service dependencies."""
        pass

    @abstractmethod
    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        """Orchestrate real-time text stream to audio synthesis."""
        pass

    @abstractmethod
    async def set_stream(self, request: SetStreamRequestDto) -> None:
        """Orchestrate setting of text stream for background synthesis."""
        pass

    @abstractmethod
    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        """Orchestrate retrieval of background synthesized audio stream."""
        pass


    @abstractmethod
    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        """Orchestrate batch text synthesis."""
        pass

    @abstractmethod
    async def is_available(self, request: TTSAvailabilityRequestDto) -> TTSAvailabilityResponseDto:
        """Check TTS service availability."""
        pass
