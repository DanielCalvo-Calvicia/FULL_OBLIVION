# PROMPT: Golden Template README.md for Python Hexagonal Microservice Ecosystem

---

## ROLE ASSIGNMENT

You are a **Principal Software Architect and Technical Documentation Expert** with deep expertise in:
- **Hexagonal Architecture** (Ports and Adapters pattern)
- **Domain-Driven Design** (DDD)
- **Python ecosystem tooling** (FastAPI, Uvicorn, Pydantic, Ruff, Mypy, Black)
- **Modular software distribution** (internal packages, versioned modules)
- **Inversion of Control** and **Composition Root** patterns

Your sole objective in this task is to produce a **single, production-grade, `README.md` file** that serves as the canonical "Golden Template" for any new Python microservice built within this ecosystem.

---

## BEHAVIORAL GUARDRAILS

You **MUST** follow these rules without exception:

1. **No placeholder text.** Every section must contain actual, production-quality documentation. Do not write `[Your description here]`, `TODO`, or any generic filler.
2. **No fabricated examples.** All code snippets must be syntactically valid Python 3.11+ and architecturally consistent with the patterns described.
3. **Do not simplify.** This template targets senior and principal engineers. Do not omit complexity in favor of brevity.
4. **Maintain section integrity.** Every section listed in this prompt must appear in the final README, in the order specified, at the correct heading level.
5. **Write in the imperative and declarative.** Documentation sections describe system behavior as fact, not opinion. Guide sections use imperative voice.
6. **Replace `[INSERT_PROJECT_NAME_HERE]`** throughout the document with the literal token `{service_name}` formatted as a Jinja-style placeholder, so consumers of the template know exactly what to substitute.

---

## ARCHITECTURE CONTEXT

This microservice ecosystem is built on **Hexagonal Architecture** (also known as Ports and Adapters). The central principle is that the **application core** (domain logic, ports, DTOs) must be **completely decoupled** from all transport, framework, and infrastructure concerns.

The key insight that drives the module distribution strategy is this:

> The `application/` layer — its `dtos/`, `ports/`, and `services/` — must be exportable as a standalone, versioned internal Python package. It must carry **zero dependencies** on FastAPI, Uvicorn, sounddevice, databases, or any other infrastructure library. This allows other microservices in the ecosystem to depend on the published contract (ports + DTOs) without pulling in any concrete implementation.

The **Composition Root** (`composition_root/`) is the **only place** where concrete implementations are wired together. It is intentionally isolated so that swapping an outbound adapter (e.g., replacing a local hardware driver with a remote gRPC call) requires zero changes to the application core.

---

## REQUIRED DIRECTORY STRUCTURE

Document this exact directory layout. Every directory must have a precise, non-generic description of its architectural role.

```
{service_name}/
├── application/
│   ├── dtos/                # Data Transfer Objects: layer-boundary contracts
│   │   └── mapper/          # Pure mapping functions between layer DTOs
│   ├── ports/               # Abstract Port definitions (ABCs): Inbound & Outbound
│   └── services/            # Framework-agnostic business logic implementations
├── composition_root/        # Dependency Injection wiring (the only coupling point)
│   ├── containers/          # IoC Container: assembles the full dependency graph
│   ├── dependencies/        # Named dependency factories (one per bounded context)
│   └── setup/               # Application bootstrap: starts server, handles lifecycle
├── infrastructure/          # Concrete adapter implementations
│   ├── inbound/             # Driven adapters: FastAPI, HTTP handlers, gRPC servers
│   └── outbound/            # Driving adapters: hardware drivers, databases, external APIs
├── tests/                   # Test suite
│   └── simple.py            # End-to-end integration test (self-hosting, no manual server)
├── .env                     # Local development environment variables
├── .env.production          # Production environment variables (never committed)
├── requirements.{platform}.txt  # Platform-specific pinned dependencies
└── README.md
```

---

## REQUIRED README SECTIONS

Generate the following sections **in this exact order**:

---

### 1. Header & Badge Block

Include:
- Service name as `# {service_name}`
- One-line architectural description beneath the title
- Badge placeholders for: Python version, license, code style (Ruff), type checker (Mypy), and test status

---

### 2. Table of Contents

Auto-linked to every section below.

---

### 3. Architectural Overview

Write a full, prose explanation (minimum 4 paragraphs) covering:

