# FULL_OBLIVION

## Project Summary

- **Project name:** FULL_OBLIVION
- **Short description:** Multi-microservice voice AI agent platform that captures audio from a local microphone, transcribes speech to text, synthesizes text to speech, and plays audio through a local speaker — all coordinated by a central brain orchestrator.
- **Main purpose:** Provide a real-time, streaming voice pipeline where a user speaks into a microphone and the system processes speech end-to-end through STT, optional AI processing, TTS, and speaker playback.
- **Key functionality:**
  - Real-time microphone audio capture and streaming
  - Speech-to-Text via OpenAI Whisper API or local faster-whisper
  - Text-to-Speech via OpenAI TTS API or local pyttsx3
  - Audio playback through a local speaker/output device
  - Full voice pipeline orchestration (mic → STT → TTS → speaker)
  - Health checks and integration monitoring across all services
  - Decoupled set/get streaming flows for independent producer/consumer patterns

## How It Works

### Main Components

The project consists of five independent Python FastAPI microservices, each running its own Uvicorn HTTP server:

| Microservice | Default Port | Responsibility |
|---|---|---|
| `brain_microservice` | `7999` | Orchestrator. Wires the voice pipeline, coordinates all other services over HTTP. Does not capture, transcribe, synthesize, or play audio itself. |
| `microphone_microservice` | `8000` | Captures audio from a local microphone using `sounddevice`/PortAudio. Streams PCM audio chunks as base64-encoded NDJSON events. |
| `stt_microservice` | `8001` | Speech-to-Text. Accepts raw PCM audio, detects voice activity, segments utterances by silence, and returns transcribed text. Supports OpenAI Whisper (`whisper-1`) or local `faster-whisper` (`small.en`). |
| `tts_microservice` | `8002` | Text-to-Speech. Accepts text stream events and returns synthesized audio bytes. Supports OpenAI TTS API (`gpt-4o-mini-tts`) or local `pyttsx3` subprocess. |
| `speaker_microservice` | `8003` | Plays raw signed 16-bit PCM audio through a local output device using `sounddevice`/PortAudio. |

### Application Flow

The full voice pipeline runs as follows:

```
User speaks → Microphone (8000) → Brain (7999) → STT (8001) → Brain → TTS (8002) → Brain → Speaker (8003) → User hears
```

In detail:

1. Brain starts the microphone stream (`POST /start` on microphone).
2. Microphone captures PCM audio, detects silence, and streams base64-encoded audio events.
3. Brain bridges microphone output to STT input (`POST /process/stream/set` on STT).
4. STT segments audio by voice activity, transcribes utterances, and pushes text to a shared queue.
5. Brain reads STT text output (`GET /process/stream/get` on STT).
6. Brain bridges STT text output to TTS input (`POST /process/stream/set` on TTS).
7. TTS synthesizes speech and streams audio bytes.
8. Brain reads TTS audio output (`GET /process/stream/get` on TTS).
9. Brain bridges TTS audio output to Speaker input (`POST /process/stream/set` on Speaker).
10. Speaker plays audio through the local output device.

All inter-service communication uses HTTP streaming with a standardized JSON stream event contract (NDJSON or SSE).

### Important Processes

- **Startup preflight** (brain): Polls all external services for health before starting the voice pipeline. Configurable timeout and poll interval.
- **Voice Activity Detection** (STT): Segments streaming audio into utterances based on volume thresholds and silence duration.
- **Silence detection** (microphone): Suppresses silent audio chunks on the wire; emits `completed` events after 2 seconds of continuous silence.
- **Autoload workers** (STT, TTS, speaker): Optional background tasks that connect to an external HTTP stream URL on startup and process it continuously, with infinite reconnect on failure.
- **Subprocess TTS** (TTS pyttsx3 mode): Generates speech by running `pyttsx3` in a Python subprocess, writing to temporary WAV files, then streaming the WAV content.

### External Communications

- **OpenAI Whisper API** (`api.openai.com`): Used by STT when `STT_ENGINE=openai`. Sends temp WAV files for transcription.
- **OpenAI TTS API** (`api.openai.com/v1/audio/speech`): Used by TTS when `TTS_ADAPTER=openai`. Streams synthesized audio bytes.
- **Inter-service HTTP**: All five microservices communicate via HTTP on `127.0.0.1` by default.

## Startup and Usage

### How the Application Starts

Each microservice is started independently. The brain service must start last because it depends on all other services being available.

**Start order:**

1. `microphone_microservice` (port 8000)
2. `stt_microservice` (port 8001)
3. `tts_microservice` (port 8002)
4. `speaker_microservice` (port 8003)
5. `brain_microservice` (port 7999) — waits for all services via preflight health checks

