# EXECUTION.md — FULL_OBLIVION

## Project Identity

- **Project name:** FULL_OBLIVION
- **Short description:** Multi-microservice voice AI agent platform that captures audio from a local microphone, transcribes speech to text (STT), synthesizes text to speech (TTS), and plays audio through a local speaker — all coordinated by a central brain orchestrator over HTTP.
- **Main role within the ecosystem:** Self-contained real-time voice pipeline. The brain orchestrator wires microphone → STT → TTS → speaker into a continuous streaming loop. Each microservice is an independent Python FastAPI/Uvicorn HTTP server.

---

## Execution Strategy

### Architecture

Five independent Python processes, each running a FastAPI application served by Uvicorn.

| Service | Default Port | Working Directory | Python Executable (Windows dev) |
|---|---|---|---|
| microphone | 8000 | `microphone_microservice/` | `microphone_microservice/windows/Scripts/python.exe` |
| stt | 8001 | `stt_microservice/` | `stt_microservice/windows/Scripts/python.exe` |
| tts | 8002 | `tts_microservice/` | `tts_microservice/windows/Scripts/python.exe` |
| speaker | 8003 | `speaker_microservice/` | `speaker_microservice/windows/Scripts/python.exe` |
| brain | 7999 | `brain_microservice/` | `brain_microservice/windows/Scripts/python.exe` |

### Startup Commands

Each service is started by running `main.py` with the service's own Python interpreter:

```
# Windows — using checked-in venvs
<project_root>/<service>/windows/Scripts/python.exe <project_root>/<service>/main.py

# Linux / Generic — using a standard venv or system Python
python <project_root>/<service>/main.py
```

There is no unified launcher script. Each service must be started as a separate process.

### Required Startup Sequence

**Strict ordering is required.**

1. `microphone_microservice` (port 8000)
2. `stt_microservice` (port 8001)
3. `tts_microservice` (port 8002)
4. `speaker_microservice` (port 8003)
5. `brain_microservice` (port 7999) — **must start last**

Services 1–4 can start in any order relative to each other. The brain **must** start after all four are accepting HTTP connections because:

- The brain runs a **startup preflight** that polls `GET /health` (or `GET /available`) on all four services.
- The preflight has a configurable timeout (default 60 seconds). If any service is not reachable within the timeout, the brain aborts startup.
- After preflight passes, the brain automatically starts the voice pipeline as a background task.

### Startup Prerequisites

- Each service reads a `.env` file from its own directory at startup.
- If using OpenAI for STT or TTS, `OPENAI_API_KEY` must be set in the respective `.env` files.
- Microphone and speaker services require a PortAudio-compatible audio input/output device on the host.
- STT in local mode (`STT_ENGINE=local`) requires sufficient CPU/RAM for `faster-whisper` model inference. The model may download on first run.
- TTS in pyttsx3 mode (`TTS_ADAPTER=pyttsx3`) requires an OS speech synthesis engine (SAPI5 on Windows, espeak on Linux).

---

## Runtime Lifecycle

### Initialization Process

Each service follows the same pattern:

1. `main.py` calls `asyncio.run(setup())`.
2. `setup()` loads environment variables from `.env` and VS Code launch profiles.
3. Dependencies are assembled via a composition root / dependency injection container.
4. A FastAPI application is built and routes are registered.
5. A Uvicorn server is created and `await server.serve()` blocks until shutdown.

**Brain-specific initialization** adds two extra steps between 3 and 4:

- **Preflight:** Polls all four external services via HTTP health checks in a loop (default 2-second interval, 60-second timeout). Blocks startup until all services report healthy.
- **Startup pipeline:** After preflight, launches the full voice pipeline (`mic → STT → TTS → speaker`) as an `asyncio.Task` background task.

### Normal Operation

