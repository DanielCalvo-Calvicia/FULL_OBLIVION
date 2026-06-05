from application.dtos.adapter_inbound_dtos import (
    ProcessStreamRequestDto as InboundStreamRequest,
    ProcessBatchRequestDto as InboundBatchRequest,
    TTSAvailabilityRequestDto as InboundAvailabilityRequest,
    SetStreamRequestDto as InboundSetStreamRequest,
    GetStreamRequestDto as InboundGetStreamRequest,
)
from application.dtos.services_dtos import (
    ProcessStreamRequestDto as ServiceStreamRequest,
    ProcessBatchRequestDto as ServiceBatchRequest,
    TTSAvailabilityRequestDto as ServiceAvailabilityRequest,
    SetStreamRequestDto as ServiceSetStreamRequest,
    GetStreamRequestDto as ServiceGetStreamRequest,
)
from infrastructure.logger import get_logger

logger = get_logger(__name__)



def map_inbound_to_service_stream_request(
    request: InboundStreamRequest,
) -> ServiceStreamRequest:
    logger.info(
        "Mapping inbound stream request to service request sample_rate=%s channels=%s",
        request.sample_rate,
        request.channels,
    )
    return ServiceStreamRequest(
        text_stream=request.text_stream,
        sample_rate=request.sample_rate,
        channels=request.channels,
    )


def map_inbound_to_service_batch_request(
    request: InboundBatchRequest,
) -> ServiceBatchRequest:
    logger.info(
        "Mapping inbound batch request to service request text_length=%s sample_rate=%s channels=%s",
        len(request.text),
        request.sample_rate,
        request.channels,
    )
    return ServiceBatchRequest(
        text=request.text,
        sample_rate=request.sample_rate,
        channels=request.channels,
    )


def map_inbound_to_service_availability_request(
    request: InboundAvailabilityRequest,
) -> ServiceAvailabilityRequest:
    logger.info("Mapping inbound availability request to service request")
    return ServiceAvailabilityRequest()


def map_inbound_to_service_set_stream_request(
    request: InboundSetStreamRequest,
) -> ServiceSetStreamRequest:
    logger.info(
        "Mapping inbound set-stream request to service request sample_rate=%s channels=%s",
        request.sample_rate,
        request.channels,
    )
    return ServiceSetStreamRequest(
        text_stream=request.text_stream,
        sample_rate=request.sample_rate,
        channels=request.channels,
    )


def map_inbound_to_service_get_stream_request(
    request: InboundGetStreamRequest,
) -> ServiceGetStreamRequest:
    logger.info("Mapping inbound get-stream request to service request")
    return ServiceGetStreamRequest()
