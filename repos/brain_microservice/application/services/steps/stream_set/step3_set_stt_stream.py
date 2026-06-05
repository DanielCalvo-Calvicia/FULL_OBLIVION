import asyncio

from application.dtos.outbound_dtos import STTSetStreamRequestDto
from application.ports.outbound_ports import STTPort
from domain.console import console_log

from ..context import AsyncStreamPipe, VoicePipelineContext, verify_stt_input


class Step3SetSTTStream:
    def __init__(self, stt_port: STTPort) -> None:
        self.stt_port = stt_port

    async def run(self, context: VoicePipelineContext) -> None:
        request = context.request
        microphone_output = context.require_microphone_output()
        console_log("flow4-attach", "pipeline step 3: setting STT input stream connector")
        stt_stream_in_pipe = AsyncStreamPipe[bytes]("stt-stream-in")
        context.stt_stream_in_pipe = stt_stream_in_pipe
        stt_input = STTSetStreamRequestDto(
            audio_stream=stt_stream_in_pipe.stream,
            sample_rate=microphone_output.sample_rate,
            chunk_size=request.microphone_chunk_size,
            silence_threshold=request.stt_silence_threshold,
            silence_limit_seconds=request.stt_silence_limit_seconds,
        )
        verify_stt_input(stt_input)
        context.stt_input = stt_input
        task = context.create_task(self.stt_port.set_stream(stt_input), "STT input")
        await asyncio.sleep(0)
        if task.done():
            await task
        context.stt_input_task = task
        console_log("flow4-attach", "STT input stream connector started")