**Paragraph 1 — The Core Problem This Architecture Solves:**
Explain why traditional layered architectures fail at scale (tight coupling between business logic and infrastructure, inability to test domain logic in isolation, inability to share contracts between services).

**Paragraph 2 — Hexagonal Architecture: The Solution:**
Explain the Ports and Adapters model. Define the "inside" (application core: ports, services, DTOs) and the "outside" (adapters: FastAPI, databases, hardware). Explain the Dependency Rule: dependencies only point inward.

**Paragraph 3 — The Composition Root:**
Explain why all wiring happens in `composition_root/` and nowhere else. Explain why this is the only place where concrete types are instantiated and injected. Explain that the rest of the codebase works exclusively through interfaces (ABCs).

**Paragraph 4 — Modular Distribution Strategy:**
Explain how the `application/` layer (ports, DTOs, services) can be extracted and published as a versioned internal Python package (e.g., via a private PyPI server or a `pyproject.toml`-based local package). Detail how other microservices can depend on the `application/` package to consume the service's port contracts and DTOs without any coupling to the infrastructure.

---

### 4. Directory Structure

Reproduce the directory tree above with **one sentence of explanation per entry**. No line may be left undescribed.

---

### 5. Layer Responsibilities

For each of the following layers, write a dedicated subsection with:
- A definition of the layer's single responsibility
- What it IS allowed to import
- What it is STRICTLY FORBIDDEN from importing
- A minimal, syntactically valid Python code example demonstrating the pattern

**Layers to document:**
- `application/ports/` — Abstract Base Class port definitions (must declare `start_autoload` and `stop_autoload` lifecycle hooks for inbound adapters)
- `application/dtos/` — Frozen dataclass DTOs (must include `InitInboundAdapterDto` for passing configuration from Composition Root to inbound adapters, keeping environment variables decoupled)
- `application/dtos/mapper/` — Pure mapping functions (no side effects)
- `application/services/` — Business logic implementing inbound ports, depending only on outbound port ABCs
- `composition_root/dependencies/` — Dependency factory functions (where environment variables are retrieved, packaged into config DTOs, and injected into adapters)
- `composition_root/containers/` — The IoC container (a frozen dataclass assembling all dependencies)
- `composition_root/setup/` — Bootstrap: `async def setup()` using `uvicorn.Server.serve()` (wiring standard FastAPI lifespan contexts to invoke inbound adapter lifecycle hooks)
- `infrastructure/inbound/` — Concrete inbound adapters (e.g., `FastApiAdapter` which accepts `InitInboundAdapterDto` and delegates complex concurrency or background streams to an isolated runner class)
- `infrastructure/outbound/` — Concrete outbound adapters (e.g., hardware drivers)

---

### 6. Modular Distribution Guide

This section must be thorough and actionable. Cover:

#### 6.1 The Distribution Contract
Explain that the `application/` directory is the **published surface area** of this service. It must be treated as a versioned API. No breaking changes to port ABCs or DTO field names may be made without a version bump.

#### 6.2 Packaging the Application Layer
Provide a complete, valid `pyproject.toml` example that packages only the `application/` directory as a distributable internal Python package named `{service_name}-contracts`. Include:
- `[project]` table with name, version, description, and `requires-python`
- `[project.dependencies]` that includes **only** `pydantic` (if used) — explicitly no FastAPI, no uvicorn
- `[tool.setuptools.packages.find]` configured to include only the `application` package

#### 6.3 Consuming the Contract in Another Service
Show a concrete `requirements.txt` or `pyproject.toml` snippet from a *consumer* service that installs `{service_name}-contracts` as a dependency. Then show a Python import example in the consumer using the shared port ABC.

#### 6.4 Versioning Strategy
Define a strict SemVer policy:
- **PATCH**: Non-breaking additions (new optional DTO fields, new non-abstract methods)
- **MINOR**: Backwards-compatible new port methods
- **MAJOR**: Any change to an existing port method signature or removal of a DTO field

---

### 7. Interface-Driven Design

This section must explain and demonstrate the full pattern with working code examples.

#### 7.1 Defining a Port (Abstract Base Class)
Show the full pattern for an inbound port and an outbound port, with strict type hints and `@abstractmethod` decorators. The example must use `from abc import ABC, abstractmethod` and include at least one async method.

#### 7.2 Implementing an Inbound Port (Service)
Show how a service class inherits from the inbound port ABC and depends on the outbound port ABC via constructor injection. **The service class must never reference a concrete type — only ABCs.**

