from application.dtos.adapter_outbound_dtos import (
    ProcessStreamResponseDto as OutboundStreamResponse,
    ProcessBatchResponseDto as OutboundBatchResponse,
    STTAvailabilityResponseDto as OutboundAvailabilityResponse,
)
from application.dtos.services_dtos import (
    ProcessStreamResponseDto as ServiceStreamResponse,
    ProcessBatchResponseDto as ServiceBatchResponse,
    STTAvailabilityResponseDto as ServiceAvailabilityResponse,
)
from runtime.logger import get_logger

logger = get_logger(__name__)


def map_outbound_to_service_stream_response(
    response: OutboundStreamResponse,
) -> ServiceStreamResponse:
    logger.debug("Mapping outbound stream response to service response.")
    return ServiceStreamResponse(
        text_stream=response.text_stream,
    )


def map_outbound_to_service_batch_response(
    response: OutboundBatchResponse,
) -> ServiceBatchResponse:
    logger.debug("Mapping outbound batch response to service response: text_length=%s.", len(response.text))
    return ServiceBatchResponse(
        text=response.text,
    )


def map_outbound_to_service_availability_response(
    response: OutboundAvailabilityResponse,
) -> ServiceAvailabilityResponse:
    logger.debug("Mapping outbound availability response to service response: is_available=%s.", response.is_available)
    return ServiceAvailabilityResponse(
        is_available=response.is_available,
    )
