# OBLIVION deployment: user guide

A step-by-step guide to putting the OBLIVION robot's software on one or several machines, checking that it works,
and looking after it afterwards. It tells you **what to do and in which order**. For the reason behind a setting, every
variable and every troubleshooting detail, see the reference manual, [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Contents

1. [What you are deploying](#1-what-you-are-deploying)
2. [Choose your layout](#2-choose-your-layout)
3. [Before you start: checklist](#3-before-you-start-checklist)
4. [Prepare a machine](#4-prepare-a-machine)
5. [Get the deployment tool](#5-get-the-deployment-tool)
6. [Layout A: everything on one machine](#6-layout-a-everything-on-one-machine)
7. [Layout B: several machines](#7-layout-b-several-machines)
8. [Check that the robot works](#8-check-that-the-robot-works)
9. [Everyday operation](#9-everyday-operation)
10. [When something goes wrong](#10-when-something-goes-wrong)
11. [Cheat sheet](#11-cheat-sheet)

Conventions: `py -3` is how Windows starts Python; on Linux and Raspberry Pi use `python3`. Text in
`<angle brackets>` is for you to fill in. Nothing in this guide contains a real key: yours go only in a machine env file.

---

## 1. What you are deploying

Seven small programs ("services"). Each one is a web service with its own code repository and its own Python virtual
environment. **Brain is the only coordinator**: it calls the others, and they never call each other.

| Service | Port | Job | Needs on its machine |
|---|---|---|---|
| microphone | 8000 | captures what you say | a microphone |
| speaker | 8003 | plays the answer | a speaker or headphones |
| stt | 8001 | speech to text | an OpenAI key, or the local Whisper model |
| tts | 8002 | text to speech | the Piper voice (downloaded for you on the first deploy, needs internet once) |
| ai-agent | 7998 | decides the reply (conversation-flow) and the arm movements (motion-flow) | at least one LLM provider key; **Python 3.12+** |
| stepper | 8005 | turns the two arm motors | a Raspberry Pi wired to the motors (or simulation) |
| brain | 7999 | runs the voice pipeline | the six above reachable |

```text
 microphone ─┐                          ┌─► stt  ─┐
             ├──────►  BRAIN  ◄─────────┤         ├─ back to Brain ─► speaker
 (your voice)┘        ▲   │             └─► tts  ─┘
                      │   └─► ai-agent (decides) ─► move an arm ─► stepper
```

The **deployment tool** (`oblivion.py`, or the one-command `launch.py`) does the work for you on each machine: it
downloads the code from GitHub, builds the virtual environments, writes every service's settings, starts things in the
right order and checks that they are healthy. You never install a service by hand.

> **There is no login or password between services.** Keep every machine on a trusted home or lab network. Never
> expose these ports to the internet.

## 2. Choose your layout

| Layout | Use it when | Effort | Go to |
|---|---|---|---|
| **A. One machine** | trying it out, developing, or one PC does everything | one command | [section 6](#6-layout-a-everything-on-one-machine) |
| **B. Several machines** | the sound card, the motors and the "thinking" live on different computers | one file, `robot.toml`, for the whole robot | [section 7](#7-layout-b-several-machines) |

A typical layout B is three machines:

| Machine | Runs | Why there |
|---|---|---|
| Windows PC | microphone, speaker | it has the sound card |
| Server (Windows or Linux, **Python 3.12+**) | brain, ai-agent, stt, tts | the heavy, network-facing parts |
| Raspberry Pi | stepper | it is wired to the motors |

ai-agent cannot run on a stock Raspberry Pi OS Bookworm (its Python is 3.11): put it on the server.

## 3. Before you start: checklist

Tick these off first; most failures come from a missing item.

- [ ] Every machine is on the same network and can reach the others (`ping <address>`). Note each address.
- [ ] Every machine has internet access during the deploy (GitHub and the Python package index).
- [ ] **Python 3.11 or newer** on every machine (**3.12 or newer** on the one that runs ai-agent) and **git**.
- [ ] An **OpenAI API key**, for speech to text. (Or plan to use the local Whisper model: no key, but a large download.)
- [ ] At least one **LLM key** for ai-agent. The default setup uses **Groq** and **Google**, so it needs both keys.
- [ ] Headphones for the first test (otherwise the robot hears itself).
- [ ] A few minutes: the first deploy of a machine downloads a lot (speech-to-text and ai-agent are the big ones).

Do not paste keys into chat, tickets or files that get committed. You will type them once, into a file that git ignores.

## 4. Prepare a machine

Do this on **every** machine, once. It only installs Python and git; the tool installs everything else.

### Windows 11

1. Install **Python** from python.org (3.12 or newer; tick **Add python.exe to PATH** and keep the **py launcher**).
2. Install **Git for Windows**.
3. Open PowerShell and check:

   ```powershell
   py -3 --version
   git --version
   ```

4. Machine with a microphone: Settings, Privacy & security, Microphone, allow desktop apps.
5. Always run the tool as `py -3 oblivion.py ...`. A new Windows blocks `.ps1` scripts, so do not use `oblivion.ps1`.

### Linux and Raspberry Pi OS

```bash
sudo apt update && sudo apt install -y git python3 python3-venv
python3 --version           # 3.11 or newer
sudo usermod -aG audio $USER    # only on machines with a microphone or speaker; then log out and in
```

## 5. Get the deployment tool

On every machine:

```bash
git clone -b feature_ai_claude_2 https://github.com/DanielCalvo-Calvicia/FULL_OBLIVION.git oblivion-deploy
cd oblivion-deploy
```

The repositories are public, so no GitHub login is needed. Everything the tool needs is in this folder, including the
`shared-logging` library (`wheels/`). Do not deploy the `main` branch yet: it is missing pieces the services need.

## 6. Layout A: everything on one machine

> **Not on a stock Raspberry Pi OS Bookworm.** `launch.py` installs all seven services, and ai-agent needs Python
> 3.12+ while Bookworm ships 3.11. On such a Pi use layout B and run ai-agent elsewhere.

### Step 1: export your keys (once, in the same terminal)

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY = "<your OpenAI key>"
$env:GROQ_API_KEY   = "<your Groq key>"
$env:GOOGLE_API_KEY = "<your Google key>"
```

Linux / Pi:

```bash
export OPENAI_API_KEY="<your OpenAI key>"
export GROQ_API_KEY="<your Groq key>"
export GOOGLE_API_KEY="<your Google key>"
```

The launcher copies them into a private, git-ignored file and never prints them. If you skip this, it asks for the
OpenAI key (hidden typing), and ai-agent will report "not available" until an LLM key is added later.

### Step 2: launch

```powershell
py -3 launch.py                       # Windows
```

```bash
python3 launch.py --system-deps       # Linux / Pi: --system-deps installs PortAudio/espeak with sudo, first time only
```

Useful options: `--stt local` (local Whisper instead of OpenAI: no key, big download), `--branch <name>` (another
code branch), `--dry-run` (print every command, change nothing).

> **Have a `robot.toml`?** Then `launch.py` uses it and ignores the steps above: the layout, settings and keys are the file's
> (one machine is picked automatically; `--machine <name>` picks one of several). It creates no other file, so fill in the keys
> in `robot.toml` and just run `py -3 launch.py`. An old `hosts/local.toml` from an earlier run is then not used.

What happens: it creates `hosts/local.toml` and `secrets/local.env` (without a `robot.toml`), downloads the code of all seven services,
builds their environments, starts them in the right order and waits until each answers. A window opens per
service on Windows. It ends with a status table; every service should be `running`.

### Step 3: talk to it

Put on **headphones**, say a sentence and pause for about two seconds. Brain opens the voice pipeline by itself, so
you should hear an answer. Continue with [section 8](#8-check-that-the-robot-works).

### Later runs

```bash
py -3 launch.py              # gets the newest code, restarts, and rolls back a service whose new version fails
py -3 launch.py --no-update  # just start what is already installed
py -3 launch.py status       # what is running
py -3 launch.py logs brain   # last lines of a service's log (default: brain)
py -3 launch.py stop         # stop everything
```

## 7. Layout B: several machines

Everything you fill in lives in **one file, `robot.toml`**: which machine runs which services and where each machine is,
plus every setting and key of every service. You fill it in once, put the **same file** on every machine, and run the same
few commands on each. There are no per-machine host files or env files, no addresses to repeat, no ports to type and no
`bind` flags to set: the tool works out the URL of every service on the other machines, the port of every service (from
`services.toml`, which you never edit) and whether a machine must listen on the network (only if another machine calls one
of its services).

The example below is the three-machine layout of section 2. Adapt the names and addresses to yours.

### Step 1: fill in the file (once)

```bash
cp robot.example.toml robot.toml
```

`robot.example.toml` is complete: the layout at the top, then every variable of every service. The secrets are already there,
empty; everything else is commented out with its default. Edit it in three places.

**a) The machines** (the top of the file):

```toml
[machines.pc]                      # the Windows PC with the sound card
address = "192.168.1.20"           # an IP or a host name: no http://, no port
services = ["microphone", "speaker"]

[machines.server]                  # brain and everything that thinks (Python 3.12+ for ai-agent)
address = "192.168.1.10"
services = ["brain", "ai-agent", "stt", "tts"]

[machines.pi]                      # the Raspberry Pi wired to the motors
address = "192.168.1.30"
services = ["stepper"]
```

**b) The keys**, in the tables further down (fill in only what you use):

```toml
[env]                              # one value for every service that uses the variable
OPENAI_API_KEY = "<your OpenAI key>"     # used by STT (and by ai-agent, if you switch it to OpenAI models)
LOG_LEVEL = "INFO"                       # uncommented from #LOG_LEVEL = 'INFO': every service

[env.ai-agent]                     # one service's own variables; they win over [env]
GROQ_API_KEY = "<your Groq key>"
GOOGLE_API_KEY = "<your Google key>"
```

**c) Any other setting**: uncomment its line and change it. For example, under `[env.stt]`, `#STT_LANGUAGE = 'en'` becomes
`STT_LANGUAGE = "es"`. Values can be text (`"usb"`), numbers (`15`) or `true`/`false`. Leave out the address, port and URLs of
the services: they come from the layout.

For the Pi's real motors set `MOCK_HARDWARE = 0` under `[env.stepper]` (only the value `1` means "simulate"). If your wiring
or motor differs from the defaults, set `STEPPER_CONFIGS` (the BCM pins of each driver) and `STEPS_PER_REVOLUTION` (full steps
times microsteps) there too: a wrong value moves the arm the wrong angle. If the wrong microphone or speaker is picked, set
`MICROPHONE_TARGET_KEYWORDS = "usb"` under `[env.microphone]` and `SPEAKER_DEVICE_KEYWORDS = "speakers,realtek"` under
`[env.speaker]`.

Put the same `robot.toml` on every machine (copy it into each machine's `oblivion-deploy` folder). It is git-ignored: the
addresses and keys are yours. Then look at what it means:

```bash
python3 oblivion.py topology
```

It lists every machine with its address, what it runs, which of its services other machines call, what it calls on the
others, and the bind address it derived. It ends with `OK` when every machine can find what it needs, or names what is
missing (for example `brain needs 'speaker': add it to a machine of the topology`). Change a port only if you must, by adding
`ports = { stepper = 18005 }` to that machine's table; the callers follow automatically.

> **Keys travel with the file.** Every machine that gets `robot.toml` gets every key in it. To keep a key off a machine (say the
> Pi should not hold the OpenAI key), leave that key out of the copy that machine gets and put it in that machine's own
> `secrets/<machine>.env` instead, one `SERVICE__NAME=value` line each (`STT__OPENAI_API_KEY=...`, or `ALL__NAME=...`).
> That optional file wins over `robot.toml`, and `chmod 600` keeps it private.

### Step 2: the Windows PC (microphone and speaker)

Allow the ports through Windows Firewall (elevated PowerShell), or accept the prompt Windows shows when the services first
start:

```powershell
New-NetFirewallRule -DisplayName OBLIVION -Direction Inbound -Protocol TCP -LocalPort 8000,8003 -Action Allow -Profile Private
```

```powershell
py -3 oblivion.py doctor   --host pc
py -3 oblivion.py validate --host pc
py -3 oblivion.py deploy   --host pc
py -3 oblivion.py status   --host pc
```

`--host pc` means "the machine `pc` of `robot.toml`".

### Step 3: the Raspberry Pi (stepper)

> **Motors.** The first time, keep the arm unloaded, command a small angle, and be ready to cut the motor power. Leave
> `MOCK_HARDWARE` out of `robot.toml` (or set it to `1`) to test everything with no motor moving.

```bash
python3 oblivion.py doctor   --host pi
python3 oblivion.py validate --host pi
python3 oblivion.py deploy   --host pi --system-deps
python3 oblivion.py status   --host pi
```

Open port 8005 on the Pi if it runs a firewall.

### Step 4: the server (brain, ai-agent, stt, tts)

If the server's default `python3` is older than 3.12, name a newer one in a small host file that only overrides that:
`cp hosts/machine.example.toml hosts/server.toml`, then set `python = "python3.12"` in it.

```bash
python3 oblivion.py doctor   --host server
python3 oblivion.py validate --host server
python3 oblivion.py plan     --host server        # optional: shows every setting and where it came from
python3 oblivion.py deploy   --host server --system-deps
python3 oblivion.py status   --host server --remote
```

`--system-deps` is Linux only (on a Windows server, leave it out). `status --remote` also checks the PC and the Pi from
here: every line should say `running`.

### Step 5: order matters

Deploy the machines that **Brain depends on first** (the PC and the Pi), then the server. Brain checks that
microphone, STT, TTS and speaker are available when it starts and, if they are not, **it exits and nothing restarts it**.
To protect you, the tool waits up to 120 seconds (`--remote-wait`) for the other machines' services before starting
Brain, and tells you what it is waiting for. If your machines boot slowly, allow longer:

```bash
python3 oblivion.py start --host server --remote-wait 300
```

### Read the messages `validate` gives you

`validate` changes nothing and needs no network. Fix every `error:` before deploying.

| It says | What to do |
|---|---|
| `stt: OPENAI_API_KEY is required ... put OPENAI_API_KEY = "..." under [env.stt] (or [env] ...) in robot.toml` | add that key to `robot.toml` |
| `warning: ai-agent: none of GROQ_API_KEY, ... is set` | add an LLM key under `[env.ai-agent]`, or accept that ai-agent will report "not available" |
| `brain needs 'speaker': add it to a machine of the topology` | `robot.toml` places no machine for that service: add it to a machine's `services` |
| `machine 'x' needs address = ... (no http://, no port ...)` | write only the IP or host name; ports come from `services.toml` |
| `'stt' is placed on both 'a' and 'b'` | a service runs on one machine: remove it from one |
| `[env.brian] is not a service of the catalogue` | a table name that is not one of the seven services: fix the spelling |
| `X is set in robot.toml but the service does not document it (typo?)` | a variable name the service does not use (checked once its code is fetched) |
| `X is computed from robot.toml ...` | you set an address, port or URL by hand; remove it: the layout works it out |
| `ai-agent needs Python 3.12+` | use a newer Python (`python = ...` in `hosts/<machine>.toml`) or move ai-agent to another machine |
| `... is not a stepper of this machine's STEPPER_CONFIGS` | Brain's arm IDs and the stepper's IDs must match |
| `warning: bind = 0.0.0.0 ...` | expected on a machine whose services other machines call; never set it by hand |

## 8. Check that the robot works

### 8.1 Are the services healthy?

```bash
py -3 oblivion.py status --host <machine> [--remote]     # or: launch.py status
```

Every line `running` and `healthy and available`. Two exceptions are normal: ai-agent says `available: no language
model provider is configured` until an LLM key is set, and the stepper answers "healthy" only.

You can also ask a service directly, from any machine:

```bash
curl http://<address>:8001/available          # stt (use the service's own port)
curl http://<address>:7999/health             # brain
```

### 8.2 The voice test (headphones on)

1. Say "Hello, how are you?" and pause for about two seconds. You should hear "Message received." at once, then a spoken
   answer written by ai-agent, not an echo of your words. If the answer takes a while you hear "Thinking." every 2 seconds.
2. Say "Move your left arm ninety degrees forward." You should hear a confirmation and see a rotate request in the
   stepper's log (or the arm move, if the motors are live).
3. Say something impossible ("Fly to the moon"): ai-agent should refuse politely.
4. Stop ai-agent and speak again: Brain says an apology and keeps running. Start ai-agent again and speak: it works
   without restarting Brain.

The log of Brain shows which step of the pipeline is active (`oblivion.py logs --host <machine> --service brain`).

## 9. Everyday operation

All commands take `--host <name>` (a machine of `robot.toml`, or the name of a host file `hosts/<name>.toml`) and optionally `--service <name>`
(short `-s`, repeatable) to act on one service.

### Look

```bash
oblivion.py status  --host <machine> [--remote]         # running state, code version, health
oblivion.py logs    --host <machine> -s brain [-n 100]  # last lines of a log
oblivion.py env     --host <machine> stt                # the final settings of a service, secrets masked, with their origin
oblivion.py plan    --host <machine>                    # everything the machine will run
```

(Write `py -3 oblivion.py` or `python3 oblivion.py`.) Logs are files in `<workdir>/logs/<service>.log` (the workdir is
`~/oblivion` unless a host file says otherwise); on Windows each service also has its own window.

### Start, stop, restart

```bash
oblivion.py stop    --host <machine>                 # everything on this machine, in the safe order
oblivion.py start   --host <machine>
oblivion.py restart --host <machine> -s brain        # one service
```

### Update to newer code

```bash
oblivion.py update --host <machine>                              # newest code of the configured branches
oblivion.py update --host <machine> --branch brain=<branch>      # one service on another branch (tags and commits work too)
oblivion.py compat                                               # do the services fit together on the code each will be deployed from?
oblivion.py update --host <machine>                              # back to the configured branches
```

`update` stops a service, fetches the code, reinstalls only if the dependencies changed, restarts it and waits for it
to be healthy. **If the new version is not healthy it puts the previous version back.** It refuses to overwrite files
you edited inside a service's folder (`--force` overrides that; `--no-rollback` keeps a failed version so you can
read its log). Update the machines in the same order as a deploy: PC and Pi first, then the server.

### Change a setting or a key

1. Edit `robot.toml`, the single file of truth: any variable of any service, keys included, or which machine runs what. Never
   edit the `.env` files inside the service folders: they are regenerated on every start. A service reads **only** that
   generated `.env`: a variable you export in your terminal or set on the machine does not reach it, so put every setting and
   key in `robot.toml` (or in a machine's own `secrets/<machine>.env`, which wins). Copy the changed file to every machine.
2. `oblivion.py validate --host <machine>`
3. `oblivion.py restart --host <machine> -s <service>`

Example: switch speech to text to the local model with `STT_ENGINE = "local"` under `[env.stt]`
(the model downloads on first start).

### Start automatically at boot or login

```bash
oblivion.py autostart install --host <machine>      # remove: autostart remove;  see what it would create: autostart print
```

- **Linux / Pi:** a systemd user service. Run once `sudo loginctl enable-linger $USER` so it starts without a login.
- **Windows:** a scheduled task that runs **at logon** (the sound services need your session). The machine must log in
  automatically for the robot to start by itself.

When the machine boots, the tool waits for the other machines' services before starting Brain (section 7, step 4).

> Autostart, Docker and real Raspberry Pi hardware have not yet been exercised end to end by this tool. Try them
> with the robot on the bench, and tell someone what you find.

### Take a machine out of service

```bash
oblivion.py autostart remove --host <machine>
oblivion.py stop --host <machine>
```

To wipe it completely, delete its workdir (default `~/oblivion`): the code, environments, logs and state. Your host and
machine env files stay in `oblivion-deploy/`.

## 10. When something goes wrong

Start with `status`, then read the log of the service that is not healthy. Most problems are one of these:

| Symptom | Likely cause and fix |
|---|---|
| `ai-agent` never becomes available | no LLM key reached it. `oblivion.py env ai-agent --host <machine>` shows what it has (keys masked). Add the `AI_AGENT__...` lines to the machine env file, then restart it |
| Replies are errors about a model or provider | the active model profile needs a provider you did not configure: add its key, or change `profile` in the service's `config/step_models.json` |
| Brain is not running after a boot or a deploy; its log ends with `StartupPreflightError` | microphone, STT, TTS or speaker was not available in time. Check them with `status --remote`, then `restart -s brain`; raise `--remote-wait` if the other machines boot slowly |
| Brain speaks "could not reach my decision-making service" | ai-agent is down, or its URL is wrong: check `curl http://<address>:7998/available` from Brain's machine |
| The arms do not move, replies work | the stepper is off or unreachable (moves are best-effort), or Brain's arm IDs are not in the stepper's `STEPPER_CONFIGS` |
| STT fails at start | `STT__OPENAI_API_KEY` missing, or set `STT_ENGINE = "local"` |
| STT hears nothing or the wrong text | wrong microphone chosen (`MICROPHONE_TARGET_KEYWORDS`), or `STT_LANGUAGE` differs from the language you speak |
| Speaker cannot open a device | list the outputs with the speaker's own Python, `<workdir>\venvs\speaker\Scripts\python.exe` (Linux: `<workdir>/venvs/speaker/bin/python`), running `-c "import sounddevice as sd; print(sd.query_devices())"`, then set `SPEAKER_DEVICE_INDEX` in the host file |
| The robot answers itself | speakers and microphone in the same room: use headphones |
| `update` says `local modifications` | you edited files inside `<workdir>/services/<service>`: undo them, or use `--force` |
| Health check times out on the first run | a slow install or the Whisper download: add `--health-timeout 600` |
| `Port already in use` | another copy is running (`status`, `stop`), or change that service's port in `robot.toml` (`ports = { name = 1234 }` on its machine) |
| `validate` says a required library is missing | the clone of this repository is incomplete: `git status`, `git pull` |
| `git clone` or `pip` fails | no internet, or a proxy: fix the network and run `deploy` again (it is safe to repeat) |

Safe to repeat: `deploy` can be run again on the same machine to repair it. For a service that will not start, the
reason is almost always in `<workdir>/logs/<service>.log`.

## 11. Cheat sheet

One machine:

```bash
py -3 launch.py                  # first run and every update
py -3 launch.py status | logs [service] | stop
```

Several machines (replace `py -3` with `python3` on Linux and Pi):

```bash
py -3 oblivion.py topology                                  # the whole robot: machines, services, what calls what
py -3 oblivion.py doctor    --host <machine>                # is this machine ready?
py -3 oblivion.py validate  --host <machine>                # is the configuration complete?
py -3 oblivion.py deploy    --host <machine> [--system-deps] # install and start
py -3 oblivion.py status    --host <machine> --remote       # is it all healthy, including the other machines?
py -3 oblivion.py update    --host <machine>                # newer code, with automatic rollback
py -3 oblivion.py restart   --host <machine> -s <service>
py -3 oblivion.py logs      --host <machine> -s <service>
py -3 oblivion.py autostart install --host <machine>
```

Add `--dry-run` to any command to see exactly what it would run without changing anything.

Ports: brain 7999, microphone 8000, stt 8001, tts 8002, speaker 8003, stepper 8005, ai-agent 7998.
Files: the single file of truth `robot.toml` (layout, settings and keys), optional `secrets/<name>.env` and `hosts/<name>.toml` overrides (all ignored by git), logs
`<workdir>/logs/`, state `<workdir>/state/`.

Where to read more: [`DEPLOYMENT.md`](DEPLOYMENT.md) (every variable, per-service settings, known limits) and
[`../README.md`](../README.md) (how the tool works: topology, branches, rollback, Docker, host file format).
