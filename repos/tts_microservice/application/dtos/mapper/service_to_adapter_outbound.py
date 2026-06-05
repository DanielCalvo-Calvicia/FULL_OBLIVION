from application.dtos.services_dtos import (
    InitServiceDto as ServiceInitRequest,
    ProcessStreamRequestDto as ServiceStreamRequest,
    ProcessBatchRequestDto as ServiceBatchRequest,
    TTSAvailabilityRequestDto as ServiceAvailabilityRequest,
    SetStreamRequestDto as ServiceSetStreamRequest,
    GetStreamRequestDto as ServiceGetStreamRequest,
)
from application.dtos.adapter_outbound_dtos import (
    InitOutboundAdapterDto as OutboundInitRequest,
    ProcessStreamRequestDto as OutboundStreamRequest,
    ProcessBatchRequestDto as OutboundBatchRequest,
    TTSAvailabilityRequestDto as OutboundAvailabilityRequest,
    SetStreamRequestDto as OutboundSetStreamRequest,
    GetStreamRequestDto as OutboundGetStreamRequest,
)
from infrastructure.logger import get_logger

logger = get_logger(__name__)



def map_service_to_outbound_init_request(
    request: ServiceInitRequest,
) -> OutboundInitRequest:
    logger.info(
        "Mapping service init request to outbound request openai_model=%s openai_voice=%s",
        request.openai_model,
        request.openai_voice,
    )
    return OutboundInitRequest(
        speech_rate=request.speech_rate,
        voice_name_preference=request.voice_name_preference,
        openai_api_key=request.openai_api_key,
        openai_model=request.openai_model,
        openai_voice=request.openai_voice,
        openai_response_format=request.openai_response_format,
        openai_instructions=request.openai_instructions,
        openai_speed=request.openai_speed,
        openai_base_url=request.openai_base_url,
    )


def map_service_to_outbound_stream_request(
    request: ServiceStreamRequest,
) -> OutboundStreamRequest:
    logger.info(
        "Mapping service stream request to outbound request sample_rate=%s channels=%s",
        request.sample_rate,
        request.channels,
    )
    return OutboundStreamRequest(
        text_stream=request.text_stream,
        sample_rate=request.sample_rate,
        channels=request.channels,
    )


def map_service_to_outbound_batch_request(
    request: ServiceBatchRequest,
) -> OutboundBatchRequest:
    logger.info(
        "Mapping service batch request to outbound request text_length=%s sample_rate=%s channels=%s",
        len(request.text),
        request.sample_rate,
        request.channels,
    )
    return OutboundBatchRequest(
        text=request.text,
        sample_rate=request.sample_rate,
        channels=request.channels,
    )


def map_service_to_outbound_availability_request(
    request: ServiceAvailabilityRequest,
) -> OutboundAvailabilityRequest:
    logger.info("Mapping service availability request to outbound request")
    return OutboundAvailabilityRequest()


def map_service_to_outbound_set_stream_request(
    request: ServiceSetStreamRequest,
) -> OutboundSetStreamRequest:
    logger.info(
        "Mapping service set-stream request to outbound request sample_rate=%s channels=%s",
        request.sample_rate,
        request.channels,
    )
    return OutboundSetStreamRequest(
        text_stream=request.text_stream,
        sample_rate=request.sample_rate,
        channels=request.channels,
    )


def map_service_to_outbound_get_stream_request(
    request: ServiceGetStreamRequest,
) -> OutboundGetStreamRequest:
    logger.info("Mapping service get-stream request to outbound request")
    return OutboundGetStreamRequest()
