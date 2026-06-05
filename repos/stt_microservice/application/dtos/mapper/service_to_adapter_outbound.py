from application.dtos.services_dtos import (
    ProcessStreamRequestDto as ServiceStreamRequest,
    SetStreamRequestDto as ServiceSetStreamRequest,
    ProcessBatchRequestDto as ServiceBatchRequest,
    STTAvailabilityRequestDto as ServiceAvailabilityRequest,
)
from application.dtos.adapter_outbound_dtos import (
    ProcessStreamRequestDto as OutboundStreamRequest,
    ProcessBatchRequestDto as OutboundBatchRequest,
    STTAvailabilityRequestDto as OutboundAvailabilityRequest,
)
from runtime.logger import get_logger

logger = get_logger(__name__)


def map_service_to_outbound_stream_request(
    request: ServiceStreamRequest | ServiceSetStreamRequest,
) -> OutboundStreamRequest:
    logger.debug(
        "Mapping service stream request to outbound request: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s.",
        request.sample_rate,
        request.chunk_size,
        request.silence_threshold,
        request.silence_limit_seconds,
    )
    return OutboundStreamRequest(
        audio_stream=request.audio_stream,
        sample_rate=request.sample_rate,
        chunk_size=request.chunk_size,
        silence_threshold=request.silence_threshold,
        silence_limit_seconds=request.silence_limit_seconds,
    )


def map_service_to_outbound_batch_request(
    request: ServiceBatchRequest,
) -> OutboundBatchRequest:
    logger.debug("Mapping service batch request to outbound request: bytes=%s sample_rate=%s.", len(request.audio_data), request.sample_rate)
    return OutboundBatchRequest(
        audio_data=request.audio_data,
        sample_rate=request.sample_rate,
    )


def map_service_to_outbound_availability_request(
    request: ServiceAvailabilityRequest,
) -> OutboundAvailabilityRequest:
    logger.debug("Mapping service availability request to outbound request.")
    return OutboundAvailabilityRequest()
