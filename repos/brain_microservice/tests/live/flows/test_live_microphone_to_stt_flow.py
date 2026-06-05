import asyncio
import os
from contextlib import suppress

import pytest

from application.dtos.outbound_dtos import MicrophoneStreamRequestDto, STTSetStreamRequestDto, STTTextStreamRequestDto
from tests.shared.live_microservices import LiveMicroservices


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MICROSERVICE_TESTS") != "1",
    reason="Set RUN_LIVE_MICROSERVICE_TESTS=1 to hit real microphone and STT services.",
)


async def _drain_text_stream_until_closed(text_stream) -> int:
    event_count = 0
    async for text in text_stream:
        cleaned = text.strip()
        if cleaned:
            event_count += 1
            print(f"[live mic->stt] text event {event_count}: {cleaned}", flush=True)
    return event_count


@pytest.mark.asyncio
async def test_live_microphone_to_stt_flow_opens_text_stream_from_real_microphone_audio() -> None:
    live = LiveMicroservices()
    stt_input_task: asyncio.Task | None = None
    try:
        microphone_output = await live.microphone_adapter.start_stream(
            MicrophoneStreamRequestDto(sample_rate=16000, chunk_size=1024)
        )
        stt_input_task = asyncio.create_task(
            live.stt_adapter.set_stream(
                STTSetStreamRequestDto(
                    audio_stream=microphone_output.audio_stream,
                    sample_rate=microphone_output.sample_rate,
                    chunk_size=1024,
                    silence_threshold=150,
                    silence_limit_seconds=0.5,
                )
            )
        )
        await asyncio.sleep(0.1)

        stt_output = await live.stt_adapter.get_stream(
            STTTextStreamRequestDto(
                sample_rate=microphone_output.sample_rate,
                chunk_size=1024,
                silence_threshold=150,
                silence_limit_seconds=0.5,
            )
        )
        event_count = await _drain_text_stream_until_closed(stt_output.text_stream)
        print(
            f"[live mic->stt] STT SSE stream closed after {event_count} text events; "
            "not reopening /process/stream/get. Waiting for explicit stop...",
            flush=True,
        )
        await asyncio.Event().wait()
    finally:
        if stt_input_task is not None and not stt_input_task.done():
            stt_input_task.cancel()
            with suppress(asyncio.CancelledError):
                await stt_input_task
        with suppress(Exception):
            await live.microphone_adapter.stop_stream()
        await live.close()
