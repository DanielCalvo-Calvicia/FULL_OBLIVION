from application.dtos.services_dtos import (
    ProcessStreamResponseDto as ServiceStreamResponse,
    ProcessBatchResponseDto as ServiceBatchResponse,
    TTSAvailabilityResponseDto as ServiceAvailabilityResponse,
    GetStreamResponseDto as ServiceGetStreamResponse,
)
from application.dtos.adapter_inbound_dtos import (
    ProcessStreamResponseDto as InboundStreamResponse,
    ProcessBatchResponseDto as InboundBatchResponse,
    TTSAvailabilityResponseDto as InboundAvailabilityResponse,
    GetStreamResponseDto as InboundGetStreamResponse,
)
from infrastructure.logger import get_logger

logger = get_logger(__name__)



def map_service_to_inbound_stream_response(
    response: ServiceStreamResponse,
) -> InboundStreamResponse:
    logger.info("Mapping service stream response to inbound response")
    return InboundStreamResponse(
        audio_stream=response.audio_stream,
    )


def map_service_to_inbound_batch_response(
    response: ServiceBatchResponse,
) -> InboundBatchResponse:
    logger.info(
        "Mapping service batch response to inbound response audio_bytes=%s",
        len(response.audio_data),
    )
    return InboundBatchResponse(
        audio_data=response.audio_data,
    )


def map_service_to_inbound_availability_response(
    response: ServiceAvailabilityResponse,
) -> InboundAvailabilityResponse:
    logger.info(
        "Mapping service availability response to inbound response is_available=%s",
        response.is_available,
    )
    return InboundAvailabilityResponse(
        is_available=response.is_available,
    )


def map_service_to_inbound_get_stream_response(
    response: ServiceGetStreamResponse,
) -> InboundGetStreamResponse:
    logger.info("Mapping service get-stream response to inbound response")
    return InboundGetStreamResponse(
        audio_stream=response.audio_stream,
    )
