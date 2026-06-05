import os
from dataclasses import dataclass
from fastapi import FastAPI
from contextlib import asynccontextmanager

from application.services.service import SpeakerService
from application.dtos.adapter_outbound_dtos import InitOutboundAdapterDto
from application.dtos.adapter_inbound_dtos import InitInboundAdapterDto
from infrastructure.outbound.speaker.sounddevice_adapter import SoundDeviceSpeakerAdapter
from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter
from runtime.logger import get_logger

logger = get_logger("composition_root")

@dataclass(slots=True, frozen=True)
class SpeakerDependency:
    adapter_outbound: SoundDeviceSpeakerAdapter
    service: SpeakerService
    adapter_inbound: FastApiAdapter

def generate_speaker_dependency() -> SpeakerDependency:
    logger.info("Generating speaker dependency graph.")

    # 1. Parse and compile Outbound configurations
    pref_device = os.getenv("SPEAKER_DEVICE_INDEX")
    device_index = int(pref_device) if (pref_device is not None and pref_device.strip() != "") else None
    logger.info("Resolved speaker device index: %s", device_index if device_index is not None else "auto")
    
    keywords_raw = os.getenv("SPEAKER_DEVICE_KEYWORDS", "i2s,hw,default,sysdefault")
    keywords = tuple(kw.strip() for kw in keywords_raw.split(",") if kw.strip())
    logger.info("Resolved speaker device selection keywords: %s", keywords)

    outbound_config = InitOutboundAdapterDto(
        device_index=device_index,
        target_keywords=keywords
    )
    
    # Instantiate outbound adapter
    logger.info("Instantiating outbound sounddevice adapter.")
    adapter_outbound = SoundDeviceSpeakerAdapter(config=outbound_config)
    logger.info("Outbound sounddevice adapter ready.")

    # 2. Build core domain service
    logger.info("Instantiating speaker application service.")
    service = SpeakerService(outbound_port=adapter_outbound)
    logger.info("Speaker application service ready.")

    # 3. Handle FastAPI App configuration and Lifespan
    adapter_inbound = None

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        logger.info("FastAPI service lifecycle bootstrap sequence initiated.")
        if adapter_inbound:
            logger.info("Starting inbound adapter autoload hook if configured.")
            adapter_inbound.start_autoload()
        yield
        logger.info("FastAPI service lifecycle shutdown sequence initiated. Running cleanups.")
        if adapter_inbound:
            logger.info("Stopping inbound adapter autoload hook if configured.")
            await adapter_inbound.stop_autoload()
        logger.info("Stopping and cleaning speaker service.")
        await service.stop_and_cleanup()
        logger.info("FastAPI service lifecycle shutdown cleanup finished.")

    logger.info("Creating FastAPI application instance.")
    app = FastAPI(
        title="Speaker Microservice",
        description="Low-latency raw audio speaker playback microservice",
        version="1.0.0",
        lifespan=app_lifespan
    )

    # 4. Instantiate inbound network adapter
    origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
    origins = tuple(o.strip() for o in origins_raw.split(",") if o.strip())
    logger.info("Resolved inbound allowed origins config: %s", origins)
    
    autoload_url = os.getenv("AUTOLOAD_STREAM_URL")
    logger.info("Resolved autoload stream URL: %s", autoload_url if autoload_url else "disabled")
    inbound_config = InitInboundAdapterDto(allow_origins=origins, autoload_stream_url=autoload_url)
    logger.info("Instantiating inbound FastAPI adapter.")
    adapter_inbound = FastApiAdapter(service_port=service, app=app, config=inbound_config)
    logger.info("Inbound FastAPI adapter ready.")

    logger.info("Speaker dependency graph generated successfully.")
    return SpeakerDependency(
        adapter_outbound=adapter_outbound,
        service=service,
        adapter_inbound=adapter_inbound
    )
