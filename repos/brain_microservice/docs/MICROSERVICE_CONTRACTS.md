# Microservice Contract Report

Generated from the current Brain microservice code, HTTP adapters, DTOs, tests, and service README files.

This report focuses on what each service must send and receive so integration debugging can start from the wire contract instead of from implementation details.

## System Overview

The Brain microservice is an HTTP orchestration service. It exposes its own API on `SERVICE_HOST:SERVICE_PORT`, default `127.0.0.1:7999`, and calls four external local microservices:

| Service | Default base URL | Role |
| --- | --- | --- |
| Brain | `http://127.0.0.1:7999` | Public orchestrator API. |
| Microphone | `http://127.0.0.1:8000` | Produces raw microphone PCM bytes as NDJSON events. |
| STT | `http://127.0.0.1:8001` | Converts NDJSON audio events to SSE-wrapped text events. |
| TTS | `http://127.0.0.1:8002` | Converts text to audio bytes as NDJSON events. |
| Speaker | `http://127.0.0.1:8003` | Plays NDJSON audio events. |

Primary end-to-end stream:

```text
Microphone /start
  -> NDJSON audio bytes
  -> STT /process/stream/set
  -> STT /process/stream/get
  -> SSE-wrapped standard text events
  -> TTS /process/stream/set
  -> TTS /process/stream/get
  -> NDJSON audio bytes
  -> Speaker /process/stream/set
```

All Brain JSON responses use this envelope:

```json
{
  "action": "string",
  "status": "success|error",
  "status_code": 200,
  "message": "string",
  "timestamp": 1710000000.0,
  "data": {}
}
```

Error responses set `status` to `error`, set `data` to `null`, and use HTTP `500` for internal errors or HTTP `502` when an external microservice raises a known `BrainMicroserviceError`.

## Shared Stream Event Contract

Microphone, STT input, TTS input, TTS output, and Speaker input streams use NDJSON: one complete standard event JSON object per line.

STT text output is parsed as Server-Sent Events for compatibility. Each event uses `data: <json>\n\n`, and the `data:` value must be exactly one standard event JSON object.

Structured stream event shape:

```json
{
  "type": "stream_started",
  "sequence": 1,
  "timestamp": "2026-05-24T12:00:00Z",
  "payload": {}
}
```

Required fields:

| Field | Type | Notes |
| --- | --- | --- |
| `type` | string | Must be one of `stream_started`, `partial`, `completed`, `heartbeat`, `error`. Unknown event types are rejected. |
| `sequence` | integer | Starts at `1` per HTTP stream and increments by `1` for every event. |
| `timestamp` | string | UTC ISO-8601 timestamp ending in `Z`. |
| `payload` | object | Event-specific data. |

Every stream must start with `{"type":"stream_started","sequence":1,"timestamp":"...Z","payload":{}}`.

Binary/audio partials use `{"type":"partial","sequence":N,"timestamp":"...Z","payload":{"bytes_base64":"..."}}`.

Text partials use `{"type":"partial","sequence":N,"timestamp":"...Z","payload":{"text":"..."}}`.

Logical completion uses `payload.reason: "completed"` plus `payload.output` for text or `payload.output_bytes_base64` for audio. Brain rejects raw text chunks, sentinel strings, `[DONE]`, `EOF`, and unstructured stream data.

Binary payloads are base64 encoded. Brain decodes `payload.bytes_base64` for `partial` audio events. TTS also supports `payload.output_bytes_base64` on `completed` as a fallback if no partial chunks were emitted.

Error event shape:

```json
{
  "type": "error",
  "sequence": 5,
  "timestamp": "2026-05-24T12:00:05Z",
  "payload": {
    "code": "stream_error",
    "message": "Human-readable detail",
    "recoverable": true
  }
}
```

When Brain receives `type: "error"`, it raises an external service error with `code: message`.

## Brain Inbound API

### `GET /health`

Purpose: Brain liveness check only.

Request:

- Body: none
- Query: none

Successful response:

```json
{
  "action": "health_check",
  "status": "success",
  "status_code": 200,
  "message": "Brain microservice is healthy",
  "timestamp": 1710000000.0,
  "data": null
}
```

### `GET /integrations/health`

Purpose: checks Microphone, STT, TTS, and Speaker availability.

Request:

- Body: none
- Query: none

Brain calls:

