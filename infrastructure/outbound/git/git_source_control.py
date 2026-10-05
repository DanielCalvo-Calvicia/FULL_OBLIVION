"""Adapter of SourceControlPort: a service's code from GitHub at a chosen branch, tag or commit, through the ``git`` command."""

from __future__ import annotations

from pathlib import Path

from application.ports.outbound.shell_port import ShellPort
from application.ports.outbound.source_control_port import SourceControlPort
from domain.errors import DeployError
from infrastructure.outbound.env.dotenv_files import GENERATED_MARK


class GitSourceControl(SourceControlPort):
    def __init__(self, shell: ShellPort) -> None:
        self._shell = shell

    def _git(self, repo: Path, *args: str, check: bool = True, mutating: bool = True):
        return self._shell.run(["git", "-C", repo, *args], check=check, capture=True, mutating=mutating)

    @staticmethod
    def is_repo(path: Path) -> bool:
        return (path / ".git").exists()

    def current_commit(self, repo: Path) -> str | None:
        if not self.is_repo(repo):
            return None
        result = self._git(repo, "rev-parse", "HEAD", check=False, mutating=False)
        return result.stdout.strip() or None if result.returncode == 0 else None

    def current_branch(self, repo: Path) -> str | None:
        if not self.is_repo(repo):
            return None
        result = self._git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False, mutating=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def status_header(self, repo: Path) -> str:
        lines = self._git(repo, "status", "-sb", check=False, mutating=False).stdout.splitlines()
        return lines[0] if lines else ""

    def remote_has_ref(self, url: str, ref: str) -> tuple[bool | None, str]:
        result = self._shell.run(
            ["git", "ls-remote", "--heads", "--tags", url, ref, f"{ref}^{{}}"], check=False, capture=True, mutating=False
        )
        if result.returncode != 0:
            return None, (result.stderr or "").strip()[-200:]
        return bool(result.stdout.strip()), ""

    def is_dirty(self, repo: Path) -> bool:
        """True when a tracked file was really edited. Rewritten bytecode and a generated ``.env`` do not count (they are
        restored on a real run, and a dry run, which restores nothing, must not report them either)."""
        changed = self._git(repo, "diff", "--name-only", "-z", "HEAD", check=False, mutating=False).stdout
        return any(path and not self._is_generated(repo, path) for path in changed.split("\0"))

    @staticmethod
    def _is_generated_env(repo: Path, relative: str) -> bool:
        """The ``.env`` this tool wrote (the stepper repo tracks a ``.env``, which the deploy overwrites)."""
        if relative != ".env":
            return False
        try:
            return (repo / relative).read_text(encoding="utf-8", errors="ignore").startswith(GENERATED_MARK)
        except OSError:
            return False

    def _is_generated(self, repo: Path, relative: str) -> bool:
        return relative.endswith(".pyc") or "__pycache__/" in relative or self._is_generated_env(repo, relative)

    def restore_generated(self, repo: Path) -> None:
        """Files that running or deploying a service rewrites are not local edits: tracked ``__pycache__/*.pyc``
        and a tracked ``.env`` that this tool generated. They are put back, so real edits stay the only thing refused."""
        out = self._git(repo, "ls-files", "-m", "-z", check=False, mutating=False).stdout
        generated = [p for p in out.split("\0") if p and self._is_generated(repo, p)]
        if generated and not self._shell.dry_run:
            self._git(repo, "checkout", "--quiet", "--", *generated)

    def _has_remote_branch(self, repo: Path, ref: str) -> bool:
        return self._git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{ref}", check=False, mutating=False).returncode == 0

    def sync(self, url: str, repo: Path, ref: str, *, force: bool = False) -> tuple[str | None, str | None]:
        """Clone if needed, then put the working tree exactly on ``ref`` of the remote.

        ``ref`` may be a branch (followed: the tree becomes the branch's latest commit), a tag or a commit.
        Returns ``(previous commit, new commit)``. A modified working tree is refused unless ``force``.
        """
        shell = self._shell
        previous = self.current_commit(repo)
        if not self.is_repo(repo):
            if not shell.dry_run:
                repo.parent.mkdir(parents=True, exist_ok=True)
            shell.run(["git", "clone", "--quiet", url, repo])
        else:
            remote = self._git(repo, "remote", "get-url", "origin", check=False, mutating=False).stdout.strip()
            if remote and remote != url:
                shell.say(f"note: {repo.name} origin is {remote}, the catalogue says {url}; keeping origin")
            self.restore_generated(repo)
            if self.is_dirty(repo) and not force:
                raise DeployError(
                    f"{repo} has local modifications; commit or discard them, or pass --force to overwrite"
                )
            self._git(repo, "fetch", "--quiet", "--prune", "--tags", "origin")

        if shell.dry_run and not self.is_repo(repo):
            shell.say(f"[dry-run] git -C {repo} checkout {ref}")
            return previous, None
        if self._has_remote_branch(repo, ref):
            self._git(repo, "checkout", "--quiet", *(["--force"] if force else []), "-B", ref, f"origin/{ref}")
        else:
            result = self._git(repo, "checkout", "--quiet", "--detach", ref, check=False)
            if result.returncode != 0:
                raise DeployError(
                    f"{repo.name}: {ref!r} is not a branch, tag or commit of {url}\n{(result.stderr or '').strip()}"
                )
        return previous, self.current_commit(repo)

    def restore(self, repo: Path, commit: str) -> None:
        """Return to a previously deployed commit (rollback)."""
        self._git(repo, "checkout", "--quiet", "--force", "--detach", commit)
