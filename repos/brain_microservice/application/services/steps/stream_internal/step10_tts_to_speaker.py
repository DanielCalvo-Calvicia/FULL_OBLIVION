from collections.abc import AsyncIterator

from domain.console import console_log

from ..context import AsyncStreamPipe, VoicePipelineContext
from .events import (
    StandardStreamEvent,
    audio_completed_event,
    audio_partial_event,
    stream_error_event,
    stream_started_event,
    validate_internal_stream_event,
)
from .external_events import decode_completed_audio, decode_event_audio, ndjson_events, raise_for_stream_error, stream_event_bytes


class Step10TTSStreamToInternalStreamToSpeakerStream:
    def __init__(
        self,
        tts_stream_out: AsyncIterator[bytes],
        speaker_stream_in: AsyncStreamPipe[bytes],
        completed_outputs_to_read: int | None = None,
    ) -> None:
        self.tts_stream_out = tts_stream_out
        self.internal_stream = AsyncStreamPipe[StandardStreamEvent]("tts-to-speaker-audio")
        self.speaker_stream_in = speaker_stream_in
        self.completed_outputs_to_read = completed_outputs_to_read

    async def run(self, context: VoicePipelineContext) -> None:
        context.tts_to_speaker_bridge = self
        task = context.create_task(self.tts_stream_to_internal_stream(), "TTS audio to internal speaker input")
        context.tts_to_speaker_task = task
        context.create_task(self.internal_stream_to_speaker_stream(), "internal TTS audio to speaker connector")

    async def tts_stream_to_internal_stream(self) -> None:
        sequence = 1
        segment_chunks: list[bytes] = []
        completed_outputs = 0
        max_outputs = self.completed_outputs_to_read or 0
        try:
            await self.internal_stream.put(stream_started_event(sequence))
            sequence += 1
            async for event in ndjson_events(self.tts_stream_out, service_name="tts"):
                if event.type in ("stream_started", "heartbeat"):
                    continue
                if event.type == "partial":
                    audio = decode_event_audio(event)
                    if audio:
                        segment_chunks.append(audio)
                        await self.internal_stream.put(audio_partial_event(sequence, audio))
                        sequence += 1
                    continue
                if event.type == "completed":
                    if not segment_chunks:
                        audio = decode_completed_audio(event)
                        if audio:
                            segment_chunks.append(audio)
                            await self.internal_stream.put(audio_partial_event(sequence, audio))
                            sequence += 1
                    completed_outputs += 1
                    completed_event = audio_completed_event(sequence, b"".join(segment_chunks))
                    sequence += 1
                    segment_chunks = []
                    console_log(
                        "flow4-attach",
                        "TTS-to-speaker internal stream completed event",
                        level="critical",
                        always=True,
                        event_type=completed_event.type,
                        sequence=completed_event.sequence,
                        timestamp=completed_event.timestamp,
                        payload=completed_event.payload,
                        completed_outputs=completed_outputs,
                    )
                    await self.internal_stream.put(completed_event)
                    if max_outputs > 0 and completed_outputs >= max_outputs:
                        break
                    continue
                if event.type == "error":
                    raise_for_stream_error(event, service_name="tts")
        except Exception as exc:
            await self.internal_stream.put(stream_error_event(sequence, str(exc)))
            raise
        finally:
            await self.internal_stream.close()

    async def internal_stream_to_speaker_stream(self) -> None:
        expected_sequence = 1
        try:
            async for event in self.internal_stream.stream:
                validate_internal_stream_event(event, expected_sequence)
                expected_sequence += 1
                if event.type in ("stream_started", "heartbeat"):
                    await self.speaker_stream_in.put(stream_event_bytes(event.type, event.sequence, event.payload))
                    continue
                if event.type == "partial":
                    await self.speaker_stream_in.put(stream_event_bytes(event.type, event.sequence, event.payload))
                    continue
                if event.type == "completed":
                    await self.speaker_stream_in.put(stream_event_bytes(event.type, event.sequence, event.payload))
                    continue
                if event.type == "error":
                    raise RuntimeError(str(event.payload.get("message", "TTS-to-speaker internal stream error")))
        except Exception as exc:
            await self.speaker_stream_in.fail(exc)
            raise
        finally:
            await self.speaker_stream_in.close()
