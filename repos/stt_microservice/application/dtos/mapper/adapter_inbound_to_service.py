from application.dtos.adapter_inbound_dtos import (
    ProcessStreamRequestDto as InboundStreamRequest,
    SetStreamRequestDto as InboundSetStreamRequest,
    GetStreamRequestDto as InboundGetStreamRequest,
    ProcessBatchRequestDto as InboundBatchRequest,
    STTAvailabilityRequestDto as InboundAvailabilityRequest,
)
from application.dtos.services_dtos import (
    ProcessStreamRequestDto as ServiceStreamRequest,
    SetStreamRequestDto as ServiceSetStreamRequest,
    GetStreamRequestDto as ServiceGetStreamRequest,
    ProcessBatchRequestDto as ServiceBatchRequest,
    STTAvailabilityRequestDto as ServiceAvailabilityRequest,
)
from runtime.logger import get_logger

logger = get_logger(__name__)


def map_inbound_to_service_stream_request(
    request: InboundStreamRequest,
) -> ServiceStreamRequest:
    logger.debug(
        "Mapping inbound stream request to service request: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s.",
        request.sample_rate,
        request.chunk_size,
        request.silence_threshold,
        request.silence_limit_seconds,
    )
    return ServiceStreamRequest(
        audio_stream=request.audio_stream,
        sample_rate=request.sample_rate,
        chunk_size=request.chunk_size,
        silence_threshold=request.silence_threshold,
        silence_limit_seconds=request.silence_limit_seconds,
    )


def map_inbound_to_service_set_stream_request(
    request: InboundSetStreamRequest,
) -> ServiceSetStreamRequest:
    logger.debug(
        "Mapping inbound set-stream request to service request: sample_rate=%s chunk_size=%s silence_threshold=%s silence_limit_seconds=%s.",
        request.sample_rate,
        request.chunk_size,
        request.silence_threshold,
        request.silence_limit_seconds,
    )
    return ServiceSetStreamRequest(
        audio_stream=request.audio_stream,
        sample_rate=request.sample_rate,
        chunk_size=request.chunk_size,
        silence_threshold=request.silence_threshold,
        silence_limit_seconds=request.silence_limit_seconds,
    )


def map_inbound_to_service_get_stream_request(
    request: InboundGetStreamRequest,
) -> ServiceGetStreamRequest:
    logger.debug("Mapping inbound get-stream request to service request.")
    return ServiceGetStreamRequest()


def map_inbound_to_service_batch_request(
    request: InboundBatchRequest,
) -> ServiceBatchRequest:
    logger.debug("Mapping inbound batch request to service request: bytes=%s sample_rate=%s.", len(request.audio_data), request.sample_rate)
    return ServiceBatchRequest(
        audio_data=request.audio_data,
        sample_rate=request.sample_rate,
    )


def map_inbound_to_service_availability_request(
    request: InboundAvailabilityRequest,
) -> ServiceAvailabilityRequest:
    logger.debug("Mapping inbound availability request to service request.")
    return ServiceAvailabilityRequest()
