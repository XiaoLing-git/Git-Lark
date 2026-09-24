"""Safe installation and removal of repository post-commit wrappers."""

import os
from pathlib import Path

from .git import hooks_directory

_MARKER = "# git-lark managed post-commit hook v1"
_BACKUP_SUFFIX = ".git-lark-backup"


def hook_path(repo: Path) -> Path:
    """Return the post-commit hook selected by Git."""
    return hooks_directory(repo) / "post-commit"


def backup_path(repo: Path) -> Path:
    """Return the adjacent path reserved for a pre-existing hook."""
    path = hook_path(repo)
    return path.with_name(path.name + _BACKUP_SUFFIX)


def is_installed(repo: Path) -> bool:
    """Return whether the current post-commit hook is managed by git-lark."""
    path = hook_path(repo)
    if not path.exists():
        return False
    try:
        first_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:3]
    except OSError:
        return False
    return _MARKER in first_lines


def install_hook(repo: Path) -> Path:
    """Install a wrapper, preserving and chaining an unrelated existing hook."""
    path = hook_path(repo)
    backup = backup_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not is_installed(repo):
        if backup.exists():
            raise FileExistsError(f"Cannot preserve existing hook because backup already exists: {backup}")
        path.replace(backup)
    content = (
        "#!/bin/sh\n"
        f"{_MARKER}\n"
        'BACKUP="$0.git-lark-backup"\n'
        'if [ -f "$BACKUP" ]; then\n'
        '  "$BACKUP" "$@" || true\n'
        "fi\n"
        'git lark hook post-commit --repo "$(git rev-parse --show-toplevel)" >/dev/null 2>&1 || true\n'
        "exit 0\n"
    )
    path.write_text(content, encoding="utf-8", newline="\n")
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        if os.name != "nt":
            raise
    return path


def uninstall_hook(repo: Path) -> bool:
    """Remove the managed wrapper and restore the previously chained hook."""
    path = hook_path(repo)
    backup = backup_path(repo)
    if not is_installed(repo):
        return False
    path.unlink()
    if backup.exists():
        backup.replace(path)
    return True
