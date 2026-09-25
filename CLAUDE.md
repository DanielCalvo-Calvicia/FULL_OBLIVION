# CLAUDE.md: deployment

Repo `FULL_OBLIVION`. A stdlib-only Python 3.11+ CLI (`oblivion.py`, package `oblivion/`) that deploys any subset of the services on one machine (Windows, Linux, Raspberry Pi). Rewritten from scratch; the previous Compose-based version is in `legacy/` for reference only. Read `README.md` (the tool) and `docs/DEPLOYMENT.md` (the manual: venvs, every env var, start order, health checks) first. Status: new, tested with fake services; Docker, systemd, scheduled tasks and real Pi hardware are untested.

## Layout

- `services.toml` catalogue of services (git URL, port, requirements per OS, apt packages, `consumes`, required env). Machine-independent. Covers the seven running services (brain, microphone, stt, tts, speaker, ai-agent, stepper); ai-agent has its own `folder`, `entry`, `host_var`/`port_var`.
- `hosts/<machine>.toml` per-machine layout (`*.example.toml` are committed, real ones are git-ignored). `secrets/*.env` per machine, git-ignored.
- `oblivion/`: `config` (registry/host, validation), `envfile` (layered env), `gitops` (clone/checkout branch, tag, commit), `installer` (venv + requirements, `-e ../` lines skipped), `runtime` (native processes, Docker), `manager` (deploy, update with rollback), `health`, `autostart`, `cli`.
- `docker/service.Dockerfile` generic image. `tests/` pytest with real git repos and processes.

## Rules

- Every external command goes through `Shell` so `--dry-run` shows it. Keep dry-run side-effect free (there is a test).
- Never write secrets into host files, `services.toml` or examples. Secrets only come from the machine's secrets file (`SERVICE__KEY=value`).
- `update` must never destroy local edits or leave a service dead: refuse on a dirty clone unless `--force`, and roll back a release that is not healthy. Keep the tests for both.
- Services never call each other; the tool only wires URLs (Brain gets the base URLs of what it consumes). Never assume `localhost` for a service that may be remote: use `[remote]`.
- Independent repos: no `-e ../sibling`. `shared-logging` has no repo yet; its source is configured in `services.toml [libraries]`. Contracts is bundled in each service's `vendor/`.
- Keep `docs/DEPLOYMENT.md` in step with each service's `.env.example` when a variable is added or removed. Never put a real key in it. `/available` answers HTTP 200 with `data.is_available`, not 503.
- `legacy/` and `repos/` (old clones) are not used; do not edit them.
- Do not commit or push unless asked.

## Commands

```powershell
& ..\brain_microservice\windows\Scripts\python.exe -m pytest tests -q     # about 100 s
& ..\brain_microservice\windows\Scripts\python.exe oblivion.py plan --host hosts\all-in-one.example.toml
```
