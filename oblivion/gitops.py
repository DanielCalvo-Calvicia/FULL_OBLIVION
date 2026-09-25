"""Getting a service's code from GitHub at a chosen branch, tag or commit."""

from __future__ import annotations

from pathlib import Path

from .config import DeployError
from .shell import Shell


def _git(shell: Shell, repo: Path, *args: str, check: bool = True, mutating: bool = True):
    return shell.run(["git", "-C", repo, *args], check=check, capture=True, mutating=mutating)


def is_repo(path: Path) -> bool:
    return (path / ".git").exists()


def current_commit(shell: Shell, repo: Path) -> str | None:
    if not is_repo(repo):
        return None
    result = _git(shell, repo, "rev-parse", "HEAD", check=False, mutating=False)
    return result.stdout.strip() or None if result.returncode == 0 else None


def current_branch(shell: Shell, repo: Path) -> str | None:
    if not is_repo(repo):
        return None
    result = _git(shell, repo, "rev-parse", "--abbrev-ref", "HEAD", check=False, mutating=False)
    return result.stdout.strip() if result.returncode == 0 else None


def is_dirty(shell: Shell, repo: Path) -> bool:
    result = _git(shell, repo, "status", "--porcelain", "--untracked-files=no", check=False, mutating=False)
    return bool(result.stdout.strip())


def restore_bytecode(shell: Shell, repo: Path) -> None:
    """Some service repos track ``__pycache__/*.pyc``; running them rewrites those files. That is not a local edit."""
    out = _git(shell, repo, "ls-files", "-m", "-z", check=False, mutating=False).stdout
    cached = [p for p in out.split("\0") if p.endswith(".pyc") or "__pycache__/" in p]
    if cached and not shell.dry_run:
        _git(shell, repo, "checkout", "--quiet", "--", *cached)


def _has_remote_branch(shell: Shell, repo: Path, ref: str) -> bool:
    return _git(shell, repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{ref}", check=False, mutating=False).returncode == 0


def sync(shell: Shell, url: str, repo: Path, ref: str, *, force: bool = False) -> tuple[str | None, str | None]:
    """Clone if needed, then put the working tree exactly on ``ref`` of the remote.

    ``ref`` may be a branch (followed: the tree becomes the branch's latest commit), a tag or a commit.
    Returns ``(previous commit, new commit)``. A modified working tree is refused unless ``force``.
    """
    previous = current_commit(shell, repo)
    if not is_repo(repo):
        if not shell.dry_run:
            repo.parent.mkdir(parents=True, exist_ok=True)
        shell.run(["git", "clone", "--quiet", url, repo])
    else:
        remote = _git(shell, repo, "remote", "get-url", "origin", check=False, mutating=False).stdout.strip()
        if remote and remote != url:
            shell.say(f"note: {repo.name} origin is {remote}, registry says {url}; keeping origin")
        restore_bytecode(shell, repo)
        if is_dirty(shell, repo) and not force:
            raise DeployError(
                f"{repo} has local modifications; commit or discard them, or pass --force to overwrite"
            )
        _git(shell, repo, "fetch", "--quiet", "--prune", "--tags", "origin")

    if shell.dry_run and not is_repo(repo):
        shell.say(f"[dry-run] git -C {repo} checkout {ref}")
        return previous, None
    if _has_remote_branch(shell, repo, ref):
        _git(shell, repo, "checkout", "--quiet", *(["--force"] if force else []), "-B", ref, f"origin/{ref}")
    else:
        result = _git(shell, repo, "checkout", "--quiet", "--detach", ref, check=False)
        if result.returncode != 0:
            raise DeployError(
                f"{repo.name}: {ref!r} is not a branch, tag or commit of {url}\n{(result.stderr or '').strip()}"
            )
    return previous, current_commit(shell, repo)


def restore(shell: Shell, repo: Path, commit: str) -> None:
    """Return to a previously deployed commit (rollback)."""
    _git(shell, repo, "checkout", "--quiet", "--force", "--detach", commit)