#### 7.3 Implementing an Outbound Port (Infrastructure Adapter)
Show a concrete outbound adapter that implements the outbound port ABC.

#### 7.4 Why ABCs Over Protocols
Explain the deliberate choice to use `ABC`/`abstractmethod` over `typing.Protocol`. The rationale: `isinstance()` checks in the Composition Root and explicit `super().__init__()` call chains provide stronger guarantees than structural subtyping for infrastructure-layer injection.

---

### 8. Data Mapping Pattern

#### 8.1 The Problem: Domain Leakage
Explain why passing raw infrastructure objects (e.g., FastAPI request models, SQLAlchemy ORM objects) directly into the service layer is an anti-pattern that creates hidden coupling.

#### 8.2 The DTO Contract
Show the standard frozen dataclass DTO pattern used in this codebase. Emphasize `@dataclass(slots=True, frozen=True)` for immutability and memory efficiency.

#### 8.3 Mapping Functions
Show the mapper pattern: pure functions in `application/dtos/mapper/` that convert between layer-boundary DTOs. These functions must have no side effects, no I/O, no logging, and must be trivially unit-testable.

#### 8.4 Mapping Layers Diagram
Render a text-based ASCII diagram showing the data flow:
```
HTTP Request → [FastAPI Adapter] → AdapterInboundDto
             → [mapper: adapter_inbound_to_service] → ServiceRequestDto
             → [Service] → ServiceResponseDto
             → [mapper: service_to_adapter_inbound] → AdapterInboundResponseDto
             → [FastAPI Adapter] → HTTP Response
```

---

### 9. Composition Root Pattern

#### 9.1 The Single Assembly Point
Explain the rule: **concrete types are instantiated in exactly one place and one place only** — `composition_root/`.

#### 9.2 Dependency Factory Pattern
Show a complete, valid `generate_{context}_dependency()` factory function that:
- Accepts configuration primitives as arguments
- Instantiates the outbound adapter with a configuration DTO
- Instantiates the service with the outbound adapter
- Instantiates the FastAPI app and the inbound adapter
- Returns a frozen dependency dataclass

#### 9.3 The IoC Container
Show the complete `BuildContainer()` function and `Container` frozen dataclass pattern.

#### 9.4 The Bootstrap Function
Show the complete `async def setup()` function that:
- Calls `BuildContainer()`
- Retrieves the FastAPI app from the inbound adapter via `get_app` property
- Creates `uvicorn.Config` and `uvicorn.Server`
- Awaits `server.serve()` for graceful lifecycle management
- Calls a `_cleanup()` coroutine after server shutdown

---

### 10. Getting Started

A step-by-step guide that a developer can follow from scratch to scaffold a new microservice using this template.

#### 10.1 Prerequisites
List exact required tools with minimum versions: Python 3.11+, pip, Git, Ruff, Mypy, Black.

#### 10.2 Clone & Configure
```bash
git clone <template-repository-url> {service_name}
cd {service_name}
cp .env.example .env
# Edit .env with your service-specific values
```

#### 10.3 Virtual Environment Setup (per platform)
Provide separate, copy-pasteable commands for Windows (PowerShell) and Linux/macOS.

#### 10.4 Install Dependencies
```bash
pip install -r requirements.{your_platform}.txt
```

#### 10.5 Run the Service
```bash
python main.py
```
Explain that the service will print its host/port and that `Ctrl+C` triggers graceful shutdown and cleanup.

#### 10.6 Run End-to-End Tests
```bash
python tests/simple.py
```
Explain that this test is self-hosting: it boots the server, runs the full API flow, and shuts down automatically.

---

### 11. Code Style & Linting

#### 11.1 Toolchain
Document the following tools and their roles:

| Tool | Role | Config file |
|------|------|-------------|
| **Ruff** | Linting + import sorting | `pyproject.toml` → `[tool.ruff]` |
| **Black** | Code formatting | `pyproject.toml` → `[tool.black]` |
| **Mypy** | Static type checking | `pyproject.toml` → `[tool.mypy]` |

#### 11.2 Enforcement Rules
Document the following non-negotiable rules:
- All public functions and methods must have type annotations.
- All module-level variables must have type annotations.
- `Any` is forbidden in `application/` and `composition_root/`. It is only permitted in `infrastructure/` with an inline `# type: ignore` comment and a justification comment on the line above.
- No `print()` statements in `application/` or `composition_root/`. Use structured logging.

