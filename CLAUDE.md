# CLAUDE.md: deployment

Repo `FULL_OBLIVION`. A stdlib-only Python 3.11+ CLI (`main.py`, also `oblivion.py`) that deploys any subset of the services on one machine (Windows, Linux, Raspberry Pi). Read `README.md` (the tool), `docs/USER_GUIDE.md` (the step-by-step operator guide: keep its commands in step with the CLI) and `docs/DEPLOYMENT.md` (the manual: venvs, every env var, start order, health checks) first.

Status: restructured on 2026-10-04 into the layered layout of the other services, with all the configuration in `config/` (layouts, one file per service, your local files). Tested with fake services and on a real Raspberry Pi 4 plus a Windows PC (a layout with the speaker on the PC and everything else on the Pi); Docker, systemd, scheduled tasks and the Pi's speed under load are untested. Tests: see "Commands". Check `git status` and `git log` for the current commit.

## Layout

- `config/`: EVERYTHING that is edited. `robot.toml` (git-ignored; template `robot.example.toml`) picks a layout and gives the machine addresses. `layouts/<name>.toml` are the committed presets (all-in-one, speaker-on-pc, audio-on-pc, stepper-on-pi, pc-server-pi). `services/<service>.toml` + `all.toml` are the committed, GENERATED defaults of every setting (all commented out). `local/<service>.toml` + `all.toml` are the operator's own values and keys (git-ignored; `*.example.toml` and `README.md` are committed). `machines/<machine>.toml` is the machine's Python, workdir, OS and bind (git-ignored, optional). `catalogue.toml` is what each service IS (git URL, port, requirements, apt, `prepare`, `consumes`, presets in `[env]`); relative library paths in it are relative to the repository root.
- `domain/` (no I/O): `entities/` (`ServiceSpec`, `Catalogue`, `Layout`/`Machine`, `Host`/`ServiceInstance`/`EnvLayer`, `ServiceSettings`, `ResolvedEnv`), `rules/` (`env_resolution`, `env_names`, `host_validation`, `topology`, `branch_overrides`, `dotenv`), `errors.py` (`DeployError`).
- `application/`: `services/` (`DeploymentService` = deploy / update with rollback / start / stop / status / plan, `EnvironmentService`, `ValidationService`, `CompatService`, `layout_service.describe_layout`), `ports/outbound/` (the Protocols: shell, source control, installer, runtime, health, state, env files, workspace), `dtos/options.py`.
- `infrastructure/`: `config/` (the TOML loaders: `paths`, `catalogue_loader`, `layout_loader`, `settings_loader`, `machine_loader`, `host_loader`), `outbound/` (`shell`, `git`, `installer`, `runtime` = native/docker/process dispatch + `tee.py` + `service_runner.py`, `health`, `state`, `env`, `autostart`, `workspace`), `inbound/cli/cli.py`.
- `composition_root/container.py`: the only place that knows both sides (`new_deployment_service`, `new_compat_service`).
- `launch.py` (one machine, one command; creates `config/robot.toml` and the key files on a first run, never overwrites), `docker/service.Dockerfile`, `wheels/` (the committed shared-logging wheel; `scripts/bundle_shared_logging.py` rebuilds it), `scripts/env_inventory.py` (regenerates `config/services/` and `config/local/*.example.toml`), `tests/`.

## Rules

- **Define every fact once, derive the rest.** A port lives only in `config/catalogue.toml` (a machine's `ports = {..}` in a layout deviates, and callers follow). An address lives only in `config/robot.toml` (a single-machine layout may carry a default one). A machine's services, its bind address and every `*_BASE_URL` are derived (`infrastructure/config/host_loader.py`, `domain/rules/topology.py`). A variable several services use is set once in `all.toml` and listed once. Constants nobody sets on a deployed machine are `internal` in the catalogue and never advertised. Do not add a second place to type a port, an address or a bind flag; `tests/test_layouts.py` also checks the ports printed in the docs against the catalogue.
- **Dependencies point inward** (`infrastructure` -> `application` -> `domain`). New external effects get a port in `application/ports/outbound/` and an adapter in `infrastructure/outbound/`, wired in `composition_root/container.py`.
- **Layers of the environment** (low to high): the service's `.env.example`, the catalogue's `[env]`, computed values, `services/all.toml`, `local/all.toml`, `services/<service>.toml`, `local/<service>.toml`. `all.toml` only reaches services that know the variable. `oblivion.py env` prints the file each value came from. The old `robot.toml` `[env]`, `hosts/`, `secrets/*.env` and `--robot` no longer exist; do not bring them back.
- Every external command goes through `Shell` so `--dry-run` shows it. Keep dry-run side-effect free (there is a test).
- Never write secrets into committed files. Committed settings files list secrets commented out (`#NAME = ""`); real keys only in `config/local/`, which is git-ignored. `launch.py` writes key files with mode 600.
- `update` must never destroy local edits or leave a service dead: refuse on a dirty clone unless `--force`, and roll back a release that is not healthy. Keep the tests for both.
- Settings reach a service ONLY through its generated `.env` (catalogue `dotenv`, `native_runtime.child_environment`, `service_runner.py` for services without dotenv support, a bind mount for Docker). Never put them back into the child's environment: python-dotenv does not override a variable already set, so an inherited one would beat the file. Keep `dotenv` in the catalogue equal to whether the service code calls `load_dotenv` (a test checks it).
- **`service_runner.py` runs inside a service's own Python, whose packages are also called `domain`, `application` and `infrastructure`.** It must never import this project by package name: it loads `domain/rules/dotenv.py` by file path (importlib) and leaves nothing behind. `tests/test_env_file_only.py` has a test with a service that has those package names. Keep it.
- `.env` parsing (`domain/rules/dotenv.py` `parse_env`/`render_value`) must drop inline `# comments` of unquoted values: ai-agent's `.env.example` has them and `int("6   # ...")` crashed it. A tracked `.env` the tool generated (stepper) is not a local edit (`GitSourceControl.restore_generated`; the generated header starts with `# Generated by oblivion`).
- Brain exits (and nothing restarts it) when its preflight fails, so `DeploymentService.wait_for_remotes` waits for required services of other machines before a start. Keep it.
- Test the install path for real, not only with fake services: a fresh clone of this repo in a folder with no `../shared-logging`, a real `pip install`, on Python 3.14 and 3.11. The fake-service tests missed bugs before.
- Keep `docs/DEPLOYMENT.md` in step with each service's `.env.example` when a variable is added or removed, and after any `.env.example` change run `brain_microservice\windows\Scripts\python.exe deployment\scripts\env_inventory.py --write` (a test fails otherwise). Variables the code reads that no `.env.example` lists go in `extra_env` in the catalogue and in `EXTRA` in the script. The inventory reads each service's SOURCE, test scripts included: do not read an environment variable in a `test/` script of a service, or it becomes an undocumented setting.
- Do not commit or push unless asked.

## Commands

```powershell
& ..\brain_microservice\windows\Scripts\python.exe -m pytest tests -q     # about 150 s
& ..\brain_microservice\windows\Scripts\python.exe oblivion.py layouts
& ..\brain_microservice\windows\Scripts\python.exe oblivion.py topology --config <a config folder>
```

Write Python test helpers and scripts with the Write tool, not shell heredocs (quotes and `\n` get mangled).