### Main Entry Points

Every microservice uses the same pattern:

```
main.py → asyncio.run(setup()) → composition_root builds dependencies → Uvicorn serves FastAPI app
```

### Startup Commands (Windows, using checked-in venvs)

```powershell
# Terminal 1 — Microphone
& D:\Hobbys\IA\FULL_OBLIVION\microphone_microservice\windows\Scripts\python.exe D:\Hobbys\IA\FULL_OBLIVION\microphone_microservice\main.py

# Terminal 2 — STT
& D:\Hobbys\IA\FULL_OBLIVION\stt_microservice\windows\Scripts\python.exe D:\Hobbys\IA\FULL_OBLIVION\stt_microservice\main.py

# Terminal 3 — TTS
& D:\Hobbys\IA\FULL_OBLIVION\tts_microservice\windows\Scripts\python.exe D:\Hobbys\IA\FULL_OBLIVION\tts_microservice\main.py

# Terminal 4 — Speaker
& D:\Hobbys\IA\FULL_OBLIVION\speaker_microservice\windows\Scripts\python.exe D:\Hobbys\IA\FULL_OBLIVION\speaker_microservice\main.py

# Terminal 5 — Brain (start last)
& D:\Hobbys\IA\FULL_OBLIVION\brain_microservice\windows\Scripts\python.exe D:\Hobbys\IA\FULL_OBLIVION\brain_microservice\main.py
```

### Required Steps Before Execution

1. Each microservice has a `.env` file with configuration. Copy `.env.example` to `.env` if not present.
2. If using OpenAI for STT or TTS, set `OPENAI_API_KEY` in the respective `.env` files.
3. Ensure a microphone input device and speaker output device are available on the host.
4. Install Python dependencies per microservice if not using the checked-in `windows/` venvs.

## Dependencies

### Required Services (Inter-Service)

| Service | Required By | Purpose |
|---|---|---|
| Microphone (8000) | Brain | Provides live audio capture streams |
| STT (8001) | Brain | Transcribes audio streams to text |
| TTS (8002) | Brain | Synthesizes text to audio streams |
| Speaker (8003) | Brain | Plays audio through local hardware |

### External APIs

| API | Required By | Purpose | When Used |
|---|---|---|---|
| OpenAI Audio Transcriptions API | STT | Remote speech-to-text via Whisper | `STT_ENGINE=openai` |
| OpenAI Audio Speech API | TTS | Remote text-to-speech | `TTS_ADAPTER=openai` |

### System Dependencies

| Dependency | Required By | Purpose |
|---|---|---|
| PortAudio / `sounddevice` | Microphone, Speaker | Audio I/O through OS audio stack |
| Python 3.11+ (3.14 used in dev) | All | Runtime |
| OS speech engine (SAPI5/espeak) | TTS (pyttsx3 mode) | Local text-to-speech synthesis |
| `faster-whisper` / CTranslate2 | STT (local mode) | Local Whisper inference on CPU |

### Python Package Dependencies (per microservice)

**Brain:** `fastapi`, `uvicorn`, `python-dotenv`, `httpx`, `pytest`, `pytest-asyncio`, `debugpy`

**Microphone:** `fastapi`, `uvicorn`, `sounddevice`, `soundfile`, `numpy`, `pytest`

**STT:** `fastapi`, `uvicorn`, `python-dotenv`, `pydantic`, `numpy`, `openai`, `faster-whisper`, `httpx`, `pytest`

**TTS:** `fastapi`, `uvicorn`, `python-dotenv`, `pydantic`, `httpx`, `pyttsx3`

**Speaker:** `fastapi`, `uvicorn`, `python-dotenv`, `httpx`, `sounddevice`, `soundfile`, `numpy`, `pytest`, `websockets`

## Inputs and Outputs

### Data Received

| Microservice | Input | Source | Format |
|---|---|---|---|
| Microphone | Audio signal | Local hardware microphone | Raw PCM via PortAudio |
| STT | Audio bytes | HTTP stream (brain or direct client) | Raw signed 16-bit PCM or NDJSON stream events with base64-encoded PCM |
| TTS | Text | HTTP stream (brain or direct client) | NDJSON stream events with text payloads |
| Speaker | Audio bytes | HTTP stream (brain or direct client) | Raw signed 16-bit PCM body |
| Brain | Orchestration triggers | HTTP client (e.g. `POST /voice/pipeline`) | JSON |

### Data Produced

