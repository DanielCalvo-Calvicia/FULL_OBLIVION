import asyncio
import os
import uvicorn
from dotenv import load_dotenv

from composition_root.containers.container import BuildContainer, Container
from infrastructure.config import get_runtime_env_file_path, resolve_environment
from infrastructure.logger import configure_logging, get_logger

logger = get_logger(__name__)


async def _cleanup(container: Container):
    logger.info("Performing graceful shutdown cleanup for container=%s", container.name)
    # Add any cleanup tasks here if needed


async def setup():
    environment = configure_logging(resolve_environment())
    logger.info("Setup started environment=%s", environment)

    # Load environment variables
    dotenv_path = get_runtime_env_file_path(environment)
    if dotenv_path:
        logger.info("Loading environment variables from %s", dotenv_path)
        load_dotenv(dotenv_path)
    else:
        logger.info("No .env file found; using process environment and defaults")

    host = os.getenv("SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("SERVICE_PORT", "8002"))
    logger.info("Runtime bind configuration resolved host=%s port=%s", host, port)

    # Build dependency graph
    logger.info("Building dependency container")
    container = BuildContainer(name="TTS Microservice")
    logger.info("Dependency container built")
    
    # Retrieve FastAPI app
    app = container.tts_dependency.adapter_inbound.get_app
    logger.info("FastAPI application resolved from inbound adapter")

    # Create server
    logger.info("Creating Uvicorn server")
    config = uvicorn.Config(
        app, 
        host=host, 
        port=port, 
        log_level="info",
        access_log=True,
        timeout_keep_alive=60,
    )
    server = uvicorn.Server(config)

    logger.info("TTS Microservice server starting on %s:%s", host, port)
    logger.info("Application started. Waiting for shutdown signal (Ctrl+C)...")

    try:
        # Run the server (this blocks until stopped)
        logger.info("Uvicorn server serve loop starting")
        await server.serve()
        logger.info("Uvicorn server serve loop finished")
    finally:
        # Clean up resources
        logger.info("Setup cleanup phase starting")
        await _cleanup(container)
        logger.info("Setup cleanup phase finished")