- All five services run indefinitely as long-lived HTTP servers.
- The brain maintains persistent HTTP streaming connections to all four services for the voice pipeline.
- STT and speaker services support optional **autoload workers** — background tasks that automatically connect to an external HTTP stream URL on startup and process it continuously, with infinite reconnect on failure. These are disabled by default (env vars `AUTOLOAD_VOICE_STREAM_URL`, `AUTOLOAD_STREAM_URL` are commented out).
- Each service supports only **one active stream at a time**. Concurrent requests may cancel or replace existing streams.

### Shutdown Process

- All services respond to `KeyboardInterrupt` (Ctrl+C) / SIGINT.
- Uvicorn handles graceful shutdown of the HTTP server.
- **Brain cleanup sequence:**
  1. Cancel background tasks (voice pipeline).
  2. Send `POST /stop` to microphone service to halt audio capture.
  3. Close all outbound HTTP client connections (microphone, STT, TTS, speaker adapters).
- **Microphone cleanup:** If a stream is active, stops it before exiting.
- **Other services:** Minimal cleanup — Uvicorn shutdown is sufficient.

### Recovery Behavior

- No built-in automatic restart for any service.
- No watchdog, supervisor, or process manager is included.
- The brain does **not** automatically reconnect if an external service crashes during operation. The voice pipeline task will fail and log the error.
- The brain **does not** restart the pipeline after failure unless the entire brain process is restarted.

### Restart Requirements

- Services can be restarted independently.
- If the brain is restarted, it re-runs the preflight check and re-establishes all stream connections.
- If a peripheral service (microphone, STT, TTS, speaker) is restarted, the brain's active pipeline will fail. The brain must be restarted to re-establish the pipeline.
- No state is persisted across restarts.

---

## Service Dependencies

### Inter-Service Dependencies

| Dependency | Required By | Required Before Startup | Can Reconnect Dynamically | Optional |
|---|---|---|---|---|
| Microphone HTTP (8000) | Brain | Yes (preflight) | No | No |
| STT HTTP (8001) | Brain | Yes (preflight) | No | No |
| TTS HTTP (8002) | Brain | Yes (preflight) | No | No |
| Speaker HTTP (8003) | Brain | Yes (preflight) | No | No |

### External API Dependencies

| Dependency | Required By | Required Before Startup | Can Reconnect Dynamically | Optional |
|---|---|---|---|---|
| OpenAI Audio Transcriptions API (`api.openai.com`) | STT | No (checked at request time) | Yes | Yes — only when `STT_ENGINE=openai` |
| OpenAI Audio Speech API (`api.openai.com/v1/audio/speech`) | TTS | No (checked at request time) | Yes | Yes — only when `TTS_ADAPTER=openai` |

### System Dependencies

| Dependency | Required By | Required Before Startup | Optional |
|---|---|---|---|
| PortAudio system libraries | Microphone, Speaker | Yes | No |
| Audio input device (microphone) | Microphone | Yes | No |
| Audio output device (speaker/headphones) | Speaker | Yes | No |
| Python 3.11+ runtime | All | Yes | No |
| OS speech engine (SAPI5/espeak) | TTS (pyttsx3 mode) | Yes | Yes — only when `TTS_ADAPTER=pyttsx3` |
| `faster-whisper` model files | STT (local mode) | Downloaded on first use | Yes — only when `STT_ENGINE=local` |
| Internet access | STT (openai), TTS (openai) | No | Yes — only for OpenAI modes |
| Temp file write access | STT (openai), TTS (pyttsx3) | Yes | No — required for temp WAV files |

---

## Resource Usage

### Network Ports

| Port | Service | Configurable Via | Protocol |
|---|---|---|---|
| 7999 | Brain | `SERVICE_PORT` env var | HTTP (TCP) |
| 8000 | Microphone | Hardcoded in setup.py | HTTP (TCP) |
| 8001 | STT | `SERVICE_PORT` env var | HTTP (TCP) |
| 8002 | TTS | `SERVICE_PORT` env var | HTTP (TCP) |
| 8003 | Speaker | `SERVICE_PORT` env var | HTTP (TCP) |

**Note:** The microphone service has its port hardcoded to `8000` in `setup.py` (not read from `.env`).

### Bind Address

