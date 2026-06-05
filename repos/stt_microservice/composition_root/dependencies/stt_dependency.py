import os
from dataclasses import dataclass

from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.ports.service_port import ServicePort
from application.ports.adapter_inbound_port import AdapterInboundPort

from application.dtos.adapter_outbound_dtos import InitOutboundAdapterDto
from application.dtos.adapter_inbound_dtos import InitInboundAdapterDto

from infrastructure.outbound.openai_stt_adapter import OpenAISTTAdapter
from infrastructure.outbound.local_stt_adapter import LocalSTTAdapter

from application.services.service import STTService
from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter
from fastapi import FastAPI
from contextlib import asynccontextmanager
from runtime.environment import apply_launch_environment
from runtime.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class STTDependency:
    adapter_outbound: AdapterOutboundPort
    service: ServicePort
    adapter_inbound: AdapterInboundPort


def generate_stt_dependency() -> STTDependency:
    runtime_environment = apply_launch_environment()
    logger.info(
        "Runtime environment loaded for dependency graph: environment=%s source=%s launch_profile=%s env_file=%s.",
        runtime_environment.name,
        runtime_environment.source,
        runtime_environment.launch_profile,
        runtime_environment.env_file,
    )

    # Read environment to determine which engine to use
    engine = os.getenv("STT_ENGINE", "openai").lower()
    language = os.getenv("STT_LANGUAGE", "en").strip() or "en"
    logger.info(
        "Generating STT dependency graph with engine '%s' and language '%s'.",
        engine,
        language,
    )
    
    if engine == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY is missing while STT_ENGINE is 'openai'.")
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI STT engine")
        config = InitOutboundAdapterDto(
            api_key=api_key,
            model_name="whisper-1",
            language=language,
        )
        logger.info("Creating OpenAI STT outbound adapter.")
        adapter_outbound = OpenAISTTAdapter(config)
    else:
        config = InitOutboundAdapterDto(model_name="small.en", language=language)
        logger.info(
            "Creating local STT outbound adapter with model '%s' and language '%s'.",
            config.model_name,
            config.language,
        )
        adapter_outbound = LocalSTTAdapter(config)

    # Wire up the service and inbound adapter
    logger.info("Creating STT service.")
    service = STTService(name="stt_service", outbound_port=adapter_outbound)
    
    adapter_inbound = None

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        logger.info("FastAPI lifespan startup started.")
        if adapter_inbound:
            logger.info("Starting inbound adapter autoload task if configured.")
            adapter_inbound.start_autoload()
        yield
        logger.info("FastAPI lifespan shutdown started.")
        if adapter_inbound:
            logger.info("Stopping inbound adapter autoload task if configured.")
            await adapter_inbound.stop_autoload()

    logger.info("Creating FastAPI application.")
    app = FastAPI(
        title="STT Microservice",
        description="Speech-to-Text inference service",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=app_lifespan,
    )
    
    autoload_url = os.getenv("AUTOLOAD_VOICE_STREAM_URL")
    if autoload_url:
        logger.info("Autoload voice stream configured: %s.", autoload_url)
    else:
        logger.info("Autoload voice stream is not configured.")

    inbound_config = InitInboundAdapterDto(
        autoload_voice_stream_url=autoload_url
    )
    
    logger.info("Creating FastAPI inbound adapter.")
    adapter_inbound = FastApiAdapter(service_port=service, app=app, config=inbound_config)
    logger.info("STT dependency graph generation completed.")

    return STTDependency(
        adapter_outbound=adapter_outbound,
        service=service,
        adapter_inbound=adapter_inbound,
    )
