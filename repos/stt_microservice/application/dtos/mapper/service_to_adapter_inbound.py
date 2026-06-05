from application.dtos.services_dtos import (
    ProcessStreamResponseDto as ServiceStreamResponse,
    SetStreamResponseDto as ServiceSetStreamResponse,
    GetStreamResponseDto as ServiceGetStreamResponse,
    ProcessBatchResponseDto as ServiceBatchResponse,
    STTAvailabilityResponseDto as ServiceAvailabilityResponse,
)
from application.dtos.adapter_inbound_dtos import (
    ProcessStreamResponseDto as InboundStreamResponse,
    SetStreamResponseDto as InboundSetStreamResponse,
    GetStreamResponseDto as InboundGetStreamResponse,
    ProcessBatchResponseDto as InboundBatchResponse,
    STTAvailabilityResponseDto as InboundAvailabilityResponse,
)
from runtime.logger import get_logger

logger = get_logger(__name__)


def map_service_to_inbound_stream_response(
    response: ServiceStreamResponse,
) -> InboundStreamResponse:
    logger.debug("Mapping service stream response to inbound response.")
    return InboundStreamResponse(
        text_stream=response.text_stream,
    )


def map_service_to_inbound_set_stream_response(
    response: ServiceSetStreamResponse,
) -> InboundSetStreamResponse:
    logger.debug("Mapping service set-stream response to inbound response: accepted=%s.", response.accepted)
    return InboundSetStreamResponse(
        accepted=response.accepted,
    )


def map_service_to_inbound_get_stream_response(
    response: ServiceGetStreamResponse,
) -> InboundGetStreamResponse:
    logger.debug("Mapping service get-stream response to inbound response.")
    return InboundGetStreamResponse(
        text_stream=response.text_stream,
    )


def map_service_to_inbound_batch_response(
    response: ServiceBatchResponse,
) -> InboundBatchResponse:
    logger.debug("Mapping service batch response to inbound response: text_length=%s.", len(response.text))
    return InboundBatchResponse(
        text=response.text,
    )


def map_service_to_inbound_availability_response(
    response: ServiceAvailabilityResponse,
) -> InboundAvailabilityResponse:
    logger.debug("Mapping service availability response to inbound response: is_available=%s.", response.is_available)
    return InboundAvailabilityResponse(
        is_available=response.is_available,
    )
