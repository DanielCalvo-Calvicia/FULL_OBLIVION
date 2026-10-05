# OBLIVION deployment manual

> This is the **reference** manual. For a step-by-step walkthrough (what to type on each machine, in order), read
> [`USER_GUIDE.md`](USER_GUIDE.md) first.

How to bring the whole robot up like a production environment: what to install, which Python virtual
environment each service needs, every environment variable and where to fill it, in which order things
start, how to check that everything is healthy and what to do when it is not.

This manual describes the platform as it is today. Where something has never been run (Docker, systemd,
scheduled tasks, real Raspberry Pi hardware) it says so. **No value in this file is a secret**: keys always
go in `config/local/`, which is never committed (section 5.2).

## Contents

1. [What gets deployed](#1-what-gets-deployed)
2. [Choose how to deploy](#2-choose-how-to-deploy)
3. [Prerequisites](#3-prerequisites)
4. [Python virtual environments](#4-python-virtual-environments)
5. [Secrets and environment variables](#5-secrets-and-environment-variables)
6. [Start order and health checks](#6-start-order-and-health-checks)
7. [Testing the whole flow](#7-testing-the-whole-flow)
8. [Several machines](#8-several-machines)
9. [Operating it](#9-operating-it)
10. [Troubleshooting](#10-troubleshooting)
11. [Known limits](#11-known-limits)

---

## 1. What gets deployed

Seven services plus one library. **Brain is the only coordinator**: services never call each other, and only
Brain talks to the stepper. There is no authentication anywhere, so keep every port on a trusted network.

| Service | Folder | Port | Env var for the port | What it does | Needs |
|---|---|---|---|---|---|
| microphone | `microphone_microservice` | 8000 | `SERVICE_PORT` | streams captured audio (PCM16 mono) | a sound input device |
| stt | `stt_microservice` | 8001 | `SERVICE_PORT` | speech to text (OpenAI Whisper API or local faster-whisper) | OpenAI key **or** local model |
| tts | `tts_microservice` | 8002 | `SERVICE_PORT` | text to speech (Piper neural voice, droid effect; pyttsx3 fallback) | the Piper voice file (about 60 MB, fetched at deploy) |
| speaker | `speaker_microservice` | 8003 | `SERVICE_PORT` | plays audio | a sound output device |
| ai-agent | `ai-agent` | 7998 | `AI_AGENT_PORT` | decides: two agents ("flows") in one service, conversation-flow writes the reply and motion-flow decides the arm movements | an LLM provider key |
| stepper | `stepper_microservice` | 8005 | `SERVICE_PORT` | drives the two arm motors | Raspberry Pi GPIO, or mock mode |
| brain | `brain_microservice` | 7999 | `SERVICE_PORT` | orchestrates the voice pipeline | the six above |

`aws_microservice` (Go, port 8080) is not part of the running robot and is not covered here.

The voice flow: microphone → Brain → STT → Brain (accumulates what was said) → ai-agent → Brain → TTS →
Brain → speaker. For every utterance Brain says "Message received." at once, then asks ai-agent's flows one after the other, in the order of `AI_AGENT_FLOWS` (conversation-flow, then motion-flow): conversation-flow writes the reply and motion-flow, only when conversation-flow has ended, decides the arm movements (or asks which detail is missing: Brain speaks that question and the answer goes only to motion-flow). While they work Brain says "Thinking." every 2 seconds; only when all of them have ended it speaks the answer and sends the movements, in order, to the stepper in the background. A stepper failure never silences the spoken reply and stops the rest of that sequence. If ai-agent is unreachable Brain speaks an apology.

Library: `shared-logging` is imported by every service. `contracts` needs nothing: each service carries the
wheel in its own `vendor/` folder and its requirements file installs it.

## 2. Choose how to deploy

| Route | Use it when | Code comes from |
|---|---|---|
| **A. `launch.py`** | one machine, everything local, you want one command | git (a branch of each repo) |
| **B. `oblivion.py` + a layout** | one or several machines, per-service branches, Docker for some services, boot autostart | git |
| **C. By hand from the workspace** | you want to run exactly the files on disk, including uncommitted work | your working folders |

> **The git routes (A and B) deploy what is committed and reachable from the repository URL.** They clone
> `https://github.com/DanielCalvo-Calvicia/<repo>.git` and check out a branch. Work that only exists as
> uncommitted changes in your working folders (for example a feature you are still finishing) is **not**
> deployed by A or B. Commit it first, then either push it or point the service's local settings file at your local repo:
>
> ```toml
> # config/local/brain.toml
> git = "D:/Hobbys/IA/OBLIVION/brain_microservice"   # a local clone source instead of GitHub
> branch = "feature_ai_claude_2"
> ```
>
> Use route C to run uncommitted code.

Branches today: every repo (including `stepper_microservice` and this one) works on `feature_ai_claude_2`,
which is the default of `launch.py` **and of `config/catalogue.toml`**. Do not deploy `main` yet: it does not carry the
vendored `contracts` wheel every service's requirements file points at, so the install fails. Change the default
in `config/catalogue.toml` to `main` once the branches are merged. A service can follow another branch, a tag or a commit
through the first lines of its settings file (`config/services/<name>.toml`, or yours in `config/local/`), or for one run
through `--branch`.

### Route A: one command

```powershell
py -3 launch.py            # Linux / Raspberry Pi: python3 launch.py
py -3 launch.py status     # state, code version and health of every service
py -3 launch.py logs ai-agent
py -3 launch.py stop
```

**With a `config/robot.toml`, the launcher uses it** (one machine is picked automatically; `--machine NAME` picks one of several) and
creates, asks and copies nothing: the layout, settings and keys are those of `config/`. **Without one**, the first run creates
`config/robot.toml` (layout `all-in-one`) and the key files in `config/local/` (all git-ignored), asks once for the OpenAI
key for speech-to-text (or reads `OPENAI_API_KEY`; use `--stt local` to avoid it), copies any LLM provider
keys that are exported in your environment into `config/local/ai-agent.toml` for ai-agent (`GROQ_API_KEY`,
`GOOGLE_API_KEY`, ...; the values are never printed), fetches the code, builds one virtual environment per
service, starts everything in order and waits until each service is healthy. It never overwrites a file you already have.

Export the LLM keys **before** the first run, in the same terminal, so they are picked up:

```powershell
$env:GROQ_API_KEY   = "<your Groq key>"       # the variable names are the point; use your own values
$env:GOOGLE_API_KEY = "<your Google key>"
py -3 launch.py
```

Later runs update to the newest code of the branch (rolling back a service that does not start) and restart.
`--no-update` only starts. `--dry-run` prints every command. On Linux/Pi add `--system-deps` the first time.
The LLM endpoints are preset in `config/catalogue.toml`; only the keys are yours. `--branch` changes the code for one run only.

### Route B: a layout

```powershell
py -3 oblivion.py layouts                           # the ready-made layouts: where each service runs
py -3 oblivion.py init --layout speaker-on-pc --address pc=192.168.1.20 --address pi=192.168.1.30   # writes config/robot.toml
py -3 oblivion.py topology                          # the whole robot; checks every machine can find what it needs
py -3 oblivion.py doctor   --host <machine>         # git, python, docker (if used), writable workdir
py -3 oblivion.py validate --host <machine>         # wiring and missing required values, no network
py -3 oblivion.py plan     --host <machine>         # every service, branch and env value with the file it came from
py -3 oblivion.py deploy   --host <machine>         # fetch code, install, write env, start, health-check
py -3 oblivion.py status   --host <machine> --remote
```

One machine: layout `all-in-one` (no addresses needed). Your keys and settings go in `config/local/` (sections 5.2 and 8).

`README.md` in this folder explains the tool itself (branches, update with rollback, Docker, autostart).
The environment layers are explained in section 5.

### Route C: by hand from the workspace

Sections 4 to 6 are exactly this route. It is also what you use to debug one service.

## 3. Prerequisites

| | Windows 11 | Linux | Raspberry Pi OS (Bookworm) |
|---|---|---|---|
| Python | 3.14 is what the workspace uses and tests run on; the deploy tool itself needs 3.11+; **ai-agent needs 3.12+** | 3.11+ (`python3`, `python3-venv`); **ai-agent needs 3.12+** | 3.11 ships with Bookworm (`sudo apt install python3 python3-venv git`): fine for everything **except ai-agent** |
| git | required for routes A and B | same | same |
| Sound | a working default input and output | ALSA/PortAudio | USB microphone, speaker or I2S DAC |
| System packages | none | `libportaudio2 portaudio19-dev` (microphone, speaker); `libsndfile1` (speaker); `espeak espeak-data libespeak1` (tts: only the pyttsx3 fallback voice, Piper brings its own) | same as Linux |
| Voices (pyttsx3 fallback only; Piper brings its own) | Windows SAPI voices (Helena is Spanish, Zira is English) | espeak | espeak |
| Disk / network | the local Whisper model downloads once (hundreds of MB); LLM and OpenAI calls need internet | | |

Linux/Pi system packages are installed by `--system-deps` (uses `sudo`) or by hand:
`sudo apt-get update && sudo apt-get install -y libportaudio2 portaudio19-dev libsndfile1 espeak espeak-data libespeak1`
(`--system-deps` runs `apt-get update` once first: a freshly imaged machine has empty package lists).

Python versions, verified by installing every service into fresh virtual environments (2026-09-25):

| Python | brain, microphone, stt, tts, speaker, stepper | ai-agent |
|---|---|---|
| 3.14 (Windows) | installs | installs |
| 3.11 (Raspberry Pi OS Bookworm's version) | installs | **fails**: the pinned `ai-sdk-python` requires Python 3.12+ |

So ai-agent cannot run on a stock Raspberry Pi OS Bookworm. The tool refuses **before installing anything**
(`validate` and `deploy`: "ai-agent needs Python 3.12+ ..."). Run ai-agent on a Windows PC or a Linux server with
Python 3.12+ (Ubuntu 24.04 ships it) and give it its own machine in a layout (Brain finds it there), or install a newer Python and set
`python = "<path>"` under `[host]` in `config/machines/<machine>.toml` (`config/machines/pi.example.toml` shows one way to get
Python 3.12 on a Pi without touching the system's, and the `speaker-on-pc` layout was deployed that way). `fastapi==0.111.0` / `pydantic==2.7.4` have no 3.14 wheels (the Windows stepper
requirements use lower bounds for that reason).

### 3.1 A fresh machine, step by step

Applies to every machine, whichever services it runs. Nothing from the development workspace is needed: the
service repositories are public on GitHub (no credentials), and `shared-logging` ships inside this repository
(`wheels/`).

**Windows 11**

1. Install Python 3.12 or newer (python.org; tick "Add python.exe to PATH" and keep the `py` launcher) and
   Git for Windows.
2. A machine with the microphone: Settings, Privacy & security, Microphone, allow desktop apps.
3. Run the tool as `py -3 oblivion.py ...`. A new Windows blocks `.ps1` scripts (execution policy), so
   `oblivion.ps1` may refuse to run.
4. A service listening on `0.0.0.0` makes Windows Defender Firewall ask on its first start: allow private
   networks. Or open the ports beforehand in an elevated PowerShell, for example for the microphone and speaker:
   `New-NetFirewallRule -DisplayName OBLIVION -Direction Inbound -Protocol TCP -LocalPort 8000,8003 -Action Allow -Profile Private`

**Linux / Raspberry Pi OS**

```bash
sudo apt update && sudo apt install -y git python3 python3-venv     # the tool installs the rest with --system-deps
sudo usermod -aG audio $USER                                        # microphone/speaker machines; log in again
```

**Every machine**

```bash
git clone -b feature_ai_claude_2 https://github.com/DanielCalvo-Calvicia/FULL_OBLIVION.git oblivion-deploy
cd oblivion-deploy
python3 oblivion.py init --layout <layout> --address <machine>=<ip> ...   # once: which layout, where each machine is (config/robot.toml)
chmod -R go-rwx config/local                                    # Linux/Pi: your keys live there (config/local/, git-ignored)
python3 oblivion.py topology                                    # optional: the whole robot as the tool understands it
python3 oblivion.py doctor   --host <machine>                   # Windows: py -3
python3 oblivion.py validate --host <machine>
python3 oblivion.py deploy   --host <machine> --system-deps     # --system-deps: Linux/Pi only (sudo apt)
python3 oblivion.py status   --host <machine> --remote
python3 oblivion.py autostart install --host <machine>
```

`config/robot.toml` and `config/local/` hold what is yours (section 5.2). The tool never copies them or any secret between machines:
you put them on each machine, and a machine keeps a key off its copy by leaving that file out. `doctor` and `validate` change nothing, and `deploy --dry-run`
prints every command first. The first deploy of a machine takes several minutes (STT and ai-agent pull large
dependencies).

## 4. Python virtual environments

One virtual environment per service, so their dependencies never clash. Routes A and B create them for you
(`<workdir>/venvs/<service>`, default workdir `~/oblivion`). This is how to build them by hand, and what the
tool runs underneath.

### 4.1 Windows (workspace layout: `<service>\windows`)

Run each block from the service's own folder. The requirements files use relative paths
(`-e ../shared-logging` and `./vendor/contracts_microservice-<version>-py3-none-any.whl`), so the working
directory matters.

```powershell
cd D:\Hobbys\IA\OBLIVION\brain_microservice
py -3.14 -m venv windows
windows\Scripts\python.exe -m pip install --upgrade pip
windows\Scripts\python.exe -m pip install -r requirements.windows.txt
```

Same three steps for every service, changing only the folder and the requirements file:

| Folder | Requirements file |
|---|---|
| `brain_microservice`, `microphone_microservice`, `stt_microservice`, `tts_microservice`, `speaker_microservice`, `stepper_microservice` | `requirements.windows.txt` |
| `ai-agent` | `requirements.txt` |

Never use a global Python to run a service; always `<service>\windows\Scripts\python.exe`.

### 4.2 Linux / Raspberry Pi

```bash
cd ~/oblivion/services/brain_microservice
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.linux.txt
```

Every service has a `requirements.linux.txt` except `ai-agent`, which uses `requirements.txt` on both systems. The
stepper's Linux file adds `RPi.GPIO`, which only builds on a Raspberry Pi. All of them resolve to prebuilt wheels on
Linux x86_64 and aarch64 (Python 3.12; 3.11 too, except `ai-agent`, which needs 3.12+).

`shared-logging` has no repository of its own yet. Where the `-e ../shared-logging` line cannot resolve
(a machine without the workspace), install it after the requirements from the wheel that ships in this
repository's `wheels/` folder, or from a checkout:

```bash
.venv/bin/python -m pip install /path/to/shared-logging
```

The deploy tool does this for you from `config/catalogue.toml` `[libraries.shared-logging]` (relative paths are relative to the repository root), trying in order `path`
(the workspace checkout, so a development machine always installs the current source), `wheel_dir`
(`wheels/`, committed in this repository, so a fresh machine that only cloned it works) and `git` (for when the
library has its own repository). `validate` and `deploy` fail before cloning anything when none is usable.
After changing shared-logging, refresh the wheel and commit it (`validate` warns when it is older than the checkout):

```powershell
brain_microservice\windows\Scripts\python.exe deployment\scripts\bundle_shared_logging.py
```

### 4.3 Checking a venv

```powershell
windows\Scripts\python.exe -c "import contracts, shared_logging, fastapi; print('ok')"
windows\Scripts\python.exe -m pip list | findstr /i "contracts fastapi uvicorn"
```

After a change in `contracts`, its version is bumped and re-bundled into every service's `vendor/`
(`brain_microservice\windows\Scripts\python.exe contracts\scripts\bundle.py`); reinstall the requirements to
pick the new wheel up. The deploy tool notices a changed wheel by itself.

## 5. Secrets and environment variables

### 5.1 The layers

**A service's settings live in its `.env` file, and only there.** On every deploy and start the tool writes the
service's `.env` (in its folder under `<workdir>/services/`) and the service reads that file when it starts. The tool does
**not** put the settings in the service's environment, and it removes from that environment any variable of the same name
that the machine or your shell has (an exported `GROQ_API_KEY`, say), because python-dotenv never overrides a variable
that is already set and such a variable would silently beat the file. Variables the file does not define (`PATH`, and
so on) pass through as usual. The file is readable by its owner only on Linux and the Pi, because it holds the API keys.

How each kind of service reads the file:

| Service | How it gets its `.env` |
|---|---|
| brain, stt, tts, speaker, stepper, ai-agent | load it themselves at start (python-dotenv, or Brain's own reader), before logging starts |
| microphone | has no `.env` support yet, so `infrastructure/outbound/runtime/service_runner.py` reads the file and starts it (catalogue key `dotenv = false`). Once its `main_flow/http.py` calls `load_dotenv`, set `dotenv = true`; a test tells you when |
| Docker (`runtime = "docker"`) | the file is bind-mounted read-only at `/app/.env`; the container has no settings variables. (A service with `dotenv = false` still gets `--env-file`) |

Two things follow from how the services read it. The services themselves load the file into their own process when
they start, which is how python-dotenv works. And python-dotenv expands `${NAME}` inside any value, so the tool refuses a
value that contains `${` (nothing real needs one). Values with a `#` or leading spaces are quoted for you.

Layers, later ones win:

| Layer | Source |
|---|---|
| `defaults` | the service repo's own `.env.example` |
| `catalogue` | `[services.<name>.env]` in `config/catalogue.toml` (what a deployed machine needs by default, such as `MOCK_HARDWARE=1`) |
| `computed` | host and port, and the base URLs of the services it consumes |
| `config/services/all.toml` | `[env]`: a value once, for every service that uses the variable (the project's defaults) |
| `config/local/all.toml` | the same, yours |
| `config/services/<service>.toml` | `[env]`: that service's own settings (the project's defaults) |
| `config/local/<service>.toml` | the same, yours: your keys and your own settings |

```powershell
py -3 oblivion.py env ai-agent --host mypc      # merged values, secrets masked, and the file each one came from
```

For route C (by hand) put the variables in a `.env` inside the service folder (every service except microphone loads
one). Setting them in the terminal's environment also works for a hand-started service, and there a variable already set
wins over the file; the deploy tool never does this.

**Brain's `APP_ENV`.** Brain runs its VS Code launch-profile logic even when deployed (its repo tracks `.vscode/launch.json`),
and that logic overrides `APP_ENV` from the `.env` with `development`. `APP_ENV` only labels Brain's log lines, so the
effect is cosmetic, but a value set in the settings files will not show up in Brain's logs. Fixing it belongs in the Brain repo.

### 5.2 The settings files: `config/services/` and `config/local/`

Everything you edit is in the **`config/`** folder, in files with one job each:

| File | Job | Committed |
|---|---|---|
| `config/robot.toml` | which layout the robot uses, and where each machine is (section 8) | no, yours |
| `config/layouts/<name>.toml` | where each service runs: the ready-made layouts | yes |
| `config/services/<service>.toml` | **one file per service**: which code it runs and its own settings, all listed at their defaults, commented out | yes |
| `config/services/all.toml` | settings several services share: the shared-logging variables and every variable more than one service uses | yes |
| `config/local/<service>.toml`, `config/local/all.toml` | **your** values and keys, same shape as the files above, and they win over them | no, yours |
| `config/machines/<machine>.toml` | what is particular to one machine: its Python, its work folder, its OS | no, yours |
| `config/catalogue.toml` | what each service is: repository, port, requirements, what it calls (almost never edited) | yes |

The files in `config/services/` are **generated** from each service's `.env.example` and source code (`scripts/env_inventory.py`;
a test fails when they no longer list everything the services read), about 60 variables, each once. Every line is commented out
and shows the default a deployed machine really gets (including what `config/catalogue.toml` presets, such as `AI_AGENT_RELOAD=0`
and `MOCK_HARDWARE=1`). What they leave out is what nobody sets on a deployed machine: the address, port and URLs (computed),
Brain's route paths and provider name, service names, the trace-export tuning knobs and the development switches (`VSCODE_*`,
test flags). Those keep their defaults and are still accepted if you do set one.

A settings file has the same few keys wherever it is:

```toml
# config/local/stepper.toml
branch = "feature_ai_claude_2"       # or: tag = "v1.0.0"  or: commit = "0123abc"   (at most one)
runtime = "native"                   # or "docker"
port = 8005                          # only to deviate from the catalogue (or write ports = { stepper = N } in the layout)
git = "https://github.com/you/fork"  # only to deploy another repository or a local checkout

[env]                                # the service's settings: numbers and true/false are fine, they become the text 0, true
MOCK_HARDWARE = 0
STEPS_PER_REVOLUTION = 3200
```

* **Change a setting:** copy its line from the service's file in `config/services/` to the same-named file in `config/local/`,
  remove the `#`, and edit the value. Nothing else is needed: a file that does not exist is simply not there.
* **Each service runs on exactly one machine,** so a service's settings need no per-machine variant: the Pi's `MOCK_HARDWARE = 0`
  sits in `config/local/stepper.toml` and only the Pi's stepper ever reads it. The same files are put on every machine, and a
  machine reads only the files of the services it runs (plus `all.toml`).
* **`all.toml` reaches every service that uses that variable, and no other:** `LOG_LEVEL` reaches all seven, `OPENAI_API_KEY`
  reaches STT and ai-agent (a service with no such setting never sees the key), `ALLOWED_ORIGINS` reaches speaker and stepper.
  A service's own file wins over `all.toml`. `SERVICE_NAME` and the computed variables are never taken from `all.toml`.
* **Priority, lowest to highest:** the service's own `.env.example`, `catalogue.toml`, the computed values, `services/all.toml`,
  `local/all.toml`, `services/<service>.toml`, `local/<service>.toml`; for the code, `--branch` on the command line wins over
  every file (section 5.1). `oblivion.py env <service> --host <machine>` shows the final value of every setting and the file it
  came from.
* **Secrets** are listed commented out in the committed files and are never active there. Put your keys in `config/local/`:
  `config/local/all.example.toml` and `config/local/ai-agent.example.toml` are the starting points, with the keys listed active and
  empty (copy one to the same name without `.example` and fill in the keys you use). The launcher (`launch.py`) writes these
  files for you on a first run. They are readable by their owner only when `launch.py` creates them.
* **Not set here:** the bind address, the port and the base URLs of the other services. They are computed from the layout and
  `config/catalogue.toml` so the services find each other; setting one here wins for that service but the others keep using the
  computed values, so `validate` warns.
* **Checked for you:** `validate` and `deploy` reject a settings file named after something that is not a service (or `all`),
  an unknown key, a value that is not a string, number or boolean, and, once the code is fetched, warn about a variable a service
  does not use (a probable typo, naming the file). Variables the code reads that no `.env.example` lists (`AI_AGENT_MODELS_FILE`,
  `AI_AGENT_MODEL_PHASE_<n>`, `GITHUB_API_KEY`) are declared in `config/catalogue.toml` (`extra_env`), and the ones nobody sets in
  `internal`. `*.example.toml` files are never read as settings.
* **Keys travel with the folder.** A machine that gets `config/local/` gets every key in it. To keep a key off a machine, leave
  that file out of that machine's copy: a service reads only the files of its own name and `all.toml`.
* **Not covered:** `aws_microservice` (Go, not deployed by this tool) reads `APP_PORT`, `AWS_REGION`, `AWS_ACCESS_KEY_ID` and
  `AWS_SECRET_ACCESS_KEY` from its own environment.

The keys the services need:

| Where in `config/local/` | Service receives | Required when |
|---|---|---|
| `all.toml` (or `stt.toml`) `OPENAI_API_KEY` | `OPENAI_API_KEY` | `STT_ENGINE=openai` (the default) |
| `ai-agent.toml` `GROQ_API_KEY` | `GROQ_API_KEY` | the active LLM profile uses Groq (default profile does) |
| `ai-agent.toml` `GOOGLE_API_KEY` | `GOOGLE_API_KEY` | the active profile uses Google models (default profile does) |
| `ai-agent.toml` `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `COHERE_API_KEY`, `GITHUB_PAT` | the same names | only if you switch models to those providers |
| `ai-agent.toml` `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | the same names | never; optional cost tracking |

`validate` and `plan` report a missing required value with the exact file to add it to. Nothing else in the
platform holds a secret. To see what a service will really get, and which file set each value:
`py -3 oblivion.py env <service> --host <machine>` (secrets are masked).

### 5.3 Per-service variables

Values shown are the defaults. Everything can be left alone except what the "Fill in" column names.

#### All services

| Variable | Default | Meaning |
|---|---|---|
| `SERVICE_NAME` | per service | name shown in logs |
| `SERVICE_HOST` | `127.0.0.1` | bind address. `0.0.0.0` only if another machine must reach it |
| `SERVICE_PORT` | see section 1 | HTTP port |
| `LOG_LEVEL` | `INFO` | `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FORMAT` | `json` | `json` (machine-readable) or `console` (`key=value`, for people) |
| `LOG_OUTPUT` | `stdout` | `stdout`, `stderr` or a file path |
| `TRACE_EXPORT_ENABLED` / `TRACE_EXPORT_URL` | off | send trace spans to a collector (see `shared-logging/docs/logging.md`) |
| `TRACE_EXPORT_HEADERS` (also `_TIMEOUT`, `_BATCH_SIZE`, `_FLUSH_INTERVAL`, `_QUEUE_SIZE`, `_ATTRIBUTES`) | see the logging guide | collector options. `TRACE_EXPORT_HEADERS` can carry credentials: put it in `config/local/all.toml` (`TRACE_EXPORT_HEADERS` under `[env]`); `plan` and `env` mask it |
| `APP_ENV` (or `ENVIRONMENT`) | `development` | label written into every log line and span (`development`, `staging`, `production`). Only Brain has it in its `.env.example`, so the others say `development` unless you set it in `config/local/all.toml` |

ai-agent uses `AI_AGENT_HOST` and `AI_AGENT_PORT` instead of `SERVICE_HOST` / `SERVICE_PORT`; the deploy tool
knows this and fills the right ones.

#### microphone (`.env.example`)

| Variable | Default | Fill in |
|---|---|---|
| `MICROPHONE_FALLBACK_SAMPLE_RATE` | `16000` | rarely |
| `MICROPHONE_TARGET_KEYWORDS` | empty | comma-separated device-name words to pick a specific input (empty = OS default). Use it when the default is wrong |
| `MICROPHONE_SHOW_METER` | `true` | `false` in a service window or log you do not want a level meter in |
| `MICROPHONE_SILENCE_THRESHOLD` | `150` | the microphone cuts what it hears into utterances (silence detection used to be STT's): the volume (RMS of 16-bit samples) under which it is silent. The cutting is always on; the rows below are its treatments |
| `MICROPHONE_SILENCE_LIMIT_SECONDS` | `2.0` | seconds of silence that end an utterance (above 0); lower answers faster, higher waits through pauses |
| `MICROPHONE_SPEECH_START_FACTOR` | `2.0` | speech starts at the threshold times this factor (at least 1) |
| `MICROPHONE_DC_OFFSET_REMOVAL` | `false` | subtract the slowly changing constant offset of the signal before measuring volume |
| `MICROPHONE_VOLUME_SMOOTHING`, `MICROPHONE_VOLUME_SMOOTHING_FACTOR` | `true`, `0.1` | measure a smoothed volume (weight of the newest chunk, above 0 up to 1) so one click is not speech |
| `MICROPHONE_NOISE_FLOOR_TRACKING` | `true` | raise the thresholds above the quietest volume heard (speech over 3 x it, silence under 2 x it); turn it off in a very quiet room whose floor stays too high |
| `MICROPHONE_RESAMPLE_TO_HZ` | `0` | rate of the audio sent on (linear interpolation, in the microphone's CPU); `0` = the device's rate, `16000` is what Whisper uses and sends less data |

Has no `.env` support in its own code: the deploy tool starts it through `infrastructure/outbound/runtime/service_runner.py`, which loads the
generated `.env` first. Started by hand (route C) it reads the process environment only.

#### stt

| Variable | Default | Fill in |
|---|---|---|
| `STT_ENGINE` | `openai` | `openai` = OpenAI Whisper API; any other value (use `local`) = faster-whisper `small.en` on the CPU |
| `STT_LANGUAGE` | `en` | ISO-639-1 code forced on the transcription (`en`, `es`). Must match the language people speak; `small.en` is English only |
| `STT_PROMPT` | empty | OpenAI engine only: words the model should spell as written, e.g. `Oblivion 306`, so it stops hearing `Obi-Wan 306`. Empty = no hint. Watch that silence does not come back as those words |
| `STT_GATE_ENABLED` | `0` | `1` = run the wake-phrase gate in this service: a second, local (free) engine under `/gate/...` that listens to everything. Needs the same on Brain: `WAKE_PHRASE_ENABLED=1`. The `prepare` step downloads its model |
| `STT_GATE_MODEL` | `tiny.en` | faster-whisper model of the gate; `base.en` is more accurate and slower (on a Pi 4 check the delay before the phrase is heard) |
| `STT_GATE_PROMPT` | `Oblivion 306` | hint that makes the gate spell the wake phrase right; use the same words as Brain's `WAKE_PHRASE` |
| `OPENAI_API_KEY` | empty | **secret**: required when `STT_ENGINE=openai` (`config/local/`, section 5.2) |

With `local` the model downloads on the first run into the Hugging Face cache (`~/.cache/huggingface`), so the
first start needs internet and takes a while; later starts are offline.

#### tts

| Variable | Default | Fill in |
|---|---|---|
| `TTS_ENGINE` | `piper` | `piper` (neural British "droid butler" voice), `espeak` (a real machine voice: formant synthesis plus a robot effect, no download needed) or `pyttsx3` (the old Windows SAPI / espeak voice). If the Piper voice or espeak is missing or cannot load, the service logs an error and uses pyttsx3, so Brain's preflight never hangs on a voice download |
| `TTS_PIPER_VOICE` | `en_GB-alan-medium` | Piper voice name. The deploy tool downloads it (`scripts/fetch_voice.py`, about 60 MB, into `models/` of the service, git-ignored) after it writes the `.env`, so a voice set in `config/local/tts.toml` is the one fetched. The machine needs internet only for that first download; later deploys find the file and skip it |
| `TTS_PIPER_MODEL_DIR` | `models` | folder of the voice files, relative to the service folder |
| `TTS_PIPER_SPEED` | `1.0` | speaking pace multiplier (`1.1` = a little brisker) |
| `TTS_PITCH_SEMITONES` | `2.0` | pitch lift of the voice, the pace is kept (`0` = as recorded) |
| `TTS_DROID_EFFECT` | `0.5` | metallic effect strength: `0` off, `0.5` light, `1` obvious, `2` maximum |
| `TTS_ESPEAK_COMMAND` | empty | espeak engine only: the program to run; empty = `espeak-ng` if installed, else `espeak` (the `espeak` apt package is already installed by `--system-deps`) |
| `TTS_ESPEAK_VOICE` | `en` | espeak only: voice and variant (`en+m3`, `en+klatt3`, `en+croak` ...) |
| `TTS_ESPEAK_SPEED` | `150` | espeak only: words per minute, 80-390 |
| `TTS_ESPEAK_PITCH` | `30` | espeak only: 0-99, lower is deeper |
| `TTS_ESPEAK_WORD_GAP_MS` | `20` | espeak only: extra silence between words, in milliseconds |
| `TTS_ROBOT_EFFECT` | `1.0` | espeak only: robot effect strength (ring modulation, sample hold, bit crush): `0` off, `1` default, `3` maximum |
| `TTS_SPEECH_RATE` | `140` | pyttsx3 only: words per minute |
| `TTS_VOICE_NAME` | `Zira` | pyttsx3 only: text the voice name must contain; otherwise the first English voice is used. On Windows Zira is English; the default system voice may be Spanish |

Voice files: `deploy` and `update` run the service's `prepare` step (`config/catalogue.toml`) once its `.env` exists. For tts it downloads the voice to a temporary folder, loads it once to prove it is intact and only then moves it into place, so an interrupted download never leaves a broken voice. A failed download (no internet) is a warning: the service starts on the pyttsx3 voice and its log says `Piper unavailable; falling back to pyttsx3`; run `deploy` again once online. To fetch by hand: `windows\Scripts\python.exe scripts\fetch_voice.py` from `tts_microservice` (Linux: `bin/python`). **Docker** bakes the default voice into the image while building (no `.env` exists then): a different `TTS_PIPER_VOICE` needs the voice on the image or `TTS_ENGINE=pyttsx3`. A Raspberry Pi 4 or newer is the realistic minimum for Piper (a PC renders about 25x faster than real time; a Pi 3 would lag).

#### speaker

| Variable | Default | Fill in |
|---|---|---|
| `SPEAKER_DEVICE_INDEX` | empty | index of the output device; empty = auto-detect from the keywords. **Set it when auto-detection picks the wrong device** (list them with the command in section 10) |
| `SPEAKER_DEVICE_KEYWORDS` | `i2s,hw,default,sysdefault` | device-name words used to auto-detect (Windows example: `speakers,realtek`) |
| `ALLOWED_ORIGINS` | `*` | CORS origins |

Speaker has no authentication (the old token option was removed).

#### ai-agent

| Variable | Default | Fill in |
|---|---|---|
| `GROQ_API_KEY`, `GOOGLE_API_KEY` | empty | **secrets** (section 5.2). Which keys you need depends on the profile below |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `COHERE_API_KEY`, `GITHUB_PAT` | empty | **secrets**, only for models on those providers |
| `GROQ_URL` | empty | **required with the default profile.** Public OpenAI-compatible endpoint, `https://api.groq.com/openai/v1` (not a secret). Set by `config/catalogue.toml` for every machine, so you normally do nothing |
| `GOOGLE_URL` | empty | **required with the default profile.** `https://generativelanguage.googleapis.com/v1beta/openai/` (also set by `config/catalogue.toml`) |
| `MISTRAL_URL`, `COHERE_URL`, `GITHUB_URL`, `OLLAMA_URL` | empty | base URL of that provider. `OLLAMA_URL` alone is enough to make ai-agent available (local models) |
| `AI_AGENT_HOST` / `AI_AGENT_PORT` | `0.0.0.0` / `7998` | bind (the deploy tool sets both from the layout) |
| `AI_AGENT_RELOAD` | `1` in `.env.example`, **`0` set by the deploy tool** | auto-reload is for development only; never `1` in a deployed service |
| `AI_AGENT_HISTORY_TURNS` | `6` | exchanges remembered per session |
| `AI_AGENT_FAST_PATH_ENABLED` | `1` | `1` = plain information/conversation skips planning and answers directly (much faster); `0` = always run the full pipeline |
| `AI_AGENT_PARALLEL_ACTIONS` | `1` | independent plan actions that may run at once; keep `1` on Groq (token-per-minute limit) |
| `AI_AGENT_MAX_ATTEMPTS` | `3` | tries of a failed LLM/tool call |
| `AI_AGENT_MODELS_FILE` | `config/step_models.json` | another model-choice file |
| `AI_AGENT_MODEL_PHASE_<n>` | unset | override the model of one phase (1 triage, 2 project manager, 3 safety gate, 4 worker, 5 MCP operator, 6 data engineer, 7 draft writer, 8 editor, 9 answer checker, 99 clarification; 20 motion planner, the movement agent's model) |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | empty | optional cost tracking; only metadata is sent |

**Choosing the LLM**: the active profile is the `profile` field of `ai-agent/config/step_models.json`
(`budget50_groq` today: the planning steps on Groq `openai/gpt-oss-120b`, the small steps on Google lite
models, so it needs `GROQ_API_KEY`, `GROQ_URL`, `GOOGLE_API_KEY`, `GOOGLE_URL`). Other profiles
(`proven`, `budget`, `balanced`, `quality`, `budget50`) use Google only. Change the file and restart to switch.
While no provider key or `OLLAMA_URL` is configured, `/available` answers 200 with `data.is_available` false (reason: no language model provider is configured) and the deploy tool reports
ai-agent as not ready.

Sessions live in ai-agent's memory only: restarting ai-agent forgets the conversation (Brain then opens a new
session by itself).

#### stepper

| Variable | Default | Fill in |
|---|---|---|
| `MOCK_HARDWARE` | `0` in `.env.example`, **`1` set by the deploy catalogue** | `1` = no GPIO, moves are only simulated. **Only the exact value `1` counts** (the stepper compares the string): `true` does NOT select the mock, and on a Raspberry Pi it would drive the real motors. Set `0` **only on the Raspberry Pi wired to the motors** (`config/local/stepper.toml`) |
| `STEPPER_CONFIGS` | two steppers (`stepper_1`, `stepper_2`) | JSON map id → `{"step": <BCM pin>, "dir": <BCM pin>, "en": <BCM pin>}`. Match your wiring |
| `STEPS_PER_REVOLUTION` | `400` | full steps × microsteps of your motor/driver (1.8° motor = 200; with 1/8 microstepping = 1600). A wrong value moves the arm the wrong angle |
| `DEFAULT_SPEED_LIMIT` | `1000.0` | the speed in steps per second a move gets when the request gives none. It is not a cap: a requested speed passes through unchanged, and the Python pulse loop itself tops out near 3500 steps/s on a Raspberry Pi 4 |
| `ALLOWED_ORIGINS` | `*` | CORS origins |

Real motors are driven only on a Raspberry Pi (`RPi.GPIO`); everywhere else the mock adapter runs. The first
time on real hardware, move a small angle with the arm unloaded and be ready to cut power.

#### brain

| Variable | Default | Fill in |
|---|---|---|
| `APP_ENV` | `development` | `development`, `staging` or `production` |
| `MICROPHONE_BASE_URL`, `STT_BASE_URL`, `TTS_BASE_URL`, `SPEAKER_BASE_URL` | `http://127.0.0.1:<port>` | **computed by the deploy tool** from the layout. Set by hand only in route C when a service is on another machine |
| `AI_AGENT_BASE_URL` | `http://127.0.0.1:7998` | same |
| `STEPPER_BASE_URL` | `http://127.0.0.1:8005` | same; optional, without a stepper the arms simply do not move |
| `*_ENDPOINT` (`MICROPHONE_START/STOP/STREAM`, `STT_SET_STREAM/GET_STREAM/BATCH`, `TTS_SET_STREAM/STREAM`, `SPEAKER_PLAY_STREAM`) | the routes the services expose | leave as they are |
| `AI_AGENT_FLOWS` | `conversation-flow,motion-flow` | the flows of ai-agent Brain asks, **one after the other, in this order** (each only when the one before has ended). Their routes are `/<flow>/session/...`. Known flows: `conversation-flow`, `motion-flow`; an unknown name stops Brain at startup |
| `PROGRESS_RECEIVED_MESSAGE`, `PROGRESS_THINKING_MESSAGE`, `PROGRESS_THINKING_INTERVAL_SECONDS` | `Message received.`, `Thinking.`, `2` | what Brain says while the flows work: the first at once when an utterance arrives, the second every N seconds until every flow has ended (the first one after N seconds, so a quick answer stays quiet). An empty text says nothing; an interval of 0 turns `Thinking.` off |
| `WAKE_PHRASE_ENABLED` | `0` | `1` = Brain answers only an utterance in which the wake phrase is heard (anywhere in the sentence); the audio of those goes to the real STT, the rest is dropped without cost. Needs `STT_GATE_ENABLED=1` on the STT service |
| `WAKE_PHRASE` | `Oblivion 306` | the phrase: a name and a code; the code may be heard as `306`, `three oh six`, `three hundred and six` |
| `WAKE_NAME_SIMILARITY` | `0.75` | how like the name a misheard word may be (0 to 1) |
| `WAKE_FOLLOWUP_SECONDS` | `15` | after the phrase alone (Brain says `WAKE_ACK_MESSAGE`) the next sentence is taken without the phrase, once, within this time; `0` = off |
| `WAKE_ACK_MESSAGE` | `Yes?` | what Brain says when the phrase comes alone |
| `WAKE_USE_GATE_STT` | `1` | `0` = no local gate (leave `STT_GATE_ENABLED=0` too): the real STT hears every utterance, which costs tokens each time, and Brain reads the phrase in its text. Use it when the local gate does not hear the phrase well |
| `WAKE_ANSWER_SECONDS` | `45` | when an agent asks a question, the next sentence (its answer) is taken without the phrase, once, within this time; `0` = off |
| `STT_GATE_PATH_PREFIX` | `/gate` | where the gate's routes are in the STT service (a contract, leave it) |
| `STEPPER_ROTATE_ENDPOINT_TEMPLATE` | `/control/{stepper_id}/rotate` | leave |
| `STEPPER_LEFT_ARM_STEPPER_ID`, `STEPPER_RIGHT_ARM_STEPPER_ID` | `stepper_1`, `stepper_2` | must be ids that exist in the stepper's `STEPPER_CONFIGS` |
| `STEPPER_DEFAULT_RPM` | `15` | arm speed |
| `PROVIDER_NAME`, `PROVIDER_TIMEOUT_SECONDS` | `local`, `30` | leave |
| `STARTUP_PREFLIGHT_ENABLED` | `true` | Brain waits for microphone, STT, TTS and speaker before opening the pipeline |
| `STARTUP_PREFLIGHT_TIMEOUT_SECONDS` | `60` | how long it waits |
| `MICROSERVICE_READY_POLL_INTERVAL_SECONDS` | `2` | polling interval |
| `RUN_LIVE_MICROSERVICE_TESTS` | `0` | tests only |

ai-agent and stepper are deliberately **not** part of the mandatory preflight: Brain starts without them.

## 6. Start order and health checks

Start dependencies first; the deploy tool does this on its own (`deploy`, `start`, `launch.py`).

1. `stepper`, `ai-agent`, `tts`, `stt`, `speaker`, `microphone` in any order (they do not depend on each other)
2. `brain` last. It waits up to `STARTUP_PREFLIGHT_TIMEOUT_SECONDS` for microphone, STT, TTS and speaker, then
   opens the voice pipeline by itself.

By hand (route C), one terminal per service, from the service folder:

```powershell
cd D:\Hobbys\IA\OBLIVION\stepper_microservice
$env:MOCK_HARDWARE = "1"
windows\Scripts\python.exe main.py

cd D:\Hobbys\IA\OBLIVION\ai-agent
$env:AI_AGENT_RELOAD = "0"      # plus the LLM keys/URLs of section 5.3, exported in this terminal
windows\Scripts\python.exe composition_root\main.py

# microphone, stt, tts, speaker, brain:  windows\Scripts\python.exe main.py   (from each folder)
```

Every service answers `GET /health` (process is up). Services that depend on a device, model or key also
answer `GET /available` (it can really work: HTTP 200 with `data.is_available` true or false and a `reason`). The deploy tool waits on both and, after a 15 s grace, reports a service that answers but says it is not available.

```bash
curl -s http://127.0.0.1:8000/available     # microphone
curl -s http://127.0.0.1:8001/available     # stt
curl -s http://127.0.0.1:8002/available     # tts
curl -s http://127.0.0.1:8003/available     # speaker
curl -s http://127.0.0.1:7998/available     # ai-agent (is_available false until an LLM key is configured)
curl -s http://127.0.0.1:8005/available     # stepper
curl -s http://127.0.0.1:7999/health        # brain
```

Answers use one envelope: `action / status / status_code / message / timestamp / data`. Use the real host
names when services are on different machines; never assume `127.0.0.1` there.

## 7. Testing the whole flow

### 7.1 Manual acceptance (real microphone, real speaker)

Use **headphones** (the robot would otherwise hear itself). With every service healthy:

1. Say "Hello, how are you?" and pause about two seconds. You should hear "Message received." at once, then (if the
   answer takes more than 2 seconds) "Thinking." every 2 seconds, then a spoken answer written by ai-agent (not an echo
   of your words).
2. Say "Move your left arm ninety degrees forward." You should hear a confirmation and, with the stepper in
   mock mode, see a rotate request in the stepper log (`py -3 launch.py logs stepper` or its console window).
   Say "Move your left arm ninety degrees and then bring it back": two rotate requests, in that order (the
   second one the opposite way). Say "Move your arm": the robot answers, then asks which arm and how far, and your answer
   goes only to the movement agent and completes the movement.
3. Say something impossible ("Fly to the moon"). ai-agent should refuse politely.
4. Stop ai-agent, speak again: Brain answers with its spoken apology and keeps running. Start ai-agent, speak
   again: the conversation works without restarting Brain.

`py -3 launch.py logs brain` shows which hop of the pipeline is active.

### 7.2 Automated, real services, mocked input

`contracts/tests/e2e/test_real_pipeline.py` starts all six services for real (own venv, real Whisper, the TTS
service's default engine, real playback, real LLM, the stepper in mock mode) and replaces only the **input data**: phrases
are synthesised with the Windows SAPI voice, or with Piper where pywin32 is missing (Linux; `make_speech.py`) and streamed as the microphone's capture. The TTS under test is
Piper `en_GB-alan-medium` when its voice file is present in the TTS service's `models/` folder (the `prepare` step fetches it),
otherwise the pyttsx3 fallback, so the SAPI/Piper voice only produces the input. It plays audio out loud and makes LLM
calls, so it is skipped unless asked for. It needs the LLM keys and URLs from section 5 exported in the
environment (never in a file) and a working output device.

```powershell
$env:E2E_REAL_LLM = "1"
$env:GROQ_API_KEY = "<key>"; $env:GROQ_URL = "https://api.groq.com/openai/v1"
$env:GOOGLE_API_KEY = "<key>"; $env:GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# $env:SPEAKER_DEVICE_INDEX = "<index>"      # if the default output cannot be opened
brain_microservice\windows\Scripts\python.exe -m pytest contracts\tests\e2e\test_real_pipeline.py -q
```

Run from `D:\Hobbys\IA\OBLIVION`. Without real hardware, the fake-hardware wire test needs no keys:
`brain_microservice\windows\Scripts\python.exe -m pytest contracts\tests -q`.

### 7.3 Tests of the deploy tool itself

```powershell
brain_microservice\windows\Scripts\python.exe -m pytest deployment\tests -q      # about 150 s (271 passed, 2 skipped on 2026-10-04), real git repos and processes
```

## 8. Several machines

### 8.1 A layout says where each service runs

Each fact is written **once**. The layout (a file in `config/layouts/`) says which machine runs which services; `config/robot.toml`
says which layout the robot uses and where each machine is; the port of every service is in `config/catalogue.toml`, which you do
not edit. Everything else is derived:

| It is | Derived from |
|---|---|
| a machine's services | the layout's `services` list for that machine |
| the URL of a service on another machine | that machine's address (`config/robot.toml`) + the service's port |
| a service's port | `config/catalogue.toml` (`ports = { name = N }` on a machine in the layout only to deviate; callers follow) |
| a machine's bind address | `0.0.0.0` only if a service on another machine calls one of its services, else `127.0.0.1` |
| `SERVICE_HOST`, `SERVICE_PORT` and every `*_BASE_URL` of a service | the four rows above |

Five layouts are ready-made (`py -3 oblivion.py layouts` lists them with their machines):

| Layout | Machines |
|---|---|
| `all-in-one` | `robot`: every service (address 127.0.0.1, nothing to configure) |
| `speaker-on-pc` | `pc`: speaker. `pi`: microphone, brain, stt, tts, ai-agent, stepper |
| `audio-on-pc` | `pc`: microphone, speaker. `pi`: brain, stt, tts, ai-agent, stepper |
| `stepper-on-pi` | `pc`: brain, microphone, stt, tts, speaker, ai-agent. `pi`: stepper |
| `pc-server-pi` | `pc`: microphone, speaker. `server`: brain, stt, tts, ai-agent. `pi`: stepper |

A layout is a small file; to make your own, copy the closest one in `config/layouts/` to a new name:

```toml
# config/layouts/speaker-on-pc.toml
description = "Speaker on the PC; microphone, brain, stt, tts, ai-agent and stepper on the Pi."

[machines.pc]
services = ["speaker"]

[machines.pi]
services = ["brain", "microphone", "stt", "tts", "ai-agent", "stepper"]
# address = "192.168.1.30"          # a default address, only for a layout that never changes (all-in-one has one)
# ports = { stepper = 18005 }       # only to deviate from the catalogue
```

`config/robot.toml` is the only file every robot needs (`oblivion.py init` writes it):

```toml
layout = "speaker-on-pc"

[addresses]                  # an IP or a host name: no http://, no port
pc = "192.168.1.20"
pi = "192.168.1.30"
```

Put `config/robot.toml` and `config/local/` on every machine. Then `--host <machine>` means "this machine of the layout".

```powershell
py -3 oblivion.py layouts                        # the ready-made layouts and the one in use
py -3 oblivion.py topology                       # every machine, its address, services, what it exposes and calls; checks the layout
py -3 oblivion.py deploy --host pi               # on the Pi; likewise --host pc on the PC
py -3 oblivion.py deploy --host pc --config D:\robot\config    # another config folder, with the same shape
```

`topology` ends with `OK` when every machine can find what it needs, and otherwise names the missing service
(`brain needs 'speaker': put it on a machine of the layout (config/layouts/)`) and lists services that no machine runs.

### 8.2 Per-machine settings and overrides

* **Settings and keys:** in `config/local/` (section 5.2): the Pi's `MOCK_HARDWARE = 0` in `stepper.toml`, the keys in `all.toml`
  and `ai-agent.toml`, a PC's `MICROPHONE_TARGET_KEYWORDS = "usb"` in `microphone.toml`. A key that only one machine should hold
  is in a file that only that machine gets.
* **What is particular to a machine:** `config/machines/<machine>.toml` (optional, `config/machines/pi.example.toml`): `python`
  (when the default `python3` is older than a service needs), `workdir` (where the clones, virtualenvs, logs and state go;
  relative paths are relative to the config folder), `os` (only to force the detection) and `bind` (only to override the derived
  address). Without a file the machine uses the defaults.
* **Branch, Docker, another repository:** `branch` / `tag` / `commit`, `runtime = "docker"`, `port` and `git` at the top of a
  service's settings file: in `config/local/<service>.toml` for your robot, or `config/services/<service>.toml` for everyone.
  The machine that runs the service picks them up; the others ignore them.

A typical three-machine robot (layout `pc-server-pi`; follow 3.1 on each):

| Machine | Runs | What `config/local/` needs for it |
|---|---|---|
| Windows PC with the sound card | microphone, speaker | nothing (device hints only if the wrong device is picked) |
| Server (Windows or Linux, Python 3.12+) | brain, ai-agent, stt, tts | `OPENAI_API_KEY` in `all.toml`, `GROQ_API_KEY` and `GOOGLE_API_KEY` in `ai-agent.toml` |
| Raspberry Pi wired to the motors | stepper | `MOCK_HARDWARE = 0` in `stepper.toml` |

The PC and the Pi bind to the network by themselves (Brain calls them); open the firewall for their ports (8000, 8003, 8005).

### 8.3 Start order across machines

Brain checks microphone, STT, TTS and speaker when it starts and, if they are not
all available within `STARTUP_PREFLIGHT_TIMEOUT_SECONDS` (60), **it exits and nothing restarts it** (verified: it logs
`StartupPreflightError` and never opens its port). So the tool waits for you: before starting a service it waits up to
`--remote-wait` seconds (default 120, `0` = do not wait) for the required services that live on other machines,
and prints which ones it is waiting for. This also covers boot (`autostart` runs
`oblivion start`) and `update`. It does not wait for the optional stepper. If the other machines take longer to
boot, raise `--remote-wait`; if Brain is dead anyway, `oblivion restart --host <machine> --service brain`.

Rules of thumb:

* Audio services belong on the machine that has the sound card; the stepper on the Raspberry Pi wired to the
  motors (`MOCK_HARDWARE = 0` in `config/local/stepper.toml` only).
* There is no authentication: trusted LAN only. `validate` warns whenever a machine binds `0.0.0.0`.
* `validate` fails when a required service is placed on no machine (the stepper is the only optional one), and `topology` and
  `validate` refuse an address that is malformed; they warn about an address that points back at this same machine.
* The mandatory preflight makes Brain wait for the four audio/speech services (and give up, see above), so
  start those machines first, keep the tool's `--remote-wait`, or raise `STARTUP_PREFLIGHT_TIMEOUT_SECONDS`.

## 9. Operating it

```powershell
py -3 oblivion.py start|stop|restart|status|logs --host mypc [--service ai-agent]
py -3 oblivion.py update --host mypc                        # newest code, rolls back a service that does not start
py -3 oblivion.py update --host mypc --branch brain=feature_x
py -3 oblivion.py autostart install --host mypc             # systemd user unit, or a scheduled task at logon (Windows)
```

* Logs: `<workdir>/logs/<service>.log`; on Windows each service also has its own console window.
  Structured JSON by default; set `LOG_FORMAT=console` for readable lines. Brain at the default `LOG_LEVEL=INFO` writes a line per
  audio chunk, about 1 GB an hour: set `LOG_LEVEL = "WARNING"` in `config/local/brain.toml` on a robot that stays on.
* State (what commit is installed): `<workdir>/state`. Generated `.env` files: in each service folder
  (`<workdir>/services/<folder>/.env`, regenerated on every deploy; edit the files under `config/`, not these).
* An update never overwrites local edits in a clone (refused unless `--force`) and never leaves a service dead.
* Linux/Pi: run `sudo loginctl enable-linger $USER` once so the user unit starts without a login.
* Rotating a key: edit the file in `config/local/` (copy it to the machine) and `restart` the service.

## 10. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `ai-agent` never becomes ready,  `data.is_available` is false in `/available` | no LLM key/URL reached it. `oblivion.py env ai-agent --host mypc` (values masked) shows what it has; add the keys to `config/local/ai-agent.toml` (the `GROQ_URL`/`GOOGLE_URL` endpoints are preset), then restart |
| `update` rolls ai-agent back to the previous commit | a service that answers but reports `is_available` false is counted as unhealthy after the grace period. Without an LLM key every new ai-agent release looks broken: fix the secrets first, or `update --no-rollback` to keep it and read its log |
| ai-agent answers, but replies are errors about a model/provider | the active profile needs a provider you did not configure: fill its key and URL or switch `profile` in `config/step_models.json` |
| Brain speaks an apology ("could not reach my decision-making service") | ai-agent is down or its URL is wrong (`AI_AGENT_BASE_URL`); check `curl .../available` from the Brain machine |
| Arms do not move, replies work | stepper missing/unreachable (moves are best effort), or `STEPPER_*_ARM_STEPPER_ID` is not an id in the stepper's `STEPPER_CONFIGS`. See Brain's log |
| Brain stays in preflight | one of microphone/stt/tts/speaker is not `available`; check each with section 6, or `STARTUP_PREFLIGHT_ENABLED=false` while debugging |
| STT fails at start with `openai` engine | `OPENAI_API_KEY` missing in `config/local/` (`all.toml` or `stt.toml`); or use `STT_ENGINE = "local"` |
| STT hears nothing / wrong text | wrong `MICROPHONE_TARGET_KEYWORDS` input, or `STT_LANGUAGE` does not match the spoken language |
| Speaker fails to open a device (`PaErrorCode -9999`, "Blocking API not supported") | the auto-selected device is a WDM-KS one. List devices and set `SPEAKER_DEVICE_INDEX` to an MME/WASAPI output: `windows\Scripts\python.exe -c "import sounddevice as sd; print(sd.query_devices())"` |
| TTS speaks with the old robotic voice | the Piper voice is missing, so the service fell back to pyttsx3 (its log says `Piper unavailable`). Run `scripts/fetch_voice.py` from the service folder, or `deploy` again with internet, then restart tts |
| TTS speaks the wrong language (pyttsx3 fallback) | Windows default voice is Spanish: set `TTS_VOICE_NAME=Zira` (already the default) or another installed English voice |
| Robot answers its own voice | speakers and microphone in the same room: use headphones |
| Stepper install fails on Python 3.14 with a Rust/`pydantic-core` error | old exact pins; the Windows requirements file now uses lower bounds. Update the stepper code |
| `deploy` / `validate` says `library 'shared-logging' is not available on this machine` | neither the workspace checkout nor `wheels/shared_logging-*.whl` exists: the clone of this repository is incomplete (`git status`, `git pull`), or run `scripts/bundle_shared_logging.py` on a machine that has the workspace and commit the wheel |
| `update` refuses ("local changes") | edits inside a clone under `<workdir>/services`; commit or discard them, or `--force` |
| A variable I exported in my shell (or set on the machine) has no effect on a service | by design: the service reads only its `.env`, and the tool removes same-named variables from its environment. Put the value in the service's file in `config/local/` (setting or key) and restart the service. `oblivion.py env <service> --host <machine>` shows what it will get |
| Health check times out on first run | dependency install or the local Whisper download is slow: `--health-timeout 600` (launch.py) |
| `validate`/`deploy` says `ai-agent needs Python 3.12+` | the interpreter that builds the venv is older (Raspberry Pi OS Bookworm has 3.11): use a newer Python via `python = ...` in `config/machines/<machine>.toml`, or run ai-agent on another machine (a layout that places it there) |
| Brain is not running after a boot or a deploy, its log ends with `StartupPreflightError` | microphone, STT, TTS or speaker was not available in time. Check them (`status --remote`), then `restart --service brain`. The tool waits for remote ones (`--remote-wait`, section 8); raise it if the other machines boot slowly |
| Port already in use | another copy is running (`launch.py status` / `stop`) or change `port =` in the service's file in `config/local/` |
| A real motor does not move through the service, though a test script moves it | check `MOCK_HARDWARE = 0` in `config/local/stepper.toml` on the Pi, and `STEPS_PER_REVOLUTION` (400 full steps x 8 microsteps = 3200 for a 0.9 degree motor on a TMC2209 at its default 1/8): a quarter of the right value moves the shaft a few degrees and looks like a twitch |
| Deployed code lacks a recent change | routes A and B deploy committed code only (section 2) |

## 11. Known limits

* Docker, systemd units, Windows scheduled tasks and real Raspberry Pi hardware have not been exercised by
  the deploy tool. Docker cannot reach a sound card on Windows, and the generic image starts `main.py`, so it
  does not fit ai-agent (`composition_root/main.py`); run ai-agent natively.
* `ai-agent` needs Python 3.12+ (verified: it does not install on 3.11, so not on stock Raspberry Pi OS
  Bookworm). It has been installed on Windows with 3.14 and started, but never on Linux; sessions are in memory only.
* What was verified on a fresh layout (2026-09-25, Windows 11, real `git clone` and `pip install` into new virtual
  environments, services started headless on spare ports): the install and start of all seven services on Python
  3.14, and the install of everything but ai-agent on Python 3.11 with the Linux file selection. **Not** verified:
  a real Linux or Raspberry Pi (apt packages, `--system-deps`, `RPi.GPIO` with the motors), systemd autostart,
  Windows scheduled tasks, Docker, cross-machine traffic and the firewall rules above.
* The Raspberry Pi stepper uses `RPi.GPIO` 0.7.1, written for Pi 1 to 4. A Pi 5 needs a different GPIO library
  (`rpi-lgpio` is the usual drop-in): unverified here, decide before wiring one.
* The real end-to-end suite (`test_real_pipeline.py`) has not yet completed a full run: it needs valid LLM
  keys and an output device that PortAudio can open.
* No service-to-service authentication exists (speaker's was removed). Do not expose these ports to the internet.
* Some service READMEs still mention removed features (speaker authentication, an OpenAI TTS engine). Trust
  the `.env.example` files and this manual.