- Microphone `GET /health`
- STT `GET /available`, falling back to `GET /health` if `/available` is unavailable
- TTS `GET /available`, falling back to `GET /health` if `/available` is unavailable
- Speaker `GET /health`

Successful response:

```json
{
  "action": "integrations_health",
  "status": "success",
  "status_code": 200,
  "message": "External integrations checked",
  "timestamp": 1710000000.0,
  "data": {
    "all_available": true,
    "services": [
      {"name": "microphone", "is_available": true, "detail": "HTTP 200"},
      {"name": "stt", "is_available": true, "detail": "HTTP 200"},
      {"name": "tts", "is_available": true, "detail": "HTTP 200"},
      {"name": "speaker", "is_available": true, "detail": "HTTP 200"}
    ]
  }
}
```

### `POST /stt/batch`

Purpose: send one finite audio body to STT and receive text.

Request:

| Part | Contract |
| --- | --- |
| Body | Raw signed 16-bit PCM audio bytes. Brain does not validate content type. |
| Query `sample_rate` | integer, default `16000`. |

Brain outbound call:

```text
POST {STT_BASE_URL}/process/batch?sample_rate=16000
Content-Type: application/octet-stream
Body: raw PCM bytes
```

Successful response:

```json
{
  "action": "stt_batch",
  "status": "success",
  "status_code": 200,
  "message": "Audio transcribed",
  "timestamp": 1710000000.0,
  "data": {"text": "transcribed text"}
}
```

### `POST /tts/play`

Purpose: synthesize text through TTS and play the generated audio through Speaker.

Request:

| Part | Contract |
| --- | --- |
| Body | UTF-8 plain text. |
| Query `sample_rate` | integer, default `24000`. |
| Query `channels` | integer, default `1`. |

Brain outbound calls:

1. `POST {TTS_BASE_URL}/process/stream/set?sample_rate=24000&channels=1` with `Content-Type: application/x-ndjson`.
2. `GET {TTS_BASE_URL}/process/stream/get?sample_rate=24000&channels=1&keep_open_after_completed=true`.
3. `POST {SPEAKER_BASE_URL}/process/stream/set?sample_rate=24000&channels=1` with NDJSON audio events.

Successful response:

```json
{
  "action": "tts_play",
  "status": "success",
  "status_code": 200,
  "message": "Speaker stream input accepted",
  "timestamp": 1710000000.0,
  "data": {"success": true}
}
```

### `POST /voice/transcribe`

Purpose: start microphone capture, feed it into STT, and return a bounded list of transcribed text segments.

Request query parameters:

| Name | Type | Default | Sent to |
| --- | --- | ---: | --- |
| `sample_rate` | int | `16000` | Microphone and STT |
| `chunk_size` | int | `1024` | Microphone and STT |
| `silence_threshold` | int | `150` | STT |
| `silence_limit_seconds` | float | `2.0` | STT |
| `max_segments` | int | `1` | Brain segment collection limit |

Brain outbound calls:

1. `POST {MICROPHONE_BASE_URL}/start` JSON body `{"sample_rate":16000,"channels":1,"chunk_size":1024}`.
2. `POST {STT_BASE_URL}/process/stream/set?...` with NDJSON audio events.
3. `GET {STT_BASE_URL}/process/stream/get?...` to read completed text events.

Successful response:

```json
{
  "action": "voice_transcribe",
  "status": "success",
  "status_code": 200,
  "message": "Microphone audio transcribed",
  "timestamp": 1710000000.0,
  "data": {"segments": ["first transcription"]}
}
```

On any failure after microphone start, Brain attempts `POST {MICROPHONE_BASE_URL}/stop`.

### `POST /voice/pipeline`

Purpose: start the long-running microphone -> STT -> TTS -> Speaker pipeline in a background task.

Request query parameters:

| Name | Type | Default | Sent to |
| --- | --- | ---: | --- |
| `microphone_sample_rate` | int | `16000` | Microphone and STT |
| `microphone_chunk_size` | int | `1024` | Microphone and STT |
| `stt_silence_threshold` | int | `150` | STT |
| `stt_silence_limit_seconds` | float | `2.0` | STT |
| `max_text_segments` | int | `0` | Brain internal text-stream limiter; `0` means no explicit limit |
| `tts_sample_rate` | int | `24000` | TTS and Speaker |
| `speaker_channels` | int | `1` | TTS and Speaker |

