import asyncio
import time

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from application.dtos.inbound_dtos import (
    BatchTranscriptionRequestDto,
    MicrophoneTranscriptionRequestDto,
    TextToSpeechPlaybackRequestDto,
    VoicePipelineRequestDto,
)
from application.dtos.mapper.inbound_to_service import (
    map_batch_transcription_request,
    map_microphone_transcription_request,
    map_text_to_speech_request,
    map_voice_pipeline_request,
)
from application.ports.service_port import BrainServicePort
from domain.console import console_log
from domain.errors import BrainMicroserviceError


class FastApiAdapter:
    def __init__(self, service: BrainServicePort, app: FastAPI) -> None:
        self._service = service
        self.app = app
        console_log("fastapi-adapter", "initializing inbound HTTP adapter")
        self.register_routes(app)

    @property
    def get_app(self) -> FastAPI:
        return self.app

    def register_routes(self, app: FastAPI) -> None:
        console_log("fastapi-adapter", "registering HTTP routes")

        @app.get("/health", tags=["Health"])
        async def health_check() -> JSONResponse:
            console_log("fastapi-adapter", "received health request")
            return self._ok("health_check", "Brain microservice is healthy", None)

        @app.get("/integrations/health", tags=["Health"])
        async def integrations_health() -> JSONResponse:
            console_log("fastapi-adapter", "received integrations health request")
            response = await self._service.check_integrations()
            data = [
                {"name": status.name, "is_available": status.is_available, "detail": status.detail}
                for status in response.services
            ]
            all_available = all(item["is_available"] for item in data)
            return self._ok(
                "integrations_health",
                "External integrations checked",
                {"all_available": all_available, "services": data},
            )

        @app.post("/stt/batch", tags=["Speech To Text"])
        async def transcribe_batch(request: Request, sample_rate: int = Query(16000)) -> JSONResponse:
            try:
                body = await request.body()
                console_log(
                    "fastapi-adapter",
                    "received STT batch request",
                    bytes=len(body),
                    sample_rate=sample_rate,
                )
                service_request = map_batch_transcription_request(
                    BatchTranscriptionRequestDto(audio_data=body, sample_rate=sample_rate)
                )
                response = await self._service.transcribe_batch(service_request)
                console_log("fastapi-adapter", "STT batch request completed", text_chars=len(response.text))
                return self._ok("stt_batch", "Audio transcribed", {"text": response.text})
            except BrainMicroserviceError as exc:
                console_log("fastapi-adapter", "STT batch request failed", error=str(exc))
                return self._error("stt_batch", str(exc), 502)
            except Exception as exc:
                console_log("fastapi-adapter", "STT batch request failed", error=str(exc))
                return self._error("stt_batch", str(exc), 500)

        @app.post("/tts/play", tags=["Text To Speech"])
        async def play_text(
            request: Request,
            sample_rate: int = Query(24000),
            channels: int = Query(1),
        ) -> JSONResponse:
            try:
                text = (await request.body()).decode("utf-8")
                console_log(
                    "fastapi-adapter",
                    "received TTS playback request",
                    text_chars=len(text),
                    sample_rate=sample_rate,
                    channels=channels,
                )
                service_request = map_text_to_speech_request(
                    TextToSpeechPlaybackRequestDto(
                        text=text,
                        sample_rate=sample_rate,
                        channels=channels,
                    )
                )
                response = await self._service.play_text(service_request)
                console_log("fastapi-adapter", "TTS playback request completed", success=response.success)
                return self._ok(
                    "tts_play",
                    response.message or "Text synthesized and played",
                    {"success": response.success},
                )
            except BrainMicroserviceError as exc:
                console_log("fastapi-adapter", "TTS playback request failed", error=str(exc))
                return self._error("tts_play", str(exc), 502)
            except Exception as exc:
                console_log("fastapi-adapter", "TTS playback request failed", error=str(exc))
                return self._error("tts_play", str(exc), 500)

        @app.post("/voice/transcribe", tags=["Voice"])
        async def transcribe_microphone(
            sample_rate: int = Query(16000),
            chunk_size: int = Query(1024),
            silence_threshold: int = Query(150),
            silence_limit_seconds: float = Query(2.0),
            max_segments: int = Query(1),
        ) -> JSONResponse:
            try:
                console_log(
                    "fastapi-adapter",
                    "received voice transcription request",
                    sample_rate=sample_rate,
                    chunk_size=chunk_size,
                    max_segments=max_segments,
                )
                service_request = map_microphone_transcription_request(
                    MicrophoneTranscriptionRequestDto(
                        sample_rate=sample_rate,
                        chunk_size=chunk_size,
                        silence_threshold=silence_threshold,
                        silence_limit_seconds=silence_limit_seconds,
                        max_segments=max_segments,
                    )
                )
                response = await self._service.transcribe_microphone(service_request)
                console_log("fastapi-adapter", "voice transcription request completed", segments=len(response.segments))
                return self._ok("voice_transcribe", "Microphone audio transcribed", {"segments": response.segments})
            except BrainMicroserviceError as exc:
                console_log("fastapi-adapter", "voice transcription request failed", error=str(exc))
                return self._error("voice_transcribe", str(exc), 502)
            except Exception as exc:
                console_log("fastapi-adapter", "voice transcription request failed", error=str(exc))
                return self._error("voice_transcribe", str(exc), 500)

        @app.post("/voice/pipeline", tags=["Voice"])
        async def run_voice_pipeline(
            microphone_sample_rate: int = Query(16000),
            microphone_chunk_size: int = Query(1024),
            stt_silence_threshold: int = Query(150),
            stt_silence_limit_seconds: float = Query(2.0),
            max_text_segments: int = Query(0),
            tts_sample_rate: int = Query(24000),
            speaker_channels: int = Query(1),
        ) -> JSONResponse:
            try:
                console_log(
                    "fastapi-adapter",
                    "received voice pipeline request - starting as background task",
                    microphone_sample_rate=microphone_sample_rate,
                    tts_sample_rate=tts_sample_rate,
                    speaker_channels=speaker_channels,
                )
                service_request = map_voice_pipeline_request(
                    VoicePipelineRequestDto(
                        microphone_sample_rate=microphone_sample_rate,
                        microphone_chunk_size=microphone_chunk_size,
                        stt_silence_threshold=stt_silence_threshold,
                        stt_silence_limit_seconds=stt_silence_limit_seconds,
                        max_text_segments=max_text_segments,
                        tts_sample_rate=tts_sample_rate,
                        speaker_channels=speaker_channels,
                    )
                )
                asyncio.create_task(self._service.run_voice_pipeline(service_request))
                return self._ok("voice_pipeline", "Voice pipeline started", {"started": True})
            except Exception as exc:
                console_log("fastapi-adapter", "voice pipeline request failed", error=str(exc))
                return self._error("voice_pipeline", str(exc), 500)

    def _ok(self, action: str, message: str, data) -> JSONResponse:
        console_log("fastapi-adapter", "sending success response", action=action)
        return JSONResponse(
            status_code=200,
            content={
                "action": action,
                "status": "success",
                "status_code": 200,
                "message": message,
                "timestamp": time.time(),
                "data": data,
            },
        )

    def _error(self, action: str, message: str, status_code: int) -> JSONResponse:
        console_log("fastapi-adapter", "sending error response", action=action, status_code=status_code, error=message)
        return JSONResponse(
            status_code=status_code,
            content={
                "action": action,
                "status": "error",
                "status_code": status_code,
                "message": message,
                "timestamp": time.time(),
                "data": None,
            },
        )
