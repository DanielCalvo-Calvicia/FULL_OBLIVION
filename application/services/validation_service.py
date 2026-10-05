"""Checks before anything changes: the layout wiring, the libraries, the Python, every required setting."""

from __future__ import annotations

import json

from application.ports.outbound.installer_port import InstallerPort
from application.services.environment_service import EnvironmentService
from domain.entities.catalogue import Catalogue
from domain.entities.host import Host
from domain.errors import DeployError
from domain.rules.host_validation import validate_host


class ValidationService:
    def __init__(self, host: Host, catalogue: Catalogue, installer: InstallerPort, env: EnvironmentService) -> None:
        self._host = host
        self._catalogue = catalogue
        self._installer = installer
        self._env = env

    def _library_problems(self, selected: list[str]) -> tuple[list[str], list[str]]:
        needed = {library for name in selected for library in self._host.services[name].spec.libraries}
        return self._installer.check_libraries(self._catalogue, needed)

    def preflight(self, selected: list[str]) -> list[str]:
        """Raise on errors, return the warnings. Run before a deploy or an update touches anything."""
        errors, warnings = validate_host(self._host)
        library_errors, library_warnings = self._library_problems(selected)
        errors += library_errors + self._installer.check_python(self._host, selected)
        warnings += library_warnings
        if errors:
            raise DeployError("invalid configuration:\n  " + "\n  ".join(errors))
        return warnings

    def validate(self, selected: list[str]) -> tuple[list[str], list[str]]:
        errors, warnings = validate_host(self._host)
        library_errors, library_warnings = self._library_problems(selected)
        errors += library_errors + self._installer.check_python(self._host, selected)
        warnings += library_warnings
        for name in selected:
            resolved = self._env.resolve(name)
            errors += resolved.errors
            warnings += resolved.warnings
        errors += self.stepper_problems()
        return errors, warnings

    def stepper_problems(self) -> list[str]:
        """A stepper that cannot start, or arms Brain would silently never move. Only checkable for what runs here.

        Values come from the service's own ``.env.example`` (after the first fetch) plus the settings files.
        """
        if "stepper" not in self._host.services:
            return []
        raw = self._env.resolve("stepper").values.get("STEPPER_CONFIGS", "")
        if not raw:
            return []  # nothing fetched yet: the service falls back to its built-in default
        try:
            configs = json.loads(raw)
            if not isinstance(configs, dict) or not configs:
                raise ValueError("expected a JSON object with one entry per stepper")
            for ident, pins in configs.items():
                missing = [pin for pin in ("step", "dir", "en") if not isinstance(pins.get(pin), int)]
                if missing:
                    raise ValueError(f"{ident} needs integer BCM pins for {', '.join(missing)}")
        except (ValueError, AttributeError) as error:
            return [f"stepper: STEPPER_CONFIGS is invalid ({error}); the stepper would not start"]
        problems = []
        if "brain" in self._host.services:
            brain = self._env.resolve("brain").values
            for variable in ("STEPPER_LEFT_ARM_STEPPER_ID", "STEPPER_RIGHT_ARM_STEPPER_ID"):
                ident = brain.get(variable)
                if ident and ident not in configs:
                    problems.append(
                        f"brain: {variable}={ident} is not a stepper of this machine's STEPPER_CONFIGS "
                        f"({', '.join(configs)}); that arm would never move"
                    )
        return problems
