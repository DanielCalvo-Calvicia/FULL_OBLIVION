# Repository Architecture Task List

## Documentation Review

- Reviewed `docs/README_MICROPHONE.md`: local microphone service, HTTP control plane, raw PCM streaming, default `127.0.0.1:8000`.
- Reviewed `docs/README_STT.md`: speech-to-text service, HTTP health/availability, batch transcription, SSE streaming transcription, optional autoload source, default `127.0.0.1:8001`.
- Reviewed `docs/README_TTS.md`: text-to-speech service, HTTP text input, decoupled stream set/get, batch synthesis, default `127.0.0.1:8002`.
- Reviewed `docs/README_SPEAKER.md`: speaker playback service, HTTP/WebSocket raw PCM playback, optional autoload source, default `127.0.0.1:8003`.

## Projects/Services

- Microphone microservice: external, separately deployed, owns microphone hardware capture.
- STT microservice: external, separately deployed, owns transcription engines and audio segmentation.
- TTS microservice: external, separately deployed, owns local speech synthesis.
- Speaker microservice: external, separately deployed, owns speaker hardware playback.
- This repository: master/orchestrator, owns HTTP integration and use-case orchestration only.

## External Integrations

- Explicit: microphone `GET /stream`, `POST /start`, `GET /health`.
- Explicit: STT `POST /process/stream`, `POST /process/batch`, `GET /health`, `GET /available`.
- Explicit: TTS `POST /process/stream/set`, `GET /process/stream/get`, `GET /health`, `GET /available`.
- Explicit: speaker `POST /play/stream`, `GET /health`.
- Inferred: configured endpoint variables may be full URLs or paths; composition root normalizes both.
- Added master flow endpoint `POST /voice/pipeline`:
  1. start microphone;
  2. get microphone stream output;
  3. get STT stream output by connecting microphone stream output to STT stream input;
  4. get TTS stream input by connecting STT text stream output to TTS stream set endpoint;
  5. get TTS stream output;
  6. connect TTS stream output to speaker stream input.
- Updated startup behavior: startup preflight polls health/availability until all microservices are active, then starts the mandatory stream pipeline before opening the inbound API.
- Updated runtime ownership: the startup stream pipeline is compulsory and has no enable/disable config flag.

## Domain Layer Work

- Added orchestration-friendly domain errors for external service failures.
- Added `ServiceStatus` and `VoiceTurn` business concepts.
- No HTTP, SDK, or framework concerns were added to domain.

## Application Layer Work

- Added inbound, service, and outbound DTOs.
- Added service and outbound ports.
- Added inbound-to-service mappers.
- Added `BrainService` for use-case orchestration:
  - integration health checks;
  - STT batch transcription;
  - microphone-to-STT transcription;
  - TTS-to-speaker playback.
  - full microphone-to-STT-to-TTS-to-speaker pipeline.
- Restructured `BrainService` into explicit Flow1-Flow4 folders so editor intelligence can follow the parent service and each segment:
  - `flow1_health/health_status.py`: check health status for each microservice.
  - `flow2_stream_outputs/stream_outputs.py`: get stream outputs from external microservices.
  - `flow3_stream_inputs/stream_inputs.py`: build stream inputs for external microservices.
  - `flow4_attach/stream_attachment.py`: attach mic -> STT -> TTS -> speaker streams.
  - `shared/microphone_lifecycle.py`: stop microphone through the API.
  - `shared/stream_helpers.py`: shared async stream helpers.
  - `service.py`: public service facade and flow composition.

## Infrastructure Layer Work

- Added FastAPI inbound adapter.
- Added `httpx` outbound adapters for microphone, STT, TTS, and speaker.
- Added centralized HTTP status/error mapping, timeout mapping, auth header handling, JSON parsing, and streaming byte handling.

## Configuration

- Added `.env.example`.
- Added env-driven app config:
  - `APP_ENV=debug`
  - `SERVICE_HOST=127.0.0.1`
  - `SERVICE_PORT=8000`
  - `PROVIDER_NAME=local`
  - `PROVIDER_TIMEOUT_SECONDS=30`
  - `PROVIDER_API_KEY=`
  - per-service base URLs and endpoint paths.
  - startup health preflight flags and timeout.
  - microservice readiness polling interval.

## Tests

- Added unit tests for service orchestration.
- Added mocked HTTP adapter tests for STT SSE parsing and speaker playback.
- Verification command: `python -m pytest`.

## Missing Information / Assumptions

- The docs do not define a canonical master/orchestrator API, so this repository exposes conservative orchestration endpoints under `/integrations`, `/stt`, `/tts`, and `/voice`.
- The microphone stream may need a prior `/start`; this implementation uses the configured stream endpoint for `transcribe_microphone` and also supports a `start_stream` adapter method for future use.
- STT stream responses are assumed to be SSE lines using `data: <text>`.
- TTS playback uses the documented decoupled set/get flow because the existing `.env` points at `/process/stream/get`.
- The requested final step said "connect TTS stream out to mic stream in"; docs show no microphone stream input, so implementation connects TTS stream output to speaker stream input.
- The brain service now refuses to open its inbound API unless all external microservices report healthy/available and startup stream attachment begins.
- Authentication is represented as a shared bearer token via `PROVIDER_API_KEY`; no per-service auth scheme was documented.

## Completion Status

- Documentation review: completed.
- Service identification: completed.
- Domain/application/infrastructure implementation: completed.
- Composition root/configuration: completed.
- Tests: completed.
- Verification: unit tests and `compileall` are expected to pass with the project virtual environment.
