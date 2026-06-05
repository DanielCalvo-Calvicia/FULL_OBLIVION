from datetime import datetime, timezone
import sys
from typing import Any

from composition_root.runtime.environment import resolve_runtime_config


LEVELS = {
    "trace": 10,
    "info": 20,
    "warn": 30,
    "error": 40,
    "critical": 50,
}

ENVIRONMENT_MIN_LEVEL = {
    "development": "trace",
    "staging": "warn",
    "production": "critical",
}


class Logger:
    def __init__(self, scope: str):
        self.scope = scope
        self.runtime_config = resolve_runtime_config()

    def trace(self, message: str, **context: Any) -> None:
        self._log("trace", message, context)

    def info(self, message: str, **context: Any) -> None:
        self._log("info", message, context)

    def warn(self, message: str, **context: Any) -> None:
        self._log("warn", message, context)

    def error(self, message: str, **context: Any) -> None:
        self._log("error", message, context)

    def critical(self, message: str, **context: Any) -> None:
        self._log("critical", message, context)

    def _log(self, level: str, message: str, context: dict[str, Any]) -> None:
        if not self._should_log(level):
            return

        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        environment = self.runtime_config.environment
        context_text = _format_context(context)
        line = f"{timestamp} [{environment}] {level.upper()} {self.scope} - {message}{context_text}"
        stream = sys.stderr if level in {"error", "critical"} else sys.stdout
        print(line, file=stream)

    def _should_log(self, level: str) -> bool:
        environment = self.runtime_config.environment
        min_level = ENVIRONMENT_MIN_LEVEL.get(environment, "trace")
        return LEVELS[level] >= LEVELS[min_level]


def get_logger(scope: str) -> Logger:
    return Logger(scope)


def _format_context(context: dict[str, Any]) -> str:
    if not context:
        return ""
    parts = [f"{key}={value!r}" for key, value in context.items()]
    return " " + " ".join(parts)
