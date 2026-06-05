# Test Suite

This directory is organized first by test environment, then by debugging
target. The goal is to make it obvious whether a failure came from pure mocked
brain behavior or from a real running external microservice.

## Folder Map

- `mock/`: fake-backed and `httpx.MockTransport` tests. These do not require
  microphone, STT, TTS, or speaker services to be running.
- `live/`: opt-in tests that call real configured microservices. These are
  skipped unless `RUN_LIVE_MICROSERVICE_TESTS=1` is set.
- `shared/`: shared fake ports, async stream helpers, and live service wiring
  used by tests in other folders. This folder should not contain pytest test
  cases.

## Common Commands

Run all mock tests:

```powershell
python -m pytest tests/mock
```

Run all live tests against real running microservices:

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live
```

Run everything VS Code discovers:

```powershell
python -m pytest tests/mock tests/live
```

Run one mock category:

```powershell
python -m pytest tests/mock/external_microservices
```

Run one live service:

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/external_microservices/stt
```

Live tests use the URLs from the current environment and `.env` configuration.
They are skipped by default so normal test runs do not require microphone, STT,
TTS, or speaker services to be running.
