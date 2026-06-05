# Mock Test Environment

This folder contains tests that do not call real external microservices.
They use fake ports or `httpx.MockTransport`, so they should be fast,
deterministic, and safe to run during normal development.

## Folder Map

- `external_microservices/`: mock HTTP adapter tests for microphone, STT, TTS,
  and speaker.
- `flows/`: fake-backed flow connection tests for health checks, stream links,
  and the full voice pipeline.
- `project/`: project behavior tests for configuration, environment handling,
  logging, and public `BrainService` methods.

## Run

```powershell
python -m pytest tests/mock
```

If a test fails here, the bug is usually inside the brain service, adapter
request/response mapping, DTO mapping, or local orchestration logic.
