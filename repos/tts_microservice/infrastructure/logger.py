import logging
import sys
from datetime import datetime, timezone

from infrastructure.config import resolve_environment

TRACE_LEVEL = 5
ENVIRONMENT_LOG_LEVELS = {
    "development": TRACE_LEVEL,
    "staging": logging.WARNING,
    "production": logging.CRITICAL,
}
ALWAYS_VISIBLE_LOGGERS = (
    "fastapi",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
)


class _EnvironmentFormatter(logging.Formatter):
    def __init__(self, environment: str):
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(
            record.created,
            tz=timezone.utc,
        ).isoformat(timespec="milliseconds")

        if record.levelno == TRACE_LEVEL:
            level_name = "TRACE"
        elif record.levelno == logging.WARNING:
            level_name = "WARN"
        else:
            level_name = record.levelname

        message = (
            f"{timestamp} | {self.environment} | {level_name} | "
            f"{record.name} | {record.getMessage()}"
        )
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"
        return message


class Logger:
    _configured_environment: str | None = None

    @classmethod
    def configure(cls, environment: str | None = None) -> str:
        resolved_environment = environment or resolve_environment()
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(
            ENVIRONMENT_LOG_LEVELS.get(
                resolved_environment,
                ENVIRONMENT_LOG_LEVELS["development"],
            )
        )

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_EnvironmentFormatter(resolved_environment))
        root_logger.addHandler(handler)

        for logger_name in ALWAYS_VISIBLE_LOGGERS:
            visible_logger = logging.getLogger(logger_name)
            visible_logger.setLevel(logging.INFO)
            visible_logger.propagate = True

        cls._configured_environment = resolved_environment
        return resolved_environment

    @staticmethod
    def get(scope: str) -> logging.Logger:
        return logging.getLogger(scope)


def _trace(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)


logging.addLevelName(TRACE_LEVEL, "TRACE")
setattr(logging.Logger, "trace", _trace)


def configure_logging(environment: str | None = None) -> str:
    return Logger.configure(environment)


def get_logger(scope: str) -> logging.Logger:
    return Logger.get(scope)
