from typing import cast

import pytest

from application.dtos.outbound_dtos import (
    MicrophoneStreamResponseDto,
    STTStreamResponseDto,
    STTTextStreamRequestDto,
)
from application.dtos.service_dtos import VoicePipelineServiceRequestDto
from application.ports.outbound_ports import STTPort
from application.services.steps.context import VoicePipelineContext
from application.services.steps.stream_get.step4_get_stt_stream import Step4GetSTTStream
from application.services.steps.stream_internal.external_events import stream_event_bytes
from tests.shared.streams import byte_stream


class ImmediateSTTOutput:
    async def get_stream(self, request: STTTextStreamRequestDto) -> STTStreamResponseDto:
        return STTStreamResponseDto(
            text_stream=byte_stream(
                (
                    b"data: " + stream_event_bytes("stream_started", 1, {}) + b"\n",
                    b"data: " + stream_event_bytes("completed", 2, {"reason": "completed", "output": "first full text"}) + b"\n",
                    b"data: " + stream_event_bytes("completed", 3, {"reason": "completed", "output": "second full text"}) + b"\n",
                )
            )
        )


@pytest.mark.asyncio
async def test_stt_output_stream_logs_each_full_text(capsys: pytest.CaptureFixture[str]) -> None:
    context = VoicePipelineContext.create(VoicePipelineServiceRequestDto())
    context.microphone_output = MicrophoneStreamResponseDto(
        sample_rate=16000,
        audio_stream=byte_stream((b"placeholder",)),
    )

    await Step4GetSTTStream(cast(STTPort, ImmediateSTTOutput())).run(context)
    received = [chunk async for chunk in context.require_stt_output().text_stream]

    captured = capsys.readouterr()
    assert b"first full text" in b"".join(received)
    assert b"second full text" in b"".join(received)
    assert "STT output stream returned full text" not in captured.out