Successful response is returned immediately after scheduling:

```json
{
  "action": "voice_pipeline",
  "status": "success",
  "status_code": 200,
  "message": "Voice pipeline started",
  "timestamp": 1710000000.0,
  "data": {"started": true}
}
```

The background task performs the same stream chain as the full system overview and then waits until cancelled.

## External Microservice Contracts Required by Brain

### Microphone

Default base URL: `MICROPHONE_BASE_URL`, default `http://127.0.0.1:8000`.

Configurable endpoints:

| Env var | Default path |
| --- | --- |
| `MICROPHONE_STREAM_ENDPOINT` | `/stream` |
| `MICROPHONE_START_ENDPOINT` | `/start` |
| `MICROPHONE_STOP_ENDPOINT` | `/stop` |

#### `GET /health`

Brain expects HTTP `200` for available. Any `401` or `403` is authentication failure. Other non-200 statuses are reported as unavailable health detail `HTTP <status>`.

#### `GET /stream`

Used by the adapter but not the main Brain flows. It opens an existing microphone stream.

Request query:

| Name | Type | Default |
| --- | --- | ---: |
| `sample_rate` | int | `16000` |
| `chunk_size` | int | `1024` |

Expected response:

- HTTP status: exactly `200`.
- Headers: optional `X-Sample-Rate`; if present and positive integer, Brain uses it as the actual audio sample rate.
- Body: NDJSON stream events.

#### `POST /start`

Used by `/voice/transcribe` and `/voice/pipeline`.

Request:

```json
{
  "sample_rate": 16000,
  "channels": 1,
  "chunk_size": 1024
}
```

Expected response:

- HTTP status: exactly `200`.
- Headers: optional `X-Sample-Rate`.
- Body: NDJSON events.

Expected NDJSON:

```json
{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}
{"type":"partial","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{"bytes_base64":"cGNtLWJ5dGVz"}}
{"type":"completed","sequence":3,"timestamp":"2026-05-24T12:00:01Z","payload":{"reason":"completed","output_bytes_base64":"cGNtLWJ5dGVz"}}
```

Brain behavior:

- Ignores `stream_started`, `heartbeat`, and `completed`.
- Decodes and forwards audio only from `partial.payload.bytes_base64`.
- Raises on `error`.
- Rejects malformed events, unknown event types, non-UTC timestamps, and non-sequential events.

#### `POST /stop`

Used for cleanup and error recovery.

Request:

```json
{}
```

Expected response:

- Any non-error status below `400` is accepted by Brain.
- `401`/`403` -> authentication error.
- `404` -> endpoint unavailable.
- `>=400` -> external service unavailable.

### STT

Default base URL: `STT_BASE_URL`, default `http://127.0.0.1:8001`.

Configurable endpoints:

| Env var | Default path |
| --- | --- |
| `STT_SET_STREAM_ENDPOINT` | `/process/stream/set` |
| `STT_GET_STREAM_ENDPOINT` | `/process/stream/get` |
| `STT_BATCH_ENDPOINT` | `/process/batch` |

#### `GET /available`

Preferred STT health endpoint.

Expected response:

```json
{"data": {"is_available": true}}
```

Also accepted:

```json
{"data": true}
```

Brain interprets `data.is_available` if `data` is an object, otherwise `bool(data)`.

If this endpoint returns `404`, Brain falls back to `GET /health`.

#### `GET /health`

Fallback health endpoint. HTTP `200` means available.

#### `POST /process/batch`

Used by Brain `/stt/batch`.

Request:

| Part | Contract |
| --- | --- |
| Query `sample_rate` | int, default `16000`. |
| Headers | `Content-Type: application/octet-stream`; optional `Authorization: Bearer <PROVIDER_API_KEY>`. |
| Body | Raw signed 16-bit PCM bytes. |

Expected response:

- HTTP status: exactly `200`.
- JSON body with either `data.text` or a string-like `data`.

Preferred response:

```json
{
  "data": {
    "text": "transcribed text"
  }
}
```

Fallback accepted response:

```json
{
  "data": "transcribed text"
}
```

#### `POST /process/stream/set`

Used to feed STT input audio in the decoupled stream flow.

Request query:

