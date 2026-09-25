# OBLIVION deployment

One command-line tool, `oblivion`, deploys the OBLIVION services on **one machine** (Windows, Linux or Raspberry Pi).
Each service is deployed on its own: any subset of services can live on any machine, and the services find each
other through URLs the tool writes into their environment. It needs only Python 3.11+ and git.

**The step-by-step manual is [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**: prerequisites, Python virtual
environments, every environment variable and secret, start order, health checks, the full-flow test and
troubleshooting. This file explains the tool.

```text
oblivion.py / oblivion.sh / oblivion.ps1   the CLI (stdlib only)
services.toml                              catalogue: repo, port, requirements, apt packages of every service
docs/DEPLOYMENT.md                         the deployment manual (start here)
hosts/<machine>.toml                       what runs on ONE machine (copy an *.example.toml)
secrets/<machine>.env                      that machine's secrets (git-ignored)
wheels/                                    the shared-logging wheel, so a fresh machine needs no workspace (scripts/bundle_shared_logging.py)
docker/service.Dockerfile                  generic image, used only for services set to runtime = "docker"
tests/                                     pytest (real git repos and real processes, no network)
legacy/                                    the previous Compose-based deployment, kept for reference
```

## Just launch everything on this machine

```bash
python launch.py              # Windows: py launch.py      Linux/Pi: python3 launch.py
python launch.py status | logs [service] | stop
```

One script for Windows, Linux and Raspberry Pi. The first run creates `hosts/local.toml` (all seven services on this
machine, bound to 127.0.0.1) and `secrets/local.env`, asks once for the OpenAI key (or reads `OPENAI_API_KEY`; use
`--stt local` for local Whisper), copies the LLM provider keys of ai-agent (`GROQ_API_KEY`, `GOOGLE_API_KEY`, ...)
from your environment into the secrets file, fetches the code of branch `feature_ai_claude` (`--branch REF` to change it), installs,
starts everything in order and waits until each service is healthy. Later runs update to the newest code of the branch
(rolling back a service that does not start) and restart; `--no-update` only starts. On Linux/Pi add `--system-deps` the
first time to apt-install PortAudio/espeak (uses sudo). `--dry-run` prints every command. Brain then opens the voice
pipeline by itself: use headphones, speak, pause two seconds, and the sentence is played back.

For several machines, other layouts or docker, use `oblivion.py` with host files as described below.

## Quick start

```bash
# 1. describe this machine (copy an example and edit it)
cp hosts/all-in-one.example.toml hosts/mypc.toml
cp secrets/example.env secrets/mypc.env       # then fill it in, and set [host] secrets in the host file

# 2. check, then deploy
python oblivion.py doctor   --host mypc       # git, python, docker (if used), writable workdir
python oblivion.py validate --host mypc       # wiring and required environment values, no network
python oblivion.py plan     --host mypc       # every service, branch and env value with its origin
python oblivion.py deploy   --host mypc       # fetch code, install, write env, start, health-check
python oblivion.py status   --host mypc --remote
```

Launchers: `./oblivion.sh ...` (Linux/Pi, finds a suitable Python) and `.\oblivion.ps1 ...` (Windows).
`--host` is `hosts/<name>.toml` or a path to any host file. Add `--dry-run` to any command to see the exact
git/pip/process commands without running them.

## One machine, one host file

```toml
[host]
name = "linux-server"
os = "auto"                  # auto | windows | linux | raspberry
workdir = "/opt/oblivion"    # clones, virtualenvs, logs, state
bind = "127.0.0.1"           # 0.0.0.0 only when other machines must reach these services
secrets = "secrets/linux-server.env"

[services.brain]             # every table under [services] is deployed HERE
[services.stt]
runtime = "docker"           # optional per service: native (default) | docker
[services.stt.env]
STT_LANGUAGE = "en"

[remote]                     # services that run on OTHER machines: only their URLs
microphone = "http://192.168.1.20:8000"
speaker    = "http://192.168.1.20:8003"
```

Rules the tool applies for you:

* A consumer's base URLs are generated: Brain gets `STT_BASE_URL=http://127.0.0.1:8001` for a local STT and the `[remote]`
  URL otherwise. `validate` fails when a required service is neither local nor remote.
* Deployment order follows dependencies (what others consume starts first, stops last).
* Before starting a service the tool waits up to `--remote-wait` seconds (default 120, `0` = off) for the required services
  listed in `[remote]` to be healthy. Brain exits if microphone, STT, TTS or speaker are not available in its own
  preflight and nothing restarts it, so this keeps a machine that boots first (autostart, `update`) from leaving Brain dead.
* `validate` checks `[remote]` URLs are well formed, that every library the services need has a usable source, and
  that the Python is new enough; it warns when ai-agent has no LLM key.
* The services have **no authentication**. `bind = "0.0.0.0"` exposes them to the whole network; keep them on a trusted LAN.

Ready-made examples in `hosts/`: `all-in-one`, `windows-audio` (microphone+speaker), `linux-server`
(brain/ai-agent/stt/tts, audio elsewhere), `raspberry-audio`, `raspberry-stepper` (only the stepper, real GPIO),
`test-branch` (a parallel copy on other ports and a feature branch).

## Code and branches

Each service is a git clone in `<workdir>/services/<name>_microservice`, taken from the URL in `services.toml`.
The branch is chosen, from lowest to highest priority, by: the registry default, `[defaults] branch` in the host
file, `branch =` under a service, and `--branch` on the command line.

```bash
python oblivion.py deploy --host mypc --branch feature_ai_claude            # every service on that branch
python oblivion.py update --host mypc --branch brain=feature_x --branch tts=v1.2   # per service; tags and commits work too
python oblivion.py update --host mypc                                        # back to the configured branches
```

* `deploy` is for the first install and for repairing. `update` moves a running machine to the (new) code.
* `update` stops the service, fetches, reinstalls only if dependencies changed, rewrites the env, starts it and waits for
  `/health` (and `/available`). **If the new version is not healthy it puts the previous commit back and restarts it**
  (`--no-rollback` keeps the failed one to inspect; `oblivion logs` shows why).
* Local edits in a clone are never overwritten: the update is refused for that service unless you pass `--force`.
* To try a branch without touching the running system, use a second host file with its own `workdir` and ports
  (see `hosts/test-branch.example.toml`).
* Private repositories work with whatever git credentials the machine already has (SSH key, credential manager).

## Environment variables

The service's `.env` is generated on every deploy/start. Layers, later wins:

| Layer | Source |
|---|---|
| `defaults` | the service repo's own `.env.example` |
| `registry` | `[services.<name>.env]` in `services.toml` |
| `computed` | `SERVICE_HOST`, `SERVICE_PORT`, and the base URLs of consumed services |
| `host` | `[services.<name>.env]` in the host file |
| `secrets` | `<SERVICE>__<VARIABLE>=value` lines in the machine's secrets file |

```bash
python oblivion.py env stt --host mypc       # merged values, secrets masked, and which layer set each one
```

Secrets file (never committed; `secrets/*` is git-ignored):

```text
STT__OPENAI_API_KEY=sk-...
```

`validate` reports required values that are missing (e.g. `OPENAI_API_KEY` when `STT_ENGINE=openai`) with the exact line to
add, and warns about host-file variables the service does not document (probably a typo).

## Running, stopping, boot

```bash
oblivion start|stop|restart|status|logs --host mypc [--service brain]
oblivion autostart install --host mypc      # systemd user unit (Linux/Pi) or a Windows scheduled task (at logon)
```

Native services are detached processes with a PID file and a log in `<workdir>/logs/<service>.log`. Autostart runs
`oblivion start` at boot/logon. On Linux/Pi run once `sudo loginctl enable-linger $USER` so it starts without a login.
Audio services (microphone, speaker) need the logged-in user's sound devices, hence "at logon" on Windows.

## Per operating system

| | Windows | Linux | Raspberry Pi |
|---|---|---|---|
| Runtime | native; Docker cannot reach the sound card (validation refuses `docker` for audio services) | native or Docker | native (audio) or Docker |
| Requirements file | `requirements.windows.txt` | `requirements.linux.txt` | as Linux (`raspberry` in `services.toml` overrides it: the stepper takes its GPIO file only here) |
| Missing file | falls back to the other OS's file with a warning (microphone and STT only have a Windows file today) | | |
| System packages | – | `oblivion deploy --system-deps` runs `apt-get update` once, then `apt-get install` for what a service needs (PortAudio, libsndfile, espeak, ...) | same |
| Boot | scheduled task at logon | systemd user unit | systemd user unit |
| Python | 3.11+ (`py -3` is found); ai-agent needs 3.12+ | 3.11+ (`python3`); ai-agent needs 3.12+ | Bookworm ships 3.11: `sudo apt install python3 python3-venv git`. **ai-agent does not install on 3.11**: run it on another machine |

`services.toml` can declare `min_python` per service; `validate` and `deploy` refuse a machine whose Python is older, before
cloning or installing anything. A Raspberry Pi is recognised from what the board reports (`/proc/device-tree/model`,
`/proc/cpuinfo`), not from the CPU architecture; set `os = "raspberry"` in the host file to force it.

**Fresh machine?** Follow `docs/DEPLOYMENT.md` section 3.1 (Python, git, firewall, the clone-and-deploy commands).

## Shared libraries

The services import `shared_logging`, which is not inside any service repo (it has no repository yet). `services.toml`
`[libraries.shared-logging]` says where each machine gets it: `path` (a checkout, the default for the workspace),
`git` (a URL, once it has a repo) or `wheel_dir`. Every `-e ../<sibling>` line in a requirements file is skipped, because
independent repos have no siblings. The contracts library is bundled inside every service (`vendor/*.whl`), so nothing
is needed for it.

Sources are tried in that order (`path`, then `wheel_dir`, then `git`) and the first usable one wins. The registry
lists `path = "../shared-logging"` (a development machine installs the live source) and `wheel_dir = "wheels"`,
a wheel committed in this repository, so **a fresh machine that only cloned this repository just works**. After
changing shared-logging run `scripts/bundle_shared_logging.py` and commit the new wheel (`validate` warns when the
wheel is older than the checkout).

## Docker (optional per service)

`runtime = "docker"` builds `oblivion/<service>:local` from the fetched code with the generic Dockerfile, publishes the
port on `bind`, runs it with `--restart unless-stopped` and the generated env file, and reaches services on the host via
`host.docker.internal`. Audio services get `--device /dev/snd` on Linux. Not supported for audio on Windows.

## Adding a service

Add a `[services.<name>]` table to `services.toml` (git URL, port, requirements files, `consumes` if it calls others),
then list it in the host files that should run it. Nothing else changes.

Keys for services that do not follow the `<name>_microservice` / `main.py` / `SERVICE_HOST`+`SERVICE_PORT`
convention (ai-agent is the example): `folder` (clone folder name), `entry` (script to run), `host_var` and
`port_var` (the env vars that service reads its bind address and port from). In a host file, `git = "<url or
local path>"` under a service points that one service at another source, e.g. a local repository.

## Tests

```bash
brain_microservice/windows/Scripts/python.exe -m pytest deployment/tests -q     # ~100 s: real git repos and processes
```

They cover branch selection, per-service branches, tag/commit deploys, update, automatic rollback of a release that does
not start, refusal to overwrite local edits, dry-run, the environment layers, validation and remote wiring. Not covered
here: Docker, systemd, scheduled tasks and Raspberry Pi hardware (they need those systems).
