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
`<angle brackets>` is for you to fill in. Nothing in this guide contains a real key: yours go only in `config/local/`,
a folder git ignores.

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
| ai-agent | 7998 | identifies each message and decides the reply or the arm movements (flows: conversation, special, movement) | at least one LLM provider key; **Python 3.12+** |
| stepper | 8005 | turns the two arm motors | a Raspberry Pi wired to the motors (or simulation) |
| camera | 8006 | serves the camera as video streams and snapshots (nothing uses it yet) | a camera on the Pi and an API key in `config/local/camera.toml` |
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

A **layout** says which machine runs which services. Five are ready-made in `config/layouts/`; you pick one, and the tool
works out every address, port and URL from it.

| Layout | Machines | Use it when | Needs |
|---|---|---|---|
| `all-in-one` | one machine runs everything | trying it out, developing, or one PC does everything | [section 6](#6-layout-a-everything-on-one-machine) |
| `speaker-on-pc` | **pc**: speaker. **pi**: everything else (camera included) | the Pi is the robot's body and your PC only plays the voice | [section 7](#7-layout-b-several-machines) |
| `audio-on-pc` | **pc**: microphone, speaker. **pi**: the rest (camera included) | the PC has the sound card | [section 7](#7-layout-b-several-machines) |
| `stepper-on-pi` | **pc**: everything but the stepper and camera. **pi**: stepper, camera | the Pi only drives the motors | [section 7](#7-layout-b-several-machines) |
| `pc-server-pi` | **pc**: microphone, speaker. **server**: brain, ai-agent, stt, tts. **pi**: stepper, camera | three machines | [section 7](#7-layout-b-several-machines) |

List them any time, and see which one your robot uses:

```bash
python3 oblivion.py layouts
```

Not one of these? Copy the closest file in `config/layouts/` to a new name and edit it: a layout is just a list of machines
and their services.

ai-agent needs Python 3.12 or newer. Stock Raspberry Pi OS Bookworm ships 3.11, so on a layout that puts ai-agent on a Pi, install a
newer Python there and name it in `config/machines/pi.toml` ([section 7, step 3](#7-layout-b-several-machines)).

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

Everything you will edit is in one folder, **`config/`**:

| In `config/` | What it is | Yours or the project's |
|---|---|---|
| `robot.toml` | which layout this robot uses, and where each machine is (a few lines) | yours, git-ignored |
| `layouts/` | where each service runs: the ready-made layouts | the project's |
| `services/` | one file per service with its settings at their defaults, and `all.toml` for what services share | the project's |
| `local/` | your keys and your own settings: one file per service, same shape as `services/`, and it wins | yours, git-ignored |
| `machines/` | what is particular to one machine: its Python, its folders (optional) | yours, git-ignored |
| `catalogue.toml` | what each service is: its repository, port, requirements (you almost never edit it) | the project's |

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

The launcher copies them into private, git-ignored files in `config/local/` (`stt.toml` and `ai-agent.toml`) and never prints
them. If you skip this, it asks for the OpenAI key (hidden typing), and ai-agent will report "not available" until an LLM
key is added later.

### Step 2: launch

```powershell
py -3 launch.py                       # Windows
```

```bash
python3 launch.py --system-deps       # Linux / Pi: --system-deps installs PortAudio/espeak with sudo, first time only
```

Useful options: `--stt local` (local Whisper instead of OpenAI: no key, big download), `--branch <name>` (another
code branch, for this run), `--dry-run` (print every command, change nothing).

What happens on the first run: it creates `config/robot.toml` (layout `all-in-one`) and your keys in `config/local/`,
downloads the code of all seven services, builds their environments, starts them in the right order and waits until each
answers. It never overwrites a file you already have. A window opens per service on Windows. It ends with a status table;
every service should be `running`.

> **Already have a `config/robot.toml`?** Then `launch.py` uses it and creates nothing: the layout, settings and keys are
> the files'. (One machine is picked automatically; `--machine <name>` picks one of several.) Put your keys in
> `config/local/` yourself, as in [section 7](#7-layout-b-several-machines), and run `py -3 launch.py`.

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

Three small steps, each in its own place, and the same files on every machine:

1. **Choose the layout and say where each machine is** (`config/robot.toml`).
2. **Put your keys and settings in `config/local/`**.
3. **Machine details, if a machine needs any** (`config/machines/<machine>.toml`).

There are no addresses to repeat, no ports to type and no `bind` flags to set: the tool works out the URL of every service on
the other machines, the port of every service (from `config/catalogue.toml`, which you never edit) and whether a machine must
listen on the network (only if another machine calls one of its services).

The examples below use the `speaker-on-pc` layout: the speaker on your PC (`pc`), everything else on the Pi (`pi`). Use
`audio-on-pc`, `stepper-on-pi` or `pc-server-pi` the same way; the machine names are the ones in the layout file.

### Step 1: choose the layout and the addresses (once)

Let the tool write the file:

```bash
python3 oblivion.py init --layout speaker-on-pc --address pc=192.168.1.20 --address pi=192.168.1.30
```

Or copy `config/robot.example.toml` to `config/robot.toml` and edit its few lines:

```toml
layout = "speaker-on-pc"

[addresses]                  # an IP or a host name: no http://, no port
pc = "192.168.1.20"
pi = "192.168.1.30"
```

Then look at what it means:

```bash
python3 oblivion.py topology
```

It lists every machine with its address, what it runs, which of its services other machines call, what it calls on the
others, and the bind address it derived. It ends with `OK` when every machine can find what it needs, or names what is
missing (for example `brain needs 'speaker': put it on a machine of the layout`). A port that must deviate from the catalogue
goes in the layout file (`ports = { stepper = 18005 }` on that machine); the callers follow automatically.

### Step 2: your keys and settings (once)

Every service has a settings file in `config/services/` that lists all its settings with their defaults, commented out. You
change nothing there. Your own values go in **`config/local/`**, in a file with the same name:

```bash
cp config/local/all.example.toml config/local/all.toml            # the OpenAI key (stt and ai-agent share it)
cp config/local/ai-agent.example.toml config/local/ai-agent.toml  # the LLM keys
```

Fill in only the keys you use:

```toml
# config/local/all.toml
[env]
OPENAI_API_KEY = "<your OpenAI key>"

# config/local/ai-agent.toml
[env]
GROQ_API_KEY = "<your Groq key>"
GOOGLE_API_KEY = "<your Google key>"
```

Any other setting works the same way: find it in the service's file in `config/services/`, copy the line to the same-named file in
`config/local/` without the `#`, and change it. For example `STT_LANGUAGE = "es"` in `config/local/stt.toml`. Values can be text
(`"usb"`), numbers (`15`) or `true`/`false`. Do not set addresses, ports or URLs of the services: they come from the layout.

The Pi's motors: the default is the **simulated** stepper. For the real motors create `config/local/stepper.toml`:

```toml
[env]
MOCK_HARDWARE = 0                # only the value 1 means "simulate"
STEPS_PER_REVOLUTION = 3200      # full steps x microsteps of YOUR driver (400 x 8 here); a wrong value moves the arm the wrong angle
```

If your wiring differs from the defaults, set `STEPPER_CONFIGS` (the BCM pins of each driver) there too. If the wrong
microphone or speaker is picked, set `MICROPHONE_TARGET_KEYWORDS = "usb"` in `config/local/microphone.toml` and
`SPEAKER_DEVICE_KEYWORDS = "speakers,realtek"` in `config/local/speaker.toml`.

Put `config/robot.toml` and the `config/local/` folder on **every machine** (copy them into each machine's `oblivion-deploy/config/`).
They are git-ignored: the addresses and keys are yours.

> **Keys travel with the folder.** Every machine that gets `config/local/` gets every key in it. To keep a key off a machine (say
> the Pi should not hold the Groq key), leave that file out of the copy that machine gets: a service only reads the files of
> its own name and `all.toml`.

### Step 3: machine details (only if a machine needs them)

If a machine's default `python3` is older than a service needs (ai-agent: 3.12), name a newer one for that machine only:

```bash
cp config/machines/pi.example.toml config/machines/pi.toml     # then uncomment and edit the lines you need
```

```toml
# config/machines/pi.toml
[host]
python = "/home/pi/.local/bin/python3.12"
```

The example file shows one way to get a newer Python on the Pi without touching the system's.

### Step 4: the PC (the speaker)

Allow the port through Windows Firewall (elevated PowerShell), or accept the prompt Windows shows when the service first
starts:

```powershell
New-NetFirewallRule -DisplayName OBLIVION -Direction Inbound -Protocol TCP -LocalPort 8003 -Action Allow -Profile Private
```

```powershell
py -3 oblivion.py doctor   --host pc
py -3 oblivion.py validate --host pc
py -3 oblivion.py deploy   --host pc
py -3 oblivion.py status   --host pc
```

`--host pc` means "the machine `pc` of the layout".

### Step 5: the Raspberry Pi (everything else)

> **Motors.** The first time, keep the arm unloaded, command a small angle, and be ready to cut the motor power. Leave
> `MOCK_HARDWARE` out of `config/local/stepper.toml` (or set it to `1`) to test everything with no motor moving.

```bash
python3 oblivion.py doctor   --host pi
python3 oblivion.py validate --host pi
python3 oblivion.py plan     --host pi            # optional: shows every setting and the file it came from
python3 oblivion.py deploy   --host pi --system-deps
python3 oblivion.py status   --host pi --remote
```

`--system-deps` is Linux only (on a Windows machine, leave it out). `status --remote` also checks the other machines from
here: every line should say `running`. Open port 8005 on the Pi if it runs a firewall and a service there is called from
another machine.

### Step 6: order matters

Deploy the machines that **Brain depends on first**, then the machine that runs Brain (here, the PC first, then the Pi).
Brain checks that microphone, STT, TTS and speaker are available when it starts and, if they are not, **it exits and nothing
restarts it**. To protect you, the tool waits up to 120 seconds (`--remote-wait`) for the other machines' services before
starting Brain, and tells you what it is waiting for. If your machines boot slowly, allow longer:

```bash
python3 oblivion.py start --host pi --remote-wait 300
```

### Read the messages `validate` gives you

`validate` changes nothing and needs no network. Fix every `error:` before deploying.

| It says | What to do |
|---|---|
| `stt: OPENAI_API_KEY is required ... set OPENAI_API_KEY = "..." in config/local/stt.toml` | add that key to the file it names (or to `config/local/all.toml`) |
| `warning: ai-agent: none of GROQ_API_KEY, ... is set` | add an LLM key in `config/local/ai-agent.toml`, or accept that ai-agent will report "not available" |
| `brain needs 'speaker': put it on a machine of the layout` | the layout places no machine for that service: pick another layout or add it to a machine in the layout file |
| `machine 'x' of layout 'y' has no address` | add `x = "<ip or host name>"` under `[addresses]` in `config/robot.toml` |
| `the address of machine 'x' must be an IP or a host name` | write only the IP or host name; ports come from `config/catalogue.toml` |
| `'stt' is placed on both 'a' and 'b'` | a service runs on one machine: remove it from one in the layout file |
| `'nope' is not a service of the catalogue` | a settings file with a name that is not one of the seven services (or `all`): fix the file name |
| `X is set in config/local/stt.toml but the service does not document it (typo?)` | a variable name the service does not use (checked once its code is fetched) |
| `X is computed from the layout ...` | you set an address, port or URL by hand; remove it: the layout works it out |
| `ai-agent needs Python 3.12+` | use a newer Python (`python = ...` in `config/machines/<machine>.toml`) or run ai-agent on another machine |
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

All commands take `--host <name>` (a machine of the layout in `config/robot.toml`) and optionally `--service <name>`
(short `-s`, repeatable) to act on one service. `--config <folder>` points the tool at another `config/` folder.

### Look

```bash
oblivion.py layouts                                     # the ready-made layouts, and the one in use
oblivion.py topology                                    # the whole robot: machines, services, what calls what
oblivion.py status  --host <machine> [--remote]         # running state, code version, health
oblivion.py logs    --host <machine> -s brain [-n 100]  # last lines of a log
oblivion.py env     --host <machine> stt                # the final settings of a service, secrets masked, with the file each came from
oblivion.py plan    --host <machine>                    # everything the machine will run
```

(Write `py -3 oblivion.py` or `python3 oblivion.py`.) Logs are files in `<workdir>/logs/<service>.log` (the workdir is
`~/oblivion` unless `config/machines/<machine>.toml` says otherwise); on Windows each service also has its own window.

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
read its log). Update the machines in the same order as a deploy.

To keep a service on a branch, tag or commit, write `branch = "..."` (or `tag`, or `commit`) at the top of its file in
`config/local/` (yours) or `config/services/` (everyone's). `--branch` on the command line wins for one run.

### Change a setting or a key

1. Edit the service's file in `config/local/` (or `all.toml` there for a setting several services share), or, for everyone,
   its file in `config/services/`. Never edit the `.env` files inside the service folders: they are regenerated on every
   start. A service reads **only** that generated `.env`: a variable you export in your terminal or set on the machine does
   not reach it. Copy the changed files to every machine that runs the service.
2. `oblivion.py validate --host <machine>`
3. `oblivion.py restart --host <machine> -s <service>`

Example: switch speech to text to the local model with `STT_ENGINE = "local"` under `[env]` in `config/local/stt.toml`
(the model downloads on first start). To see where any value comes from: `oblivion.py env --host <machine> stt`.

### Start automatically at boot or login

```bash
oblivion.py autostart install --host <machine>      # remove: autostart remove;  see what it would create: autostart print
```

- **Linux / Pi:** a systemd user service. Run once `sudo loginctl enable-linger $USER` so it starts without a login.
- **Windows:** a scheduled task that runs **at logon** (the sound services need your session). The machine must log in
  automatically for the robot to start by itself.

When the machine boots, the tool waits for the other machines' services before starting Brain (section 7, step 6).

> Autostart, Docker and real Raspberry Pi hardware have not yet been exercised end to end by this tool. Try them
> with the robot on the bench, and tell someone what you find.

### Take a machine out of service

```bash
oblivion.py autostart remove --host <machine>
oblivion.py stop --host <machine>
```

To wipe it completely, delete its workdir (default `~/oblivion`): the code, environments, logs and state. Your files in
`config/` stay in `oblivion-deploy/`.

## 10. When something goes wrong

Start with `status`, then read the log of the service that is not healthy. Most problems are one of these:

| Symptom | Likely cause and fix |
|---|---|
| `ai-agent` never becomes available | no LLM key reached it. `oblivion.py env ai-agent --host <machine>` shows what it has (keys masked) and from which file. Add the key to `config/local/ai-agent.toml`, then restart it |
| Replies are errors about a model or provider | the active model profile needs a provider you did not configure: add its key, or change `profile` in the service's `config/step_models.json` |
| Brain is not running after a boot or a deploy; its log ends with `StartupPreflightError` | microphone, STT, TTS or speaker was not available in time. Check them with `status --remote`, then `restart -s brain`; raise `--remote-wait` if the other machines boot slowly |
| Brain speaks "could not reach my decision-making service" | ai-agent is down, or its URL is wrong: check `curl http://<address>:7998/available` from Brain's machine |
| The arms do not move, replies work | the stepper is off or unreachable (moves are best-effort), still in simulation (`MOCK_HARDWARE`), or Brain's arm IDs are not in the stepper's `STEPPER_CONFIGS` |
| The arm moves the wrong angle, or only twitches | `STEPS_PER_REVOLUTION` does not match your driver's microstepping (full steps x microsteps) |
| STT fails at start | `OPENAI_API_KEY` missing in `config/local/`, or set `STT_ENGINE = "local"` |
| STT hears nothing or the wrong text | wrong microphone chosen (`MICROPHONE_TARGET_KEYWORDS`), or `STT_LANGUAGE` differs from the language you speak |
| Speaker cannot open a device | list the outputs with the speaker's own Python, `<workdir>\venvs\speaker\Scripts\python.exe` (Linux: `<workdir>/venvs/speaker/bin/python`), running `-c "import sounddevice as sd; print(sd.query_devices())"`, then set `SPEAKER_DEVICE_INDEX` in `config/local/speaker.toml` |
| The robot answers itself | speakers and microphone in the same room: use headphones |
| `update` says `local modifications` | you edited files inside `<workdir>/services/<service>`: undo them, or use `--force` |
| Health check times out on the first run | a slow install or the Whisper download: add `--health-timeout 600` |
| `Port already in use` | another copy is running (`status`, `stop`), or change that service's port: `port = 1234` in its `config/local/` file, or `ports = { name = 1234 }` on its machine in the layout |
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
py -3 oblivion.py layouts                                   # the ready-made layouts
py -3 oblivion.py init      --layout <name> --address <machine>=<ip>   # write config/robot.toml
py -3 oblivion.py topology                                  # the whole robot: machines, services, what calls what
py -3 oblivion.py doctor    --host <machine>                # is this machine ready?
py -3 oblivion.py validate  --host <machine>                # is the configuration complete?
py -3 oblivion.py deploy    --host <machine> [--system-deps] # install and start
py -3 oblivion.py status    --host <machine> --remote       # is it all healthy, including the other machines?
py -3 oblivion.py update    --host <machine>                # newer code, with automatic rollback
py -3 oblivion.py restart   --host <machine> -s <service>
py -3 oblivion.py logs      --host <machine> -s <service>
py -3 oblivion.py env       --host <machine> <service>      # a service's settings and the file each came from
py -3 oblivion.py autostart install --host <machine>
```

Add `--dry-run` to any command to see exactly what it would run without changing anything.

Ports: brain 7999, microphone 8000, stt 8001, tts 8002, speaker 8003, stepper 8005, camera 8006, ai-agent 7998.
Files: `config/robot.toml` (the layout and addresses), `config/local/` (your keys and settings) and `config/machines/` (all ignored by git),
logs `<workdir>/logs/`, state `<workdir>/state/`.

Where to read more: [`DEPLOYMENT.md`](DEPLOYMENT.md) (every variable, per-service settings, known limits) and
[`../README.md`](../README.md) (how the tool works: layouts, the files under `config/`, branches, rollback, Docker).
