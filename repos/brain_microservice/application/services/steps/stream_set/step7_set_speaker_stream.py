import asyncio

from application.dtos.outbound_dtos import SpeakerPlaybackRequestDto
from application.ports.outbound_ports import SpeakerPort
from domain.console import console_log

from ..context import AsyncStreamPipe, VoicePipelineContext, verify_speaker_input


class Step7SetSpeakerStream:
    def __init__(self, speaker_port: SpeakerPort) -> None:
        self.speaker_port = speaker_port

    async def run(self, context: VoicePipelineContext) -> None:
        request = context.request
        console_log("flow4-attach", "pipeline step 7: setting speaker input stream connector")
        speaker_stream_in_pipe = AsyncStreamPipe[bytes]("speaker-stream-in")
        context.speaker_stream_in_pipe = speaker_stream_in_pipe
        speaker_input = SpeakerPlaybackRequestDto(
            speaker_stream_in_pipe.stream,
            sample_rate=request.tts_sample_rate,
            channels=request.speaker_channels,
        )
        verify_speaker_input(speaker_input)
        context.speaker_input = speaker_input
        speaker_task = context.create_task(self.speaker_port.play_stream(speaker_input), "speaker playback")
        await asyncio.sleep(0)
        if speaker_task.done():
            await speaker_task
        context.speaker_task = speaker_task
        console_log("flow4-attach", "speaker input stream connector started")