All services bind to `127.0.0.1` by default. Configurable via `SERVICE_HOST` env var (except microphone, which is hardcoded to `127.0.0.1`).

### Filesystem Paths

| Path | Service | Purpose | Persistent |
|---|---|---|---|
| `<service>/windows/` | All (Windows) | Checked-in Python virtual environments | Yes (dev only) |
| `<service>/.env` | All | Runtime configuration | Yes |
| System temp directory | STT, TTS | Temporary WAV files created/deleted per utterance | No |
| HuggingFace cache (`~/.cache/huggingface/`) | STT (local mode) | `faster-whisper` model cache | Yes |

### Hardware Devices

| Device | Service | Access Type |
|---|---|---|
| Audio input (microphone) | Microphone | Exclusive via PortAudio/sounddevice |
| Audio output (speaker) | Speaker | Exclusive via PortAudio/sounddevice |

---

## Conflict Analysis

### Port Conflicts

| Resource | Conflict Scenario | Mitigation |
|---|---|---|
| TCP port 7999 | Another service or a second brain instance binds the same port | Change `SERVICE_PORT` in brain `.env` |
| TCP port 8000 | Another service or a second microphone instance binds the same port | **Cannot be changed via env** — hardcoded in `microphone_microservice/composition_root/setup/setup.py`. Requires code change. |
| TCP port 8001 | Another service or a second STT instance binds the same port | Change `SERVICE_PORT` in STT `.env` |
| TCP port 8002 | Another service or a second TTS instance binds the same port | Change `SERVICE_PORT` in TTS `.env` |
| TCP port 8003 | Another service or a second speaker instance binds the same port | Change `SERVICE_PORT` in speaker `.env` |

### Hardware Device Conflicts

| Resource | Conflict Scenario | Mitigation |
|---|---|---|
| Audio input device | Microphone service holds exclusive access via PortAudio. A second microphone instance or another application capturing the same device will fail. | Only run one microphone instance per physical input device. Use `SPEAKER_DEVICE_INDEX` / `SPEAKER_DEVICE_KEYWORDS` to select specific devices if multiple are available. |
| Audio output device | Speaker service holds exclusive access via PortAudio. Same constraint as above. | Only run one speaker instance per physical output device. |

### Shared Files

| Resource | Conflict Scenario | Mitigation |
|---|---|---|
| `.env` files | Multiple instances of the same service reading/writing the same `.env` file | Use separate working directories or override env vars via process environment |
| System temp directory | Multiple STT/TTS instances writing temp WAV files simultaneously | Files use unique names (no conflict expected), but concurrent writes to the same temp dir could cause I/O contention |

### Cross-Project Conflicts

