# Live Test Environment

This folder contains tests that call real configured microservices. These tests
are skipped by default and only run when `RUN_LIVE_MICROSERVICE_TESTS=1` is set.

Live tests use the current environment and `.env` values for service URLs.
Make sure microphone, STT, TTS, and speaker services are running before using
this environment.

## Folder Map

- `external_microservices/`: one live smoke test per external service.
- `flows/`: live health, per-connection, full-pipeline, and attachment checks
  across real services.

## Run

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live
```

If a test fails here while mock tests pass, the likely problem is service
availability, service configuration, or an HTTP contract mismatch with a real
external microservice.