#### 11.3 Pre-commit Configuration
Provide a complete `.pre-commit-config.yaml` example that runs Ruff, Black, and Mypy on every commit.

---

### 12. Conventional Commits

Document the full Conventional Commits specification as it applies to this project.

Include a table of commit types with descriptions and examples:

| Type | When to use | Example |
|------|-------------|---------|
| `feat` | New feature or port method | `feat(ports): add get_volume_level to AdapterOutboundPort` |
| `fix` | Bug fix in any layer | `fix(outbound): handle stereo-to-mono conversion overflow` |
| `refactor` | Internal restructuring without behavior change | `refactor(composition_root): extract dependency factory` |
| `docs` | Documentation only | `docs(readme): add modular distribution guide` |
| `test` | Test additions or changes | `test(e2e): add stream lifecycle assertions to simple.py` |
| `chore` | Tooling, config, dependencies | `chore(deps): pin uvicorn to 0.34.x` |
| `perf` | Performance improvement | `perf(outbound): reduce numpy allocation in stereo mixdown` |
| `ci` | CI/CD pipeline changes | `ci: add mypy check to pre-commit` |

**Breaking Change Rule:** Any commit that changes a port ABC signature, removes a DTO field, or changes a public API contract MUST append `!` to the type and include a `BREAKING CHANGE:` footer in the commit body.

Example:
```
feat(ports)!: rename start_stream to open_stream in AdapterOutboundPort

BREAKING CHANGE: All outbound adapter implementations must rename
start_stream() to open_stream(). Consumer packages must bump their
{service_name}-contracts dependency to ^2.0.0.
```

---

### 13. Environment Variables

Provide a reference table documenting all expected `.env` keys:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_ENV` | Yes | `debug` | Execution environment (`debug` or `production`) |
| `SERVICE_HOST` | No | `127.0.0.1` | Host address for the Uvicorn server |
| `SERVICE_PORT` | No | `8000` | Port for the Uvicorn server |
| `LOG_LEVEL` | No | `info` | Uvicorn log level |

---

### 14. API Reference

#### 14.1 Base URL
```
http://{SERVICE_HOST}:{SERVICE_PORT}
```

#### 14.2 Health Check

```
GET /health
```

**Response:**
```json
{
  "action": "health_check",
  "status": "success",
  "status_code": 200,
  "message": "Service is healthy",
  "timestamp": 1747497600.0,
  "data": null
}
```

#### 14.3 Standard Response Envelope
All JSON responses from this service follow this envelope contract. Document each field:

| Field | Type | Description |
|-------|------|-------------|
| `action` | `str` | The endpoint action identifier |
| `status` | `"success" \| "error"` | Outcome of the request |
| `status_code` | `int` | HTTP status code (mirrored in body for client convenience) |
| `message` | `str` | Human-readable outcome description |
| `timestamp` | `float` | Unix epoch timestamp of response generation |
| `data` | `any \| null` | Payload; `null` for void responses |

---

### 15. Contributing

#### 15.1 Branch Strategy
- `main` — always deployable, protected
- `develop` — integration branch
- `feature/{ticket-id}-{short-description}` — feature branches
- `fix/{ticket-id}-{short-description}` — bug fix branches

#### 15.2 Pull Request Requirements
- All Mypy, Ruff, and Black checks must pass.
- At least one reviewer approval required.
- PR title must follow Conventional Commits format.
- Breaking changes require two reviewer approvals and a `BREAKING CHANGE:` footer.

---

### 16. License

Include a standard MIT License block with `{year}` and `{author}` as substitution tokens.

---

## FINAL OUTPUT INSTRUCTIONS

1. Output **only** the `README.md` content. Do not include any preamble, meta-commentary, or explanation of your choices outside the document itself.
2. The document must be **immediately usable**. Copy-paste into a new repository and it must work as a complete, professional README.
3. Every code block must specify a language identifier (` ```python `, ` ```bash `, ` ```toml `, etc.).
4. Use **GitHub Flavored Markdown** exclusively.
5. All internal links in the Table of Contents must use GitHub-compatible anchor syntax (lowercase, spaces replaced with `-`).
6. Target length: **minimum 1,200 lines of markdown**. This is a comprehensive architectural document, not a summary.
