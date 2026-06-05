import asyncio
import base64
from collections.abc import Iterator

import pytest

from application.services.steps.stream_internal.events import StandardStreamEvent
from application.services.steps.context import AsyncStreamPipe
from application.services.steps.stream_internal.step8_mic_to_stt import Step8MicStreamToInternalStreamToSTTStream
from application.services.steps.stream_internal.step9_stt_to_tts import Step9STTStreamToInternalStreamToTTSStream
from application.services.steps.stream_internal.step10_tts_to_speaker import Step10TTSStreamToInternalStreamToSpeakerStream
from application.services.steps.stream_internal.external_events import stream_event_bytes
from domain.console import configure_logger
from tests.shared.streams import byte_stream


@pytest.fixture(autouse=True)
def reset_logger_environment() -> Iterator[None]:
    configure_logger("development")
    yield
    configure_logger("development")


@pytest.mark.asyncio
async def test_mic_to_stt_internal_stream_emits_standard_audio_events_with_full_completion() -> None:
    bridge = Step8MicStreamToInternalStreamToSTTStream(
        byte_stream((_audio_events((b"mic-", b"audio"), completed_field="output_bytes_base64"),)),
        AsyncStreamPipe("stt-in"),
    )

    await bridge.mic_stream_to_internal_stream()

    events = await _collect_until_completed(bridge.internal_stream.stream)
    _assert_standard_sequence(events)
    assert [event.type for event in events] == ["stream_started", "partial", "partial", "completed"]
    assert events[1].payload == {"bytes_base64": base64.b64encode(b"mic-").decode("ascii")}
    assert events[2].payload == {"bytes_base64": base64.b64encode(b"audio").decode("ascii")}
    assert events[3].payload == {
        "reason": "completed",
        "output_bytes_base64": base64.b64encode(b"mic-audio").decode("ascii"),
    }


@pytest.mark.asyncio
async def test_stt_to_tts_internal_stream_emits_standard_text_events_with_full_completion() -> None:
    bridge = Step9STTStreamToInternalStreamToTTSStream(
        byte_stream((_sse_text_events(("hello ", "world")),)),
        AsyncStreamPipe("tts-in"),
    )

    await bridge.stt_stream_to_internal_stream()

    events = await _collect_until_completed(bridge.internal_stream.stream)
    _assert_standard_sequence(events)
    assert [event.type for event in events] == ["stream_started", "partial", "partial", "completed"]
    assert events[1].payload == {"text": "hello "}
    assert events[2].payload == {"text": "world"}
    assert events[3].payload == {"reason": "completed", "output": "hello world"}


@pytest.mark.asyncio
async def test_tts_to_speaker_internal_stream_emits_standard_audio_events_with_full_completion() -> None:
    bridge = Step10TTSStreamToInternalStreamToSpeakerStream(
        byte_stream((_audio_events((b"tts-", b"audio"), completed_field="output_bytes_base64"),)),
        AsyncStreamPipe("speaker-in"),
    )

    await bridge.tts_stream_to_internal_stream()

    events = await _collect_until_completed(bridge.internal_stream.stream)
    _assert_standard_sequence(events)
    assert [event.type for event in events] == ["stream_started", "partial", "partial", "completed"]
    assert events[3].payload == {
        "reason": "completed",
        "output_bytes_base64": base64.b64encode(b"tts-audio").decode("ascii"),
    }


@pytest.mark.parametrize("environment", ("staging", "production"))
@pytest.mark.asyncio
async def test_internal_stream_logs_only_completed_event_in_restricted_environments(
    environment: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logger(environment)
    bridge = Step9STTStreamToInternalStreamToTTSStream(
        byte_stream((_sse_text_events(("hello",)),)),
        AsyncStreamPipe("tts-in"),
    )

    await bridge.stt_stream_to_internal_stream()

    output = capsys.readouterr().out
    assert f"[{environment}] [critical] [flow4-attach] STT-to-TTS internal stream completed event" in output
    assert "STT to TTS internal text pipe running" not in output
    assert "received STT text segment for internal TTS pipe" not in output
    assert "STT to TTS internal text pipe closed" not in output


@pytest.mark.asyncio
async def test_internal_stream_remains_open_after_completed_event_until_pipeline_shutdown() -> None:
    bridge = Step9STTStreamToInternalStreamToTTSStream(
        byte_stream((_sse_text_events(("hello",)),)),
        AsyncStreamPipe("tts-in"),
    )

    await bridge.stt_stream_to_internal_stream()
    stream = bridge.internal_stream.stream
    events = await _collect_until_completed(stream)

    assert events[-1].type == "completed"
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()


def _assert_standard_sequence(events: list[StandardStreamEvent]) -> None:
    for index, event in enumerate(events, start=1):
        assert event.sequence == index
        assert event.timestamp.endswith("Z")
        assert isinstance(event.payload, dict)
    assert events[0].type == "stream_started"
    assert events[0].payload == {}


async def _collect_until_completed(stream) -> list[StandardStreamEvent]:
    events = []
    async for event in stream:
        events.append(event)
        if event.type == "completed":
            break
    return events


def _audio_events(chunks: tuple[bytes, ...], *, completed_field: str = "bytes_base64") -> bytes:
    events = [stream_event_bytes("stream_started", 1, {})]
    sequence = 2
    for chunk in chunks:
        events.append(stream_event_bytes("partial", sequence, {"bytes_base64": base64.b64encode(chunk).decode("ascii")}))
        sequence += 1
    events.append(
        stream_event_bytes(
            "completed",
            sequence,
            {"reason": "completed", completed_field: base64.b64encode(b"".join(chunks)).decode("ascii")},
        )
    )
    return b"".join(events)


def _sse_text_events(texts: tuple[str, ...]) -> bytes:
    events = [b"data: " + stream_event_bytes("stream_started", 1, {}) + b"\n"]
    sequence = 2
    for text in texts:
        events.append(b"data: " + stream_event_bytes("completed", sequence, {"reason": "completed", "output": text}) + b"\n")
        sequence += 1
    return b"".join(events)