| Name | Type | Default |
| --- | --- | ---: |
| `sample_rate` | int | `16000` |
| `chunk_size` | int | `1024` |
| `silence_threshold` | int | `150` |
| `silence_limit_seconds` | float | `2.0` |

Request headers:

```text
Content-Type: application/x-ndjson
Authorization: Bearer <PROVIDER_API_KEY>  # only when configured
```

Request body: NDJSON standard stream events.

Expected NDJSON:

```json
{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}
{"type":"partial","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{"bytes_base64":"cGNtLWJ5dGVz"}}
{"type":"completed","sequence":3,"timestamp":"2026-05-24T12:00:02Z","payload":{"reason":"completed","output_bytes_base64":"cGNtLWJ5dGVz"}}
```

Expected response:

- HTTP status: exactly `200`.
- Body can be JSON such as `{"data":{"accepted":true}}`; Brain does not inspect it.

#### `GET /process/stream/get`

Used to retrieve transcribed text from the decoupled stream.

Request query:

| Name | Type | Default |
| --- | --- | ---: |
| `sample_rate` | int | `16000` |
| `chunk_size` | int | `1024` |
| `silence_threshold` | int | `150` |
| `silence_limit_seconds` | float | `2.0` |

Expected response:

- HTTP status: exactly `200`.
- Content: SSE-style stream where each event contains one `data: <standard-event-json>` field.

Expected SSE:

```text
data: {"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}

data: {"type":"partial","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{"text":"hel"}}

data: {"type":"completed","sequence":3,"timestamp":"2026-05-24T12:00:02Z","payload":{"reason":"silence","output":"hello"}}

```

Brain behavior:

- Ignores `stream_started`, `heartbeat`, and structured `partial` events.
- Yields text from `completed.payload.output`.
- Also accepts `completed.payload.text` if `output` is missing.
- Rejects SSE `data:` values that are not standard event JSON objects. Raw `data: hello world` is invalid; use `data: {"type":"completed","sequence":N,"timestamp":"...Z","payload":{"reason":"completed","output":"hello world"}}`.
- Treats incomplete chunked close as normal stream completion.

### TTS

Default base URL: `TTS_BASE_URL`, default `http://127.0.0.1:8002`.

Configurable endpoints:

| Env var | Default path |
| --- | --- |
| `TTS_SET_STREAM_ENDPOINT` | `/process/stream/set` |
| `TTS_STREAM_ENDPOINT` | `/process/stream/get` |

#### `GET /available`

Preferred TTS health endpoint.

Expected response:

```json
{"data": {"is_available": true}}
```

Also accepted:

```json
{"data": true}
```

If unavailable, Brain falls back to `GET /health`.

#### `GET /health`

Fallback health endpoint. HTTP `200` means available.

#### `POST /process/stream/set`

Used to feed text into the decoupled TTS stream.

Request query:

| Name | Type | Default |
| --- | --- | ---: |
| `sample_rate` | int | `24000` |
| `channels` | int | `1` |

Request headers:

```text
Content-Type: application/x-ndjson
Authorization: Bearer <PROVIDER_API_KEY>  # only when configured
```

Request body:

- Brain sends `stream_started` once per text input stream.
- Each normal text segment is sent as a separate `completed` event with `payload.output`.
- `partial` events are reserved for oversized text segments; Brain sends one or more `partial.payload.text` chunks, then a `completed.payload.output` event for that same logical segment.

Example:

```json
{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}
{"type":"completed","sequence":2,"timestamp":"2026-05-24T12:00:02Z","payload":{"reason":"completed","output":"hello"}}
```

Expected response:

- HTTP status: `200` or `202`.
- Body is not inspected.

#### `GET /process/stream/get`

Used to retrieve synthesized audio bytes.

Request query:

| Name | Type | Default from Brain |
| --- | --- | ---: |
| `sample_rate` | int | `24000` |
| `channels` | int | `1` |
| `keep_open_after_completed` | bool | `true` |

Expected response:

- HTTP status: exactly `200`.
- Body: NDJSON stream events.

Expected NDJSON:

```json
{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}
{"type":"partial","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{"bytes_base64":"cGNtLWF1ZGlv","byte_count":9,"chunk_index":1}}
{"type":"completed","sequence":3,"timestamp":"2026-05-24T12:00:02Z","payload":{"reason":"completed","output_bytes_base64":"cGNtLWF1ZGlv","total_bytes":9,"chunk_count":1}}
```

