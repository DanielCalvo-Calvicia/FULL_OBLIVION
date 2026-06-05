from abc import ABC, abstractmethod

from application.dtos.adapter_outbound_dtos import (
    InitOutboundAdapterDto,
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


class AdapterOutboundPort(ABC):
    @abstractmethod
    async def init(self, config: InitOutboundAdapterDto) -> None:
        """Initialize or reconfigure the outbound TTS adapter."""
        pass

    @abstractmethod
    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        """Send a text stream to the TTS engine and yield an audio stream."""
        pass

    @abstractmethod
    async def set_stream(self, request: SetStreamRequestDto) -> None:
        """Set text stream on the TTS adapter to begin background synthesis."""
        pass

    @abstractmethod
    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        """Get the active synthesized audio stream from the TTS adapter."""
        pass


    @abstractmethod
    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        """Send a complete text block to the TTS engine and return transcribed audio data."""
        pass

    @abstractmethod
    async def is_available(self, request: TTSAvailabilityRequestDto) -> TTSAvailabilityResponseDto:
        """Check if the TTS engine is healthy and ready."""
        pass
