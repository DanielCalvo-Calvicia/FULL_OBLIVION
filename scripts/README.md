# Scripts

Scripts are grouped by purpose.

## One-Command Start

Use these when starting from scratch. They bootstrap repositories, prepare generated Dockerfiles, build images, and start the selected scenario.

```powershell
.\scripts\start.ps1 -Scenario full
```

```bash
./scripts/start.sh full
```

Scenarios:

- `full`
- `brain-remote`
- `windows-audio`
- `windows-speaker`
- `software-only`
- `audio-only`
- `raspberry-services`

## Repository Management

Located in `scripts/repo/`.

| Script | Purpose |
|---|---|
| `bootstrap.sh` / `bootstrap.ps1` | Clone service repositories, copy generated Dockerfiles, create `.env`, optionally build images |
| `update.sh` / `update.ps1` | Pull cloned repositories and refresh generated Dockerfiles |
| `rebuild.sh` / `rebuild.ps1` | Rebuild all or selected Docker images |

## Execution

Located in `scripts/run/`.

Run `scripts/repo/bootstrap.*` before using these scripts. Execution scripts start Docker Compose services and require the cloned repositories under `repos/`.

| Script | Purpose |
|---|---|
| `bash/start-full-local.sh` | Start all five local containers |
| `bash/start-brain-remote.sh` | Start brain only, using configured remote service URLs |
| `bash/start-software-only.sh` | Start STT and TTS containers |
| `bash/start-audio-only.sh` | Start microphone and speaker containers |
| `bash/start-raspberry-services.sh` | Start STT, TTS, and speaker containers |
| `bash/stop-full-oblivion.sh` | Stop selected profiles |
| `bash/restart-full-oblivion.sh` | Restart selected profiles |
| `powershell/*.ps1` | Windows equivalents for Task Scheduler or manual execution |

## Simulation

Located in `scripts/simulate/`.

These scripts print intended commands and rendered Compose services without starting containers.