Brain behavior:

- Ignores `stream_started` and `heartbeat`.
- Decodes and forwards audio from `partial.payload.bytes_base64`.
- If a `completed` event arrives before any partial chunks for that logical output and includes `output_bytes_base64`, Brain decodes that as a fallback audio chunk.
- `/tts/play` stops after one completed logical output.
- Full voice pipeline keeps reading completed outputs indefinitely unless `max_text_segments` closes the internal text stream.

### Speaker

Default base URL: `SPEAKER_BASE_URL`, default `http://127.0.0.1:8003`.

Configurable endpoint:

| Env var | Default path |
| --- | --- |
| `SPEAKER_PLAY_STREAM_ENDPOINT` | `/process/stream/set` |

`SPEAKER_STREAM_ENDPOINT` is accepted as a fallback env var for the same endpoint.

#### `GET /health`

Brain expects HTTP `200` for available.

#### `POST /process/stream/set`

Used to play TTS audio bytes.

Request query:

| Name | Type | Default |
| --- | --- | ---: |
| `sample_rate` | int | `24000` |
| `channels` | int | `1` |

Request headers:

```text
Content-Type: application/x-ndjson
Authorization: Bearer <PROVIDER_API_KEY>  # only when configured
```

Request body: NDJSON standard audio events emitted by Brain from TTS audio.

Expected NDJSON:

```json
{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}
{"type":"partial","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{"bytes_base64":"cGNtLWF1ZGlv"}}
{"type":"completed","sequence":3,"timestamp":"2026-05-24T12:00:02Z","payload":{"reason":"completed","output_bytes_base64":"cGNtLWF1ZGlv"}}
```

Expected response:

- HTTP status: exactly `200`.
- JSON body is optional.

Preferred JSON response:

```json
{
  "action": "set_stream_http",
  "status": "success",
  "status_code": 200,
  "message": "Playback stream accepted",
  "data": null
}
```

Also accepted:

```json
{
  "data": {
    "message": "Playback stream accepted"
  }
}
```

If response content type is not JSON, body is invalid JSON, or no message is present, Brain uses fallback message `"Speaker stream input accepted"`.

## Configuration Contract

Brain reads these environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` / `VSCODE_ENV` | `development` | Runtime environment label. Supported: `development`, `staging`, `production`; aliases include `dev`, `debug`, `prod`. |
| `SERVICE_HOST` | `127.0.0.1` | Brain bind host. |
| `SERVICE_PORT` | `7999` | Brain bind port. |
| `PROVIDER_NAME` | `local` | Metadata only in current Brain code. |
| `PROVIDER_TIMEOUT_SECONDS` | `30.0` | HTTP client timeout; stream reads have no read timeout. |
| `PROVIDER_API_KEY` | empty | If set, Brain sends `Authorization: Bearer <value>` to all external microservices. |
| `MICROPHONE_BASE_URL` | `http://127.0.0.1:8000` | Microphone origin. |
| `MICROPHONE_STREAM_ENDPOINT` | `/stream` | Microphone active stream endpoint. |
| `MICROPHONE_START_ENDPOINT` | `/start` | Microphone start endpoint. |
| `MICROPHONE_STOP_ENDPOINT` | `/stop` | Microphone stop endpoint. |
| `STT_BASE_URL` | `http://127.0.0.1:8001` | STT origin. |
| `STT_SET_STREAM_ENDPOINT` | `/process/stream/set` | STT audio input endpoint. |
| `STT_GET_STREAM_ENDPOINT` | `/process/stream/get` | STT text output endpoint. |
| `STT_BATCH_ENDPOINT` | `/process/batch` | STT batch endpoint. |
| `TTS_BASE_URL` | `http://127.0.0.1:8002` | TTS origin. |
| `TTS_SET_STREAM_ENDPOINT` | `/process/stream/set` | TTS text input endpoint. |
| `TTS_STREAM_ENDPOINT` | `/process/stream/get` | TTS audio output endpoint. |
| `SPEAKER_BASE_URL` | `http://127.0.0.1:8003` | Speaker origin. |
| `SPEAKER_PLAY_STREAM_ENDPOINT` | `/process/stream/set` | Speaker playback endpoint. |
| `SPEAKER_STREAM_ENDPOINT` | unset | Fallback for `SPEAKER_PLAY_STREAM_ENDPOINT`. |
| `STARTUP_PREFLIGHT_ENABLED` | `true` | Whether startup probes external microservices. |
| `STARTUP_PREFLIGHT_TIMEOUT_SECONDS` | `60.0` | Startup probe timeout budget. |
| `MICROSERVICE_READY_POLL_INTERVAL_SECONDS` | `2.0` | Startup polling interval. |

