# FULL_OBLIVION Deployment Guide

This deployment system runs the FULL_OBLIVION microservices with Docker Compose profiles. It supports same-host container deployment and hybrid LAN deployment where services run on different machines, such as a Windows host for the microphone and a Raspberry Pi for STT, TTS, or speaker.

Full containerized audio deployment is best suited to a Linux Docker host. Windows and macOS Docker Desktop do not provide reliable host microphone/speaker passthrough, so run hardware-bound services natively on those platforms when needed.

## Prerequisites

- Docker Engine 24+ with Docker Compose v2.
- Git.
- Internet access for repository clones, image builds, and OpenAI-backed STT/TTS modes.
- Linux audio hardware access for full containerized microphone/speaker use.
- Root `.env` configured from `.env.example`. Use `STT_OPENAI_API_KEY` when `STT_ENGINE=openai` and `TTS_OPENAI_API_KEY` when `TTS_ADAPTER=openai`.

## Bootstrap

For a single command from scratch, use:

```powershell
.\scripts\start.ps1 -Scenario full
```

```bash
./scripts/start.sh full
```

Available scenarios are `full`, `brain-remote`, `windows-audio`, `windows-speaker`, `software-only`, `audio-only`, and `raspberry-services`.

Use `windows-audio` when `microphone_microservice` and `speaker_microservice` are running natively in VS Code on Windows and Docker should start brain, STT, and TTS:

```powershell
.\scripts\start.ps1 -Scenario windows-audio
```

This sets:

```ini
BRAIN_MICROPHONE_BASE_URL=http://host.docker.internal:8000
BRAIN_SPEAKER_BASE_URL=http://host.docker.internal:8003
BRAIN_STARTUP_PREFLIGHT_ENABLED=false
```

Use `windows-speaker` when `speaker_microservice` is running natively in VS Code on Windows and Docker should start brain, microphone, STT, and TTS:

```powershell
.\scripts\start.ps1 -Scenario windows-speaker
```

This sets `BRAIN_SPEAKER_BASE_URL=http://host.docker.internal:8003` and `BRAIN_STARTUP_PREFLIGHT_ENABLED=false` for the Docker run.

Manual bootstrap commands are also available when you want separate control over cloning and starting.

PowerShell:

```powershell
.\scripts\repo\bootstrap.ps1
```

Bash:

```bash
./scripts/repo/bootstrap.sh
```

Bootstrap creates `repos/`, clones the five service repositories, creates root `.env` from `.env.example` if needed, copies generated Dockerfiles from `dockerfiles/` into the cloned repositories, and builds the full stack.

Run bootstrap before any `scripts/run/*` execution script. The run scripts expect build contexts such as `repos/tts_microservice` to exist.

To clone and prepare files without building:

```powershell
.\scripts\repo\bootstrap.ps1 -SkipBuild
```

```bash
./scripts/repo/bootstrap.sh --skip-build
```

## Configuration

Edit root `.env` before starting services. This is the only Compose env source. Docker Compose reads `D:\Hobbys\IA\FULL_OBLIVION\.env` and maps those root values into each container using the exact original project env var names.

Do not rely on `.env` files inside `repos/<service>_microservice/`. They are not required for Docker Compose and are not expected to exist after a clean GitHub clone.

The most common settings are:

```ini
STT_OPENAI_API_KEY=
STT_ENGINE=openai

TTS_OPENAI_API_KEY=
TTS_ADAPTER=openai

BRAIN_MICROPHONE_BASE_URL=http://microphone:8000
BRAIN_STT_BASE_URL=http://stt:8001
BRAIN_TTS_BASE_URL=http://tts:8002
BRAIN_SPEAKER_BASE_URL=http://speaker:8003
```

Docker Compose uses the original internal service ports `7999` through `8003`.

For distributed hosts, replace dependency URLs with LAN-reachable addresses from the brain container or process:

```ini
BRAIN_MICROPHONE_BASE_URL=http://192.168.1.20:8000
BRAIN_STT_BASE_URL=http://192.168.1.30:8001
BRAIN_TTS_BASE_URL=http://192.168.1.30:8002
BRAIN_SPEAKER_BASE_URL=http://192.168.1.31:8003
```

## From Scratch Compose Generation

Use this sequence when the workspace starts with no cloned service repositories and no generated Compose build contexts:

