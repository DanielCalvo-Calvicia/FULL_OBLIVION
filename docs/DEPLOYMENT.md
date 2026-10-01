# OBLIVION deployment manual

> This is the **reference** manual. For a step-by-step walkthrough (what to type on each machine, in order), read
> [`USER_GUIDE.md`](USER_GUIDE.md) first.

How to bring the whole robot up like a production environment: what to install, which Python virtual
environment each service needs, every environment variable and where to fill it, in which order things
start, how to check that everything is healthy and what to do when it is not.

This manual describes the platform as it is today. Where something has never been run (Docker, systemd,
scheduled tasks, real Raspberry Pi hardware) it says so. **No value in this file is a secret**: keys always
go in `robot.toml`, the single file of truth, which is never committed (section 5.2).

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
| **B. `oblivion.py` + `robot.toml`** | one or several machines, per-service branches, Docker for some services, boot autostart | git |
| **C. By hand from the workspace** | you want to run exactly the files on disk, including uncommitted work | your working folders |

> **The git routes (A and B) deploy what is committed and reachable from the repository URL.** They clone
> `https://github.com/DanielCalvo-Calvicia/<repo>.git` and check out a branch. Work that only exists as
> uncommitted changes in your working folders (for example a feature you are still finishing) is **not**
> deployed by A or B. Commit it first, then either push it or point a host file (`hosts/<machine>.toml`) at your local repo:
>
> ```toml
> [services.brain]
> git = "D:/Hobbys/IA/OBLIVION/brain_microservice"   # a local clone source instead of GitHub
> branch = "feature_ai_claude_2"
> ```
>
> Use route C to run uncommitted code.

Branches today: every repo (including `stepper_microservice` and this one) works on `feature_ai_claude_2`,
which is the default of `launch.py` **and of `services.toml`**. Do not deploy `main` yet: it does not carry the
vendored `contracts` wheel every service's requirements file points at, so the install fails. Change the default
in `services.toml` to `main` once the branches are merged.

### Route A: one command

```powershell
py -3 launch.py            # Linux / Raspberry Pi: python3 launch.py
py -3 launch.py status     # state, code version and health of every service
py -3 launch.py logs ai-agent
py -3 launch.py stop
```

**With a `robot.toml`, the launcher uses it** (one machine is picked automatically; `--machine NAME` picks one of several) and
creates, asks and copies nothing: the layout, settings and keys are that file's. **Without one**, the first run creates
`hosts/local.toml` and `secrets/local.env` (both git-ignored), asks once for the OpenAI
key for speech-to-text (or reads `OPENAI_API_KEY`; use `--stt local` to avoid it), copies any LLM provider
keys that are exported in your environment into `secrets/local.env` (the machine-local overlay) for ai-agent (`GROQ_API_KEY`,
`GOOGLE_API_KEY`, ...; the values are never printed), fetches the code, builds one virtual environment per
service, starts everything in order and waits until each service is healthy.

Export the LLM keys **before** the first run, in the same terminal, so they are picked up:

```powershell
$env:GROQ_API_KEY   = "<your Groq key>"       # the variable names are the point; use your own values
$env:GOOGLE_API_KEY = "<your Google key>"
py -3 launch.py
```

Later runs update to the newest code of the branch (rolling back a service that does not start) and restart.
`--no-update` only starts. `--dry-run` prints every command. On Linux/Pi add `--system-deps` the first time.
If `hosts/local.toml` already exists from an older version it is **not** rewritten: add
`[services.ai-agent]` and `[services.stepper]` by hand (the LLM endpoints are preset in `services.toml`), or delete the file
and let `launch.py` create it again.

### Route B: `robot.toml`

