import asyncio

from application.ports.outbound_ports import MicrophonePort, SpeakerPort, STTPort, TTSPort
from domain.console import console_log
from domain.errors import ExternalServiceUnavailableError

from ..context import VoicePipelineContext


class Step1CheckHealth:
    def __init__(
        self,
        microphone_port: MicrophonePort,
        stt_port: STTPort,
        tts_port: TTSPort,
        speaker_port: SpeakerPort,
    ) -> None:
        self.microphone_port = microphone_port
        self.stt_port = stt_port
        self.tts_port = tts_port
        self.speaker_port = speaker_port

    async def run(self, context: VoicePipelineContext) -> None:
        console_log("flow4-attach", "pipeline step 1: checking adapter availability", level="warn")
        checks = await asyncio.gather(
            self.microphone_port.check_health(),
            self.stt_port.check_health(),
            self.tts_port.check_health(),
            self.speaker_port.check_health(),
        )
        names = ("microphone", "stt", "tts", "speaker")
        unavailable = [name for name, response in zip(names, checks) if not response.is_available]
        if unavailable:
            raise ExternalServiceUnavailableError(
                ",".join(unavailable),
                "required adapter availability check failed before loading streams",
            )
        console_log("flow4-attach", "pipeline step 1 completed: all adapters available", level="warn")
