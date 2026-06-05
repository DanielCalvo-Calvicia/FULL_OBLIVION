from collections.abc import AsyncIterator

from domain.console import console_log

from ..context import AsyncStreamPipe, VoicePipelineContext
from .events import (
    StandardStreamEvent,
    event_completed_text,
    event_text,
    stream_error_event,
    stream_started_event,
    text_completed_event,
    text_partial_event,
    validate_internal_stream_event,
)
from .external_events import raise_for_stream_error, sse_events


class Step9STTStreamToInternalStreamToTTSStream:
    def __init__(
        self,
        stt_stream_out: AsyncIterator[bytes],
        tts_stream_in: AsyncStreamPipe[str],
    ) -> None:
        self.stt_stream_out = stt_stream_out
        self.tts_stream_in = tts_stream_in
        self.internal_stream = AsyncStreamPipe[StandardStreamEvent]("stt-to-tts-text")

    async def run(self, context: VoicePipelineContext) -> None:
        context.stt_to_tts_bridge = self
        task = context.create_task(self.stt_stream_to_internal_stream(), "STT text to internal TTS input")
        context.stt_to_tts_task = task
        context.create_task(self.internal_stream_to_tts_stream(), "internal STT text to TTS connector")

    async def stt_stream_to_internal_stream(self) -> None:
        text_count = 0
        sequence = 1
        chunks: list[str] = []
        try:
            await self.internal_stream.put(stream_started_event(sequence))
            sequence += 1
            async for event in sse_events(self.stt_stream_out, service_name="stt"):
                if event.type in ("stream_started", "heartbeat"):
                    continue
                if event.type == "partial":
                    text = event.payload.get("text", "")
                    if isinstance(text, str) and text.strip():
                        console_log("stt-adapter", "received STT partial text event", level="warn", event=event.sequence, chars=len(text))
                    continue
                if event.type == "completed":
                    text = event.payload.get("output", event.payload.get("text", ""))
                    if isinstance(text, str) and text.strip():
                        text_count += 1
                        chunks.append(text)
                        console_log("stt-adapter", "parsed STT completed text event", level="warn", event=event.sequence, chars=len(text))
                        await self.internal_stream.put(text_partial_event(sequence, text))
                        sequence += 1
                    continue
                if event.type == "error":
                    raise_for_stream_error(event, service_name="stt")
            completed_event = text_completed_event(sequence, "".join(chunks))
            console_log(
                "flow4-attach",
                "STT-to-TTS internal stream completed event",
                level="critical",
                always=True,
                event_type=completed_event.type,
                sequence=completed_event.sequence,
                timestamp=completed_event.timestamp,
                payload=completed_event.payload,
            )
            await self.internal_stream.put(completed_event)
        except Exception as exc:
            await self.internal_stream.put(stream_error_event(sequence, str(exc)))
            raise
        finally:
            await self.internal_stream.close()

    async def internal_stream_to_tts_stream(self) -> None:
        expected_sequence = 1
        completed = False
        try:
            async for event in self.internal_stream.stream:
                validate_internal_stream_event(event, expected_sequence)
                expected_sequence += 1
                if event.type in ("stream_started", "heartbeat"):
                    continue
                if event.type == "partial":
                    await self.tts_stream_in.put(event_text(event))
                    continue
                if event.type == "completed":
                    event_completed_text(event)
                    completed = True
                    break
                if event.type == "error":
                    raise RuntimeError(str(event.payload.get("message", "STT-to-TTS internal stream error")))
            if not completed:
                raise RuntimeError("STT-to-TTS internal stream ended before completed event")
        except Exception as exc:
            await self.tts_stream_in.fail(exc)
            raise
        finally:
            await self.tts_stream_in.close()