```powershell
copy robot.example.toml robot.toml                  # the layout and every setting and key: sections 5.2 and 8
py -3 oblivion.py topology                          # the whole robot; checks every machine can find what it needs
py -3 oblivion.py doctor   --host <machine>         # git, python, docker (if used), writable workdir
py -3 oblivion.py validate --host <machine>         # wiring and missing required values, no network
py -3 oblivion.py plan     --host <machine>         # every service, branch and env value with its origin
py -3 oblivion.py deploy   --host <machine>         # fetch code, install, write env, start, health-check
py -3 oblivion.py status   --host <machine> --remote
```

One machine: give `[machines.pc]` all seven services and the address `127.0.0.1`. A hand-written host file
(`hosts/all-in-one.example.toml`) still works without a `robot.toml`.

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
Python 3.12+ (Ubuntu 24.04 ships it) and give it its own machine in `robot.toml` (Brain finds it there), or install a newer Python and set
`[host] python = "<path>"`. `fastapi==0.111.0` / `pydantic==2.7.4` have no 3.14 wheels (the Windows stepper
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
cp robot.example.toml robot.toml                               # once: the layout, the settings and the keys; then the same file on every machine
chmod 600 robot.toml                                            # Linux/Pi: it holds keys
python3 oblivion.py topology                                    # optional: the whole robot as the tool understands it
python3 oblivion.py doctor   --host <machine>                   # Windows: py -3
python3 oblivion.py validate --host <machine>
python3 oblivion.py deploy   --host <machine> --system-deps     # --system-deps: Linux/Pi only (sudo apt)
python3 oblivion.py status   --host <machine> --remote
python3 oblivion.py autostart install --host <machine>
```

`robot.toml` is the single file of truth (section 5.2). The tool never copies it or any secret between machines: you put
the file on each machine, and a machine may keep a key out of its copy by using its own `secrets/<machine>.env`. `doctor` and `validate` change nothing, and `deploy --dry-run`
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

The deploy tool does this for you from `services.toml` `[libraries.shared-logging]`, trying in order `path`
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
| microphone | has no `.env` support yet, so `oblivion/service_runner.py` reads the file and starts it (registry key `dotenv = false`). Once its `main_flow/http.py` calls `load_dotenv`, set `dotenv = true`; a test tells you when |
| Docker (`runtime = "docker"`) | the file is bind-mounted read-only at `/app/.env`; the container has no settings variables. (A service with `dotenv = false` still gets `--env-file`) |

Two things follow from how the services read it. The services themselves load the file into their own process when
they start, which is how python-dotenv works. And python-dotenv expands `${NAME}` inside any value, so the tool refuses a
value that contains `${` (nothing real needs one). Values with a `#` or leading spaces are quoted for you.

Layers, later ones win:

| Layer | Source |
|---|---|
| `defaults` | the service repo's own `.env.example` |
| `registry` | `[services.<name>.env]` in `services.toml` |
| `computed` | host and port, and the base URLs of the services it consumes |
| `robot ALL` | `[env]` of `robot.toml`: one value for every service that uses the variable |
| `env file ALL` | `ALL__<VARIABLE>=value` lines of the optional machine-local `secrets/<machine>.env` |
| `host` | `[services.<name>.env]` in a host file |
| `robot` | `[env.<service>]` of `robot.toml` |
| `service file` | `[env]` of `services/<service>.toml`: one file per service, which may also pin its `branch`, `tag` or `commit` (see `README.md`) |
| `env file` | `<SERVICE>__<VARIABLE>=value` lines of the optional machine-local `secrets/<machine>.env` |

```powershell
py -3 oblivion.py env ai-agent --host mypc      # merged values, secrets masked, and the layer of each one
```

For route C (by hand) put the variables in a `.env` inside the service folder (every service except microphone loads
one). Setting them in the terminal's environment also works for a hand-started service, and there a variable already set
wins over the file; the deploy tool never does this.

**Brain's `APP_ENV`.** Brain runs its VS Code launch-profile logic even when deployed (its repo tracks `.vscode/launch.json`),
and that logic overrides `APP_ENV` from the `.env` with `development`. `APP_ENV` only labels Brain's log lines, so the
effect is cosmetic, but a value set in the host file will not show up in Brain's logs. Fixing it belongs in the Brain repo.

### 5.2 `robot.toml`: the single file of truth

**One file holds everything you fill in**: the layout of the robot and every setting and key of every service. It is
`robot.toml` (git-ignored). `robot.example.toml` is the complete template:
the layout at the top, then every **variable worth setting** of **every** service (about 60, each once), generated from each
service's `.env.example` and source code (`scripts/env_inventory.py`; a test fails when it no longer lists everything the
services read). What it leaves out is what nobody sets on a deployed machine: the address, port and URLs (computed), Brain's
route paths and provider name, service names, the trace-export tuning knobs and the development switches (`VSCODE_*`, test
flags). Those keep their defaults and are still accepted if you do set one.

```powershell
copy robot.example.toml robot.toml               # Linux/Pi: cp; then fill in the machines and only the variables you use
```

```toml
[machines.server]                     # 1. where things run (section 8)
address = "192.168.1.10"
services = ["brain", "ai-agent", "stt", "tts"]

[env]                                 # 2. one value for every service that uses the variable
LOG_LEVEL = "DEBUG"                   #    reaches all seven services
OPENAI_API_KEY = "<your key>"         #    reaches STT and ai-agent, and no other service

[env.stt]                             # 3. one service's own variables; they win over [env]
STT_LANGUAGE = "es"
[env.stepper]
MOCK_HARDWARE = 0                     #    numbers and true/false are fine: they become the text 0, true
```

* **Each service runs on exactly one machine,** so `[env.<service>]` needs no per-machine variant: the Pi's `MOCK_HARDWARE = 0`
  sits under `[env.stepper]` and only the Pi's stepper ever reads it. The same file is put on every machine, and a machine
  reads only the tables of the services it runs.
* **`[env]` reaches every service that uses that variable, and no other:** `LOG_LEVEL` reaches all seven, `OPENAI_API_KEY`
  reaches STT and ai-agent (a service with no such setting never sees the key), `ALLOWED_ORIGINS` reaches speaker and
  stepper. `[env.<service>]` wins over `[env]`. `SERVICE_NAME` and the computed variables are never taken from `[env]`.
* **In the template** the secrets are listed active and empty (fill them in); every other variable is commented out with its
  default (`#STT_LANGUAGE = 'en'`): uncomment and edit only what you want to change. Values shown are the ones a deployed
  machine really gets (they include what `services.toml` presets, such as `AI_AGENT_RELOAD=0` and `MOCK_HARDWARE=1`).
* **Not set here:** the bind address, the port and the base URLs of the other services. They are computed from the layout and
  `services.toml` so the services find each other; setting one here wins for that service but the others keep using the
  computed values, so `validate` warns.
* **Checked for you:** `validate` and `deploy` reject an `[env.<name>]` that is not a service or a value that is not a string,
  number or boolean, and, once the code is fetched, warn about a variable a service does not use (a probable typo, naming
  `robot.toml`). Variables the code reads that no `.env.example` lists (`AI_AGENT_MODELS_FILE`, `AI_AGENT_MODEL_PHASE_<n>`,
  `GITHUB_API_KEY`) are declared in `services.toml` (`extra_env`), and the ones nobody sets in `internal`.
* **Keys travel with the file.** A machine that gets `robot.toml` gets every key in it. To keep a key off a machine, leave it
  out of that machine's copy and use the optional overlay below.
* **Not covered:** `aws_microservice` (Go, not deployed by this tool) reads `APP_PORT`, `AWS_REGION`, `AWS_ACCESS_KEY_ID` and
  `AWS_SECRET_ACCESS_KEY` from its own environment.

**The machine-local overlay (optional).** `secrets/<machine>.env` (git-ignored; picked up by name for a machine of
`robot.toml`, or named by `[host] env_file` in a host file, whose older name is `secrets`) holds `<SERVICE>__<VARIABLE>=value`
lines (`STT__OPENAI_API_KEY=...`, the service in upper case with `-` written as `_`) and `ALL__<VARIABLE>=value` lines. It wins
over `robot.toml`, so it is the place for a key that only one machine should hold, and it is how `launch.py` stores the keys it
asks for. `validate` warns about a line in it that nothing reads (no `SERVICE__` prefix, an unknown service, a variable set
twice, a missing file). `scripts/env_inventory.py` and this section are the only places that describe the variables;
`plan` and `env` show, for any service, the final value and the layer that set it.

The keys the services need:

| Where in `robot.toml` | Service receives | Required when |
|---|---|---|
| `[env]` (or `[env.stt]`) `OPENAI_API_KEY` | `OPENAI_API_KEY` | `STT_ENGINE=openai` (the default) |
| `[env.ai-agent]` `GROQ_API_KEY` | `GROQ_API_KEY` | the active LLM profile uses Groq (default profile does) |
| `[env.ai-agent]` `GOOGLE_API_KEY` | `GOOGLE_API_KEY` | the active profile uses Google models (default profile does) |
| `[env.ai-agent]` `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `COHERE_API_KEY`, `GITHUB_PAT` | the same names | only if you switch models to those providers |
| `[env.ai-agent]` `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | the same names | never; optional cost tracking |

`validate` and `plan` report a missing required value with the exact place to add it. Nothing else in the
platform holds a secret. To see what a service will really get, and which layer set each value:
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
| `TRACE_EXPORT_HEADERS` (also `_TIMEOUT`, `_BATCH_SIZE`, `_FLUSH_INTERVAL`, `_QUEUE_SIZE`, `_ATTRIBUTES`) | see the logging guide | collector options. `TRACE_EXPORT_HEADERS` can carry credentials: put it in `robot.toml` (`TRACE_EXPORT_HEADERS` under `[env]`, or in the machine's own `secrets/<machine>.env`); `plan` and `env` mask it |
| `APP_ENV` (or `ENVIRONMENT`) | `development` | label written into every log line and span (`development`, `staging`, `production`). Only Brain has it in its `.env.example`, so the others say `development` unless you set it in the host file |

ai-agent uses `AI_AGENT_HOST` and `AI_AGENT_PORT` instead of `SERVICE_HOST` / `SERVICE_PORT`; the deploy tool
knows this and fills the right ones.

#### microphone (`.env.example`)

| Variable | Default | Fill in |
|---|---|---|
| `MICROPHONE_FALLBACK_SAMPLE_RATE` | `16000` | rarely |
| `MICROPHONE_TARGET_KEYWORDS` | empty | comma-separated device-name words to pick a specific input (empty = OS default). Use it when the default is wrong |
| `MICROPHONE_SHOW_METER` | `true` | `false` in a service window or log you do not want a level meter in |

Has no `.env` support in its own code: the deploy tool starts it through `oblivion/service_runner.py`, which loads the
generated `.env` first. Started by hand (route C) it reads the process environment only.

#### stt

| Variable | Default | Fill in |
|---|---|---|
| `STT_ENGINE` | `openai` | `openai` = OpenAI Whisper API; any other value (use `local`) = faster-whisper `small.en` on the CPU |
| `STT_LANGUAGE` | `en` | ISO-639-1 code forced on the transcription (`en`, `es`). Must match the language people speak; `small.en` is English only |
| `OPENAI_API_KEY` | empty | **secret**: required when `STT_ENGINE=openai` (`robot.toml`, section 5.2) |

With `local` the model downloads on the first run into the Hugging Face cache (`~/.cache/huggingface`), so the
first start needs internet and takes a while; later starts are offline.

#### tts

| Variable | Default | Fill in |
|---|---|---|
| `TTS_ENGINE` | `piper` | `piper` (neural British "droid butler" voice) or `pyttsx3` (the old Windows SAPI / espeak voice). If the Piper voice is missing or cannot load, the service logs an error and uses pyttsx3, so Brain's preflight never hangs on a voice download |
| `TTS_PIPER_VOICE` | `en_GB-alan-medium` | Piper voice name. The deploy tool downloads it (`scripts/fetch_voice.py`, about 60 MB, into `models/` of the service, git-ignored) after it writes the `.env`, so a voice set in `robot.toml` is the one fetched. The machine needs internet only for that first download; later deploys find the file and skip it |
| `TTS_PIPER_MODEL_DIR` | `models` | folder of the voice files, relative to the service folder |
| `TTS_PIPER_SPEED` | `1.0` | speaking pace multiplier (`1.1` = a little brisker) |
| `TTS_PITCH_SEMITONES` | `2.0` | pitch lift of the voice, the pace is kept (`0` = as recorded) |
| `TTS_DROID_EFFECT` | `0.5` | metallic effect strength: `0` off, `0.5` light, `1` obvious, `2` maximum |
| `TTS_SPEECH_RATE` | `140` | pyttsx3 only: words per minute |
| `TTS_VOICE_NAME` | `Zira` | pyttsx3 only: text the voice name must contain; otherwise the first English voice is used. On Windows Zira is English; the default system voice may be Spanish |

Voice files: `deploy` and `update` run the service's `prepare` step (`services.toml`) once its `.env` exists. For tts it downloads the voice to a temporary folder, loads it once to prove it is intact and only then moves it into place, so an interrupted download never leaves a broken voice. A failed download (no internet) is a warning: the service starts on the pyttsx3 voice and its log says `Piper unavailable; falling back to pyttsx3`; run `deploy` again once online. To fetch by hand: `windows\Scripts\python.exe scripts\fetch_voice.py` from `tts_microservice` (Linux: `bin/python`). **Docker** bakes the default voice into the image while building (no `.env` exists then): a different `TTS_PIPER_VOICE` needs the voice on the image or `TTS_ENGINE=pyttsx3`. A Raspberry Pi 4 or newer is the realistic minimum for Piper (a PC renders about 25x faster than real time; a Pi 3 would lag).

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
| `GROQ_URL` | empty | **required with the default profile.** Public OpenAI-compatible endpoint, `https://api.groq.com/openai/v1` (not a secret). Set by `services.toml` for every host file, so you normally do nothing |
| `GOOGLE_URL` | empty | **required with the default profile.** `https://generativelanguage.googleapis.com/v1beta/openai/` (also set by `services.toml`) |
| `MISTRAL_URL`, `COHERE_URL`, `GITHUB_URL`, `OLLAMA_URL` | empty | base URL of that provider. `OLLAMA_URL` alone is enough to make ai-agent available (local models) |
| `AI_AGENT_HOST` / `AI_AGENT_PORT` | `0.0.0.0` / `7998` | bind (the deploy tool sets both from the host file) |
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
| `MOCK_HARDWARE` | `0` in `.env.example`, **`1` set by the deploy catalogue** | `1` = no GPIO, moves are only simulated. **Only the exact value `1` counts** (the stepper compares the string): `true` does NOT select the mock, and on a Raspberry Pi it would drive the real motors. Set `0` **only on the Raspberry Pi wired to the motors** (host-file override) |
| `STEPPER_CONFIGS` | two steppers (`stepper_1`, `stepper_2`) | JSON map id → `{"step": <BCM pin>, "dir": <BCM pin>, "en": <BCM pin>}`. Match your wiring |
| `STEPS_PER_REVOLUTION` | `400` | full steps × microsteps of your motor/driver (1.8° motor = 200; with 1/8 microstepping = 1600). A wrong value moves the arm the wrong angle |
| `DEFAULT_SPEED_LIMIT` | `1000.0` | steps per second cap |
| `ALLOWED_ORIGINS` | `*` | CORS origins |

Real motors are driven only on a Raspberry Pi (`RPi.GPIO`); everywhere else the mock adapter runs. The first
time on real hardware, move a small angle with the arm unloaded and be ready to cut power.

#### brain

| Variable | Default | Fill in |
|---|---|---|
| `APP_ENV` | `development` | `development`, `staging` or `production` |
| `MICROPHONE_BASE_URL`, `STT_BASE_URL`, `TTS_BASE_URL`, `SPEAKER_BASE_URL` | `http://127.0.0.1:<port>` | **computed by the deploy tool** from `robot.toml` (or the host file's `[remote]`). Set by hand only in route C when a service is on another machine |
| `AI_AGENT_BASE_URL` | `http://127.0.0.1:7998` | same |
| `STEPPER_BASE_URL` | `http://127.0.0.1:8005` | same; optional, without a stepper the arms simply do not move |
| `*_ENDPOINT` (`MICROPHONE_START/STOP/STREAM`, `STT_SET_STREAM/GET_STREAM/BATCH`, `TTS_SET_STREAM/STREAM`, `SPEAKER_PLAY_STREAM`) | the routes the services expose | leave as they are |
| `AI_AGENT_FLOWS` | `conversation-flow,motion-flow` | the flows of ai-agent Brain asks, **one after the other, in this order** (each only when the one before has ended). Their routes are `/<flow>/session/...`. Known flows: `conversation-flow`, `motion-flow`; an unknown name stops Brain at startup |
| `PROGRESS_RECEIVED_MESSAGE`, `PROGRESS_THINKING_MESSAGE`, `PROGRESS_THINKING_INTERVAL_SECONDS` | `Message received.`, `Thinking.`, `2` | what Brain says while the flows work: the first at once when an utterance arrives, the second every N seconds until every flow has ended (the first one after N seconds, so a quick answer stays quiet). An empty text says nothing; an interval of 0 turns `Thinking.` off |
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
brain_microservice\windows\Scripts\python.exe -m pytest deployment\tests -q      # about 140 s (270 passed on 2026-10-01), real git repos and processes
```

## 8. Several machines

### 8.1 The layout is the top of `robot.toml`

Each fact is written **once**, and everything you fill in is in `robot.toml`. Its `[machines.*]` tables are the layout (which
machine runs which services, and where each machine is); its `[env]` tables are the settings and keys (section 5.2); the port of
every service is in `services.toml`, which you do not edit. Everything that used to be repeated per machine is derived:

| It is | Derived from | Used to be |
|---|---|---|
| a machine's services | the machine's `services` list | a `[services.*]` table per host file |
| the URL of a service on another machine | that machine's `address` + the service's port | a `[remote]` line per host file, address and port typed by hand |
| a service's port | `services.toml` (`ports = { name = N }` on a machine only to deviate; callers follow) | the same number in the host file, the `[remote]` URLs and the docs |
| a machine's bind address | `0.0.0.0` only if a service on another machine calls one of its services, else `127.0.0.1` | `bind = ...` set by hand in each host file |
| `SERVICE_HOST`, `SERVICE_PORT` and every `*_BASE_URL` of a service | the four rows above | (already computed, from the repeated values) |

```toml
# robot.toml, the layout part (git-ignored; robot.example.toml is the template)
[machines.pc]
address = "192.168.1.20"            # an IP or a host name: no http://, no port
services = ["microphone", "speaker"]
[machines.server]
address = "192.168.1.10"
services = ["brain", "ai-agent", "stt", "tts"]
[machines.pi]
address = "192.168.1.30"
services = ["stepper"]
# ports = { stepper = 18005 }       # only to deviate from services.toml
```

Put the same file on every machine. Then `--host <machine>` means "this machine of `robot.toml`": no host file is needed.

```powershell
py -3 oblivion.py topology                       # every machine, its address, services, what it exposes and calls; checks the layout
py -3 oblivion.py deploy --host server           # on the server; likewise --host pc and --host pi on theirs
py -3 oblivion.py deploy --host pc --robot D:\robot\robot.toml    # another file
```

`topology` ends with `OK` when every machine can find what it needs, and otherwise names the missing service
(`brain needs 'speaker': add it to a machine of the topology`) and lists services that no machine runs.

### 8.2 Per-machine settings and overrides

* **Settings and keys:** in `robot.toml` (section 5.2): the Pi's `MOCK_HARDWARE = 0` under `[env.stepper]`, the server's keys, a
  PC's `MICROPHONE_TARGET_KEYWORDS = "usb"` under `[env.microphone]`. A key that only one machine should hold goes in that
  machine's own `secrets/<machine>.env` (the optional overlay), which wins.
* **Overrides:** a host file `hosts/<machine>.toml` with `[host] machine = "<machine>"` on top of the topology, only to pin a
  branch, use Docker for a service, name a Python or change the workdir (`hosts/machine.example.toml`). It cannot add a
  service that the topology places elsewhere. `bind` and `[remote]` in it still work and win over the derived values, and a
  `[remote]` entry may be just an address (`192.168.1.20`, given the service's catalogue port), `address:port` or a URL.
* **Without a topology** (one machine, or old host files with `[services.*]`, `bind` and `[remote]`) everything works as
  before: `hosts/all-in-one.example.toml`, `hosts/test-branch.example.toml`.

A typical three-machine robot (follow 3.1 on each):

| Machine | Runs | What `robot.toml` needs for it |
|---|---|---|
| Windows PC with the sound card | microphone, speaker | nothing (device hints only if the wrong device is picked) |
| Server (Windows or Linux, Python 3.12+) | brain, ai-agent, stt, tts | `OPENAI_API_KEY` under `[env]`, `GROQ_API_KEY` and `GOOGLE_API_KEY` under `[env.ai-agent]` |
| Raspberry Pi wired to the motors | stepper | `MOCK_HARDWARE = 0` under `[env.stepper]` |

The PC and the Pi bind to the network by themselves (Brain calls them); open the firewall for their ports (8000, 8003, 8005).

### 8.3 Start order across machines

Brain checks microphone, STT, TTS and speaker when it starts and, if they are not
all available within `STARTUP_PREFLIGHT_TIMEOUT_SECONDS` (60), **it exits and nothing restarts it** (verified: it logs
`StartupPreflightError` and never opens its port). So the tool waits for you: before starting a service it waits up to
`--remote-wait` seconds (default 120, `0` = do not wait) for the required services that live on other machines,
and prints which ones it is waiting for. This also covers boot (`autostart` runs
`oblivion start`) and `update`. It does not wait for the optional stepper. If the other machines take longer to
boot, raise `--remote-wait`; if Brain is dead anyway, `oblivion restart --host <server> --service brain`.

Rules of thumb:

* Audio services belong on the machine that has the sound card; the stepper on the Raspberry Pi wired to the
  motors (`MOCK_HARDWARE = 0` under `[env.stepper]` only).
* There is no authentication: trusted LAN only. `validate` warns whenever a machine binds `0.0.0.0`.
* `validate` fails when a required service is placed on no machine (the stepper is the only optional one), when an
  address is malformed, and warns about a `[remote]` entry that points at this same machine.
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
  Structured JSON by default; set `LOG_FORMAT=console` for readable lines.
* State (what commit is installed): `<workdir>/state`. Generated `.env` files: in each service folder
  (`<workdir>/services/<folder>/.env`, regenerated on every deploy; edit `robot.toml`, not these).
* An update never overwrites local edits in a clone (refused unless `--force`) and never leaves a service dead.
* Linux/Pi: run `sudo loginctl enable-linger $USER` once so the user unit starts without a login.
* Rotating a key: edit `robot.toml` (copy it to the machine) or the machine's own `secrets/<machine>.env`, and `restart` the service.

## 10. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `ai-agent` never becomes ready,  `data.is_available` is false in `/available` | no LLM key/URL reached it. `oblivion.py env ai-agent --host mypc` (values masked) shows what it has; add the keys under `[env.ai-agent]` in `robot.toml` (the `GROQ_URL`/`GOOGLE_URL` endpoints are preset), then restart |
| `update` rolls ai-agent back to the previous commit | a service that answers but reports `is_available` false is counted as unhealthy after the grace period. Without an LLM key every new ai-agent release looks broken: fix the secrets first, or `update --no-rollback` to keep it and read its log |
| ai-agent answers, but replies are errors about a model/provider | the active profile needs a provider you did not configure: fill its key and URL or switch `profile` in `config/step_models.json` |
| Brain speaks an apology ("could not reach my decision-making service") | ai-agent is down or its URL is wrong (`AI_AGENT_BASE_URL`); check `curl .../available` from the Brain machine |
| Arms do not move, replies work | stepper missing/unreachable (moves are best effort), or `STEPPER_*_ARM_STEPPER_ID` is not an id in the stepper's `STEPPER_CONFIGS`. See Brain's log |
| Brain stays in preflight | one of microphone/stt/tts/speaker is not `available`; check each with section 6, or `STARTUP_PREFLIGHT_ENABLED=false` while debugging |
| STT fails at start with `openai` engine | `OPENAI_API_KEY` missing in `robot.toml` (under `[env]` or `[env.stt]`); or use `STT_ENGINE = "local"` |
| STT hears nothing / wrong text | wrong `MICROPHONE_TARGET_KEYWORDS` input, or `STT_LANGUAGE` does not match the spoken language |
| Speaker fails to open a device (`PaErrorCode -9999`, "Blocking API not supported") | the auto-selected device is a WDM-KS one. List devices and set `SPEAKER_DEVICE_INDEX` to an MME/WASAPI output: `windows\Scripts\python.exe -c "import sounddevice as sd; print(sd.query_devices())"` |
| TTS speaks with the old robotic voice | the Piper voice is missing, so the service fell back to pyttsx3 (its log says `Piper unavailable`). Run `scripts/fetch_voice.py` from the service folder, or `deploy` again with internet, then restart tts |
| TTS speaks the wrong language (pyttsx3 fallback) | Windows default voice is Spanish: set `TTS_VOICE_NAME=Zira` (already the default) or another installed English voice |
| Robot answers its own voice | speakers and microphone in the same room: use headphones |
| Stepper install fails on Python 3.14 with a Rust/`pydantic-core` error | old exact pins; the Windows requirements file now uses lower bounds. Update the stepper code |
| `deploy` / `validate` says `library 'shared-logging' is not available on this machine` | neither the workspace checkout nor `wheels/shared_logging-*.whl` exists: the clone of this repository is incomplete (`git status`, `git pull`), or run `scripts/bundle_shared_logging.py` on a machine that has the workspace and commit the wheel |
| `update` refuses ("local changes") | edits inside a clone under `<workdir>/services`; commit or discard them, or `--force` |
| A variable I exported in my shell (or set on the machine) has no effect on a service | by design: the service reads only its `.env`, and the tool removes same-named variables from its environment. Put the value in `robot.toml` (setting or key) and restart the service. `oblivion.py env <service> --host <machine>` shows what it will get |
| Health check times out on first run | dependency install or the local Whisper download is slow: `--health-timeout 600` (launch.py) |
| `validate`/`deploy` says `ai-agent needs Python 3.12+` | the interpreter that builds the venv is older (Raspberry Pi OS Bookworm has 3.11): use a newer Python via `[host] python`, or run ai-agent on another machine and list it under `[remote]` |
| Brain is not running after a boot or a deploy, its log ends with `StartupPreflightError` | microphone, STT, TTS or speaker was not available in time. Check them (`status --remote`), then `restart --service brain`. The tool waits for remote ones (`--remote-wait`, section 8); raise it if the other machines boot slowly || Port already in use | another copy is running (`launch.py status` / `stop`) or change `port =` in the host file |
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