| Resource | Conflict Scenario | Mitigation |
|---|---|---|
| Ports 7999–8003 | Other projects in `D:\Hobbys\IA\Full_Ai_Agent\` contain related microservices that may use the same ports | Ensure only one set of services runs at a time, or change ports via env vars |

---

## Concurrency Rules

**Classification: Single Instance Only**

Reasoning:

- Each service supports only **one active stream at a time**. Concurrent requests cancel or replace existing streams.
- The microphone and speaker services require **exclusive access** to hardware audio devices.
- The microphone service port is **hardcoded** — two instances would fail to bind.
- The brain assumes exactly one instance of each external service at the configured URLs.
- There is no load balancer, service discovery, or multi-instance coordination.

---

## Startup Ordering

### Dependency Graph

```
microphone (8000) ──┐
stt        (8001) ──┤
tts        (8002) ──├──> brain (7999)
speaker    (8003) ──┘
```

### Ordering Rules

| Service | Must Start Before | Must Start After | Can Start Independently |
|---|---|---|---|
| Microphone | Brain | — | Yes (among peers) |
| STT | Brain | — | Yes (among peers) |
| TTS | Brain | — | Yes (among peers) |
| Speaker | Brain | — | Yes (among peers) |
| Brain | — | Microphone, STT, TTS, Speaker | No |

### Startup Phases

1. **Phase 1** (parallel): Start microphone, STT, TTS, speaker simultaneously.
2. **Phase 2** (sequential): Wait for all Phase 1 services to be accepting HTTP connections.
3. **Phase 3**: Start brain. Its preflight will validate all dependencies are ready.

---

## Health Monitoring

### Health Endpoints

| Service | Endpoint | Method | Healthy Response |
|---|---|---|---|
| Brain | `/health` | GET | HTTP 200 JSON `{"status":"success"}` |
| Brain | `/integrations/health` | GET | HTTP 200 JSON with `data.all_available: true` |
| Microphone | `/health` | GET | HTTP 200 |
| STT | `/available` | GET | HTTP 200 JSON with `data.is_available: true` |
| STT | `/health` (fallback) | GET | HTTP 200 |
| TTS | `/available` | GET | HTTP 200 JSON with `data.is_available: true` |
| TTS | `/health` (fallback) | GET | HTTP 200 |
| Speaker | `/health` | GET | HTTP 200 |

### Recommended Health Check Strategy

- **Liveness:** `GET /health` on each service. Returns 200 if the HTTP server is running.
- **Readiness (brain only):** `GET /integrations/health` validates all downstream services are reachable and responsive.
- **Deep health:** Brain's `/integrations/health` is the single check that validates the entire system is wired correctly.

### Log-Based Monitoring

- All services log structured messages at startup, during operation, and at shutdown.
- Log levels are environment-dependent: `development` = all, `staging` = warnings+, `production` = critical only.
- Key log markers:
  - `"startup preflight completed successfully"` — brain ready.
  - `"voice pipeline started"` — pipeline active.
  - `"voice pipeline failed"` — pipeline crashed.
  - `"keyboard interrupt received"` — graceful shutdown initiated.

---

## Failure Recovery

### Safe Restart Procedure

1. Send SIGINT (Ctrl+C) to the brain first. This triggers cleanup (stop microphone, close connections).
2. Send SIGINT to the remaining four services in any order.
3. Restart in the correct startup order: microphone → STT → TTS → speaker → brain.

### Dependency Recovery

- If a peripheral service crashes (e.g., STT dies):
  1. The brain's active pipeline will encounter an HTTP error and fail.
  2. Restart the crashed service.
  3. Restart the brain to re-run preflight and re-establish the pipeline.
- The brain does **not** auto-recover from downstream failures.

### Crash Recovery Requirements

- No persistent state to recover. All stream state is ephemeral.
- Temporary WAV files in the system temp directory may be orphaned after a crash. These can be safely deleted.
- `faster-whisper` model cache is durable and does not need recovery.
- OpenAI API keys in `.env` files are unaffected by crashes.

### Data Integrity Considerations

- No databases. No persistent data.
- Audio streams are ephemeral — a crash loses in-flight audio and transcriptions.
- There is no replay, journaling, or durable queue between services.

---

## Containerization Notes

### Host Networking

- All inter-service communication uses `127.0.0.1`. In Docker Compose, **replace loopback addresses with service names** or use host networking.
- The brain's env vars (`MICROPHONE_BASE_URL`, `STT_BASE_URL`, `TTS_BASE_URL`, `SPEAKER_BASE_URL`) must be updated to point to container service names (e.g., `http://microphone:8000`).

### Privileged Mode / Device Passthrough

| Service | Requirement | Reason |
|---|---|---|
| Microphone | Host audio device passthrough | PortAudio needs access to the host microphone. On Linux: mount ALSA/PulseAudio/PipeWire sockets. On Windows: not straightforward in containers. |
| Speaker | Host audio device passthrough | PortAudio needs access to the host audio output. Same constraints as microphone. |
| TTS (pyttsx3) | OS speech engine | Requires SAPI5 (Windows) or espeak (Linux) installed in the container. |

### Volume Mounts

