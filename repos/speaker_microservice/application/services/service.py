from application.ports.service_port import SpeakerServicePort
from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.dtos.services_dtos import PlaybackStreamRequestDto, PlaybackStreamResponseDto, SpeakerCleanupResponseDto
from runtime.logger import get_logger

logger = get_logger("application.service")

class SpeakerService(SpeakerServicePort):
    def __init__(self, outbound_port: AdapterOutboundPort):
        self.outbound_port = outbound_port
        logger.info("SpeakerService initialized with outbound port: %s", type(outbound_port).__name__)

    async def play(self, request: PlaybackStreamRequestDto) -> PlaybackStreamResponseDto:
        """Validate and route playback request to the outbound hardware port."""
        logger.info(
            "Received playback request in service layer: sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        if request.sample_rate <= 0:
            logger.warning("Rejecting playback request with invalid sample rate: %s", request.sample_rate)
            response = PlaybackStreamResponseDto(success=False, message="Invalid sample rate. Must be positive.")
            if request.setup_future is not None and not request.setup_future.done():
                request.setup_future.set_result(response)
            return response
        if request.channels <= 0:
            logger.warning("Rejecting playback request with invalid channel count: %s", request.channels)
            response = PlaybackStreamResponseDto(success=False, message="Invalid channel count. Must be positive.")
            if request.setup_future is not None and not request.setup_future.done():
                request.setup_future.set_result(response)
            return response
        
        logger.info("Playback request validated. Forwarding to outbound adapter.")
        response = await self.outbound_port.play_stream(request)
        logger.info("Outbound adapter completed playback: success=%s message=%s", response.success, response.message)
        return response

    async def stop_and_cleanup(self) -> SpeakerCleanupResponseDto:
        """Coordinate graceful teardown and release of device resources."""
        logger.info("Service cleanup requested. Forwarding cleanup to outbound adapter.")
        response = await self.outbound_port.cleanup()
        logger.info("Service cleanup finished: success=%s", response.success)
        return response
