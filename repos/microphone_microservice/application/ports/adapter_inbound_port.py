from abc import ABC, abstractmethod

from fastapi import FastAPI

from application.ports.service_port import ServicePort

from application.dtos.adapter_inbound_dtos import (
    StartMicrophoneStreamRequestDto,
    StartMicrophoneStreamResponseDto,
    StopMicrophoneStreamRequestDto,
    StopMicrophoneStreamResponseDto,
    MicrophoneAvailabilityRequestDto,
    MicrophoneAvailabilityResponseDto,
)

class AdapterInboundPort(ABC):   

    @property
    @abstractmethod
    def get_app(self) -> FastAPI:
        pass

    @abstractmethod
    def __init__(self, service_port: ServicePort, app: FastAPI):
        pass
    
    @abstractmethod
    def register_routes(self, app: FastAPI) -> None:
        pass

    @abstractmethod
    async def start_stream(self, request: StartMicrophoneStreamRequestDto) -> StartMicrophoneStreamResponseDto:
        """Start continuous microphone streaming."""
        pass

    @abstractmethod
    async def stop_stream(self, request: StopMicrophoneStreamRequestDto) -> StopMicrophoneStreamResponseDto:
        """Stop active microphone stream."""
        pass

    @abstractmethod
    async def is_available(self, request: MicrophoneAvailabilityRequestDto) -> MicrophoneAvailabilityResponseDto:
        """Check if microphone is available."""
        pass
