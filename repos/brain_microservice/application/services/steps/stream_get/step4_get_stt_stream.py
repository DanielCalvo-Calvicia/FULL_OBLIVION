import asyncio

from application.dtos.outbound_dtos import STTTextStreamRequestDto
from application.ports.outbound_ports import STTPort
from domain.console import console_log
from domain.errors import ExternalServiceUnavailableError

from ..context import VoicePipelineContext, verify_stt_output


class Step4GetSTTStream:
    def __init__(self, stt_port: STTPort) -> None:
        self.stt_port = stt_port

    async def run(self, context: VoicePipelineContext) -> None:
        request = context.request
        microphone_output = context.require_microphone_output()
        console_log("flow4-attach", "pipeline step 4: getting STT stream")
        stt_output = await _open_stream_after_set_is_ready(
            lambda: self.stt_port.get_stream(
                STTTextStreamRequestDto(
                    sample_rate=microphone_output.sample_rate,
                    chunk_size=request.microphone_chunk_size,
                    silence_threshold=request.stt_silence_threshold,
                    silence_limit_seconds=request.stt_silence_limit_seconds,
                )
            ),
            component="stt",
        )
        verify_stt_output(stt_output)
        context.stt_output = stt_output


async def _open_stream_after_set_is_ready(open_stream, *, component: str, attempts: int = 5, delay_seconds: float = 0.1):
    for attempt in range(1, attempts + 1):
        try:
            return await open_stream()
        except ExternalServiceUnavailableError as exc:
            if "endpoint not found" not in exc.message and "No active stream" not in exc.message:
                raise
            if attempt == attempts:
                raise
            console_log(
                "flow4-attach",
                "stream output not ready after set; retrying",
                service=component,
                attempt=attempt,
                error=exc.message,
            )
            await asyncio.sleep(delay_seconds)
    raise RuntimeError("unreachable stream retry state")
