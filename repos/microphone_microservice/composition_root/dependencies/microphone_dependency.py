from dataclasses import dataclass

from fastapi import FastAPI

from application.ports.adapter_inbound_port import AdapterInboundPort
from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.ports.service_port import ServicePort

from application.services.service import MicrophoneService

from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter
from infrastructure.outbound.windows_sounddevice import MicrophoneAdapter
from composition_root.runtime.logger import get_logger

from application.dtos.adapter_outbound_dtos import (
    InitOutboundAdapterDto,
)


logger = get_logger("dependency")

@dataclass(slots=True, frozen=True)
class MicrophoneDependency:
    adapter_inbound: AdapterInboundPort
    adapter_outbound: AdapterOutboundPort
    service: ServicePort

def generate_microphone_dependency(
    default_fallback_rate: int = 16000,
    target_keywords: list[str] | None = None,
    name: str = "Microphone"
) -> MicrophoneDependency:
    selected_keywords = [] if target_keywords is None else target_keywords
    logger.info(
        "Generating microphone dependency",
        name=name,
        default_fallback_rate=default_fallback_rate,
        target_keywords=selected_keywords,
    )
    init_outbound_adapter_dto = InitOutboundAdapterDto(
        default_fallback_rate=default_fallback_rate,
        target_keywords=selected_keywords
    )
    logger.info("Creating outbound MicrophoneAdapter")
    adapter_outbound: AdapterOutboundPort = MicrophoneAdapter(init_outbound_adapter_dto)
    
    logger.info("Creating MicrophoneService")
    service: ServicePort = MicrophoneService(
        name=name, 
        controller_port=adapter_outbound
    )
    
    logger.info("Creating FastAPI app")
    app = FastAPI(
        title=name,
        description=f"Adapter exposing {name} via FastAPI",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    logger.info("Creating inbound FastApiAdapter and registering routes")
    adapter_inbound: AdapterInboundPort = FastApiAdapter(
        service_port=service,
        app=app
    )

    logger.info("Microphone dependency graph ready")
    return MicrophoneDependency(        
        adapter_inbound=adapter_inbound,
        adapter_outbound=adapter_outbound,
        service=service
    )