1. Clone and prepare every service:

```powershell
.\scripts\repo\bootstrap.ps1 -SkipBuild
```

```bash
./scripts/repo/bootstrap.sh --skip-build
```

This creates `repos/brain_microservice`, `repos/microphone_microservice`, `repos/stt_microservice`, `repos/tts_microservice`, and `repos/speaker_microservice`.

2. Generate the root env file:

```powershell
Copy-Item .env.example .env
```

```bash
cp .env.example .env
```

Bootstrap performs this step automatically when `.env` is missing. Edit the root `.env` after it exists.

3. Set service-scoped root variables in `.env`.

For OpenAI-backed STT/TTS, set:

```ini
STT_OPENAI_API_KEY=
TTS_OPENAI_API_KEY=
```

For Brain dependency routing, set:

```ini
BRAIN_MICROPHONE_BASE_URL=http://microphone:8000
BRAIN_STT_BASE_URL=http://stt:8001
BRAIN_TTS_BASE_URL=http://tts:8002
BRAIN_SPEAKER_BASE_URL=http://speaker:8003
```

Compose then injects those values into the Brain container as the original names `MICROPHONE_BASE_URL`, `STT_BASE_URL`, `TTS_BASE_URL`, and `SPEAKER_BASE_URL`.

4. Refresh generated Dockerfiles into the cloned repos:

```powershell
.\scripts\repo\update.ps1
```

```bash
./scripts/repo/update.sh
```

The canonical generated Dockerfiles live in `dockerfiles/*.Dockerfile`. The cloned repos receive working copies at `repos/<service>_microservice/Dockerfile`, and `docker-compose.yml` builds from the canonical `dockerfiles/*.Dockerfile` paths.

5. Validate the rendered Compose file:

```powershell
docker compose --profile full config --quiet
```

```bash
docker compose --profile full config --quiet
```

6. Build and start the desired profile:

```powershell
docker compose --profile full up -d --build
```

```bash
docker compose --profile full up -d --build
```

The scenario wrappers combine these steps. For example, `.\scripts\start.ps1 -Scenario full` bootstraps with `-SkipBuild`, then starts the selected Compose profiles with `--build`.

## Starting Services

Full pipeline:

```bash
docker compose --profile full up -d
```

Brain only. Use this when dependencies are already running on other hosts or were started with other profiles:

```bash
docker compose --profile brain up -d
```

Software-only STT/TTS:

```bash
docker compose --profile stt --profile tts up -d
```

Audio-only microphone/speaker:

```bash
docker compose --profile audio up -d
```

Equivalent execution scripts:

```bash
./scripts/run/bash/start-full-local.sh
./scripts/run/bash/start-brain-remote.sh
./scripts/run/bash/start-software-only.sh
./scripts/run/bash/start-audio-only.sh
./scripts/run/bash/start-raspberry-services.sh
```

PowerShell equivalents are available with the same names ending in `.ps1`.

Stop or restart:

```bash
./scripts/run/bash/stop-full-oblivion.sh full
./scripts/run/bash/restart-full-oblivion.sh stt tts
```

```powershell
.\scripts\run\powershell\stop-full-oblivion.ps1 -Profiles full
.\scripts\run\powershell\restart-full-oblivion.ps1 -Profiles stt,tts
```

## Simulating Deployment Choices

The `scripts/simulate-*.sh` files are dry-run helpers. They print the intended commands, expected URLs, health checks, and rendered Compose services without starting containers.

Available simulations:

```bash
./scripts/simulate/simulate-full-local.sh
./scripts/simulate/simulate-brain-remote.sh
./scripts/simulate/simulate-software-only.sh
./scripts/simulate/simulate-audio-only.sh
./scripts/simulate/simulate-raspberry-services.sh
./scripts/simulate/simulate-all.sh
```

For example, to preview a Windows microphone plus Raspberry Pi service layout:

```bash
BRAIN_MICROPHONE_BASE_URL=http://192.168.1.20:8000 \
BRAIN_STT_BASE_URL=http://192.168.1.30:8001 \
BRAIN_TTS_BASE_URL=http://192.168.1.30:8002 \
BRAIN_SPEAKER_BASE_URL=http://192.168.1.30:8003 \
./scripts/simulate/simulate-brain-remote.sh
```

## Stopping Services