| Volume | Service | Purpose |
|---|---|---|
| `.env` file or environment injection | All | Configuration. Prefer Docker env vars or secrets over mounting `.env` files. |
| `/tmp` or equivalent | STT, TTS | Temporary WAV file creation. Default container temp is usually sufficient. |
| HuggingFace cache dir | STT (local) | Persist `faster-whisper` model downloads across container restarts. |
| ALSA/PulseAudio socket | Microphone, Speaker | Audio device access on Linux (e.g., `/run/user/1000/pulse/native`). |

### Environment Variables

All services require at minimum:

- `APP_ENV` — runtime environment (`development`, `staging`, `production`).
- `SERVICE_HOST` — bind address (set to `0.0.0.0` in containers to accept connections from other containers).
- `SERVICE_PORT` — bind port.

Brain additionally requires:

- `MICROPHONE_BASE_URL`, `STT_BASE_URL`, `TTS_BASE_URL`, `SPEAKER_BASE_URL` — set to Docker Compose service names.

STT and TTS additionally require (for OpenAI mode):

- `OPENAI_API_KEY` — **inject via Docker secrets, not baked into images.**
- `STT_ENGINE` / `TTS_ADAPTER` — engine selection.

### Key Constraints

- **No Dockerfiles or docker-compose.yml exist** in the project.
- **The `windows/` virtual environments** are platform-specific and must not be copied into containers. Build fresh venvs from `requirements.linux.txt` or `requirements.windows.txt`.
- **Dependencies are not version-pinned** — a lockfile should be generated for reproducible container builds.

---

## Orchestration Recommendations

### Start Priority

| Priority | Service | Reason |
|---|---|---|
| 1 (highest) | Microphone | No dependencies; hardware init may be slow. |
| 1 | STT | No dependencies; model download may be slow on first run (local mode). |
| 1 | TTS | No dependencies. |
| 1 | Speaker | No dependencies; hardware init may be slow. |
| 2 (lowest) | Brain | Depends on all four services being healthy. |

### Restart Policy

| Service | Recommended Policy | Reason |
|---|---|---|
| Microphone | `on-failure` with backoff | Hardware device may not be immediately available. |
| STT | `on-failure` with backoff | May fail on first run during model download. |
| TTS | `on-failure` with backoff | Generally stable; restart on unexpected failure. |
| Speaker | `on-failure` with backoff | Hardware device may not be immediately available. |
| Brain | `on-failure` with backoff | Should restart after peripheral services recover. Preflight handles dependency waiting. |

### Health-Check Strategy

- Use HTTP `GET /health` as liveness probe for all services (interval: 10s, timeout: 5s, retries: 3).
- Use Brain's `GET /integrations/health` as a system-level readiness probe.
- The brain's built-in preflight (60s timeout, 2s poll) serves as a startup probe. External orchestrators should set a startup grace period of at least 90 seconds for the brain.

### Scaling Limitations

- **Cannot scale horizontally.** Single-instance design per service.
- **Cannot run multiple pipeline instances** — one active stream per service.
- Hardware-bound services (microphone, speaker) are limited to one instance per physical device.

### Isolation Requirements

- Microphone and speaker services need host-level hardware access.
- STT and TTS can run in fully isolated containers (no hardware requirements) when using OpenAI mode.
- STT in local mode (`faster-whisper`) is CPU-intensive and may benefit from resource limits/reservations.
- All services communicate exclusively over HTTP — no shared memory, IPC, or message queues.

---

## Execution Metadata

