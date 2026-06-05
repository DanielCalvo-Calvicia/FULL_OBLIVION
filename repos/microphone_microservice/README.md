# Microphone Microservice

A Windows-oriented Python FastAPI service for exposing local microphone audio over HTTP.

The service owns one local microphone input stream at a time. It uses `sounddevice`/PortAudio for capture, wraps microphone reads in an async iterator, and returns audio through standard JSON stream events. The default wire format is newline-delimited JSON (`application/x-ndjson`); clients can request SSE compatibility with `Accept: text/event-stream`.

## What It Does

- Starts an HTTP server on `127.0.0.1:8000`.
- Opens a local microphone stream with configurable sample rate, channel count, and chunk size.
- Streams PCM audio chunks as base64-encoded standard stream events.
- Exposes endpoints for start, stop, availability, and health.
- Uses a hexagonal ports-and-adapters layout so FastAPI and `sounddevice` stay outside the application service boundary.

## Requirements

- Windows
- Python 3.11 or newer recommended
- A working local microphone input device
- PortAudio-compatible audio stack through `sounddevice`

Install dependencies:

```powershell
windows\Scripts\python.exe -m pip install -r requirements.windows.txt
```

If you are not using the checked-in `windows` virtual environment, replace `windows\Scripts\python.exe` with your own Python executable.

## Run Locally

```powershell
windows\Scripts\python.exe main.py
```

The service binds to:

```text
http://127.0.0.1:8000
```

FastAPI docs are available while the service is running:

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`
- `http://127.0.0.1:8000/openapi.json`

## Endpoints

| Method | Path | Response | Purpose |
|---|---|---|---|
| `POST` | `/start` | `application/x-ndjson` or `text/event-stream` | Start the microphone and stream audio events. |
| `POST` | `/stop` | JSON | Stop the active microphone stream. |
| `GET` | `/available` | JSON | Report whether this adapter currently has an active stream. |
| `GET` | `/health` | JSON | Basic health response. |

### Start Stream

```powershell
curl.exe -N -X POST http://127.0.0.1:8000/start `
  -H "Content-Type: application/json" `
  -d "{\"sample_rate\":16000,\"channels\":1,\"chunk_size\":1024}"
```

Request body defaults:

| Field | Default | Notes |
|---|---:|---|
| `sample_rate` | `16000` | Requested microphone sample rate. The adapter retries with the hardware default if this fails. |
| `channels` | `1` | Requested input channels. If mono fails, the adapter retries stereo and downmixes to mono. |
| `chunk_size` | `1024` | Number of frames read per chunk. |

### Stop Stream

```powershell
curl.exe -X POST http://127.0.0.1:8000/stop -H "Content-Type: application/json" -d "{}"
```

Example response:

```json
{
  "action": "stop_stream",
  "status": "success",
  "status_code": 200,
  "message": "Microphone stream stopped successfully",
  "timestamp": 1710000000.0,
  "data": true
}
```

### Availability

```powershell
curl.exe http://127.0.0.1:8000/available
```

`data` is `true` only when the adapter currently has an active stream.

### Health

```powershell
curl.exe http://127.0.0.1:8000/health
```

## Streaming Event Contract

`POST /start` emits standard JSON stream events.

By default, responses use NDJSON (`application/x-ndjson`) with one complete JSON object per line:

```json
{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}
{"type":"partial","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{"bytes_base64":"cGNtLWJ5dGVz"}}
{"type":"completed","sequence":3,"timestamp":"2026-05-24T12:00:03Z","payload":{"reason":"completed","output_bytes_base64":"cGNtLWJ5dGVz"}}
```

When a client sends `Accept: text/event-stream`, the response uses SSE (`text/event-stream`). Each SSE frame contains exactly one `data:` line, and the value after `data:` is exactly the same standard JSON event object:

```text
data:{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}

data:{"type":"partial","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{"bytes_base64":"cGNtLWJ5dGVz"}}

data:{"type":"completed","sequence":3,"timestamp":"2026-05-24T12:00:03Z","payload":{"reason":"completed","output_bytes_base64":"cGNtLWJ5dGVz"}}
```

The SSE stream does not emit `event:` fields, `[DONE]`, `EOF`, or other sentinel data.

Every event has:

| Field | Type | Description |
|---|---|---|
| `type` | string | One of `stream_started`, `partial`, `completed`, `heartbeat`, or `error`. |
| `sequence` | integer | Monotonically increasing sequence number for one HTTP stream response. |
| `timestamp` | string | UTC ISO-8601 timestamp. |
| `payload` | object | Event-specific payload. |

Current microphone streams emit:

| Type | Payload | Meaning |
|---|---|---|
| `stream_started` | `{}` | The HTTP stream has started. |
| `partial` | `{"bytes_base64":"..."}` | One non-silent microphone audio chunk. Silent chunks are not emitted. |
| `completed` | `{"reason":"completed","output_bytes_base64":"..."}` | The current recording segment is complete after 2 continuous seconds of silence, or because the underlying stream ended. |
| `error` | `{"code":"audio_stream_failed","message":"Audio stream failed while producing events.","recoverable":true}` | Streaming failed while producing events. |

