"""Small, explicit wrappers around Git commands."""

import subprocess
from pathlib import Path

from .models import ChangedFile, CommitInfo


class GitError(RuntimeError):
    """Report a failed Git command with its stderr output."""


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    """Run Git in a repository and capture raw output for robust path parsing."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(error or f"git {' '.join(args)} failed with exit code {result.returncode}")
    return result


def _decode(value: bytes) -> str:
    """Decode Git's conventional UTF-8 output while preserving malformed positions."""
    return value.decode("utf-8", errors="replace")


def repository_root(repo: Path) -> Path:
    """Resolve the top-level worktree directory."""
    output = _decode(run_git(repo, "rev-parse", "--show-toplevel").stdout).strip()
    return Path(output).resolve()


def git_directory(repo: Path) -> Path:
    """Resolve the actual Git metadata directory, including worktree layouts."""
    root = repository_root(repo)
    output = _decode(run_git(root, "rev-parse", "--git-dir").stdout).strip()
    path = Path(output)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def hooks_directory(repo: Path) -> Path:
    """Resolve the hooks directory selected by Git for this repository."""
    root = repository_root(repo)
    output = _decode(run_git(root, "rev-parse", "--git-path", "hooks").stdout).strip()
    path = Path(output)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def get_local_config(repo: Path, key: str) -> str | None:
    """Read one repository-local Git configuration value."""
    result = run_git(repo, "config", "--local", "--get", key, check=False)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise GitError(_decode(result.stderr).strip())
    return _decode(result.stdout).strip()


def set_local_config(repo: Path, key: str, value: str) -> None:
    """Set one repository-local Git configuration value."""
    run_git(repo, "config", "--local", key, value)


def unset_local_config(repo: Path, key: str) -> None:
    """Remove all local values for a key without failing when it is absent."""
    run_git(repo, "config", "--local", "--unset-all", key, check=False)


def _parse_changed_files(output: bytes) -> tuple[ChangedFile, ...]:
    """Parse NUL-delimited name-status output, including rename and copy pairs."""
    fields = [_decode(field) for field in output.split(b"\0") if field]
    files: list[ChangedFile] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if status.startswith(("R", "C")):
            if index + 1 >= len(fields):
                raise ValueError("Git rename or copy output is incomplete")
            files.append(ChangedFile(status, fields[index + 1], fields[index]))
            index += 2
            continue
        if index >= len(fields):
            raise ValueError("Git changed-file output is incomplete")
        files.append(ChangedFile(status, fields[index]))
        index += 1
    return tuple(files)


def _collect_changed_files(root: Path) -> tuple[ChangedFile, ...]:
    """Collect HEAD changes relative to its first parent, including root commits."""
    parent = run_git(root, "rev-parse", "--verify", "HEAD^1", check=False)
    if parent.returncode == 0:
        output = run_git(root, "diff", "--name-status", "-z", "-M", "HEAD^1", "HEAD").stdout
    else:
        output = run_git(
            root,
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-z",
            "-M",
            "HEAD",
        ).stdout
    return _parse_changed_files(output)


def collect_commit_info(repo: Path) -> CommitInfo:
    """Read notification data exclusively from the repository's current HEAD."""
    root = repository_root(repo)
    metadata = _decode(run_git(root, "log", "-1", "--format=%H%x00%h%x00%an%x00%aI%x00%B").stdout)
    sha, short_sha, author, authored_at, message = metadata.split("\0", 4)
    branch_result = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    branch = _decode(branch_result.stdout).strip() if branch_result.returncode == 0 else "DETACHED"
    return CommitInfo(
        repository=root.name,
        branch=branch,
        sha=sha,
        short_sha=short_sha,
        author=author,
        authored_at=authored_at,
        message=message.strip(),
        files=_collect_changed_files(root),
    )
