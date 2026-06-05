import asyncio

from application.dtos.service_dtos import VoicePipelineServiceRequestDto
from application.services.service import BrainService
from domain.console import console_log


def start_startup_pipeline(service: BrainService) -> asyncio.Task:
    console_log("startup-pipeline", "starting voice pipeline - streams will stay active until shutdown")
    return asyncio.create_task(_run_startup_pipeline(service))


async def _run_startup_pipeline(service: BrainService) -> None:
    try:
        await service.run_voice_pipeline(VoicePipelineServiceRequestDto())
    except asyncio.CancelledError:
        console_log("startup-pipeline", "voice pipeline cancelled by shutdown")
        raise
    except Exception as exc:
        console_log(
            "startup-pipeline",
            "voice pipeline failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
