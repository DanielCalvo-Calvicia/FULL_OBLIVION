from collections.abc import AsyncIterator

from domain.console import console_log

from ..context import AsyncStreamPipe, VoicePipelineContext
from .events import (
    StandardStreamEvent,
    stream_error_event,
    validate_internal_stream_event,
)
from .external_events import decode_completed_audio, decode_event_audio, ndjson_events, raise_for_stream_error, stream_event_bytes


class Step8MicStreamToInternalStreamToSTTStream:
    def __init__(
        self,
        mic_stream_out: AsyncIterator[bytes],
        stt_stream_in: AsyncStreamPipe[bytes],
    ) -> None:
        self.mic_stream_out = mic_stream_out
        self.internal_stream = AsyncStreamPipe[StandardStreamEvent]("mic-to-stt-audio")
        self.stt_stream_in = stt_stream_in

    async def run(self, context: VoicePipelineContext) -> None:
        context.mic_to_stt_bridge = self
        context.create_task(self.mic_stream_to_internal_stream(), "microphone audio to internal STT input")
        context.create_task(self.internal_stream_to_stt_stream(), "internal microphone audio to STT connector")

    async def mic_stream_to_internal_stream(self) -> None:
        partials_since_completed = 0
        try:
            async for event in ndjson_events(self.mic_stream_out, service_name="microphone"):
                if event.type in ("stream_started", "heartbeat"):
                    await self.internal_stream.put(event)
                    continue
                if event.type == "partial":
                    partials_since_completed += 1
                    audio = decode_event_audio(event)
                    if audio:
                        console_log("flow4-attach", "decoded microphone partial audio", bytes=len(audio))
                    await self.internal_stream.put(event)
                    continue
                if event.type == "completed":
                    if partials_since_completed == 0:
                        audio = decode_completed_audio(event)
                        if audio:
                            console_log("flow4-attach", "decoded microphone completed audio fallback", bytes=len(audio))
                    partials_since_completed = 0
                    console_log(
                        "flow4-attach",
                        "mic-to-STT internal stream completed event",
                        level="critical",
                        always=True,
                        event_type=event.type,
                        sequence=event.sequence,
                        timestamp=event.timestamp,
                        payload=event.payload,
                    )
                    await self.internal_stream.put(event)
                    continue
                if event.type == "error":
                    raise_for_stream_error(event, service_name="microphone")
        except Exception as exc:
            await self.internal_stream.put(stream_error_event(1, str(exc)))
            raise
        finally:
            await self.internal_stream.close()

    async def internal_stream_to_stt_stream(self) -> None:
        expected_sequence = 1
        try:
            async for event in self.internal_stream.stream:
                validate_internal_stream_event(event, expected_sequence)
                expected_sequence += 1
                if event.type in ("stream_started", "heartbeat"):
                    await self.stt_stream_in.put(stream_event_bytes(event.type, event.sequence, event.payload))
                    continue
                if event.type == "partial":
                    await self.stt_stream_in.put(stream_event_bytes(event.type, event.sequence, event.payload))
                    continue
                if event.type == "completed":
                    payload = dict(event.payload)
                    if "output_bytes_base64" not in payload and isinstance(payload.get("bytes_base64"), str):
                        payload["output_bytes_base64"] = payload["bytes_base64"]
                    await self.stt_stream_in.put(stream_event_bytes(event.type, event.sequence, payload))
                    continue
                if event.type == "error":
                    raise RuntimeError(str(event.payload.get("message", "mic-to-STT internal stream error")))
        except Exception as exc:
            await self.stt_stream_in.fail(exc)
            raise
        finally:
            await self.stt_stream_in.close()
