# OBLIVION deployment

One command-line tool, `oblivion`, deploys the OBLIVION services on **one machine** (Windows, Linux or Raspberry Pi).
Each service is deployed on its own: any subset of services can live on any machine, and the services find each
other through URLs the tool writes into their environment. It needs only Python 3.11+ and git.

**New here? Start with the [user guide, `docs/USER_GUIDE.md`](docs/USER_GUIDE.md)**: what to install, what to type on each
machine, in which order, how to check it and how to look after it.

**The reference manual is [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**: prerequisites, Python virtual
environments, every environment variable and secret, start order, health checks, the full-flow test and
troubleshooting. This file explains the tool.

```text
oblivion.py / oblivion.sh / oblivion.ps1   the CLI (stdlib only)
services.toml                              catalogue: repo, port, requirements, apt packages of every service
docs/USER_GUIDE.md                         step-by-step instructions for deploying and operating (start here)
docs/DEPLOYMENT.md                         the reference manual: every variable, per-service settings, limits
robot.toml                                 THE single file of truth: machines, addresses, services AND every setting and key (copy robot.example.toml; git-ignored)
hosts/<machine>.toml                       optional overrides of ONE machine (copy machine.example.toml)
secrets/<machine>.env                      optional machine-local overlay: keys that must not travel in robot.toml (git-ignored)
wheels/                                    the shared-logging wheel, so a fresh machine needs no workspace (scripts/bundle_shared_logging.py)
docker/service.Dockerfile                  generic image, used only for services set to runtime = "docker"
tests/                                     pytest (real git repos and real processes, no network)
```

## Just launch everything on this machine

```bash
python launch.py              # Windows: py launch.py      Linux/Pi: python3 launch.py
python launch.py status | logs [service] | stop
```

One script for Windows, Linux and Raspberry Pi. **If a `robot.toml` exists, `launch.py` deploys the machine it describes (a
single machine is picked automatically, several need `--machine NAME`) and creates nothing: the keys and settings come from that
file.** Without one, the first run creates `hosts/local.toml` (all seven services on this
machine, bound to 127.0.0.1) and `secrets/local.env`, asks once for the OpenAI key (or reads `OPENAI_API_KEY`; use
`--stt local` for local Whisper), copies the LLM provider keys of ai-agent (`GROQ_API_KEY`, `GOOGLE_API_KEY`, ...)
from your environment into the machine env file, fetches the code of branch `feature_ai_claude` (`--branch REF` to change it), installs,
starts everything in order and waits until each service is healthy. Later runs update to the newest code of the branch
(rolling back a service that does not start) and restart; `--no-update` only starts. On Linux/Pi add `--system-deps` the
first time to apt-install PortAudio/espeak (uses sudo). `--dry-run` prints every command. Brain then opens the voice
pipeline by itself: use headphones, speak, pause two seconds, and the sentence is played back.

For several machines, other layouts or docker, use `oblivion.py` with host files as described below.

## Quick start

Everything you fill in is in **one file**, `robot.toml`:

```bash
cp robot.example.toml robot.toml        # edit: the machines at the top, then the keys and any setting you want to change
python oblivion.py topology             # the whole robot as the tool understands it; checks every machine can find what it needs
python oblivion.py doctor   --host <machine>     # git, python, docker (if used), writable workdir
python oblivion.py validate --host <machine>     # wiring and required values, no network
python oblivion.py plan     --host <machine>     # every service, branch and env value with the layer that set it
python oblivion.py deploy   --host <machine>     # fetch code, install, write env, start, health-check
python oblivion.py status   --host <machine> --remote
```

Put the same `robot.toml` on every machine and run the last five commands on each with its own name. One machine? Give
`[machines.pc]` all seven services and the address `127.0.0.1`. Or skip the file and run `python launch.py`, which needs only a
key. A hand-written host file (`hosts/all-in-one.example.toml`) still works.

Launchers: `./oblivion.sh ...` (Linux/Pi, finds a suitable Python) and `.\oblivion.ps1 ...` (Windows).
`--host` is a machine of `robot.toml`, `hosts/<name>.toml` or a path to any host file. Add `--dry-run` to any command to see the exact
git/pip/process commands without running them.

## The robot once, and one machine at a time

Every fact is written in **one** place, and the rest is derived:

| Fact | Written in | Derived from it |
|---|---|---|
| which machine runs which services, and where each machine is | `robot.toml`, `[machines.*]` (copy `robot.example.toml`) | each machine's service list; the URL of every service on the other machines (`http://<address>:<port>`); each machine's bind address (`0.0.0.0` only when another machine calls one of its services); every service's host, port and `*_BASE_URL` |
| the port of every service | `services.toml` | everything above (a machine's `ports = { name = N }` deviates, callers follow) |
| settings and keys | `robot.toml`, `[env]` and `[env.<service>]` (`robot.example.toml` lists every variable of every service) | the `.env` of each service |

```toml
# robot.toml, the layout part (git-ignored: the addresses and keys are yours)
[machines.pc]
address = "192.168.1.20"
services = ["microphone", "speaker"]
[machines.server]
address = "192.168.1.10"
services = ["brain", "ai-agent", "stt", "tts"]
[machines.pi]
address = "192.168.1.30"
services = ["stepper"]
```

```bash
python oblivion.py topology                 # the whole robot: machines, services, what each exposes and calls; checks it
python oblivion.py deploy --host server     # on the server; --host pc and --host pi on theirs. No host file needed
```

`--host` is a machine of `robot.toml`, a host file `hosts/<name>.toml`, or a path. A **host file** is only for overrides
(`hosts/machine.example.toml`): `[host] machine = "server"` plus a pinned branch, `runtime = "docker"` for a service, a
Python, a workdir. Without a topology (one machine, or older host files) it still describes the machine by hand:

```toml
[host]
name = "all-in-one"
env_file = "secrets/all-in-one.env"
# workdir = "~/oblivion"     # clones, virtualenvs, logs, state
# bind = "127.0.0.1"         # the default

[services.brain]             # every table under [services] is deployed HERE
[services.stt]
runtime = "docker"           # optional per service: native (default) | docker
[services.stt.env]
STT_LANGUAGE = "en"

[remote]                     # services on OTHER machines: an address, address:port or a URL (a bare address gets the catalogue port)
microphone = "192.168.1.20"
```

Rules the tool applies for you:

* A consumer's base URLs are generated: Brain gets `STT_BASE_URL=http://127.0.0.1:8001` for a local STT and the other machine's
  address otherwise. `validate` fails when a required service is placed on no machine.
* Deployment order follows dependencies (what others consume starts first, stops last).
* Before starting a service the tool waits up to `--remote-wait` seconds (default 120, `0` = off) for the required services
  of other machines to be healthy. Brain exits if microphone, STT, TTS or speaker are not available in its own
  preflight and nothing restarts it, so this keeps a machine that boots first (autostart, `update`) from leaving Brain dead.
* `validate` checks addresses are well formed, that every library the services need has a usable source, and
  that the Python is new enough; it warns when ai-agent has no LLM key.
* The services have **no authentication**. A machine binds `0.0.0.0` only when another one calls it: keep them on a trusted LAN.

Examples: `robot.example.toml`, and in `hosts/`: `machine.example.toml` (overrides on top of the topology),
`all-in-one.example.toml`, `test-branch.example.toml` (a parallel copy on other ports and a feature branch).

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

The service's `.env` is generated on every deploy/start, and **it is the service's only source of settings**: the tool does not put them in the
service's environment, and it removes same-named variables of the machine or your shell from it, so a stray exported variable can never
beat the file. Services read the file themselves (python-dotenv); the microphone, which cannot, is started through `oblivion/service_runner.py`
(`dotenv = false` in `services.toml`); a Docker container gets the file bind-mounted at `/app/.env`.

**You fill in one file, `robot.toml`.** Its `[env]` table holds a value once for every service that uses that variable, and
`[env.<service>]` one service's own (it wins). Each service runs on exactly one machine, so nothing is per machine; put the same file
on every machine. `robot.example.toml` lists every variable of every service: the secrets empty, everything else commented out at its
default, so you uncomment and edit only what you want to change. Values may be strings, numbers or `true`/`false`.

```toml
[env]                                # every service that uses the variable
LOG_LEVEL = "DEBUG"                  # reaches all seven services
OPENAI_API_KEY = "<your key>"        # reaches STT and ai-agent, and no other service

[env.ai-agent]                       # this service only
GROQ_API_KEY = "<your key>"
[env.stepper]
MOCK_HARDWARE = 0                    # only the Raspberry Pi runs the stepper, so only the Pi reads this
```

The address, port and URLs of the other services are computed from the layout and `services.toml`, not set here. Layers, later wins:

| Layer | Source |
|---|---|
| `defaults` | the service repo's own `.env.example` |
| `registry` | `[services.<name>.env]` in `services.toml` |
| `computed` | `SERVICE_HOST`, `SERVICE_PORT`, and the base URLs of consumed services |
| `robot ALL` | `[env]` of `robot.toml` |
| `env file ALL` | `ALL__<VARIABLE>=value` lines of the optional machine-local `secrets/<machine>.env` |
| `host` | `[services.<name>.env]` in a host file |
| `robot` | `[env.<service>]` of `robot.toml` |
| `env file` | `<SERVICE>__<VARIABLE>=value` lines of the optional machine-local `secrets/<machine>.env` |

```bash
python oblivion.py env stt --host server     # merged values, secrets masked, and which layer set each one
```

**Keys travel with the file:** every machine that gets `robot.toml` gets every key in it. To keep a key off a machine, leave it out of
that machine's copy and put it in that machine's own `secrets/<machine>.env` (`STT__OPENAI_API_KEY=...`, or `ALL__NAME=...`), which
wins over `robot.toml`. `launch.py` stores the keys it asks for there.

`scripts/env_inventory.py` regenerates `robot.example.toml` from the services' `.env.example` files and source code; a test fails when
the committed template no longer lists everything they read.

`validate` reports required values that are missing (e.g. `OPENAI_API_KEY` when `STT_ENGINE=openai`) with the exact place to add them,
and warns about lines nothing reads and about variables a service does not document (probably a typo), naming the file they are in.

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
