from application.dtos.adapter_inbound_dtos import StartSpeakerStreamRequestDto as InboundStreamRequest
from application.dtos.services_dtos import PlaybackStreamRequestDto as ServicePlaybackRequest
from runtime.logger import get_logger

logger = get_logger("application.mapper.inbound_to_service")

def map_inbound_to_service_playback_request(
    request: InboundStreamRequest,
) -> ServicePlaybackRequest:
    logger.trace(
        "Mapping inbound playback request to service DTO: sample_rate=%s channels=%s",
        request.sample_rate,
        request.channels,
    )
    return ServicePlaybackRequest(
        audio_stream=request.audio_stream,
        sample_rate=request.sample_rate,
        channels=request.channels,
        setup_future=request.setup_future,
    )
