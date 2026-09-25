# FULL_OBLIVION Documentation

This folder holds all top-level documentation for the FULL_OBLIVION voice AI agent platform. Use this page as the entry point and index.

## Organization

```text
docs/
├── README.md                     # This index + report
├── architecture/                 # How the system is structured and runs
│   ├── dependency_graph.md
│   └── execution.md
└── deployment/                   # How to deploy and operate the stack
    ├── deployment.md
    ├── deployment_guide.md
    ├── service_selection.md
    └── windows_autostart.md
```

The repo-root `README.md` and `scripts/README.md` intentionally stay where they are, following the convention of keeping a README next to what it describes. The per-microservice docs under `repos/*_microservice/` are self-contained sub-projects and are out of scope for this index.

## Architecture

Documentation describing how the system is composed and how it runs.

| Document | Summary |
|---|---|
| [`architecture/dependency_graph.md`](architecture/dependency_graph.md) | Mermaid diagrams of the full voice pipeline, startup dependencies, and service-selection expansion, plus the runtime dependency matrix and conflict points. |
| [`architecture/execution.md`](architecture/execution.md) | Native (non-Docker) execution model: per-service startup commands, required startup order, runtime lifecycle, health endpoints, conflict analysis, and failure recovery. |

## Deployment & Operations

Documentation for building, deploying, selecting, and auto-starting the stack.

| Document | Summary |
|---|---|
| [`deployment/deployment.md`](deployment/deployment.md) | Comprehensive Docker Compose deployment specification: repository sources, per-service build strategy, Dockerfile templates, the Compose profile system, health checks, volumes, and execution metadata. |
| [`deployment/deployment_guide.md`](deployment/deployment_guide.md) | Practical, step-by-step deployment guide: bootstrap, configuration, from-scratch Compose generation, starting/stopping, logs, health checks, hybrid/multi-host layouts, and systemd/Windows auto-start. |
| [`deployment/service_selection.md`](deployment/service_selection.md) | Reference for the Docker Compose profiles (`full`, `brain`, `stt`, `tts`, `audio`, and aliases), dependency URLs, selection rules, scaling limits, and platform guidance. |
| [`deployment/windows_autostart.md`](deployment/windows_autostart.md) | Running the stack via Windows Task Scheduler: common scripts, task setup, and remote-service URL configuration. |

## Related Docs (not moved)

| Document | Location | Why it stays |
|---|---|---|
| [`README.md`](../README.md) | repo root | Standard project entry point; rendered by hosts at the repo root. |
| [`scripts/README.md`](../scripts/README.md) | `scripts/` | Documents the scripts in that folder; kept adjacent to the code it describes. |
| `repos/*_microservice/**` | per microservice | Each microservice is a self-contained sub-project with its own docs. |

## Renames Applied

Filenames were normalized to `snake_case` (per the project naming convention) while relocating:

| Old (repo root) | New |
|---|---|
| `DEPENDENCY_GRAPH.md` | `docs/architecture/dependency_graph.md` |
| `EXECUTION.md` | `docs/architecture/execution.md` |
| `DEPLOYMENT.md` | `docs/deployment/deployment.md` |
| `DEPLOYMENT_GUIDE.md` | `docs/deployment/deployment_guide.md` |
| `SERVICE_SELECTION.md` | `docs/deployment/service_selection.md` |
| `WINDOWS_AUTOSTART.md` | `docs/deployment/windows_autostart.md` |