| Microservice | Output | Destination | Format |
|---|---|---|---|
| Microphone | Audio stream | HTTP response to brain/client | NDJSON or SSE stream events with base64-encoded PCM chunks |
| STT | Transcribed text | HTTP SSE/NDJSON response | Stream events with text payloads |
| TTS | Synthesized audio | HTTP NDJSON response | Stream events with base64-encoded audio chunks |
| Speaker | Playback status | HTTP NDJSON response | `stream_started`, `completed`, `error` events |
| Brain | Pipeline status, health, transcriptions | HTTP JSON response | JSON envelope |

### APIs Exposed

| Microservice | Key Endpoints |
|---|---|
| Brain (7999) | `GET /health`, `GET /integrations/health`, `POST /stt/batch`, `POST /tts/play`, `POST /voice/transcribe`, `POST /voice/pipeline` |
| Microphone (8000) | `GET /health`, `GET /available`, `POST /start`, `POST /stop` |
| STT (8001) | `GET /health`, `GET /available`, `POST /process/batch`, `POST /process/stream`, `POST /process/stream/set`, `GET /process/stream/get` |
| TTS (8002) | `GET /health`, `GET /available`, `POST /process/batch`, `POST /process/stream`, `POST /process/stream/set`, `GET /process/stream/get` |
| Speaker (8003) | `GET /health`, `POST /process/stream/set` |

### Standard Stream Event Contract

All streaming communication uses a standard JSON event shape:

```json
{
  "type": "stream_started | partial | completed | heartbeat | error",
  "sequence": 1,
  "timestamp": "2026-05-24T12:00:00Z",
  "payload": {}
}
```

Wire format is NDJSON (`application/x-ndjson`) for most endpoints, or SSE (`text/event-stream`) for STT output.

## Runtime Requirements

| Requirement | Microservices Affected | Notes |
|---|---|---|
| Local microphone device | Microphone | PortAudio-compatible input device |
| Local speaker/output device | Speaker | PortAudio-compatible output device |
| Internet access | STT (openai mode), TTS (openai mode) | OpenAI API calls |
| Local network (loopback) | All | Inter-service HTTP on `127.0.0.1` |
| Sufficient CPU/RAM | STT (local mode) | `faster-whisper` `small.en` model inference |
| PortAudio system libraries | Microphone, Speaker | On Linux: `portaudio19-dev`, `python3-pyaudio`, `python3-sounddevice` |
| OS speech engine | TTS (pyttsx3 mode) | SAPI5 on Windows, espeak on Linux |
| Temp file write access | STT (openai mode), TTS (pyttsx3 mode) | Temporary WAV files created and deleted per utterance |

## Deployment Notes

### Required Ports

| Port | Service | Configurable Via |
|---|---|---|
| 7999 | Brain | `SERVICE_PORT` in brain `.env` |
| 8000 | Microphone | `SERVICE_PORT` in microphone `.env` |
| 8001 | STT | `SERVICE_PORT` in stt `.env` |
| 8002 | TTS | `SERVICE_PORT` in tts `.env` |
| 8003 | Speaker | `SERVICE_PORT` in speaker `.env` |

### Key Environment Variables

| Variable | Used By | Purpose |
|---|---|---|
| `APP_ENV` | All | Runtime environment (`development`, `staging`, `production`) |
| `SERVICE_HOST` | All | Bind address (default `127.0.0.1`) |
| `SERVICE_PORT` | All | Bind port (varies per service) |
| `STT_ENGINE` | STT | `openai` or `local` |
| `TTS_ADAPTER` | TTS | `openai` or `pyttsx3` |
| `OPENAI_API_KEY` | STT, TTS | Required for OpenAI modes |
| `OPENAI_TTS_MODEL` | TTS | OpenAI model (default `gpt-4o-mini-tts`) |
| `OPENAI_TTS_VOICE` | TTS | OpenAI voice (default `alloy`) |
| `TTS_SPEECH_RATE` | TTS | Local pyttsx3 speech rate (default `140`) |
| `TTS_VOICE_NAME` | TTS | Local pyttsx3 voice name (default `Zira`) |
| `SPEAKER_DEVICE_INDEX` | Speaker | Explicit output device index (empty = auto-detect) |
| `SPEAKER_DEVICE_KEYWORDS` | Speaker | Keywords for device auto-selection |
| `AUTOLOAD_STREAM_URL` | Speaker | Optional auto-connect to external audio stream |
| `AUTOLOAD_VOICE_STREAM_URL` | STT | Optional auto-connect to external audio stream |
| `MICROPHONE_BASE_URL` | Brain | Microphone service URL |
| `STT_BASE_URL` | Brain | STT service URL |
| `TTS_BASE_URL` | Brain | TTS service URL |
| `SPEAKER_BASE_URL` | Brain | Speaker service URL |
| `STARTUP_PREFLIGHT_ENABLED` | Brain | Enable health polling before pipeline start |
| `STARTUP_PREFLIGHT_TIMEOUT_SECONDS` | Brain | Max wait for all services (default `60`) |

