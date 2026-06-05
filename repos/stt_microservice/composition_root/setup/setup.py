import asyncio
import os
import uvicorn

from composition_root.containers.container import BuildContainer, Container
from runtime.environment import apply_launch_environment
from runtime.logger import get_logger

logger = get_logger(__name__)


async def _cleanup(container: Container):
    logger.info("Performing graceful shutdown cleanup for container '%s'.", container.name)
    # Add any cleanup tasks here if needed


async def setup():
    logger.info("Starting setup sequence.")
    runtime_environment = apply_launch_environment()
    logger.info(
        "Runtime environment loaded: environment=%s source=%s launch_profile=%s env_file=%s.",
        runtime_environment.name,
        runtime_environment.source,
        runtime_environment.launch_profile,
        runtime_environment.env_file,
    )

    host = os.getenv("SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("SERVICE_PORT", "8001"))
    logger.info("Resolved service bind address: %s:%s.", host, port)

    # Build dependency graph
    logger.info("Building dependency graph.")
    container = BuildContainer(name="STT Microservice")
    logger.info("Dependency graph built for container '%s'.", container.name)
    
    # Retrieve FastAPI app
    app = container.stt_dependency.adapter_inbound.get_app
    logger.info("FastAPI app retrieved from inbound adapter.")

    # Create server
    config = uvicorn.Config(
        app, 
        host=host, 
        port=port, 
        log_level="info",
        timeout_keep_alive=60,
    )
    server = uvicorn.Server(config)
    logger.info("Uvicorn server configured with keep-alive timeout of 60 seconds.")

    logger.info("STT Microservice server starting on %s:%s.", host, port)
    logger.info("Application started. Waiting for shutdown signal (Ctrl+C).")

    try:
        # Run the server (this blocks until stopped)
        logger.info("Starting Uvicorn server.")
        await server.serve()
    finally:
        # Clean up resources
        logger.info("Server stopped. Running cleanup.")
        await _cleanup(container)
