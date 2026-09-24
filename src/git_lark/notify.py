"""Commit notification rendering, delivery, deduplication, and failure logging."""

import logging
from pathlib import Path

from .config import ConfigStore
from .git import collect_commit_info, get_local_config, git_directory, repository_root
from .models import CommitInfo, Profile
from .providers import send_message
from .secrets import SecretStore

_MAX_MESSAGE_LENGTH = 3500


def build_notification_messages(info: CommitInfo, max_length: int = _MAX_MESSAGE_LENGTH) -> tuple[str, ...]:
    """Render commit details and split large changed-file lists into safe messages."""
    header = (
        "【Git 提交通知】\n"
        f"仓库：{info.repository}\n"
        f"分支：{info.branch}\n"
        f"提交：{info.short_sha}\n"
        f"作者：{info.author}\n"
        f"时间：{info.authored_at}\n\n"
        f"{info.message}\n\n"
        f"涉及文件（{len(info.files)}）："
    )
    file_lines = [item.display() for item in info.files] or ["（无文件变更）"]
    if len(header) + len(file_lines[0]) + 20 > max_length:
        raise ValueError("Notification header or one changed-file path is too long")
    chunks: list[list[str]] = [[]]
    for line in file_lines:
        candidate = "\n".join([*chunks[-1], line])
        if chunks[-1] and len(header) + len(candidate) + 20 > max_length:
            chunks.append([line])
        else:
            chunks[-1].append(line)
    total = len(chunks)
    return tuple(
        f"{header}{f'（第 {index}/{total} 条）' if total > 1 else ''}\n" + "\n".join(chunk)
        for index, chunk in enumerate(chunks, start=1)
    )


def selected_profile(repo: Path, config: ConfigStore) -> Profile:
    """Resolve the profile selected in repository-local Git configuration."""
    profile_name = get_local_config(repo, "git-lark.profile")
    if not profile_name:
        raise ValueError("No profile selected; run: git lark init --profile NAME")
    return config.get_profile(profile_name)


def _state_directory(repo: Path) -> Path:
    """Return the repository-local notification state directory."""
    return git_directory(repo) / "git-lark"


def _logger(repo: Path) -> logging.Logger:
    """Create a per-call file logger under Git metadata."""
    directory = _state_directory(repo)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"git_lark.{directory}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in tuple(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = logging.FileHandler(directory / "notify.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _close_logger(logger: logging.Logger) -> None:
    """Close handlers so Windows can release log files immediately."""
    for handler in tuple(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def notify_head(
    repo: Path,
    config: ConfigStore | None = None,
    secrets: SecretStore | None = None,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    """Notify the current HEAD and return success plus rendered messages."""
    root = repository_root(repo)
    if (get_local_config(root, "git-lark.enabled") or "true").lower() in {"false", "0", "no", "off"}:
        return True, ()
    config = config or ConfigStore()
    secrets = secrets or SecretStore(config.directory)
    profile = selected_profile(root, config)
    info = collect_commit_info(root)
    messages = build_notification_messages(info)
    state_directory = _state_directory(root)
    state_file = state_directory / f"last-successful-{profile.name}.sha"
    if not force and state_file.exists() and state_file.read_text(encoding="utf-8").strip() == info.sha:
        return True, messages
    if dry_run:
        return True, messages
    for message in messages:
        send_message(profile, message, secrets)
    state_directory.mkdir(parents=True, exist_ok=True)
    state_file.write_text(info.sha + "\n", encoding="utf-8")
    return True, messages


def notify_head_fail_open(repo: Path) -> bool:
    """Notify HEAD while logging every error and always allowing Git to continue."""
    logger: logging.Logger | None = None
    try:
        logger = _logger(repo)
        notify_head(repo)
        return True
    except Exception:
        if logger is not None:
            logger.exception("Git commit notification failed")
        return False
    finally:
        if logger is not None:
            _close_logger(logger)
