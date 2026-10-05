"""Where everything you edit lives: one ``config/`` folder."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # infrastructure/config/paths.py -> the repository root
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"


@dataclass(frozen=True)
class ConfigPaths:
    """The files of one configuration. ``--config DIR`` points the tool at another folder with the same shape."""

    root: Path = field(default=DEFAULT_CONFIG_DIR)

    @property
    def base_dir(self) -> Path:
        """Relative paths in the catalogue (the shared libraries) are relative to this: the repository root."""
        return self.root.parent

    @property
    def catalogue(self) -> Path:
        return self.root / "catalogue.toml"

    @property
    def robot(self) -> Path:
        return self.root / "robot.toml"

    @property
    def layouts(self) -> Path:
        return self.root / "layouts"

    @property
    def services(self) -> Path:
        return self.root / "services"

    @property
    def machines(self) -> Path:
        return self.root / "machines"

    @property
    def local(self) -> Path:
        return self.root / "local"

    def layout_file(self, name: str) -> Path:
        return self.layouts / f"{name}.toml"

    def machine_file(self, name: str) -> Path:
        return self.machines / f"{name}.toml"

    def label(self, path: Path) -> str:
        """``config/services/brain.toml``: a file as the messages name it (the path you would open to change it)."""
        try:
            return f"{self.root.name}/{path.resolve().relative_to(self.root.resolve()).as_posix()}"
        except ValueError:
            return str(path)
