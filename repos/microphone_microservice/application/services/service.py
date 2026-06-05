from application.ports.service_port import ServicePort
from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.dtos.services_dtos import (
    StartMicrophoneStreamRequestDto as ServiceDto_StartMicrophoneStreamRequestDto,
    StartMicrophoneStreamResponseDto as ServiceDto_StartMicrophoneStreamResponseDto,
    StopMicrophoneStreamRequestDto as ServiceDto_StopMicrophoneStreamRequestDto,
    StopMicrophoneStreamResponseDto as ServiceDto_StopMicrophoneStreamResponseDto,
    MicrophoneAvailabilityRequestDto as ServiceDto_MicrophoneAvailabilityRequestDto,
    MicrophoneAvailabilityResponseDto as ServiceDto_MicrophoneAvailabilityResponseDto,
)

from application.dtos.mapper.service_to_adapter_outbound import (
    map_service_to_adapter_start_request,
    map_service_to_adapter_stop_request,
    map_service_to_adapter_availability_request,
)
from application.dtos.mapper.adapter_outbound_to_service import (
    map_adapter_to_service_start_response,
    map_adapter_to_service_stop_response,
    map_adapter_to_service_availability_response,
)
from composition_root.runtime.logger import get_logger


logger = get_logger("service")

class MicrophoneService(ServicePort):
    def __init__(self, name: str, controller_port: AdapterOutboundPort):        
        self.name = name
        self.controller_port = controller_port
        logger.info("MicrophoneService initialized", name=name)

    async def start_stream(
        self, 
        request: ServiceDto_StartMicrophoneStreamRequestDto
    ) -> ServiceDto_StartMicrophoneStreamResponseDto:
        """Start the microphone stream."""
        logger.info(
            "start_stream received",
            sample_rate=request.sample_rate,
            channels=request.channels,
            chunk_size=request.chunk_size,
        )

        logger.trace("start_stream mapping service DTO to outbound DTO")
        port_request_dto = map_service_to_adapter_start_request(request)
        
        logger.trace("start_stream calling outbound adapter")
        port_response = await self.controller_port.start_stream(port_request_dto)

        logger.trace(
            "start_stream mapping outbound response to service DTO",
            sample_rate=port_response.sample_rate,
        )
        service_response = map_adapter_to_service_start_response(port_response)

        logger.info("start_stream completed")
        return service_response


    async def stop_stream(self, request: ServiceDto_StopMicrophoneStreamRequestDto) -> ServiceDto_StopMicrophoneStreamResponseDto:
        """Stop the microphone stream."""
        logger.info("stop_stream received")
        logger.trace("stop_stream mapping service DTO to outbound DTO")
        port_request_dto = map_service_to_adapter_stop_request(request)

        logger.trace("stop_stream calling outbound adapter")
        port_response = await self.controller_port.stop_stream(port_request_dto)

        logger.info("stop_stream outbound response", success=port_response.success)
        service_response = map_adapter_to_service_stop_response(port_response)

        logger.info("stop_stream completed")
        return service_response


    async def is_available(self, request: ServiceDto_MicrophoneAvailabilityRequestDto) -> ServiceDto_MicrophoneAvailabilityResponseDto:
        """Check if the microphone is available."""
        logger.info("is_available received")
        logger.trace("is_available mapping service DTO to outbound DTO")
        port_request_dto = map_service_to_adapter_availability_request(request)

        logger.trace("is_available calling outbound adapter")
        port_response = await self.controller_port.is_available(port_request_dto)

        logger.info("is_available outbound response", is_available=port_response.is_available)
        service_response = map_adapter_to_service_availability_response(port_response)

        logger.info("is_available completed")
        return service_response
