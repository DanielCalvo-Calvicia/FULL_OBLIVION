import os
from dataclasses import dataclass

from composition_root.environment import resolve_runtime_environment


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_env: str
    service_host: str
    service_port: int
    provider_name: str
    provider_timeout_seconds: float
    provider_api_key: str
    microphone_base_url: str
    microphone_stream_endpoint: str
    microphone_start_endpoint: str
    microphone_stop_endpoint: str
    stt_base_url: str
    stt_set_stream_endpoint: str
    stt_get_stream_endpoint: str
    stt_batch_endpoint: str
    tts_base_url: str
    tts_set_stream_endpoint: str
    tts_get_stream_endpoint: str
    speaker_base_url: str
    speaker_play_stream_endpoint: str
    startup_preflight_enabled: bool
    startup_preflight_timeout_seconds: float
    microservice_ready_poll_interval_seconds: float


def load_config() -> AppConfig:
    runtime_environment = resolve_runtime_environment()
    return AppConfig(
        app_env=runtime_environment.value,
        service_host=os.getenv("SERVICE_HOST", "127.0.0.1"),
        service_port=_int_env("SERVICE_PORT", 7999),
        provider_name=os.getenv("PROVIDER_NAME", "local"),
        provider_timeout_seconds=_float_env("PROVIDER_TIMEOUT_SECONDS", 30.0),
        provider_api_key=os.getenv("PROVIDER_API_KEY", ""),
        microphone_base_url=_base_url("MICROPHONE_BASE_URL", "http://127.0.0.1:8000"),
        microphone_stream_endpoint=_endpoint(
            "MICROPHONE_STREAM_ENDPOINT",
            "http://127.0.0.1:8000/stream",
            "/stream",
        ),
        microphone_start_endpoint=_endpoint(
            "MICROPHONE_START_ENDPOINT",
            "http://127.0.0.1:8000/start",
            "/start",
        ),
        microphone_stop_endpoint=_endpoint(
            "MICROPHONE_STOP_ENDPOINT",
            "http://127.0.0.1:8000/stop",
            "/stop",
        ),
        stt_base_url=_base_url("STT_BASE_URL", "http://127.0.0.1:8001"),
        stt_set_stream_endpoint=_endpoint(
            "STT_SET_STREAM_ENDPOINT",
            "http://127.0.0.1:8001/process/stream/set",
            "/process/stream/set",
        ),
        stt_get_stream_endpoint=_endpoint(
            "STT_GET_STREAM_ENDPOINT",
            "http://127.0.0.1:8001/process/stream/get",
            "/process/stream/get",
        ),
        stt_batch_endpoint=_endpoint(
            "STT_BATCH_ENDPOINT",
            "http://127.0.0.1:8001/process/batch",
            "/process/batch",
        ),
        tts_base_url=_base_url("TTS_BASE_URL", "http://127.0.0.1:8002"),
        tts_set_stream_endpoint=_endpoint(
            "TTS_SET_STREAM_ENDPOINT",
            "http://127.0.0.1:8002/process/stream/set",
            "/process/stream/set",
        ),
        tts_get_stream_endpoint=_endpoint(
            "TTS_STREAM_ENDPOINT",
            "http://127.0.0.1:8002/process/stream/get",
            "/process/stream/get",
        ),
        speaker_base_url=_base_url("SPEAKER_BASE_URL", "http://127.0.0.1:8003"),
        speaker_play_stream_endpoint=_endpoint(
            "SPEAKER_PLAY_STREAM_ENDPOINT",
            "http://127.0.0.1:8003/process/stream/set",
            "/process/stream/set",
            fallback_env_name="SPEAKER_STREAM_ENDPOINT",
        ),
        startup_preflight_enabled=_bool_env("STARTUP_PREFLIGHT_ENABLED", True),
        startup_preflight_timeout_seconds=_float_env("STARTUP_PREFLIGHT_TIMEOUT_SECONDS", 60.0),
        microservice_ready_poll_interval_seconds=_float_env("MICROSERVICE_READY_POLL_INTERVAL_SECONDS", 2.0),
    )


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _base_url(name: str, default: str) -> str:
    explicit = os.getenv(name)
    if explicit:
        return explicit.rstrip("/")
    return _origin(default)


def _endpoint(name: str, default_url: str, fallback_path: str, fallback_env_name: str | None = None) -> str:
    value = os.getenv(name)
    if value is None and fallback_env_name is not None:
        value = os.getenv(fallback_env_name)
    if value is None:
        value = default_url
    if value.startswith("http://") or value.startswith("https://"):
        origin = _origin(default_url)
        if value.startswith(origin):
            path = value[len(origin) :]
            return path or fallback_path
    return value


def _origin(url: str) -> str:
    parts = url.split("/")
    return "/".join(parts[:3]).rstrip("/")