The service treats `partial` events as live non-silent PCM audio chunks. It suppresses silent chunks on the wire, uses them only to track silence over signed 16-bit mono PCM, and emits `completed` after 2 continuous seconds of silence. The `completed.payload.output_bytes_base64` value contains the buffered non-silent recording bytes and excludes the trailing silence that triggered completion. After a `completed` event, the HTTP stream can remain open and a later non-silent chunk can start another recording segment. Clients should read line by line, decode `bytes_base64` or `output_bytes_base64`, and act on `completed` events instead of waiting for the HTTP connection to close.

Minimal Python client:

```python
import base64
import json

import httpx

with httpx.stream(
    "POST",
    "http://127.0.0.1:8000/start",
    json={"sample_rate": 16000, "channels": 1, "chunk_size": 1024},
    timeout=None,
) as response:
    response.raise_for_status()
    for line in response.iter_lines():
        event = json.loads(line)
        if event["type"] == "partial":
            chunk = base64.b64decode(event["payload"]["bytes_base64"])
            # Use the PCM audio bytes.
        elif event["type"] == "completed":
            output = base64.b64decode(event["payload"]["output_bytes_base64"])
            # Process one completed logical output.
        elif event["type"] == "error":
            raise RuntimeError(event["payload"]["message"])
```

`httpx` is used by the example and by `tests/simple.py`, but it is not currently listed in `requirements.windows.txt`.

## Architecture

```mermaid
flowchart LR
    Client["HTTP client"] --> Inbound["FastApiAdapter"]
    Inbound --> Service["MicrophoneService"]
    Service --> Outbound["MicrophoneAdapter"]
    Outbound --> SoundDevice["sounddevice / PortAudio"]
    SoundDevice --> Mic["Windows microphone"]
```

Key files:

| Path | Responsibility |
|---|---|
| `main.py` | Process entry point. Calls async setup. |
| `composition_root/setup/setup.py` | Builds the container and starts Uvicorn. |
| `composition_root/containers/container.py` | Assembles top-level dependencies. |
| `composition_root/dependencies/microphone_dependency.py` | Creates the FastAPI app, service, and adapters. |
| `infrastructure/inbound/http/fastapi_adapter.py` | Registers HTTP routes and formats JSON/NDJSON responses. |
| `application/services/service.py` | Framework-neutral service orchestration. |
| `application/ports/*.py` | Abstract inbound, service, and outbound contracts. |
| `application/dtos/*.py` | Boundary DTOs. |
| `application/dtos/mapper/*.py` | DTO mapping functions. |
| `infrastructure/outbound/windows_sounddevice.py` | Microphone device selection, stream lifecycle, reads, telemetry, and stereo-to-mono downmixing. |

## Runtime Behavior

Startup flow:

1. `main.py` calls `asyncio.run(setup())`.
2. `setup()` resolves runtime environment configuration.
3. `BuildContainer()` creates the microphone dependency graph.
4. `FastApiAdapter` registers routes on a FastAPI app.
5. Uvicorn serves the app on `127.0.0.1:8000`.
6. On server shutdown, cleanup stops the microphone if the adapter is still active.

Microphone behavior:

- Invalid non-positive `sample_rate`, `channels`, or `chunk_size` values are rejected.
- A second `/start` while a stream is active raises an error.
- Input devices are scanned with `sounddevice.query_devices()`.
- `target_keywords` can prefer named devices, but the current container passes an empty list.
- If no keyword matches, the OS default input device is used.
- If the requested sample rate fails, the adapter retries with the hardware default sample rate.
- If mono opening fails, the adapter retries stereo and downmixes stereo PCM to mono bytes with NumPy.
- `/stop` is idempotent when no stream is active.

## Configuration

Runtime environment is resolved from:

1. Process environment: `APP_ENV`, then `VSCODE_ENV`.
2. Selected VS Code launch profile `env`: `APP_ENV`, then `VSCODE_ENV`.
3. Selected VS Code launch profile `envFile`: `APP_ENV`, then `VSCODE_ENV`.
4. Safe default: `development`.

Supported environment values:

| Value | Aliases | Application log threshold |
|---|---|---|
| `development` | `dev`, `debug`, `local` | `trace` |
| `staging` | `stage` | `warn` |
| `production` | `prod` | `critical` |

Environment files:

| File | Purpose |
|---|---|
| `.env` | Development values. |
| `.env.staging` | Staging values. |
| `.env.production` | Production values. |

The `.env*` files include `LOG_LEVEL` for readability, but the custom logger currently derives its threshold from `APP_ENV` rather than reading `LOG_LEVEL` directly.

## Tests

Run the test suite:

```powershell
windows\Scripts\python.exe -m pytest -q
```

Useful test files:

| Path | Notes |
|---|---|
| `tests/test_runtime_environment.py` | Unit tests for environment resolution and logger filtering. |
| `tests/test_start_endpoint.py` | Tests the `/start` endpoint streaming event behavior with mocked audio dependencies. |
| `tests/simple.py` | Manual E2E-style script that starts the service and calls endpoints. Requires microphone access and `httpx`. |

## Dependencies

Declared in `requirements.windows.txt`:

- `fastapi`
- `uvicorn`
- `sounddevice`
- `soundfile`
- `numpy`
- `pytest`

## Known Limitations

- The service is local-only by default, but it has no authentication or authorization.
- Any local process that can call the port can start microphone capture.
- Only one active microphone stream is supported.
- `/start` both opens the hardware stream and returns a streaming response, so client disconnect behavior should be tested carefully for production use.
- `httpx` is needed for the example client and `tests/simple.py`, but it is not declared in `requirements.windows.txt`.
- There is no Dockerfile or CI workflow in this repository.
