import uvicorn

from composition_root.containers.container import BuildContainer
from composition_root.runtime.environment import resolve_runtime_config
from composition_root.runtime.logger import get_logger
from infrastructure.outbound.windows_sounddevice import MicrophoneAdapter
from application.dtos.adapter_outbound_dtos import StopMicrophoneStreamRequestDto

NAME: str = "Microphone Microservice"
logger = get_logger("setup")

async def setup() -> None:    
    runtime_config = resolve_runtime_config()

    logger.info(
        f"{NAME} - Starting Server",
        environment=runtime_config.environment,
        source=runtime_config.source,
        launch_profile=runtime_config.launch_profile,
    )

    logger.info("Building application container")
    container = BuildContainer(name=NAME)
    
    # We retrieve the FastAPI app instance from the inbound adapter
    logger.info("Retrieving FastAPI app from inbound adapter")
    app = container.microphone_dependency.adapter_inbound.get_app
    
    logger.info("Server bind configured", host="0.0.0.0", port=8000)

    # We configure and create a uvicorn Server instance
    logger.info("Creating Uvicorn config and server")
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)

    logger.info("Application started. Waiting for shutdown signal (Ctrl+C)...")
    
    # Uvicorn's serve() method is an asynchronous blocking call that automatically 
    # listens for termination signals (like Ctrl+C) and shuts down gracefully.
    logger.info("Entering Uvicorn serve loop")
    await server.serve()
    
    # Once Uvicorn has finished shutting down, we execute our custom cleanup logic.
    logger.info("Uvicorn stopped; starting cleanup")
    await _cleanup(container)
    


async def _cleanup(container) -> None:
    logger.info("Inspecting outbound adapter state")
    adapter = container.microphone_dependency.adapter_outbound

    if isinstance(adapter, MicrophoneAdapter):
        logger.info("MicrophoneAdapter state inspected", started=adapter.started)
        if adapter.started:
            logger.warn("Stopping microphone stream before exit")
            await adapter.stop_stream(StopMicrophoneStreamRequestDto())

    logger.info("Cleanup finished")
