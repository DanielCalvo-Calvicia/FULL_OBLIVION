"""Getting a service's code from GitHub at a chosen branch, tag or commit."""

from __future__ import annotations

from pathlib import Path

from .config import DeployError
from .envfile import GENERATED_MARK
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
    """True when a tracked file was really edited. Rewritten bytecode and a generated ``.env`` do not count (they are
    restored on a real run, and a dry run, which restores nothing, must not report them either)."""
    changed = _git(shell, repo, "diff", "--name-only", "-z", "HEAD", check=False, mutating=False).stdout
    return any(path and not _is_generated(repo, path) for path in changed.split("\0"))


def _is_generated_env(repo: Path, relative: str) -> bool:
    """The ``.env`` this tool wrote (the stepper repo tracks a ``.env``, which the deploy overwrites)."""
    if relative != ".env":
        return False
    try:
        return (repo / relative).read_text(encoding="utf-8", errors="ignore").startswith(GENERATED_MARK)
    except OSError:
        return False


def _is_generated(repo: Path, relative: str) -> bool:
    return relative.endswith(".pyc") or "__pycache__/" in relative or _is_generated_env(repo, relative)


def restore_generated(shell: Shell, repo: Path) -> None:
    """Files that running or deploying a service rewrites are not local edits: tracked ``__pycache__/*.pyc``
    and a tracked ``.env`` that this tool generated. They are put back, so real edits stay the only thing refused."""
    out = _git(shell, repo, "ls-files", "-m", "-z", check=False, mutating=False).stdout
    generated = [p for p in out.split("\0") if p and _is_generated(repo, p)]
    if generated and not shell.dry_run:
        _git(shell, repo, "checkout", "--quiet", "--", *generated)


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
        restore_generated(shell, repo)
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
