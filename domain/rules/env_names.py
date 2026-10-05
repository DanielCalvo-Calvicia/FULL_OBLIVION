"""Which environment variable names are secrets, which a service knows, and which the tool computes itself."""

from __future__ import annotations

import re
from collections.abc import Callable
from fnmatch import fnmatchcase

from domain.entities.service_spec import ServiceSpec
from domain.rules.dotenv import parse_env

# TRACE_EXPORT_HEADERS is where a collector's Authorization header goes
_SECRET_NAME = re.compile(r"KEY(?!WORDS)|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|GITHUB_PAT|HEADERS", re.IGNORECASE)
# Tuning knobs whose defaults suit every deployment and that no service needs to see: accepted, never advertised.
TUNING_VARS = frozenset({
    "SERVICE_NAME", "VSCODE_ENV", "TRACE_EXPORT_TIMEOUT", "TRACE_EXPORT_BATCH_SIZE", "TRACE_EXPORT_FLUSH_INTERVAL",
    "TRACE_EXPORT_QUEUE_SIZE",
})
# Read by shared-logging in every service (see shared-logging/docs/logging.md), so never a "typo" in a settings file
SHARED_LOGGING_VARS = frozenset({
    "SERVICE_NAME", "LOG_LEVEL", "LOG_FORMAT", "LOG_OUTPUT", "APP_ENV", "ENVIRONMENT", "VSCODE_ENV",
    *(f"TRACE_EXPORT_{s}" for s in ("ENABLED", "URL", "TIMEOUT", "BATCH_SIZE", "FLUSH_INTERVAL", "QUEUE_SIZE", "HEADERS", "ATTRIBUTES")),
})


def is_secret(key: str) -> bool:
    return bool(_SECRET_NAME.search(key))


def mask(key: str, value: str) -> str:
    return "********" if is_secret(key) and value else value


def computed_variables(spec: ServiceSpec) -> set[str]:
    """Set by the tool from the layout: bind address, port, URLs of the consumed services."""
    return {spec.host_var, spec.port_var, *spec.consumes.values()}


def _matches(key: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(key, pattern) for pattern in patterns)


def known_variables(spec: ServiceSpec, example_text: str | None) -> tuple[Callable[[str], bool], bool]:
    """``(is_known, documented)``: whether a variable name is one the service uses, and whether its ``.env.example`` was seen.

    Knowledge comes from the catalogue (its presets, required keys and providers, the shared-logging names, what the tool
    computes, ``extra_env``, ``internal``) and, once the code is fetched, from the service's own ``.env.example`` text.
    """
    known = {
        *spec.env, *(rule.key for rule in spec.require), *spec.require_any, *computed_variables(spec), *SHARED_LOGGING_VARS,
    }
    documented = example_text is not None
    if example_text is not None:
        known.update(parse_env(example_text))
        known.update(re.findall(r"^#\s?([A-Z][A-Z0-9_]{2,})=", example_text, re.M))  # commented-out variables are documented too

    def is_known(key: str) -> bool:
        return key in known or _matches(key, spec.extra_env) or _matches(key, spec.internal)

    return is_known, documented
