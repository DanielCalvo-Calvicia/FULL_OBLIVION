import asyncio
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE any project code that reads os.getenv().
# VS Code debugpy with integratedTerminal does not always inject envFile
# variables, so this explicit call guarantees the file is loaded.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from composition_root.setup.setup import setup
from runtime.environment import apply_launch_environment
from runtime.logger import configure_application_logging, get_logger

runtime_environment = apply_launch_environment()
configure_application_logging(runtime_environment.name)
logger = get_logger(__name__)


if __name__ == "__main__":
    try:
        logger.info(
            "Starting STT microservice entry point: environment=%s source=%s launch_profile=%s env_file=%s.",
            runtime_environment.name,
            runtime_environment.source,
            runtime_environment.launch_profile,
            runtime_environment.env_file,
        )
        asyncio.run(setup())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting.")
