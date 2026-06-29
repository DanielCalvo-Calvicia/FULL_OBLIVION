# FULL_OBLIVION Service Selection Guide

Docker Compose profiles control which microservices are active.

## Profiles

| Profile | Services | Use Case |
|---|---|---|
| `full` | brain, microphone, stt, tts, speaker | Complete voice pipeline |
| `brain` | brain | Orchestrator using configured dependency URLs |
| `microphone` | microphone | Standalone audio capture |
| `stt` | stt | Standalone transcription |
| `tts` | tts | Standalone synthesis |
| `speaker` | speaker | Standalone playback |
| `audio` | microphone, speaker | Audio I/O pair |
| `transcription` | stt | Alias for STT |
| `synthesis` | tts | Alias for TTS |

## Examples

Full voice pipeline:

```bash
docker compose --profile full up -d
```

Brain-only deployment for remote or already-running dependencies:

```bash
docker compose --profile brain up -d
```

Software-only STT/TTS:

```bash
docker compose --profile stt --profile tts up -d
```

Standalone TTS:

```bash
docker compose --profile tts up -d
```

## Dependency URLs

`brain` depends on all four peripheral services:

- `microphone`
- `stt`
- `tts`
- `speaker`

Those dependencies may be local Compose services or remote services on other machines. Configure them in `.env`:

```ini
MICROPHONE_BASE_URL=http://microphone:8000
STT_BASE_URL=http://stt:8001
TTS_BASE_URL=http://tts:8002
SPEAKER_BASE_URL=http://speaker:8003
```

For distributed hosts, use LAN IPs or DNS names:

```ini
MICROPHONE_BASE_URL=http://192.168.1.20:8000
STT_BASE_URL=http://192.168.1.30:8001
TTS_BASE_URL=http://192.168.1.30:8002
SPEAKER_BASE_URL=http://192.168.1.31:8003
```

Brain performs startup preflight against these URLs and waits for the configured services.

## Selection Rules

| Requested | Deployed | Reason |
|---|---|---|
| `full` | all services | Full pipeline profile includes every service |
| `brain` | brain | Dependencies are addressed by configured URLs |
| `brain` + `full` | all services | Same-host full Compose pipeline |
| `stt` | stt | STT has no service dependency |
| `tts` | tts | TTS has no service dependency |
| `audio` | microphone, speaker | Audio profile groups hardware I/O services |
| `stt` + `tts` | stt, tts | Software-only processing |

## Scaling Rules

Do not use `replicas` or multiple containers for any service. The current services support one active stream each, and microphone/speaker require exclusive hardware access.

## Platform Guidance

Linux can run the full stack when audio device passthrough is configured.

Windows and macOS should use software-only profiles in Docker, or run microphone/speaker natively on the host for audio hardware access. For multi-host deployments, expose each native service on a LAN-reachable bind address and update brain's base URLs.
