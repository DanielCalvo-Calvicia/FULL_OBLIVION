"""The deployment operations: install, update (with rollback), start, stop, status, validate."""

from __future__ import annotations

import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import gitops, health, installer, runtime
from .config import DeployError, Host, Registry, validate_host
from .envfile import ResolvedEnv, mask, render, resolve_env
from .shell import Shell
from .state import State

REMOTE_POLL_SECONDS = 3.0


@dataclass
class Options:
    force: bool = False
    system_deps: bool = False
    rollback: bool = True
    health_timeout: float = 60.0
    skip_health: bool = False
    remote_wait: float = 120.0  # seconds to wait for the required services of other machines before starting


@dataclass
class Manager:
    shell: Shell
    host: Host
    registry: Registry
    options: Options = field(default_factory=Options)

    def __post_init__(self) -> None:
        self.state = State(self.host.state_dir())

    # ------------------------------------------------------------------ selection

    def select(self, names: list[str] | None) -> list[str]:
        """Local services to act on, dependencies (services others consume) first."""
        wanted = names or list(self.host.services)
        for name in wanted:
            if name not in self.host.services:
                raise DeployError(f"{name!r} is not deployed on host {self.host.name!r} (has: {', '.join(self.host.services)})")
        ordered: list[str] = []

        def visit(service: str) -> None:
            if service in ordered or service not in wanted:
                return
            for dependency in self.host.services[service].spec.consumes:
                if dependency in self.host.services:
                    visit(dependency)
            ordered.append(service)

        for service in wanted:
            visit(service)
        return ordered

    # ------------------------------------------------------------------ environment

    def resolve(self, name: str) -> ResolvedEnv:
        defaults = self.host.service_dir(name) / ".env.example"
        return resolve_env(self.host, name, defaults)

    def env_target(self, name: str) -> Path:
        if self.host.services[name].runtime == "docker":
            return self.host.workdir / "env" / f"{name}.env"
        return self.host.service_dir(name) / ".env"

    def write_env(self, name: str) -> dict[str, str]:
        resolved = self.resolve(name)
        if resolved.errors:
            raise DeployError("\n".join(resolved.errors))
        for warning in resolved.warnings:
            self.shell.say(f"warning: {warning}")
        target = self.env_target(name)
        if self.shell.dry_run:
            self.shell.say(f"[dry-run] write {target} ({len(resolved.values)} variables)")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render(resolved.values, self.host.name), encoding="utf-8")
            try:
                target.chmod(0o600)  # it holds the API keys: readable by this user only (no effect on Windows)
            except OSError:
                pass
        return resolved.values

    # ------------------------------------------------------------------ prepare

    def fetch_code(self, name: str) -> tuple[str | None, str | None]:
        instance = self.host.services[name]
        self.shell.say(f"{name}: code {instance.spec.git} @ {instance.branch}")
        return gitops.sync(
            self.shell, instance.spec.git, self.host.service_dir(name), instance.branch, force=self.options.force
        )

    def install(self, name: str) -> None:
        instance = self.host.services[name]
        previous = self.state.get(name).get("fingerprint")
        if instance.runtime == "docker":
            runtime.require_docker(self.shell)
            self._install_docker(name)
            return
        fingerprint, warnings = installer.install_native(
            self.shell, self.host, self.registry, name,
            previous_fingerprint=previous, system_deps=self.options.system_deps,
        )
        for warning in warnings:
            self.shell.say(f"warning: {warning}")
        if not self.shell.dry_run:
            self.state.update(name, fingerprint=fingerprint)

    def _install_docker(self, name: str) -> None:
        spec = self.host.services[name].spec
        requirements, warning = installer.requirements_file(self.host, spec, self.host.service_dir(name))
        if warning:
            self.shell.say(f"warning: {warning}")
        if requirements is None:
            raise DeployError(f"{name}: no requirements file to build the image from")
        wheels_dir = self.host.workdir / "build" / f"{name}-wheels"
        if not self.shell.dry_run:
            wheels_dir.mkdir(parents=True, exist_ok=True)
        for library in spec.libraries:
            kind, location = installer.library_source(self.registry, library)
            if kind == "wheel_dir":  # already a wheel: no build needed
                for wheel in installer.bundled_wheels(self.registry, library):
                    self.shell.say(f"copy {wheel.name} -> {wheels_dir}")
                    if not self.shell.dry_run:
                        shutil.copy2(wheel, wheels_dir / wheel.name)
                continue
            self.shell.run([
                self.host.python or sys.executable, "-m", "pip", "wheel", "--quiet", "--no-deps",
                "-w", wheels_dir, *installer.library_pip_args(self.registry, library),
            ])
        wheels = sorted(wheels_dir.glob("*.whl")) if wheels_dir.exists() else []
        context = runtime.prepare_docker_context(
            self.shell, self.host, name, installer.filtered_requirements(requirements), wheels
        )
        runtime.docker_build(self.shell, self.host, name, context)

    # ------------------------------------------------------------------ run

    def wait_for_remotes(self, name: str) -> None:
        """Wait, up to ``remote_wait`` seconds, for the required services of OTHER machines that ``name`` consumes.

        Brain exits when its own startup preflight times out and nothing restarts it, so a machine that boots
        (autostart) or is deployed before the machines it depends on would leave Brain dead. Not reachable in
        time is a warning, not an error: the service still gets to try, and its own preflight decides.
        """
        spec = self.host.services[name].spec
        pending = {
            target: self.host.remote[target]
            for target in spec.consumes
            if target in self.host.remote and target not in self.host.services
            and target not in spec.optional_consumes and target in self.registry.services
        }
        if not pending or self.shell.dry_run or self.options.remote_wait <= 0:
            return
        self.shell.say(f"{name}: waiting up to {self.options.remote_wait:g}s for {', '.join(pending)} on other machines")
        deadline = time.monotonic() + self.options.remote_wait
        while True:
            # concurrently: an unreachable host takes seconds to fail, and one pass must not outlast the deadline
            with ThreadPoolExecutor(max_workers=len(pending)) as pool:
                results = {t: pool.submit(health.check, url, self.registry.services[t]) for t, url in pending.items()}
            for target, future in results.items():
                if future.result()[0]:
                    self.shell.say(f"{name}: {target} is up at {pending.pop(target)}")
            if not pending or time.monotonic() >= deadline:
                break
            time.sleep(REMOTE_POLL_SECONDS)
        for target, url in pending.items():
            self.shell.say(f"warning: {name}: {target} at {url} is not reachable yet; starting anyway")

    def start_one(self, name: str, env: dict[str, str] | None = None) -> None:
        env = env if env is not None else self.write_env(name)
        self.wait_for_remotes(name)
        instance = self.host.services[name]
        if instance.runtime == "docker":
            runtime.require_docker(self.shell)
            runtime.docker_start(self.shell, self.host, name, self.env_target(name))
        else:
            runtime.native_start(self.shell, self.host, name, env)

    def stop_one(self, name: str) -> None:
        if self.host.services[name].runtime == "docker":
            runtime.docker_stop(self.shell, self.host, name)
        else:
            runtime.native_stop(self.shell, self.host, name)

    def base_url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.host.services[name].port}"

    def _record(self, name: str, **fields: object) -> None:
        if not self.shell.dry_run:
            self.state.update(name, **fields)

    def wait_healthy(self, name: str) -> tuple[bool, str]:
        if self.shell.dry_run or self.options.skip_health:
            return True, "not checked"
        return health.wait(self.base_url(name), self.host.services[name].spec, self.options.health_timeout)

    def start(self, names: list[str] | None) -> list[str]:
        failures: list[str] = []
        for name in self.select(names):
            try:
                self.start_one(name)
                ok, detail = self.wait_healthy(name)
                self.shell.say(f"{name}: {detail}")
                if not ok:
                    failures.append(f"{name}: {detail}")
            except DeployError as error:
                failures.append(_describe(name, error))
        return failures

    def stop(self, names: list[str] | None) -> None:
        for name in reversed(self.select(names)):
            self.stop_one(name)

    # ------------------------------------------------------------------ deploy / update

    def deploy(self, names: list[str] | None) -> list[str]:
        """First install (or repair): fetch code, install dependencies, write env, start, check."""
        selected = self.select(names)
        self.preflight(selected)
        failures: list[str] = []
        for name in selected:
            try:
                previous, commit = self.fetch_code(name)
                self.install(name)
                env = self.write_env(name)
                self.stop_one(name)
                self.start_one(name, env)
                ok, detail = self.wait_healthy(name)
                self.shell.say(f"{name}: {detail}")
                self._record(name, branch=self.host.services[name].branch, commit=commit, previous_commit=previous)
                if not ok:
                    failures.append(f"{name}: {detail}")
            except DeployError as error:
                failures.append(_describe(name, error))
        return failures

    def update(self, names: list[str] | None) -> list[str]:
        """Move services to the configured branches; a service whose new version does not become
        healthy is put back on the version that was running."""
        selected = self.select(names)
        self.preflight(selected)
        failures: list[str] = []
        for name in selected:
            instance = self.host.services[name]
            repo = self.host.service_dir(name)
            was_running = runtime.is_running(self.shell, self.host, name)
            before = gitops.current_commit(self.shell, repo)
            code_replaced = False
            try:
                self.stop_one(name)
                _, after = self.fetch_code(name)
                code_replaced = after != before
                self.install(name)
                env = self.write_env(name)
                self.start_one(name, env)
                ok, detail = self.wait_healthy(name)
                if not ok:
                    raise DeployError(f"new version is not healthy ({detail})")
                self.shell.say(f"{name}: updated {(before or '-')[:8]} -> {(after or '-')[:8]}  ({detail})")
                self._record(name, branch=instance.branch, commit=after, previous_commit=before)
            except DeployError as error:
                failures.append(_describe(name, error))
                self.shell.say(f"{name}: FAILED: {error}")
                if self.options.rollback and before and not self.shell.dry_run:
                    if code_replaced:
                        self._rollback(name, before, was_running, failures)
                    elif was_running:
                        # the code was not touched (e.g. refused because of local edits): just bring it back up
                        self._restart_untouched(name, failures)
        return failures

    def _restart_untouched(self, name: str, failures: list[str]) -> None:
        try:
            self.start_one(name)
            ok, detail = self.wait_healthy(name)
            self.shell.say(f"{name}: previous version restarted ({detail})")
            if not ok:
                failures.append(f"{name}: previous version does not start either ({detail})")
        except DeployError as error:
            failures.append(_describe(name, error, "could not restart the previous version: "))

    def _rollback(self, name: str, commit: str, restart: bool, failures: list[str]) -> None:
        self.shell.say(f"{name}: rolling back to {commit[:8]}")
        try:
            self.stop_one(name)
            gitops.restore(self.shell, self.host.service_dir(name), commit)
            self.install(name)
            env = self.write_env(name)
            if restart:
                self.start_one(name, env)
                ok, detail = self.wait_healthy(name)
                self.shell.say(f"{name}: rollback {'healthy' if ok else 'NOT healthy: ' + detail}")
                if not ok:
                    failures.append(f"{name}: rollback is not healthy either ({detail})")
        except DeployError as error:
            failures.append(f"{name}: rollback failed: {error}")

    def _library_problems(self, selected: list[str]) -> tuple[list[str], list[str]]:
        needed = {library for name in selected for library in self.host.services[name].spec.libraries}
        return installer.check_libraries(self.registry, needed)

    def preflight(self, selected: list[str]) -> None:
        errors, warnings = validate_host(self.host)
        library_errors, library_warnings = self._library_problems(selected)
        errors += library_errors + installer.check_python(self.shell, self.host, selected)
        warnings += library_warnings
        for warning in warnings:
            self.shell.say(f"warning: {warning}")
        if errors:
            raise DeployError("invalid host file:\n  " + "\n  ".join(errors))

    # ------------------------------------------------------------------ inspect

    def validate(self, names: list[str] | None) -> tuple[list[str], list[str]]:
        errors, warnings = validate_host(self.host)
        selected = self.select(names)
        library_errors, library_warnings = self._library_problems(selected)
        errors += library_errors + installer.check_python(self.shell, self.host, selected)
        warnings += library_warnings
        for name in selected:
            resolved = self.resolve(name)
            errors += resolved.errors
            warnings += resolved.warnings
        return errors, warnings

    def plan_lines(self, names: list[str] | None) -> list[str]:
        lines = [
            f"host {self.host.name}: {self.host.os_family}{' (Raspberry Pi)' if self.host.is_raspberry else ''}, "
            f"workdir {self.host.workdir}, bind {self.host.bind}"
        ]
        for name in self.select(names):
            instance = self.host.services[name]
            lines.append(f"  {name:<10} {instance.runtime:<6} port {instance.port}  {instance.spec.git} @ {instance.branch}")
            resolved = self.resolve(name)
            for key, value in sorted(resolved.values.items()):
                lines.append(f"      {key}={mask(key, value)}   [{resolved.layer_of[key]}]")
        for name, url in self.host.remote.items():
            lines.append(f"  remote {name:<10} {url}")
        return lines

    def status(self, names: list[str] | None, include_remote: bool) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        for name in self.select(names):
            instance = self.host.services[name]
            running = runtime.is_running(self.shell, self.host, name)
            repo = self.host.service_dir(name)
            code = f"{gitops.current_branch(self.shell, repo) or '-'}@{(gitops.current_commit(self.shell, repo) or '-')[:8]}"
            if running:
                ok, detail = health.check(self.base_url(name), instance.spec)
                rows.append((name, "running" if ok else "UNHEALTHY", f"{detail}; {code}; {instance.runtime}"))
            else:
                rows.append((name, "stopped", f"{code}; {instance.runtime}"))
        if include_remote:
            for name, url in self.host.remote.items():
                spec = self.registry.services.get(name)
                if spec:
                    ok, detail = health.check(url, spec)
                    rows.append((f"{name} (remote)", "running" if ok else "UNREACHABLE", f"{detail}; {url}"))
        return rows


def _describe(name: str, error: Exception, prefix: str = "") -> str:
    """``name: message`` unless the message already starts with the service name."""
    text = str(error)
    return f"{prefix}{text}" if text.startswith(f"{name}:") and not prefix else f"{name}: {prefix}{text}"
