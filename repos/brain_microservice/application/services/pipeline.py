import asyncio

from application.dtos.service_dtos import VoicePipelineServiceRequestDto, VoicePipelineServiceResponseDto
from application.ports.outbound_ports import MicrophonePort, SpeakerPort, STTPort, TTSPort
from application.services.steps.context import VoicePipelineContext, verify_speaker_response
from application.services.steps.health_check.step1_health_check import Step1CheckHealth
from application.services.steps.stream_get.step2_get_mic_stream import Step2GetMicrophoneStream
from application.services.steps.stream_get.step4_get_stt_stream import Step4GetSTTStream
from application.services.steps.stream_get.step6_get_tts_stream import Step6GetTTSStream
from application.services.steps.stream_internal.step8_mic_to_stt import Step8MicStreamToInternalStreamToSTTStream
from application.services.steps.stream_internal.step9_stt_to_tts import Step9STTStreamToInternalStreamToTTSStream
from application.services.steps.stream_internal.step10_tts_to_speaker import Step10TTSStreamToInternalStreamToSpeakerStream
from application.services.steps.stream_set.step3_set_stt_stream import Step3SetSTTStream
from application.services.steps.stream_set.step5_set_tts_stream import Step5SetTTSStream
from application.services.steps.stream_set.step7_set_speaker_stream import Step7SetSpeakerStream
from domain.console import console_log


class VoicePipelineFlow:
    """Service-level executor for the live voice stream pipeline."""

    def __init__(
        self,
        microphone_port: MicrophonePort,
        stt_port: STTPort,
        tts_port: TTSPort,
        speaker_port: SpeakerPort,
    ) -> None:
        self.microphone_port = microphone_port
        self.health_step = Step1CheckHealth(microphone_port, stt_port, tts_port, speaker_port)
        self.get_microphone_step = Step2GetMicrophoneStream(microphone_port)
        self.set_stt_step = Step3SetSTTStream(stt_port)
        self.get_stt_step = Step4GetSTTStream(stt_port)
        self.set_tts_step = Step5SetTTSStream(tts_port)
        self.get_tts_step = Step6GetTTSStream(tts_port)
        self.set_speaker_step = Step7SetSpeakerStream(speaker_port)

    async def run(self, request: VoicePipelineServiceRequestDto) -> VoicePipelineServiceResponseDto:
        console_log(
            "flow4-attach",
            "starting voice pipeline",
            mic_sample_rate=request.microphone_sample_rate,
            mic_chunk_size=request.microphone_chunk_size,
            tts_sample_rate=request.tts_sample_rate,
            speaker_channels=request.speaker_channels,
            max_text_segments=request.max_text_segments,
        )
        context = VoicePipelineContext.create(request)
        try:
            await self.health_step.run(context)
            await self.get_microphone_step.run(context)
            await self.set_stt_step.run(context)
            await self.get_stt_step.run(context)
            await self.set_tts_step.run(context)
            await self.get_tts_step.run(context)
            await self.set_speaker_step.run(context)

            mic_to_stt = Step8MicStreamToInternalStreamToSTTStream(
                context.require_microphone_output().audio_stream,
                context.require_stt_stream_in_pipe(),
            )
            await mic_to_stt.run(context)

            stt_to_tts = Step9STTStreamToInternalStreamToTTSStream(
                context.require_stt_output().text_stream,
                context.require_tts_stream_in_pipe(),
            )
            await stt_to_tts.run(context)

            tts_to_speaker = Step10TTSStreamToInternalStreamToSpeakerStream(
                context.require_tts_output().audio_stream,
                context.require_speaker_stream_in_pipe(),
                completed_outputs_to_read=request.max_text_segments if request.max_text_segments > 0 else None,
            )
            await tts_to_speaker.run(context)
            console_log("flow4-attach", "all pipeline streams active - running until cancelled")
            await context.require_tts_input_task()
            if context.tts_to_speaker_task is not None:
                await context.tts_to_speaker_task
            speaker_response = await context.require_speaker_task()
            verify_speaker_response(speaker_response)
            text_segments = context.require_counted_text_stream().count
            if text_segments == 0:
                console_log("flow4-attach", "voice pipeline completed without detected speech")
                return VoicePipelineServiceResponseDto(
                    success=False,
                    message="No speech was detected before the STT stream completed.",
                    text_segments_forwarded=0,
                )
            console_log(
                "flow4-attach",
                "voice pipeline completed",
                text_segments=text_segments,
                success=speaker_response.success,
            )
            return VoicePipelineServiceResponseDto(
                success=speaker_response.success,
                message=speaker_response.message,
                text_segments_forwarded=text_segments,
            )
        except asyncio.CancelledError:
            console_log("flow4-attach", "voice pipeline cancelled")
            raise
        except Exception as exc:
            console_log(
                "flow4-attach",
                "voice pipeline failed during setup",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await _stop_microphone_safely(self.microphone_port, "pipeline setup error")
            raise
        finally:
            await context.cancel_pending_tasks()


async def _stop_microphone_safely(microphone_port: MicrophonePort, reason: str) -> None:
    try:
        console_log("brain-service", "stopping microphone via API", reason=reason)
        await microphone_port.stop_stream()
    except Exception as exc:
        console_log("brain-service", "microphone stop failed", reason=reason, error=str(exc))
