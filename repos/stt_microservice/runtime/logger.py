import logging
import sys
from dataclasses import dataclass

from runtime.environment import DEFAULT_ENVIRONMENT, SUPPORTED_ENVIRONMENTS


TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")
logging.addLevelName(logging.WARNING, "WARN")

_LOG_LEVELS_BY_ENVIRONMENT = {
    "development": TRACE_LEVEL,
    "staging": logging.WARNING,
    "production": logging.CRITICAL,
}


class _EnvironmentFilter(logging.Filter):
    def __init__(self, environment: str):
        super().__init__()
        self.environment = environment
        self.minimum_level = _LOG_LEVELS_BY_ENVIRONMENT[environment]

    def filter(self, record: logging.LogRecord) -> bool:
        record.environment = self.environment
        return record.levelno >= self.minimum_level


@dataclass(slots=True)
class Logger:
    _logger: logging.Logger

    def trace(self, message: str, *args, **kwargs) -> None:
        self._logger.log(TRACE_LEVEL, message, *args, **kwargs)

    def debug(self, message: str, *args, **kwargs) -> None:
        self.trace(message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs) -> None:
        self._logger.info(message, *args, **kwargs)

    def warn(self, message: str, *args, **kwargs) -> None:
        self._logger.warning(message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs) -> None:
        self._logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs) -> None:
        self._logger.error(message, *args, **kwargs)

    def exception(self, message: str, *args, **kwargs) -> None:
        self._logger.exception(message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs) -> None:
        self._logger.critical(message, *args, **kwargs)


def configure_application_logging(environment: str) -> None:
    """Configure project loggers only; Uvicorn/FastAPI logging stays untouched."""
    normalized = environment if environment in SUPPORTED_ENVIRONMENTS else DEFAULT_ENVIRONMENT

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(environment)s %(levelname)s [%(name)s] %(message)s"
        )
    )
    handler.addFilter(_EnvironmentFilter(normalized))

    root_names = ("application", "composition_root", "infrastructure", "__main__")
    for name in root_names:
        project_logger = logging.getLogger(name)
        project_logger.handlers.clear()
        project_logger.addHandler(handler)
        project_logger.setLevel(TRACE_LEVEL)
        project_logger.propagate = False


def get_logger(name: str) -> Logger:
    return Logger(logging.getLogger(name))
