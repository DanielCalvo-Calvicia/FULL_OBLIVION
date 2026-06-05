import asyncio
import sys

from composition_root.setup.setup import setup
from runtime.logger import configure_logging, get_logger

runtime_environment = configure_logging()
logger = get_logger("main")

if __name__ == "__main__":
    try:
        logger.info(
            "Speaker microservice process entrypoint reached with environment=%s source=%s.",
            runtime_environment.name,
            runtime_environment.source,
        )
        asyncio.run(setup())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting speaker microservice.")
        sys.exit(0)
    except Exception:
        logger.exception("Unhandled exception reached process entrypoint.")
        raise
