from .. import adapter_inbound_dtos as adapter_dtos
from .. import services_dtos as service_dtos
from composition_root.runtime.logger import get_logger


logger = get_logger("mapper:inbound->service")


# =====================================================================
# FLOW 1: Starting the Microphone Stream
# =====================================================================

def map_adapter_to_service_start_request(
    adapter_dto: adapter_dtos.StartMicrophoneStreamRequestDto
) -> service_dtos.StartMicrophoneStreamRequestDto:
    """
    Maps an inbound adapter stream request to a service layer request.
    Executed when the adapter forwards a start request into the service layer.
    """
    logger.trace(
        "start request",
        sample_rate=adapter_dto.sample_rate,
        channels=adapter_dto.channels,
        chunk_size=adapter_dto.chunk_size,
    )
    return service_dtos.StartMicrophoneStreamRequestDto(
        sample_rate=adapter_dto.sample_rate,
        channels=adapter_dto.channels,
        chunk_size=adapter_dto.chunk_size
    )


# =====================================================================
# FLOW 2: Stopping the Microphone Stream
# =====================================================================

def map_adapter_to_service_stop_request(
    adapter_dto: adapter_dtos.StopMicrophoneStreamRequestDto
) -> service_dtos.StopMicrophoneStreamRequestDto:
    """
    Maps an inbound adapter stop request to a service layer stop request.
    Executed when the adapter forwards the stop request into the service layer.
    """
    logger.trace("stop request")
    return service_dtos.StopMicrophoneStreamRequestDto()


# =====================================================================
# FLOW 3: Checking Microphone Availability
# =====================================================================

def map_adapter_to_service_availability_request(
    adapter_dto: adapter_dtos.MicrophoneAvailabilityRequestDto
) -> service_dtos.MicrophoneAvailabilityRequestDto:
    """
    Maps an inbound adapter availability request to a service layer availability request.
    Executed when the adapter forwards the availability request into the service layer.
    """
    logger.trace("availability request")
    return service_dtos.MicrophoneAvailabilityRequestDto()


