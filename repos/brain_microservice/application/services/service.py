import asyncio

from application.dtos.outbound_dtos import (
    MicrophoneStreamRequestDto,
    SpeakerPlaybackRequestDto,
    STTBatchRequestDto,
    STTSetStreamRequestDto,
    STTTextStreamRequestDto,
    TTSAudioStreamRequestDto,
    TTSTextStreamRequestDto,
)
from application.dtos.service_dtos import (
    BatchTranscriptionServiceRequestDto,
    BatchTranscriptionServiceResponseDto,
    HealthCheckServiceResponseDto,
    MicrophoneTranscriptionServiceRequestDto,
    MicrophoneTranscriptionServiceResponseDto,
    TextToSpeechPlaybackServiceRequestDto,
    TextToSpeechPlaybackServiceResponseDto,
    VoicePipelineServiceRequestDto,
    VoicePipelineServiceResponseDto,
)
from application.ports.outbound_ports import HealthCheckPort, MicrophonePort, SpeakerPort, STTPort, TTSPort
from application.ports.service_port import BrainServicePort
from application.services.pipeline import VoicePipelineFlow
from application.services.steps.context import (
    AsyncStreamPipe,
    verify_microphone_output,
    verify_speaker_input,
    verify_speaker_response,
    verify_stt_input,
    verify_stt_output,
    verify_tts_output,
)
from application.services.steps.stream_internal.external_events import raise_for_stream_error, sse_events, text_stream_as_ndjson_events
from application.services.steps.stream_internal.step10_tts_to_speaker import Step10TTSStreamToInternalStreamToSpeakerStream
from application.services.steps.stream_internal.step8_mic_to_stt import Step8MicStreamToInternalStreamToSTTStream
from domain.console import console_log
from domain.errors import ExternalServiceError
from domain.models import ServiceStatus


