from .. import adapter_outbound_dtos as adapter_dtos
from .. import services_dtos as service_dtos
from composition_root.runtime.logger import get_logger


logger = get_logger("mapper:service->outbound")


# =====================================================================
# FLOW 1: Starting the Microphone Stream
# =====================================================================

def map_service_to_adapter_start_request(
    service_dto: service_dtos.StartMicrophoneStreamRequestDto
) -> adapter_dtos.StartMicrophoneStreamRequestDto:
    """
    Maps a service layer stream request to an outbound adapter request.
    Executed when entering the adapter from the service layer.
    """
    logger.trace(
        "start request",
        sample_rate=service_dto.sample_rate,
        channels=service_dto.channels,
        chunk_size=service_dto.chunk_size,
    )
    return adapter_dtos.StartMicrophoneStreamRequestDto(
        sample_rate=service_dto.sample_rate,
        channels=service_dto.channels,
        chunk_size=service_dto.chunk_size
    )


# =====================================================================
# FLOW 2: Stopping the Microphone Stream
# =====================================================================

def map_service_to_adapter_stop_request(
    service_dto: service_dtos.StopMicrophoneStreamRequestDto
) -> adapter_dtos.StopMicrophoneStreamRequestDto:
    """
    Maps a service layer stop request to an outbound adapter stop request.
    Executed when entering the adapter from the service layer.
    """
    logger.trace("stop request")
    return adapter_dtos.StopMicrophoneStreamRequestDto()


    
# =====================================================================
# FLOW 3: Checking Microphone Availability
# =====================================================================

def map_service_to_adapter_availability_request(
    service_dto: service_dtos.MicrophoneAvailabilityRequestDto
) -> adapter_dtos.MicrophoneAvailabilityRequestDto:
    """
    Maps a service layer availability request to an outbound adapter availability request.
    Executed when entering the adapter from the service layer.
    """
    logger.trace("availability request")
    return adapter_dtos.MicrophoneAvailabilityRequestDto()