```yaml
project_name: FULL_OBLIVION
startup_command:
  microphone: "python microphone_microservice/main.py"
  stt: "python stt_microservice/main.py"
  tts: "python tts_microservice/main.py"
  speaker: "python speaker_microservice/main.py"
  brain: "python brain_microservice/main.py"
working_directory:
  microphone: "microphone_microservice/"
  stt: "stt_microservice/"
  tts: "tts_microservice/"
  speaker: "speaker_microservice/"
  brain: "brain_microservice/"
startup_dependencies:
  microphone: []
  stt: []
  tts: []
  speaker: []
  brain: [microphone, stt, tts, speaker]
runtime_dependencies:
  microphone: [portaudio, audio_input_device]
  stt: [openai_api_or_faster_whisper]
  tts: [openai_api_or_pyttsx3]
  speaker: [portaudio, audio_output_device]
  brain: [microphone_http, stt_http, tts_http, speaker_http]
ports:
  microphone: 8000
  stt: 8001
  tts: 8002
  speaker: 8003
  brain: 7999
volumes:
  - ".env files per service"
  - "/tmp (STT and TTS temp WAV files)"
  - "~/.cache/huggingface (STT local mode model cache)"
  - "ALSA/PulseAudio socket (microphone and speaker on Linux)"
devices:
  microphone: [audio_input]
  speaker: [audio_output]
exclusive_resources:
  - "TCP port 8000 (microphone, hardcoded)"
  - "TCP port 8001 (stt)"
  - "TCP port 8002 (tts)"
  - "TCP port 8003 (speaker)"
  - "TCP port 7999 (brain)"
  - "Audio input device (microphone)"
  - "Audio output device (speaker)"
health_checks:
  microphone: "GET http://127.0.0.1:8000/health -> 200"
  stt: "GET http://127.0.0.1:8001/available -> 200"
  tts: "GET http://127.0.0.1:8002/available -> 200"
  speaker: "GET http://127.0.0.1:8003/health -> 200"
  brain: "GET http://127.0.0.1:7999/health -> 200"
  brain_deep: "GET http://127.0.0.1:7999/integrations/health -> 200 + all_available=true"
restart_policy: "on-failure with backoff"
supports_multiple_instances: false
startup_priority:
  microphone: 1
  stt: 1
  tts: 1
  speaker: 1
  brain: 2
shutdown_priority:
  brain: 1
  microphone: 2
  stt: 2
  tts: 2
  speaker: 2
container_requirements:
  microphone: "host audio device passthrough, host networking or service discovery"
  stt: "CPU/RAM for local inference, or internet access for OpenAI"
  tts: "espeak/SAPI5 for pyttsx3, or internet access for OpenAI"
  speaker: "host audio device passthrough, host networking or service discovery"
  brain: "network access to all four services, SERVICE_HOST=0.0.0.0"
```

---

## Unknown Information

- **Target production platform:** Code references both Windows development (SAPI5, checked-in `windows/` venvs) and Linux/Raspberry Pi production (device keywords like `i2s`, `hw`; Linux requirements with PortAudio system packages). The exact production hardware is not defined.
- **Production environment files:** `.env.production` exists for microphone and TTS but not for brain, STT, or speaker. Production-specific configuration is incomplete.
- **Microphone port configurability:** Port 8000 is hardcoded in `microphone_microservice/composition_root/setup/setup.py`. It is unclear whether this is intentional or an oversight — all other services read the port from env vars.
- **Microphone bind address configurability:** Similarly hardcoded to `127.0.0.1` in the microphone setup.
- **`faster-whisper` model cache location:** Not configured by the application. Depends on external HuggingFace/CTranslate2 caching defaults.
- **Python version compatibility:** Development uses Python 3.14 (based on bytecode tags). Compatibility of ML dependencies (`faster-whisper`, `ctranslate2`, `onnxruntime`) with Python 3.14 is unverified.
- **PCM byte order:** Little-endian is inferred from test code but not explicitly declared.
- **Network topology for production:** Whether services run on the same host, across a LAN, or in containers is not defined.
- **AI/LLM processing between STT and TTS:** The brain currently bridges STT text directly to TTS. Whether an LLM step is planned between them is not evident.
- **CORS configuration:** `ALLOWED_ORIGINS` is configured in speaker `.env` but CORS middleware registration is not confirmed for all services.
- **Graceful shutdown timeout:** Uvicorn's default shutdown timeout is used. No explicit `timeout_graceful_shutdown` is configured.
- **Brain pipeline auto-restart:** The brain's `STARTUP_INTERNAL_PIPELINE_RESTART_DELAY_SECONDS` env var exists but its implementation behavior (whether it auto-restarts the pipeline on failure) is not confirmed in the current code.
