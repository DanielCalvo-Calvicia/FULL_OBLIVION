from dataclasses import dataclass

from fastapi import FastAPI

from application.services.service import BrainService
from composition_root.config import AppConfig
from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter
from infrastructure.outbound.http.base import HttpServiceConfig
from infrastructure.outbound.http.microphone.microphone_adapter import HttpMicrophoneAdapter
from infrastructure.outbound.http.speaker.speaker_adapter import HttpSpeakerAdapter
from infrastructure.outbound.http.stt.stt_adapter import HttpSTTAdapter
from infrastructure.outbound.http.tts.tts_adapter import HttpTTSAdapter


@dataclass(frozen=True, slots=True)
class BrainCoreDependency:
    service: BrainService
    microphone_adapter: HttpMicrophoneAdapter
    stt_adapter: HttpSTTAdapter
    tts_adapter: HttpTTSAdapter
    speaker_adapter: HttpSpeakerAdapter


@dataclass(frozen=True, slots=True)
class BrainDependency:
    adapter_inbound: FastApiAdapter
    service: BrainService
    microphone_adapter: HttpMicrophoneAdapter
    stt_adapter: HttpSTTAdapter
    tts_adapter: HttpTTSAdapter
    speaker_adapter: HttpSpeakerAdapter


def generate_brain_core_dependency(config: AppConfig) -> BrainCoreDependency:
    microphone_adapter = HttpMicrophoneAdapter(
        _http_config("microphone", config.microphone_base_url, config),
        stream_endpoint=config.microphone_stream_endpoint,
        start_endpoint=config.microphone_start_endpoint,
        stop_endpoint=config.microphone_stop_endpoint,
    )
    stt_adapter = HttpSTTAdapter(
        _http_config("stt", config.stt_base_url, config),
        set_stream_endpoint=config.stt_set_stream_endpoint,
        get_stream_endpoint=config.stt_get_stream_endpoint,
        batch_endpoint=config.stt_batch_endpoint,
    )
    tts_adapter = HttpTTSAdapter(
        _http_config("tts", config.tts_base_url, config),
        set_stream_endpoint=config.tts_set_stream_endpoint,
        get_stream_endpoint=config.tts_get_stream_endpoint,
    )
    speaker_adapter = HttpSpeakerAdapter(
        _http_config("speaker", config.speaker_base_url, config),
        play_stream_endpoint=config.speaker_play_stream_endpoint,
    )
    service = BrainService(
        microphone_port=microphone_adapter,
        stt_port=stt_adapter,
        tts_port=tts_adapter,
        speaker_port=speaker_adapter,
    )
    return BrainCoreDependency(
        service=service,
        microphone_adapter=microphone_adapter,
        stt_adapter=stt_adapter,
        tts_adapter=tts_adapter,
        speaker_adapter=speaker_adapter,
    )


def generate_brain_dependency_from_core(core: BrainCoreDependency) -> BrainDependency:
    app = FastAPI(
        title="Brain Microservice",
        description="Master orchestrator for microphone, STT, TTS, and speaker microservices.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    adapter_inbound = FastApiAdapter(service=core.service, app=app)
    return BrainDependency(
        adapter_inbound=adapter_inbound,
        service=core.service,
        microphone_adapter=core.microphone_adapter,
        stt_adapter=core.stt_adapter,
        tts_adapter=core.tts_adapter,
        speaker_adapter=core.speaker_adapter,
    )


def generate_brain_dependency(config: AppConfig) -> BrainDependency:
    return generate_brain_dependency_from_core(generate_brain_core_dependency(config))


def _http_config(name: str, base_url: str, config: AppConfig) -> HttpServiceConfig:
    return HttpServiceConfig(
        service_name=name,
        base_url=base_url,
        timeout_seconds=config.provider_timeout_seconds,
        api_key=config.provider_api_key,
    )
