from application.dtos.adapter_outbound_dtos import (
    ProcessStreamResponseDto as OutboundStreamResponse,
    ProcessBatchResponseDto as OutboundBatchResponse,
    TTSAvailabilityResponseDto as OutboundAvailabilityResponse,
    GetStreamResponseDto as OutboundGetStreamResponse,
)
from application.dtos.services_dtos import (
    ProcessStreamResponseDto as ServiceStreamResponse,
    ProcessBatchResponseDto as ServiceBatchResponse,
    TTSAvailabilityResponseDto as ServiceAvailabilityResponse,
    GetStreamResponseDto as ServiceGetStreamResponse,
)
from infrastructure.logger import get_logger

logger = get_logger(__name__)



def map_outbound_to_service_stream_response(
    response: OutboundStreamResponse,
) -> ServiceStreamResponse:
    logger.info("Mapping outbound stream response to service response")
    return ServiceStreamResponse(
        audio_stream=response.audio_stream,
    )


def map_outbound_to_service_batch_response(
    response: OutboundBatchResponse,
) -> ServiceBatchResponse:
    logger.info(
        "Mapping outbound batch response to service response audio_bytes=%s",
        len(response.audio_data),
    )
    return ServiceBatchResponse(
        audio_data=response.audio_data,
    )


def map_outbound_to_service_availability_response(
    response: OutboundAvailabilityResponse,
) -> ServiceAvailabilityResponse:
    logger.info(
        "Mapping outbound availability response to service response is_available=%s",
        response.is_available,
    )
    return ServiceAvailabilityResponse(
        is_available=response.is_available,
    )


def map_outbound_to_service_get_stream_response(
    response: OutboundGetStreamResponse,
) -> ServiceGetStreamResponse:
    logger.info("Mapping outbound get-stream response to service response")
    return ServiceGetStreamResponse(
        audio_stream=response.audio_stream,
    )