### Persistent Storage

- No databases are used by any microservice.
- No persistent file storage. Temporary WAV files are created and deleted during STT/TTS processing.
- `faster-whisper` model files may be cached by external Hugging Face mechanisms.

### Docker Containerization Challenges

- **Microphone service** requires access to the host audio input device (PortAudio). On Linux, this means mapping ALSA/PulseAudio/PipeWire sockets. On Windows, direct hardware access is not straightforward in containers.
- **Speaker service** requires access to the host audio output device (PortAudio). Same constraints as microphone.
- **TTS pyttsx3 mode** requires an OS speech synthesis engine (SAPI5 on Windows, espeak on Linux). Containers would need these installed.
- **STT local mode** requires sufficient CPU/RAM for `faster-whisper` inference. Model download may occur on first run.
- **Inter-service networking** is currently hardcoded to `127.0.0.1`. In Docker Compose, service names or a shared network must replace loopback addresses.
- **No Dockerfiles or docker-compose.yml exist** in any microservice.
- **No CI/CD pipelines** exist.
- **Dependencies are not version-pinned** (only lower bounds). A lock file should be generated for reproducible builds.
- **The `windows/` virtual environments** checked into each microservice are platform-specific and should not be copied into containers.

### Recommended Docker Compose Topology

```
brain (7999) ──HTTP──> microphone (8000)
              ──HTTP──> stt (8001)
              ──HTTP──> tts (8002)
              ──HTTP──> speaker (8003)
```

The brain container needs network access to all four other containers. Microphone and speaker containers need host audio device access. STT and TTS containers may need internet access for OpenAI API calls, or sufficient CPU for local inference.

## Related Projects

- The brain microservice `docs/` folder contains contract documentation for all external microservices (`README_MICROPHONE.md`, `README_STT.md`, `README_TTS.md`, `README_SPEAKER.md`).
- The STT microservice autoloader is configured to consume from `http://127.0.0.1:8000/start` (microphone service).
- The speaker microservice autoloader is configured to consume from `http://127.0.0.1:8002/process/stream/get` (TTS service).
- Indexed codebases at `D:\Hobbys\IA\Full_Ai_Agent\` contain earlier or related versions of some microservices (`brain_microservice`, `stt_microservice`, `tts_microservice`).

## Important Notes

- **No authentication or authorization** is implemented on any endpoint. Any client that can reach the ports can start microphone capture, trigger transcription, incur OpenAI API costs, or play audio.
- **Checked-in `.env` files contain real OpenAI API keys.** These should be rotated and excluded from version control.
- **Each microservice has a checked-in `windows/` Python virtual environment.** These are large, platform-specific, and should not be used in production deployment.
- **Audio format assumption:** All services assume raw signed 16-bit PCM audio. There is no container format (WAV/MP3/Opus) on the wire between services.
- **Single-instance design:** Each microservice supports only one active stream at a time. Concurrent requests may cancel or replace existing streams.
- **The brain starts the voice pipeline automatically during startup** (configurable via `STARTUP_INTERNAL_PIPELINE_ENABLED`).
- **VS Code launch profiles** are configured for each microservice with development/staging/production environment selection.
- **Log filtering** varies by environment: development shows all logs, staging shows warnings+, production shows only critical.

## Unknown Information

- **Target deployment platform:** Code structure suggests both Windows development and Linux/Raspberry Pi production (device keywords like `i2s`, `hw`; Linux requirement files with PortAudio system packages). The exact production hardware is unknown.
- **Production environment configuration:** `.env.production` and `.env.staging` files are referenced in VS Code launch profiles but not present in all microservices.
- **`faster-whisper` model cache location:** Not configured by the application. Model download behavior depends on external Hugging Face/CTranslate2 caching.
- **Python version compatibility:** Development uses Python 3.14 (based on `__pycache__` bytecode tags). Compatibility of all ML dependencies (`faster-whisper`, `ctranslate2`, `onnxruntime`) with Python 3.14 is unverified.
- **Exact PCM byte order:** Little-endian is inferred from test code but not explicitly declared by any service.
- **Network topology for production:** Whether services run on the same host, across a local network, or in containers is not defined.
- **Scaling strategy:** No load balancing, service discovery, or multi-instance support is implemented.
- **AI/LLM processing between STT and TTS:** The brain currently bridges STT text directly to TTS. Whether an LLM or other AI processing step is planned between them is not evident in the current code.
- **CORS behavior:** `ALLOWED_ORIGINS` is configured but CORS middleware is not registered in the speaker service. Status in other services is unknown.