class BrainService(BrainServicePort):
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
        self.voice_pipeline = VoicePipelineFlow(microphone_port, stt_port, tts_port, speaker_port)

    async def check_integrations(self) -> HealthCheckServiceResponseDto:
        console_log("flow1-health", "checking external microservice health")
        services = (
            await self._check("microphone", self.microphone_port),
            await self._check("stt", self.stt_port),
            await self._check("tts", self.tts_port),
            await self._check("speaker", self.speaker_port),
        )
        console_log("flow1-health", "external microservice health checked", services=len(services))
        return HealthCheckServiceResponseDto(services=services)

    async def transcribe_batch(
        self, request: BatchTranscriptionServiceRequestDto
    ) -> BatchTranscriptionServiceResponseDto:
        console_log("flow4-attach", "starting batch transcription", audio_bytes=len(request.audio_data), sample_rate=request.sample_rate)
        response = await self.stt_port.process_batch(
            STTBatchRequestDto(audio_data=request.audio_data, sample_rate=request.sample_rate)
        )
        console_log("flow4-attach", "batch transcription finished", text_chars=len(response.text))
        return BatchTranscriptionServiceResponseDto(text=response.text)

    async def transcribe_microphone(
        self, request: MicrophoneTranscriptionServiceRequestDto
    ) -> MicrophoneTranscriptionServiceResponseDto:
        try:
            console_log(
                "flow4-attach",
                "starting microphone transcription attachment",
                sample_rate=request.sample_rate,
                chunk_size=request.chunk_size,
                max_segments=request.max_segments,
            )
            microphone_output = await self.microphone_port.start_stream(
                MicrophoneStreamRequestDto(sample_rate=request.sample_rate, chunk_size=request.chunk_size)
            )
            verify_microphone_output(microphone_output)
            stt_stream_in_pipe = AsyncStreamPipe[bytes]("transcribe-stt-stream-in")
            stt_input = STTSetStreamRequestDto(
                audio_stream=stt_stream_in_pipe.stream,
                sample_rate=microphone_output.sample_rate,
                chunk_size=request.chunk_size,
                silence_threshold=request.silence_threshold,
                silence_limit_seconds=request.silence_limit_seconds,
            )
            verify_stt_input(stt_input)
            stt_input_task = asyncio.create_task(self.stt_port.set_stream(stt_input))
            mic_to_stt = Step8MicStreamToInternalStreamToSTTStream(microphone_output.audio_stream, stt_stream_in_pipe)
            mic_parse_task = asyncio.create_task(mic_to_stt.mic_stream_to_internal_stream())
            mic_forward_task = asyncio.create_task(mic_to_stt.internal_stream_to_stt_stream())
            await asyncio.sleep(0)
            if stt_input_task.done():
                await stt_input_task

            try:
                stt_output = await self.stt_port.get_stream(
                    STTTextStreamRequestDto(
                        sample_rate=stt_input.sample_rate,
                        chunk_size=stt_input.chunk_size,
                        silence_threshold=stt_input.silence_threshold,
                        silence_limit_seconds=stt_input.silence_limit_seconds,
                    )
                )
                verify_stt_output(stt_output)
                segments: list[str] = []
                async for event in sse_events(stt_output.text_stream, service_name="stt"):
                    if event.type in ("stream_started", "heartbeat", "partial"):
                        continue
                    if event.type == "completed":
                        text = event.payload.get("output", event.payload.get("text", ""))
                        cleaned = text.strip() if isinstance(text, str) else ""
                        if cleaned:
                            segments.append(cleaned)
                            console_log("flow4-attach", "received STT transcription segment", segment=len(segments), chars=len(cleaned))
                        if len(segments) >= request.max_segments:
                            console_log("flow4-attach", "microphone transcription segment limit reached", max_segments=request.max_segments)
                            break
                        continue
                    if event.type == "error":
                        raise_for_stream_error(event, service_name="stt")
            finally:
                for task in (mic_parse_task, mic_forward_task):
                    if not task.done():
                        task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                await _finish_task(stt_input_task, "STT input forwarding task cancelled for transcription")
            console_log("flow4-attach", "microphone transcription finished", segments=len(segments))
            return MicrophoneTranscriptionServiceResponseDto(segments=tuple(segments))
        except Exception:
            await _stop_microphone_safely(self.microphone_port, "microphone transcription error")
            raise

    async def play_text(
        self, request: TextToSpeechPlaybackServiceRequestDto
    ) -> TextToSpeechPlaybackServiceResponseDto:
        console_log("flow4-attach", "starting text playback attachment", text_chars=len(request.text), sample_rate=request.sample_rate, channels=request.channels)
        await self.tts_port.set_text_stream(
            TTSTextStreamRequestDto(
                text_stream=text_stream_as_ndjson_events(_single_text_stream(request.text)),
                sample_rate=request.sample_rate,
                channels=request.channels,
            )
        )
        tts_output = await self.tts_port.get_stream(
            TTSAudioStreamRequestDto(
                sample_rate=request.sample_rate,
                channels=request.channels,
                completed_outputs_to_read=1,
            )
        )
        verify_tts_output(tts_output)
        speaker_stream_in_pipe = AsyncStreamPipe[bytes]("play-text-speaker-stream-in")
        speaker_input = SpeakerPlaybackRequestDto(
            speaker_stream_in_pipe.stream,
            sample_rate=request.sample_rate,
            channels=request.channels,
        )
        verify_speaker_input(speaker_input)
        speaker_task = asyncio.create_task(self.speaker_port.play_stream(speaker_input))
        tts_to_speaker = Step10TTSStreamToInternalStreamToSpeakerStream(
            tts_output.audio_stream,
            speaker_stream_in_pipe,
            completed_outputs_to_read=1,
        )
        tts_parse_task = asyncio.create_task(tts_to_speaker.tts_stream_to_internal_stream())
        tts_forward_task = asyncio.create_task(tts_to_speaker.internal_stream_to_speaker_stream())
        try:
            await tts_parse_task
            await tts_forward_task
            speaker_response = await speaker_task
        finally:
            for task in (tts_parse_task, tts_forward_task, speaker_task):
                if not task.done():
                    task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        verify_speaker_response(speaker_response)
        console_log("flow4-attach", "text playback attachment finished", success=speaker_response.success, detail=speaker_response.message)
        return TextToSpeechPlaybackServiceResponseDto(success=speaker_response.success, message=speaker_response.message)

    async def run_voice_pipeline(
        self, request: VoicePipelineServiceRequestDto
    ) -> VoicePipelineServiceResponseDto:
        return await self.voice_pipeline.run(request)

    async def _check(self, name: str, port: HealthCheckPort) -> ServiceStatus:
        try:
            console_log("flow1-health", "checking microservice", service=name)
            response = await port.check_health()
            return ServiceStatus(name=name, is_available=response.is_available, detail=response.detail)
        except ExternalServiceError as exc:
            console_log("flow1-health", "microservice check failed", service=name, error=exc.message)
            return ServiceStatus(name=name, is_available=False, detail=exc.message)
        except Exception as exc:
            console_log("flow1-health", "microservice check failed", service=name, error=str(exc))
            return ServiceStatus(name=name, is_available=False, detail=str(exc))


async def _finish_task(task: asyncio.Task, cancelled_message: str) -> None:
    if task.done():
        await task
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        console_log("flow4-attach", cancelled_message)


async def _single_text_stream(text: str):
    if text:
        yield text


async def _stop_microphone_safely(microphone_port: MicrophonePort, reason: str) -> None:
    try:
        console_log("brain-service", "stopping microphone via API", reason=reason)
        await microphone_port.stop_stream()
    except Exception as exc:
        console_log("brain-service", "microphone stop failed", reason=reason, error=str(exc))
