# Windows Auto-Start Guide

Use the PowerShell scripts in `scripts/` with Windows Task Scheduler.

## Common Scripts

| Scenario | Script |
|---|---|
| Full local Docker stack | `scripts/run/powershell/start-full-local.ps1` |
| Brain only with remote services | `scripts/run/powershell/start-brain-remote.ps1` |
| STT/TTS only | `scripts/run/powershell/start-software-only.ps1` |
| Audio-only containers | `scripts/run/powershell/start-audio-only.ps1` |
| Raspberry-style STT/TTS/speaker set | `scripts/run/powershell/start-raspberry-services.ps1` |
| Stop selected profiles | `scripts/run/powershell/stop-full-oblivion.ps1` |
| Restart selected profiles | `scripts/run/powershell/restart-full-oblivion.ps1` |

## Task Scheduler Setup

Create a task that runs at user logon or system startup.

Program:

```text
powershell.exe
```

Arguments:

```text
-ExecutionPolicy Bypass -File "D:\Hobbys\IA\FULL_OBLIVION\scripts\start.ps1" -Scenario brain-remote
```

Start in:

```text
D:\Hobbys\IA\FULL_OBLIVION
```

## Remote Service URLs

For brain-only Windows execution, configure `.env` or system environment variables:

```ini
MICROPHONE_BASE_URL=http://192.168.1.20:8000
STT_BASE_URL=http://192.168.1.30:8001
TTS_BASE_URL=http://192.168.1.30:8002
SPEAKER_BASE_URL=http://192.168.1.31:8003
```

Docker Compose automatically reads `.env` from the repository root.

## Notes

- Docker Desktop must be running before the task executes.
- For native microphone or speaker services, create separate tasks that start those service processes.
- Native services must bind to a LAN-reachable address when other hosts need to call them.
