from composition_root.config import load_config


def test_load_config_accepts_full_endpoint_urls(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SERVICE_PORT", "8010")
    monkeypatch.setenv("STT_SET_STREAM_ENDPOINT", "http://127.0.0.1:8001/process/stream/set")
    monkeypatch.setenv("STT_GET_STREAM_ENDPOINT", "http://127.0.0.1:8001/process/stream/get")

    config = load_config()

    assert config.service_port == 8010
    assert config.stt_base_url == "http://127.0.0.1:8001"
    assert config.stt_set_stream_endpoint == "/process/stream/set"
    assert config.stt_get_stream_endpoint == "/process/stream/get"


def test_load_config_normalizes_debug_environment_alias(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "debug")

    config = load_config()

    assert config.app_env == "development"


def test_load_config_uses_new_speaker_play_stream_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SPEAKER_PLAY_STREAM_ENDPOINT", "http://127.0.0.1:8003/process/stream/set")

    config = load_config()

    assert config.speaker_play_stream_endpoint == "/process/stream/set"


def test_load_config_keeps_old_speaker_stream_endpoint_as_fallback(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SPEAKER_PLAY_STREAM_ENDPOINT", raising=False)
    monkeypatch.setenv("SPEAKER_STREAM_ENDPOINT", "http://127.0.0.1:8003/process/stream/set")

    config = load_config()

    assert config.speaker_play_stream_endpoint == "/process/stream/set"