```bash
docker compose --profile full down
```

Compose stops `brain` before its dependency services because `brain` depends on `microphone`, `stt`, `tts`, and `speaker`.
For manual shutdown in hybrid deployments, stop brain first, then stop the dependency services on their own hosts.

## Logs

All services:

```bash
docker compose --profile full logs -f
```

One service:

```bash
docker compose logs -f brain
```

## Health Checks

Basic service checks:

```bash
curl http://localhost:7999/health
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
```

System-level readiness:

```bash
curl http://localhost:7999/integrations/health
```

`/available` on STT and TTS is a deeper engine readiness check:

```bash
curl http://localhost:8001/available
curl http://localhost:8002/available
```

## Updating

PowerShell:

```powershell
.\scripts\repo\update.ps1 -Rebuild
```

Bash:

```bash
./scripts/repo/update.sh --rebuild
```

The update scripts remove generated Dockerfiles from cloned repos before pulling, run `git pull --ff-only`, then copy the generated Dockerfiles back into place.

## Rebuilding

All services:

```powershell
.\scripts\repo\rebuild.ps1
```

```bash
./scripts/repo/rebuild.sh
```

Specific services:

```powershell
.\scripts\repo\rebuild.ps1 stt tts
```

```bash
./scripts/repo/rebuild.sh stt tts
```

## Linux Audio Setup

For direct ALSA access, uncomment the `/dev/snd` device mapping in `docker-compose.yml` for `microphone` and/or `speaker`.

For PulseAudio or PipeWire Pulse compatibility, mount the host user socket and set `PULSE_SERVER`. The included compose file contains commented examples. Exact paths and permissions vary by distribution.

If audio devices are unavailable, microphone or speaker containers may still become HTTP-healthy but fail when a stream opens. Use brain `/integrations/health` plus live pipeline testing to validate audio behavior.

## Hybrid And Multi-Host Deployment

Services can run on different hosts as long as brain can reach their HTTP ports.

Example layout:

| Host | Runs | Notes |
|---|---|---|
| Windows PC | native `microphone_microservice` | Must bind to a LAN-reachable address, not only `127.0.0.1` |
| Raspberry Pi | `stt`, `tts`, `speaker` containers or native services | Speaker needs local audio output access |
| Any host | `brain` container or native process | Configure root `.env` `BRAIN_*_BASE_URL` values to service host IPs |

If a service binds only to `127.0.0.1`, other machines cannot reach it. Set `SERVICE_HOST=0.0.0.0` where supported, or update that service's bind configuration.

The microphone service currently hardcodes `127.0.0.1:8000` for native runs. The generated Dockerfile patches this for containers, but native Windows distributed use may require changing the microphone source or launch configuration so it listens on the LAN interface.

## Linux systemd Auto-Start

Systemd unit templates are provided in `systemd/`. They assume the deployment root is installed at:

```text
/opt/full_oblivion
```

Install one unit:

```bash
sudo cp systemd/full-oblivion-raspberry-services.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable full-oblivion-raspberry-services.service
sudo systemctl start full-oblivion-raspberry-services.service
```

Available units:

```text
full-oblivion-full.service
full-oblivion-brain-remote.service
full-oblivion-software-only.service
full-oblivion-raspberry-services.service
```

If the repo lives somewhere else, update `WorkingDirectory`, `ExecStart`, and `ExecStop` in the copied unit file.

## Windows Auto-Start

Use `WINDOWS_AUTOSTART.md` for Task Scheduler setup. The PowerShell scripts in `scripts/` are intended for Windows auto execution.

## Windows And macOS Limitations

Docker Desktop does not reliably expose host microphone and speaker devices to Linux containers. Recommended layouts:

- Containerize `stt`, `tts`, and optionally `brain`.
- Run hardware-bound `microphone_microservice` or `speaker_microservice` natively on the host that owns the device.
- Point brain URLs at host-reachable native or containerized services.

## Common Failure Causes

- Missing Git authentication for private repositories.
- Missing Docker daemon.
- Missing `STT_OPENAI_API_KEY` or `TTS_OPENAI_API_KEY` in root `.env` for OpenAI modes.
- Host port conflicts on `7999` through `8003`.
- Linux audio permissions or unavailable `/dev/snd`.
- First local STT startup taking a long time while faster-whisper downloads model files.
