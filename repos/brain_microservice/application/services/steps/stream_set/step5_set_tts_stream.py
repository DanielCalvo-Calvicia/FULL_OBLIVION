import asyncio

from application.dtos.outbound_dtos import TTSTextStreamRequestDto
from application.ports.outbound_ports import TTSPort
from domain.console import console_log

from ..context import AsyncStreamPipe, VoicePipelineContext, limit_and_count_text_stream
from ..stream_internal.external_events import text_stream_as_ndjson_events


class Step5SetTTSStream:
    def __init__(self, tts_port: TTSPort) -> None:
        self.tts_port = tts_port

    async def run(self, context: VoicePipelineContext) -> None:
        request = context.request
        console_log("flow4-attach", "pipeline step 5: setting TTS input stream connector")
        tts_stream_in_pipe = AsyncStreamPipe[str]("tts-stream-in")
        context.tts_stream_in_pipe = tts_stream_in_pipe
        counted_text_stream = limit_and_count_text_stream(tts_stream_in_pipe.stream, request.max_text_segments)
        context.counted_text_stream = counted_text_stream
        tts_input = TTSTextStreamRequestDto(
            text_stream=text_stream_as_ndjson_events(counted_text_stream.text_stream),
            sample_rate=request.tts_sample_rate,
            channels=request.speaker_channels,
        )
        context.tts_input = tts_input
        tts_input_task = context.create_task(self.tts_port.set_text_stream(tts_input), "TTS text input")
        await asyncio.sleep(0)
        if tts_input_task.done():
            await tts_input_task
        context.tts_input_task = tts_input_task
        console_log("flow4-attach", "TTS input stream connector started")
