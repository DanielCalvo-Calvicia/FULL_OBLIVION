"""The deployment operations on one machine: install, update (with rollback), start, stop, status, plan, validate."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from application.dtos.options import Options
from application.ports.outbound.env_files_port import EnvFilesPort
from application.ports.outbound.health_port import HealthPort
from application.ports.outbound.installer_port import InstallerPort
from application.ports.outbound.runtime_port import RuntimePort
from application.ports.outbound.shell_port import ShellPort
from application.ports.outbound.source_control_port import SourceControlPort
from application.ports.outbound.state_port import StatePort
from application.services.environment_service import EnvironmentService
from application.services.validation_service import ValidationService
from domain.entities.catalogue import Catalogue
from domain.entities.environment import ResolvedEnv
from domain.entities.host import Host
from domain.errors import DeployError
from domain.rules.env_names import mask

REMOTE_POLL_SECONDS = 3.0


class DeploymentService:
    def __init__(
        self,
        host: Host,
        catalogue: Catalogue,
        options: Options,
        *,
        shell: ShellPort,
        git: SourceControlPort,
        installer: InstallerPort,
        runtime: RuntimePort,
        health: HealthPort,
        state: StatePort,
        env_files: EnvFilesPort,
    ) -> None:
        self.host = host
        self.catalogue = catalogue
        self.options = options
        self.shell = shell
        self.state = state
        self._git = git
        self._installer = installer
        self._runtime = runtime
        self._health = health
        self.environment = EnvironmentService(host, env_files, runtime, shell)
        self.validation = ValidationService(host, catalogue, installer, self.environment)

    # ------------------------------------------------------------------ selection

    def select(self, names: list[str] | None) -> list[str]:
        """Local services to act on, dependencies (services others consume) first."""
        wanted = names or list(self.host.services)
        for name in wanted:
            if name not in self.host.services:
                raise DeployError(f"{name!r} is not deployed on machine {self.host.name!r} (has: {', '.join(self.host.services)})")
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
        return self.environment.resolve(name)

    def write_env(self, name: str) -> dict[str, str]:
        return self.environment.write(name)

    # ------------------------------------------------------------------ steps of a deploy

    def prepare(self, name: str) -> None:
        """Run the service's ``prepare`` script (config/catalogue.toml) with its own python, after its .env is written.

        For what cannot ship in git or pip, e.g. tts' Piper voice (about 60 MB). It sees the final settings, so a
        voice chosen in the settings files is the one fetched. A failure is a warning: the service has a fallback and a
        machine that is offline during a deploy must still come up. Docker images run it while building instead.
        """
        instance = self.host.services[name]
        if instance.runtime != "native" or not instance.spec.prepare:
            return
        python = self.shell.python_of(self.host.venv_dir(name))
        result = self.shell.run([python, *instance.spec.prepare], cwd=self.host.service_dir(name), check=False)
        if result.returncode != 0:
            self.shell.say(f"warning: {name}: `{' '.join(instance.spec.prepare)}` failed ({result.returncode}); see above")

    def fetch_code(self, name: str) -> tuple[str | None, str | None]:
        instance = self.host.services[name]
        self.shell.say(f"{name}: code {instance.spec.git} @ {instance.branch}")
        return self._git.sync(instance.spec.git, self.host.service_dir(name), instance.branch, force=self.options.force)

    def install(self, name: str) -> None:
        instance = self.host.services[name]
        if instance.runtime == "docker":
            self._installer.build_image(self.host, self.catalogue, name)
            return
        previous = self.state.get(name).get("fingerprint")
        fingerprint, warnings = self._installer.install_native(
            self.host, self.catalogue, name, previous_fingerprint=previous, system_deps=self.options.system_deps
        )
        for warning in warnings:
            self.shell.say(f"warning: {warning}")
        if not self.shell.dry_run:
            self.state.update(name, fingerprint=fingerprint)

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
            and target not in spec.optional_consumes and target in self.catalogue.services
        }
        if not pending or self.shell.dry_run or self.options.remote_wait <= 0:
            return
        self.shell.say(f"{name}: waiting up to {self.options.remote_wait:g}s for {', '.join(pending)} on other machines")
        deadline = time.monotonic() + self.options.remote_wait
        while True:
            # concurrently: an unreachable host takes seconds to fail, and one pass must not outlast the deadline
            with ThreadPoolExecutor(max_workers=len(pending)) as pool:
                results = {t: pool.submit(self._health.check, url, self.catalogue.services[t]) for t, url in pending.items()}
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
        self._runtime.start(self.host, name, env, self.environment.target(name))

    def stop_one(self, name: str) -> None:
        self._runtime.stop(self.host, name)

    def base_url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.host.services[name].port}"

    def _record(self, name: str, **fields: object) -> None:
        if not self.shell.dry_run:
            self.state.update(name, **fields)

    def wait_healthy(self, name: str) -> tuple[bool, str]:
        if self.shell.dry_run or self.options.skip_health:
            return True, "not checked"
        return self._health.wait(self.base_url(name), self.host.services[name].spec, self.options.health_timeout)

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

    def preflight(self, selected: list[str]) -> None:
        for warning in self.validation.preflight(selected):
            self.shell.say(f"warning: {warning}")

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
                self.prepare(name)
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
            was_running = self._runtime.is_running(self.host, name)
            before = self._git.current_commit(repo)
            code_replaced = False
            try:
                self.stop_one(name)
                _, after = self.fetch_code(name)
                code_replaced = after != before
                self.install(name)
                env = self.write_env(name)
                self.prepare(name)
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
            self._git.restore(self.host.service_dir(name), commit)
            self.install(name)
            env = self.write_env(name)
            self.prepare(name)
            if restart:
                self.start_one(name, env)
                ok, detail = self.wait_healthy(name)
                self.shell.say(f"{name}: rollback {'healthy' if ok else 'NOT healthy: ' + detail}")
                if not ok:
                    failures.append(f"{name}: rollback is not healthy either ({detail})")
        except DeployError as error:
            failures.append(f"{name}: rollback failed: {error}")

    # ------------------------------------------------------------------ inspect

    def validate(self, names: list[str] | None) -> tuple[list[str], list[str]]:
        return self.validation.validate(self.select(names))

    def plan_lines(self, names: list[str] | None) -> list[str]:
        lines = [
            f"machine {self.host.name}: {self.host.os_family}{' (Raspberry Pi)' if self.host.is_raspberry else ''}, "
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
            running = self._runtime.is_running(self.host, name)
            repo = self.host.service_dir(name)
            code = f"{self._git.current_branch(repo) or '-'}@{(self._git.current_commit(repo) or '-')[:8]}"
            if running:
                ok, detail = self._health.check(self.base_url(name), instance.spec)
                rows.append((name, "running" if ok else "UNHEALTHY", f"{detail}; {code}; {instance.runtime}"))
            else:
                rows.append((name, "stopped", f"{code}; {instance.runtime}"))
        if include_remote:
            for name, url in self.host.remote.items():
                spec = self.catalogue.services.get(name)
                if spec:
                    ok, detail = self._health.check(url, spec)
                    rows.append((f"{name} (remote)", "running" if ok else "UNREACHABLE", f"{detail}; {url}"))
        return rows


def _describe(name: str, error: Exception, prefix: str = "") -> str:
    """``name: message`` unless the message already starts with the service name."""
    text = str(error)
    return f"{prefix}{text}" if text.startswith(f"{name}:") and not prefix else f"{name}: {prefix}{text}"
