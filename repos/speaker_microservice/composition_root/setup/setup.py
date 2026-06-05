import asyncio
import os
import uvicorn
from dotenv import load_dotenv, find_dotenv

from composition_root.containers.container import BuildContainer, Container
from runtime.environment import resolve_runtime_environment
from runtime.logger import get_logger

logger = get_logger("setup")

async def _cleanup(container: Container):
    logger.info("Performing final setup-layer cleanup for container: %s", container)
    # Cleanups are registered in FastAPI lifespan, but can be added here if needed

async def setup():
    runtime_environment = resolve_runtime_environment()
    logger.info(
        "Resolved runtime environment: environment=%s source=%s.",
        runtime_environment.name,
        runtime_environment.source,
    )

    # Load environment variables
    dotenv_path = find_dotenv('.env')
    if dotenv_path:
        load_dotenv(dotenv_path)
        logger.info("Loaded environment variables from %s", dotenv_path)
    else:
        logger.info("No .env file found. Falling back to process environment and defaults.")

    host = os.getenv("SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("SERVICE_PORT", "8003"))
    logger.info("Resolved service bind configuration: host=%s port=%s", host, port)

    # Build dependency graph
    logger.info("Building dependency container.")
    container = BuildContainer(name="Speaker Microservice")
    logger.info("Dependency container built successfully.")
    
    # Retrieve FastAPI app
    app = container.speaker_dependency.adapter_inbound.app
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

    logger.info("Speaker Microservice - Starting Server (sounddevice)")
    logger.info("Application startup complete. Waiting for shutdown signal.")

    try:
        # Run the server (this blocks until stopped)
        logger.info("Starting Uvicorn server.")
        await server.serve()
    finally:
        # Clean up resources
        logger.info("Uvicorn server stopped. Entering setup cleanup.")
        await _cleanup(container)
