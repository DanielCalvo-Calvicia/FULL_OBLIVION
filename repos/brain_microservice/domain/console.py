from datetime import datetime
from enum import IntEnum
from typing import Any


class LogLevel(IntEnum):
    trace = 10
    info = 20
    warn = 30
    error = 40
    critical = 50


_ENVIRONMENT = "development"
_MIN_LEVEL_BY_ENVIRONMENT = {
    "development": LogLevel.trace,
    "staging": LogLevel.warn,
    "production": LogLevel.critical,
}


class Logger:
    def __init__(self, scope: str) -> None:
        self._scope = scope

    def trace(self, message: str, **fields: Any) -> None:
        _write_log(self._scope, LogLevel.trace, message, **fields)

    def info(self, message: str, **fields: Any) -> None:
        _write_log(self._scope, LogLevel.info, message, **fields)

    def warn(self, message: str, **fields: Any) -> None:
        _write_log(self._scope, LogLevel.warn, message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        _write_log(self._scope, LogLevel.error, message, **fields)

    def critical(self, message: str, **fields: Any) -> None:
        _write_log(self._scope, LogLevel.critical, message, **fields)


def configure_logger(environment: str) -> None:
    global _ENVIRONMENT
    _ENVIRONMENT = environment


def get_logger(scope: str) -> Logger:
    return Logger(scope)


def console_log(
    component: str,
    message: str,
    level: str = "info",
    always: bool = False,
    blank_lines: int = 0,
    **fields: Any,
) -> None:
    logger = get_logger(component)
    log_method = getattr(logger, level, logger.info)
    if always:
        log_level = LogLevel[level] if level in LogLevel.__members__ else LogLevel.info
        _write_log(component, log_level, message, force=True, blank_lines=blank_lines, **fields)
        return
    log_method(message, blank_lines=blank_lines, **fields)


def _write_log(scope: str, level: LogLevel, message: str, force: bool = False, blank_lines: int = 0, **fields: Any) -> None:
    min_level = _MIN_LEVEL_BY_ENVIRONMENT.get(_ENVIRONMENT, LogLevel.trace)
    if not force and level < min_level:
        return

    timestamp = datetime.now().isoformat(timespec="seconds")
    suffix = ""
    if fields:
        rendered = " ".join(f"{key}={value}" for key, value in fields.items())
        suffix = f" | {rendered}"
    if blank_lines > 0:
        print("\n" * blank_lines, end="", flush=True)
    print(f"[{timestamp}] [{_ENVIRONMENT}] [{level.name}] [{scope}] {message}{suffix}", flush=True)
    if blank_lines > 0:
        print("\n" * blank_lines, end="", flush=True)
