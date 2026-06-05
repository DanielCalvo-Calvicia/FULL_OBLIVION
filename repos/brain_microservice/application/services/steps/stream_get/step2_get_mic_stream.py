from application.dtos.outbound_dtos import MicrophoneStreamRequestDto
from application.ports.outbound_ports import MicrophonePort
from domain.console import console_log

from ..context import VoicePipelineContext, verify_microphone_output


class Step2GetMicrophoneStream:
    def __init__(self, microphone_port: MicrophonePort) -> None:
        self.microphone_port = microphone_port

    async def run(self, context: VoicePipelineContext) -> None:
        request = context.request
        console_log("flow4-attach", "pipeline step 2: getting microphone stream")
        microphone_output = await self.microphone_port.start_stream(
            MicrophoneStreamRequestDto(
                sample_rate=request.microphone_sample_rate,
                chunk_size=request.microphone_chunk_size,
            )
        )
        verify_microphone_output(microphone_output)
        context.microphone_output = microphone_output
