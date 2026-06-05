from application.dtos.services_dtos import PlaybackStreamResponseDto as ServicePlaybackResponse
from application.dtos.adapter_inbound_dtos import StartSpeakerStreamResponseDto as InboundPlaybackResponse
from runtime.logger import get_logger

logger = get_logger("application.mapper.service_to_inbound")

def map_service_to_inbound_playback_response(
    response: ServicePlaybackResponse,
) -> InboundPlaybackResponse:
    logger.trace(
        "Mapping service playback response to inbound DTO: success=%s message=%s",
        response.success,
        response.message,
    )
    return InboundPlaybackResponse(
        success=response.success,
        message=response.message,
    )
