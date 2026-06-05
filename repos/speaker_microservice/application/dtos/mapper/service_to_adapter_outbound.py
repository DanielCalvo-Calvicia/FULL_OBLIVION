from application.dtos.services_dtos import PlaybackStreamRequestDto as ServicePlaybackRequest
from application.dtos.services_dtos import PlaybackStreamRequestDto as OutboundPlaybackRequest
from runtime.logger import get_logger

logger = get_logger("application.mapper.service_to_outbound")

def map_service_to_outbound_playback_request(
    request: ServicePlaybackRequest,
) -> OutboundPlaybackRequest:
    # They are isomorphic currently, but kept distinct at boundaries
    logger.trace(
        "Mapping service playback request to outbound DTO: sample_rate=%s channels=%s",
        request.sample_rate,
        request.channels,
    )
    return OutboundPlaybackRequest(
        audio_stream=request.audio_stream,
        sample_rate=request.sample_rate,
        channels=request.channels,
    )
