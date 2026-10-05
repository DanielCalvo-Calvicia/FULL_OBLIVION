# config/local: your private settings

Everything in this folder except this file and the `*.example.toml` templates is **git-ignored**: it is yours, and it holds the keys.

A file here has the same shape as the file with the same name in `config/services/`, and it **wins over it**:

| File | What it is for |
|---|---|
| `all.toml` | `[env]` settings (and keys) several services share, for example `OPENAI_API_KEY` for stt and ai-agent |
| `<service>.toml` | one service's private settings, its keys, and anything you want different on this robot: `[env]`, and `branch` / `tag` / `commit`, `runtime`, `port`, `git` |

To start: copy an `*.example.toml` to the same name without `.example`, and fill in the keys you use.

```toml
# config/local/stepper.toml: real motors on the Pi, 400 full steps x 1/8 microstepping
[env]
MOCK_HARDWARE = 0
STEPS_PER_REVOLUTION = 3200
```

Check what a service will really get, and which file each value came from:

    python oblivion.py env stepper --host pi
