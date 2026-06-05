from application.ports.service_port import ServicePort
from application.ports.adapter_outbound_port import AdapterOutboundPort

from application.dtos.services_dtos import (
    InitServiceDto as ServiceInitRequest,
    ProcessStreamRequestDto as ServiceStreamRequest,
    ProcessStreamResponseDto as ServiceStreamResponse,
    ProcessBatchRequestDto as ServiceBatchRequest,
    ProcessBatchResponseDto as ServiceBatchResponse,
    TTSAvailabilityRequestDto as ServiceAvailabilityRequest,
    TTSAvailabilityResponseDto as ServiceAvailabilityResponse,
    SetStreamRequestDto as ServiceSetStreamRequest,
    GetStreamRequestDto as ServiceGetStreamRequest,
    GetStreamResponseDto as ServiceGetStreamResponse,
)

from application.dtos.mapper.service_to_adapter_outbound import (
    map_service_to_outbound_init_request,
    map_service_to_outbound_stream_request,
    map_service_to_outbound_batch_request,
    map_service_to_outbound_availability_request,
    map_service_to_outbound_set_stream_request,
    map_service_to_outbound_get_stream_request,
)
from application.dtos.mapper.adapter_outbound_to_service import (
    map_outbound_to_service_stream_response,
    map_outbound_to_service_batch_response,
    map_outbound_to_service_availability_response,
    map_outbound_to_service_get_stream_response,
)
from infrastructure.logger import get_logger


logger = get_logger(__name__)


class TTSService(ServicePort):
    def __init__(self, name: str, outbound_port: AdapterOutboundPort):
        self.name = name
        self.outbound_port = outbound_port
        logger.info("TTSService initialized name=%s outbound_port=%s", name, type(outbound_port).__name__)

    async def init(self, request: ServiceInitRequest) -> None:
        logger.info("TTSService.init started outbound_port=%s", type(self.outbound_port).__name__)
        outbound_req = map_service_to_outbound_init_request(request)
        await self.outbound_port.init(outbound_req)
        logger.info("TTSService.init finished")

    async def process_stream(self, request: ServiceStreamRequest) -> ServiceStreamResponse:
        logger.info(
            "TTSService.process_stream started sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        outbound_req = map_service_to_outbound_stream_request(request)
        outbound_res = await self.outbound_port.process_stream(outbound_req)
        response = map_outbound_to_service_stream_response(outbound_res)
        logger.info("TTSService.process_stream finished")
        return response

    async def process_batch(self, request: ServiceBatchRequest) -> ServiceBatchResponse:
        logger.info(
            "TTSService.process_batch started text_length=%s sample_rate=%s channels=%s",
            len(request.text),
            request.sample_rate,
            request.channels,
        )
        outbound_req = map_service_to_outbound_batch_request(request)
        outbound_res = await self.outbound_port.process_batch(outbound_req)
        response = map_outbound_to_service_batch_response(outbound_res)
        logger.info("TTSService.process_batch finished audio_bytes=%s", len(response.audio_data))
        return response

    async def is_available(self, request: ServiceAvailabilityRequest) -> ServiceAvailabilityResponse:
        logger.info("TTSService.is_available started")
        outbound_req = map_service_to_outbound_availability_request(request)
        outbound_res = await self.outbound_port.is_available(outbound_req)
        response = map_outbound_to_service_availability_response(outbound_res)
        logger.info("TTSService.is_available finished is_available=%s", response.is_available)
        return response

    async def set_stream(self, request: ServiceSetStreamRequest) -> None:
        logger.info(
            "TTSService.set_stream started sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        outbound_req = map_service_to_outbound_set_stream_request(request)
        await self.outbound_port.set_stream(outbound_req)
        logger.info("TTSService.set_stream finished")

    async def get_stream(self, request: ServiceGetStreamRequest) -> ServiceGetStreamResponse:
        logger.info("TTSService.get_stream started")
        outbound_req = map_service_to_outbound_get_stream_request(request)
        outbound_res = await self.outbound_port.get_stream(outbound_req)
        response = map_outbound_to_service_get_stream_response(outbound_res)
        logger.info("TTSService.get_stream finished")
        return response
