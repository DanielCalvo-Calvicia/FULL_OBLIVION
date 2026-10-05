"""Getting a service's code at a chosen branch, tag or commit, and asking where a checkout stands."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SourceControlPort(Protocol):
    def sync(self, url: str, repo: Path, ref: str, *, force: bool = False) -> tuple[str | None, str | None]:
        """Clone if needed, then put the working tree exactly on ``ref`` of the remote.

        Returns ``(previous commit, new commit)``. A modified working tree is refused unless ``force``.
        """
        ...

    def restore(self, repo: Path, commit: str) -> None:
        """Return to a previously deployed commit (rollback)."""
        ...

    def current_commit(self, repo: Path) -> str | None: ...

    def current_branch(self, repo: Path) -> str | None: ...

    def status_header(self, repo: Path) -> str:
        """The first line of ``git status -sb``: the branch and how far it is ahead of or behind its remote."""
        ...

    def remote_has_ref(self, url: str, ref: str) -> tuple[bool | None, str]:
        """``(exists, detail)``: whether ``ref`` is a branch or tag of the remote; ``None`` when it cannot be reached."""
        ...
