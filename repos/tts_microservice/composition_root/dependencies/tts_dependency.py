import os
from dataclasses import dataclass

from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.ports.service_port import ServicePort
from application.ports.adapter_inbound_port import AdapterInboundPort

from application.dtos.adapter_inbound_dtos import InitInboundAdapterDto
from application.dtos.services_dtos import InitServiceDto

from infrastructure.outbound.tts.pyttsx3_adapter import PyTTSx3Adapter
from infrastructure.outbound.tts.openai_tts_adapter import OpenAITTSAdapter
from application.services.service import TTSService
from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter

from fastapi import FastAPI
from contextlib import asynccontextmanager
from infrastructure.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class TTSDependency:
    adapter_outbound: AdapterOutboundPort
    service: ServicePort
    adapter_inbound: AdapterInboundPort


def generate_tts_dependency() -> TTSDependency:
    logger.info("Generating TTS dependency graph")

    # Build outbound adapter config
    tts_adapter = os.getenv("TTS_ADAPTER", "pyttsx3").strip().lower()
    speech_rate = int(os.getenv("TTS_SPEECH_RATE", "140"))
    voice_name = os.getenv("TTS_VOICE_NAME", "Zira")
    openai_speed = os.getenv("OPENAI_TTS_SPEED")
    logger.info(
        "Resolved outbound TTS config adapter=%s speech_rate=%s voice_name_preference=%s",
        tts_adapter,
        speech_rate,
        voice_name,
    )

    service_config = InitServiceDto(
        speech_rate=speech_rate,
        voice_name_preference=voice_name,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        openai_voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
        openai_response_format=os.getenv("OPENAI_TTS_RESPONSE_FORMAT", "wav"),
        openai_instructions=os.getenv("OPENAI_TTS_INSTRUCTIONS"),
        openai_speed=float(openai_speed) if openai_speed else None,
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )

    if tts_adapter == "openai":
        logger.info("Creating OpenAITTSAdapter")
        adapter_outbound = OpenAITTSAdapter()
    elif tts_adapter == "pyttsx3":
        logger.info("Creating PyTTSx3Adapter")
        adapter_outbound = PyTTSx3Adapter()
    else:
        raise ValueError("TTS_ADAPTER must be either 'pyttsx3' or 'openai'.")

    # Wire the core domain service
    logger.info("Creating TTSService")
    service = TTSService(name="tts_service", outbound_port=adapter_outbound)

    adapter_inbound: AdapterInboundPort | None = None

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        logger.info("FastAPI lifespan startup started")
        logger.info("Initializing TTSService")
        await service.init(service_config)
        if adapter_inbound is not None:
            logger.info("Starting inbound adapter autoload")
            adapter_inbound.start_autoload()
        yield
        logger.info("FastAPI lifespan shutdown started")
        if adapter_inbound is not None:
            logger.info("Stopping inbound adapter autoload")
            await adapter_inbound.stop_autoload()
        logger.info("FastAPI lifespan shutdown finished")

    logger.info("Creating FastAPI application")
    app = FastAPI(
        title="TTS Microservice",
        description="Text-to-Speech synthesis service",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=app_lifespan,
    )
    
    inbound_config = InitInboundAdapterDto()
    logger.info("Creating FastApiAdapter and registering routes")
    adapter_inbound = FastApiAdapter(service_port=service, app=app, config=inbound_config)

    dependency = TTSDependency(
        adapter_outbound=adapter_outbound,
        service=service,
        adapter_inbound=adapter_inbound,
    )
    logger.info("TTS dependency graph generated")
    return dependency