Endpoint env vars may be absolute URLs or paths. If an absolute URL starts with the matching default origin, Brain stores only the path. If it points elsewhere, Brain keeps the absolute URL.

## Status and Failure Rules

Common HTTP status handling:

| Status | Brain behavior |
| --- | --- |
| `200` | Required for stream opens, STT set/get/batch, Speaker play, and Microphone start. |
| `202` | Accepted only by TTS text upload. |
| `401` / `403` | External authentication error. |
| `404` | External endpoint unavailable. STT/TTS availability checks may fall back from `/available` to `/health`. |
| `>=400` | External service unavailable. Error body text is truncated to 200 characters. |
| Any unexpected success status | External service unavailable, except TTS text upload allows `202`. |

Content and parsing failures:

| Failure | Brain behavior |
| --- | --- |
| Non-JSON response where JSON is required | External invalid response error. |
| Stream event is not JSON object | External invalid response error. |
| Stream event missing `type`, `sequence`, `timestamp`, or object `payload` | External invalid response error. |
| Unknown stream event type | External invalid response error. |
| Non-sequential stream event | External invalid response error. |
| Stream timestamp not UTC ISO-8601 ending in `Z` | External invalid response error. |
| Audio event missing `bytes_base64` | External invalid response error. |
| Invalid base64 audio | External invalid response error. |
| STT incomplete chunked close | Treated as stream completion. |

## Debugging Checklist

Use this sequence when a flow fails:

1. Call Brain `GET /integrations/health`.
2. If a service is unavailable, call its health endpoint directly: Microphone/Speaker `/health`, STT/TTS `/available`.
3. Verify sample rates and channels match the flow:
   - Microphone/STT input defaults to `16000 Hz`, chunk size `1024`.
   - TTS/Speaker output defaults to `24000 Hz`, mono.
4. For NDJSON streams, verify each line is one complete standard event JSON object.
5. For STT output, verify each SSE event is separated by a blank line and contains `data: <standard-event-json>`.
6. For audio bytes, verify base64 field names:
   - Microphone partial: `payload.bytes_base64`.
   - TTS partial: `payload.bytes_base64`.
   - TTS completed fallback: `payload.output_bytes_base64`.
7. For STT text, verify final text is in `completed.payload.output` or `completed.payload.text`.
8. Confirm status codes:
   - Microphone `/start`: `200`, not `202`.
   - STT `/process/stream/set`: `200`, not `202`.
   - TTS `/process/stream/set`: `200` or `202`.
   - Speaker `/process/stream/set`: `200`.
9. If auth is configured, confirm every external service accepts `Authorization: Bearer <PROVIDER_API_KEY>`.

## Source Map

Primary Brain code used for this report:

| Area | File |
| --- | --- |
| Brain inbound HTTP routes | `infrastructure/inbound/http/fastapi_adapter.py` |
| Outbound HTTP client and stream parser | `infrastructure/outbound/http/base.py` |
| Microphone client adapter | `infrastructure/outbound/http/microphone/microphone_adapter.py` |
| STT client adapter | `infrastructure/outbound/http/stt/stt_adapter.py` |
| TTS client adapter | `infrastructure/outbound/http/tts/tts_adapter.py` |
| Speaker client adapter | `infrastructure/outbound/http/speaker/speaker_adapter.py` |
| Brain service orchestration | `application/services/service.py` |
| Voice pipeline orchestration | `application/services/pipeline.py` |
| Inbound DTOs | `application/dtos/inbound_dtos.py` |
| Outbound DTOs | `application/dtos/outbound_dtos.py` |
| Runtime configuration | `composition_root/config.py` |
| Adapter contract tests | `tests/mock/external_microservices/*/test_*_adapter.py` |
| External service handoff docs | `docs/README_MICROPHONE.md`, `docs/README_STT.md`, `docs/README_TTS.md`, `docs/README_SPEAKER.md` |
