from .. import adapter_outbound_dtos as adapter_dtos
from .. import services_dtos as service_dtos
from composition_root.runtime.logger import get_logger


logger = get_logger("mapper:outbound->service")

# =====================================================================
# FLOW 1: Starting the Microphone Stream
# =====================================================================

def map_adapter_to_service_start_response(
    adapter_dto: adapter_dtos.StartMicrophoneStreamResponseDto
) -> service_dtos.StartMicrophoneStreamResponseDto:
    """
    Maps an outbound adapter stream response back to the service layer response.
    Executed when returning the stream from the adapter back to the core.
    """
    logger.trace("start response", sample_rate=adapter_dto.sample_rate)
    return service_dtos.StartMicrophoneStreamResponseDto(
        stream=adapter_dto.stream,
        sample_rate=adapter_dto.sample_rate
    )



# =====================================================================
# FLOW 2: Stopping the Microphone Stream
# =====================================================================

def map_adapter_to_service_stop_response(
    adapter_dto: adapter_dtos.StopMicrophoneStreamResponseDto
) -> service_dtos.StopMicrophoneStreamResponseDto:
    """
    Maps an outbound adapter stop confirmation to a service layer response.
    """
    logger.trace("stop response", success=adapter_dto.success)
    return service_dtos.StopMicrophoneStreamResponseDto(
        success=adapter_dto.success
    )


# =====================================================================
# FLOW 3: Checking Microphone Availability
# =====================================================================

def map_adapter_to_service_availability_response(
    adapter_dto: adapter_dtos.MicrophoneAvailabilityResponseDto
) -> service_dtos.MicrophoneAvailabilityResponseDto:
    """
    Maps an outbound adapter hardware availability status to a service layer response.
    """
    logger.trace("availability response", is_available=adapter_dto.is_available)
    return service_dtos.MicrophoneAvailabilityResponseDto(
        is_available=adapter_dto.is_available
    )


