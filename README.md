# OBLIVION deployment

One command-line tool, `oblivion`, deploys the OBLIVION services on **one machine** (Windows, Linux or Raspberry Pi).
Each service is deployed on its own: any subset of services can live on any machine, and the services find each
other through URLs the tool writes into their environment. It needs only Python 3.11+ and git.

**New here? Start with the [user guide, `docs/USER_GUIDE.md`](docs/USER_GUIDE.md)**: what to install, what to type on each
machine, in which order, how to check it and how to look after it.

**The reference manual is [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**: prerequisites, Python virtual
environments, every environment variable and secret, start order, health checks, the full-flow test and
troubleshooting. This file explains the tool.

## What is in this repository

The code is laid out like the other OBLIVION services (`main.py`, `composition_root/`, `application/`, `domain/`,
`infrastructure/`); everything you edit is in one folder, `config/`.

```text
config/                                    EVERYTHING YOU EDIT (details below)
  robot.toml                                 which layout this robot uses, and where each machine is   (yours, git-ignored)
  layouts/<name>.toml                        where each service runs: all-in-one, speaker-on-pc, audio-on-pc, stepper-on-pi, pc-server-pi
  services/<service>.toml, all.toml          one file per service, all its settings at their defaults (generated); all.toml = shared settings
  local/<service>.toml, all.toml             YOUR keys and settings, same shape, they win           (yours, git-ignored)
  machines/<machine>.toml                    Python, folders, OS of one machine (optional)          (yours, git-ignored)
  catalogue.toml                             what each service is: repository, port, requirements, apt packages, `prepare` step

main.py  oblivion.py  oblivion.sh  oblivion.ps1   the CLI (stdlib only); oblivion.py is the same command under the name people type
launch.py                                  one command to deploy and start a whole robot on this machine
domain/                                    the rules, no I/O: entities (service, host, layout, settings), env layering, validation, topology
application/                               the use cases: deploy, update with rollback, start/stop, status, plan, validate, compat, layout check
  ports/outbound/                            what the use cases need from the outside: shell, git, installer, runtime, health, state, env files
infrastructure/                            the adapters: config/ loaders (TOML), git, pip/venv, processes and Docker, HTTP health, the CLI
composition_root/                          wires the adapters to the use cases (container.py)
docs/USER_GUIDE.md                         step-by-step instructions for deploying and operating (start here)
docs/DEPLOYMENT.md                         the reference manual: every variable, per-service settings, limits
wheels/                                    the shared-logging wheel, so a fresh machine needs no workspace (scripts/bundle_shared_logging.py)
docker/service.Dockerfile                  generic image, used only for services set to runtime = "docker"
scripts/                                   env_inventory.py (regenerates config/services/ from the services), bundle_shared_logging.py
tests/                                     pytest (real git repos and real processes, no network)
```

Dependencies point inward only: `infrastructure` -> `application` -> `domain`. `tests/` mirrors the layers.

## Just launch everything on this machine

```bash
python launch.py              # Windows: py launch.py      Linux/Pi: python3 launch.py
python launch.py status | logs [service] | stop
```

One script for Windows, Linux and Raspberry Pi. **If a `config/robot.toml` exists, `launch.py` deploys the machine it
describes (one machine is picked automatically, several need `--machine NAME`) and creates nothing: the keys and settings come
from `config/`.** Without one, the first run creates `config/robot.toml` (layout `all-in-one`: all seven services on this machine,
bound to 127.0.0.1) and your keys in `config/local/` (it asks once for the OpenAI key, or reads `OPENAI_API_KEY`; use `--stt local`
for local Whisper; it copies the LLM provider keys of ai-agent, `GROQ_API_KEY`, `GOOGLE_API_KEY`, ..., from your environment), and never
overwrites a file you have. It fetches the code of branch `feature_ai_claude_2` (`--branch REF` for one run), installs, starts
everything in order and waits until each service is healthy. Later runs update to the newest code of the branch (rolling back a
service that does not start) and restart; `--no-update` only starts. On Linux/Pi add `--system-deps` the first time to apt-install
PortAudio/espeak (uses sudo). `--dry-run` prints every command. Brain then opens the voice pipeline by itself: use headphones, speak,
pause two seconds, and the sentence is played back.

For several machines, other layouts or docker, use `oblivion.py` as described below.

## Quick start

```bash
python oblivion.py layouts                          # the ready-made layouts, and the one in use
python oblivion.py init --layout speaker-on-pc --address pc=192.168.1.20 --address pi=192.168.1.30   # writes config/robot.toml
cp config/local/all.example.toml config/local/all.toml     # your keys: fill in the ones you use (config/local/README.md)
python oblivion.py topology                         # the whole robot as the tool understands it; checks every machine can find what it needs
python oblivion.py doctor   --host <machine>        # git, python, docker (if used), writable workdir
python oblivion.py validate --host <machine>        # wiring and required values, no network
python oblivion.py plan     --host <machine>        # every service, branch and env value with the file it came from
python oblivion.py deploy   --host <machine>        # fetch code, install, write env, start, health-check
python oblivion.py status   --host <machine> --remote
```

Put the same `config/robot.toml` and `config/local/` on every machine and run the last five commands on each with its own name.
Launchers: `./oblivion.sh ...` (Linux/Pi, finds a suitable Python) and `.\oblivion.ps1 ...` (Windows). `--host` is a machine of the
layout. `--config DIR` uses another config folder with the same shape. Add `--dry-run` to any command to see the exact
git/pip/process commands without running them.

## The files you edit, and what each one answers

| Question | File |
|---|---|
| Which services run on which machine? | a layout in `config/layouts/`, chosen in `config/robot.toml` |
| Where is each machine? | `[addresses]` in `config/robot.toml` |
| How is this service set up? What are its defaults? | `config/services/<service>.toml` |
| What do I want different on this robot? Where do my keys go? | `config/local/<service>.toml` (and `all.toml` for what several services share) |
| What is special about this machine (its Python, its folders)? | `config/machines/<machine>.toml` |
| What is a service (repository, port, requirements)? | `config/catalogue.toml` (almost never edited) |

Every fact is written in **one** place and the rest is derived:

| Fact | Written in | Derived from it |
|---|---|---|
| which machine runs which services | a layout, `config/layouts/` | each machine's service list; the URL of every service on the other machines (`http://<address>:<port>`); each machine's bind address (`0.0.0.0` only if another machine calls one of its services) |
| where each machine is | `[addresses]` in `config/robot.toml` | the URLs above |
| the port of every service | `config/catalogue.toml` (a machine's `ports = { name = N }` in the layout deviates, and callers follow) | everything above |
| settings and keys | `config/services/`, `config/local/` | the `.env` of each service |

A layout is a small file; copy the closest one to make your own:

```toml
# config/layouts/speaker-on-pc.toml
description = "Speaker on the PC; microphone, brain, stt, tts, ai-agent and stepper on the Pi."
[machines.pc]
services = ["speaker"]
[machines.pi]
services = ["brain", "microphone", "stt", "tts", "ai-agent", "stepper"]
```

```toml
# config/robot.toml
layout = "speaker-on-pc"
[addresses]
pc = "192.168.1.20"
pi = "192.168.1.30"
```

```bash
python oblivion.py topology                 # the whole robot: machines, services, what each exposes and calls; checks it
python oblivion.py deploy --host pi         # on the Pi; --host pc on the PC
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

## Machine settings

`config/machines/<machine>.toml` (optional; `config/machines/pi.example.toml` is the template) holds what is particular to one
physical machine, under `[host]`:

```toml
[host]
python = "/home/pi/.local/bin/python3.12"   # the Python that builds the virtualenvs, when the default python3 is older than a service needs
workdir = "~/oblivion"                      # clones, virtualenvs, logs, state (relative = relative to the config folder)
os = "raspberry"                            # auto (default), windows, linux or raspberry: only to force the detection
bind = "127.0.0.1"                          # only to override the derived bind address
```

## Code and branches

Each service is a git clone in `<workdir>/services/<name>_microservice`, taken from the URL in `config/catalogue.toml`.
The branch, tag or commit is chosen, from lowest to highest priority, by: the catalogue default, `branch` / `tag` / `commit` at the top of
`config/services/<service>.toml`, the same in `config/local/<service>.toml`, and `--branch` on the command line.

```bash
python oblivion.py deploy --host mypc --branch feature_ai_claude_2            # every service on that branch
python oblivion.py update --host mypc --branch brain=feature_x --branch tts=v1.2   # per service; tags and commits work too
python oblivion.py update --host mypc                                        # back to the configured branches
```

* `deploy` is for the first install and for repairing. `update` moves a running machine to the (new) code.
* `update` stops the service, fetches, reinstalls only if dependencies changed, rewrites the env, starts it and waits for
  `/health` (and `/available`). **If the new version is not healthy it puts the previous commit back and restarts it**
  (`--no-rollback` keeps the failed one to inspect; `oblivion logs` shows why).
* Local edits in a clone are never overwritten: the update is refused for that service unless you pass `--force`.
* To try a branch without touching the running system, use another config folder with its own `workdir` (`config/machines/`) and
  `ports` (in its layout), and pass `--config`.
* Private repositories work with whatever git credentials the machine already has (SSH key, credential manager).
* A settings file may also name another repository or a local checkout: `git = "<url or path>"` at the top of
  `config/local/<service>.toml` deploys exactly what is committed there.

## One file per service: code version, runtime and own settings

Each service has its own file in `config/services/` (the project's defaults, generated) and, if you want something different, one in
`config/local/` (yours, with the same name and shape; it wins):

```toml
# config/local/tts.toml
tag = "v1.2.0"            # which code: set at most one of branch, tag or commit (nothing = the next lower file, then the catalogue)
runtime = "native"        # or "docker"
[env]
TTS_PIPER_SPEED = 1.1     # this service's own settings and keys
```

* Tags are how versions of the whole robot can be pinned later: give every service the same `tag`.
* A settings file of a service that runs on another machine is not applied on this one.
* A mistake (an unknown service, two of branch/tag/commit, an unknown key, a value that is not text, number or boolean) stops the
  command with a message naming the file.
* `scripts/env_inventory.py --write` regenerates `config/services/*.toml` and `config/local/*.example.toml` from the services'
  `.env.example` files and source; a test fails when they are out of date.

## Do the services fit together? `compat`

```bash
python oblivion.py compat                 # offline, against the development workspace next to this repository
python oblivion.py compat --remote        # also: does each branch/tag exist on its git remote (needs the network)
python oblivion.py compat --service tts --workspace <dir>
```

For every service it prints the branch, tag or commit it will be deployed from (and which file chose it) and checks, in the
workspace: exactly one bundled `contracts` wheel, the same version in every service and equal to the `contracts` source;
every requirements file installs that wheel; the port of its `.env.example` is the catalogue's; the checkout is on the branch it
will be deployed from; and **no commit is unpushed** (a deploy takes the code from the remote, not from the working copy).
Errors exit 1; warnings (a checkout on another branch, unpushed or behind commits) do not.

## Environment variables

The service's `.env` is generated on every deploy/start, and **it is the service's only source of settings**: the tool does not put them in the
service's environment, and it removes same-named variables of the machine or your shell from it, so a stray exported variable can never
beat the file. Services read the file themselves (python-dotenv); the microphone, which cannot, is started through
`infrastructure/outbound/runtime/service_runner.py` (`dotenv = false` in `config/catalogue.toml`); a Docker container gets the file
bind-mounted at `/app/.env`.

**Your settings are in two folders with the same file names.** `config/services/` has the project's defaults, one file per
service plus `all.toml` for what several services share; `config/local/` has yours, which wins. A value in `all.toml` reaches every
service that uses that variable, and no other. Each service runs on exactly one machine, so nothing is per machine; put the same files
on every machine. Values may be strings, numbers or `true`/`false`.

```toml
# config/local/all.toml                # every service that uses the variable
[env]
OPENAI_API_KEY = "<your key>"          # reaches STT and ai-agent, and no other service

# config/local/ai-agent.toml           # this service only
[env]
GROQ_API_KEY = "<your key>"

# config/local/stepper.toml
[env]
MOCK_HARDWARE = 0                      # only the Raspberry Pi runs the stepper, so only the Pi reads this
```

The address, port and URLs of the other services are computed from the layout and the catalogue, not set here. Layers, later wins:

| Layer | Source |
|---|---|
| `defaults` | the service repo's own `.env.example` |
| `catalogue` | `[services.<name>.env]` in `config/catalogue.toml` |
| `computed` | `SERVICE_HOST`, `SERVICE_PORT`, and the base URLs of consumed services |
| `config/services/all.toml` | `[env]`: shared settings, the project's defaults |
| `config/local/all.toml` | the same, yours |
| `config/services/<service>.toml` | `[env]`: the service's own settings, the project's defaults |
| `config/local/<service>.toml` | the same, yours |

```bash
python oblivion.py env stt --host server     # merged values, secrets masked, and which file set each one
```

**Keys travel with the folder:** every machine that gets `config/local/` gets every key in it. To keep a key off a machine, leave that
file out of that machine's copy.

`validate` reports required values that are missing (e.g. `OPENAI_API_KEY` when `STT_ENGINE=openai`) with the exact file to add them to,
and warns about variables a service does not document (probably a typo), naming the file they are in.

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
| Requirements file | `requirements.windows.txt` | `requirements.linux.txt` | as Linux (`raspberry` in `config/catalogue.toml` overrides it: the stepper takes its GPIO file only here) |
| Missing file | falls back to the other OS's file with a warning (microphone and STT only have a Windows file today) | | |
| System packages | – | `oblivion deploy --system-deps` runs `apt-get update` once, then `apt-get install` for what a service needs (PortAudio, libsndfile, espeak, ...) | same |
| Boot | scheduled task at logon | systemd user unit | systemd user unit |
| Python | 3.11+ (`py -3` is found); ai-agent needs 3.12+ | 3.11+ (`python3`); ai-agent needs 3.12+ | Bookworm ships 3.11: `sudo apt install python3 python3-venv git`. **ai-agent does not install on 3.11**: install a newer Python (see `config/machines/pi.example.toml`) or run it on another machine |

`config/catalogue.toml` can declare `min_python` per service; `validate` and `deploy` refuse a machine whose Python is older, before
cloning or installing anything. A Raspberry Pi is recognised from what the board reports (`/proc/device-tree/model`,
`/proc/cpuinfo`), not from the CPU architecture; set `os = "raspberry"` in `config/machines/<machine>.toml` to force it.

**Fresh machine?** Follow `docs/DEPLOYMENT.md` section 3.1 (Python, git, firewall, the clone-and-deploy commands).

## Shared libraries

The services import `shared_logging`, which is not inside any service repo (it has no repository yet). `config/catalogue.toml`
`[libraries.shared-logging]` says where each machine gets it: `path` (a checkout, the default for the workspace),
`git` (a URL, once it has a repo) or `wheel_dir`. Relative paths there are relative to the repository root. Every
`-e ../<sibling>` line in a requirements file is skipped, because independent repos have no siblings. The contracts library is
bundled inside every service (`vendor/*.whl`), so nothing is needed for it.

Sources are tried in that order (`path`, then `wheel_dir`, then `git`) and the first usable one wins. The catalogue
lists `path = "../shared-logging"` (a development machine installs the live source) and `wheel_dir = "wheels"`,
a wheel committed in this repository, so **a fresh machine that only cloned this repository just works**. After
changing shared-logging run `scripts/bundle_shared_logging.py` and commit the new wheel (`validate` warns when the
wheel is older than the checkout).

## Docker (optional per service)

`runtime = "docker"` (in the service's settings file) builds `oblivion/<service>:local` from the fetched code with the generic
Dockerfile, publishes the port on `bind`, runs it with `--restart unless-stopped` and the generated env file, and reaches services
on the host via `host.docker.internal`. Audio services get `--device /dev/snd` on Linux. Not supported for audio on Windows.

## Adding a service

Add a `[services.<name>]` table to `config/catalogue.toml` (git URL, port, requirements files, `consumes` if it calls others),
add the service to a machine of the layouts that should run it, and run `scripts/env_inventory.py --write` to generate its settings
file. Nothing else changes.

Keys for services that do not follow the `<name>_microservice` / `main.py` / `SERVICE_HOST`+`SERVICE_PORT`
convention (ai-agent is the example): `folder` (clone folder name), `entry` (script to run), `host_var` and
`port_var` (the env vars that service reads its bind address and port from).

`prepare = ["scripts/x.py"]` is a script run with the service's own Python after its `.env` has been written, by `deploy`, `update` and
rollback (a Docker build runs it through the `PREPARE` build argument); a failure only warns. tts uses it to download the Piper voice
(`scripts/fetch_voice.py`, about 60 MB), which is in neither git nor pip. `min_python`, `require_any` (a warning when none of several
variables is set) and `internal` (variables nobody sets on a deployed machine, never advertised) are the other optional keys.

## Tests

```bash
brain_microservice/windows/Scripts/python.exe -m pytest deployment/tests -q     # ~150 s: real git repos and processes
```

They cover branch selection, per-service branches, tag/commit deploys, update, automatic rollback of a release that does
not start, refusal to overwrite local edits, dry-run, the layouts and the settings files, the environment layers, validation and
remote wiring, and that a service with the same package names as this tool keeps its own. Not covered
here: Docker, systemd, scheduled tasks and Raspberry Pi hardware (they need those systems).
