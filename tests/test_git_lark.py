"""Regression tests for configuration, hooks, Git metadata, and notification state."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_lark.config import ConfigStore
from git_lark.git import collect_commit_info, set_local_config
from git_lark.hooks import backup_path, hook_path, install_hook, is_installed, uninstall_hook
from git_lark.models import ChangedFile, CommitInfo, Profile
from git_lark.notify import build_notification_messages, notify_head
from git_lark.secrets import SecretStore


def _git(repo: Path, *args: str) -> None:
    """Run one Git command for an isolated test repository."""
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _create_repository(path: Path) -> Path:
    """Create an isolated repository with one deterministic commit."""
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")
    (path / "example.txt").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "example.txt")
    _git(path, "commit", "-m", "initial commit")
    return path


class ConfigAndSecretTest(unittest.TestCase):
    """Verify profile metadata and secret values remain independently persistent."""

    def test_profile_and_secret_round_trip(self) -> None:
        """A stored profile should refer to a decryptable secret without embedding it."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ConfigStore(root)
            secrets = SecretStore(root)
            profile = Profile(
                "development",
                "feishu_webhook",
                {},
                {"webhook_url": "profile:development:webhook_url"},
            )

            config.save_profile(profile)
            secrets.set("profile:development:webhook_url", "https://example.invalid/hook")

            self.assertEqual(config.get_profile("development"), profile)
            self.assertEqual(secrets.get("profile:development:webhook_url"), "https://example.invalid/hook")
            self.assertNotIn("example.invalid", config.path.read_text(encoding="utf-8"))


class HookManagementTest(unittest.TestCase):
    """Verify managed hooks preserve and restore unrelated repository hooks."""

    def test_install_chains_existing_hook_and_uninstall_restores_it(self) -> None:
        """An existing post-commit file must survive a complete install/uninstall cycle."""
        with tempfile.TemporaryDirectory() as directory:
            repo = _create_repository(Path(directory) / "repo")
            original = "#!/bin/sh\necho original\n"
            current_hook = hook_path(repo)
            current_hook.write_text(original, encoding="utf-8", newline="\n")

            install_hook(repo)

            self.assertTrue(is_installed(repo))
            self.assertEqual(backup_path(repo).read_text(encoding="utf-8"), original)
            self.assertIn("git lark hook post-commit", current_hook.read_text(encoding="utf-8"))

            self.assertTrue(uninstall_hook(repo))
            self.assertFalse(backup_path(repo).exists())
            self.assertEqual(current_hook.read_text(encoding="utf-8"), original)


class GitAndNotificationTest(unittest.TestCase):
    """Verify commit collection, rendering, delivery, and per-SHA deduplication."""

    def test_collect_commit_info_reads_root_commit(self) -> None:
        """Root commits should expose metadata and their newly added files."""
        with tempfile.TemporaryDirectory() as directory:
            repo = _create_repository(Path(directory) / "repo")

            info = collect_commit_info(repo)

            self.assertEqual(info.repository, "repo")
            self.assertEqual(info.author, "Test User")
            self.assertEqual(info.message, "initial commit")
            self.assertEqual(info.files, (ChangedFile("A", "example.txt"),))

    def test_message_splits_file_lists_without_losing_header(self) -> None:
        """Small limits should create multiple complete message pages."""
        info = CommitInfo(
            repository="demo",
            branch="main",
            sha="a" * 40,
            short_sha="a" * 8,
            author="Developer",
            authored_at="2026-09-24T10:00:00+08:00",
            message="feat: example",
            files=tuple(ChangedFile("M", f"folder/file-{index}.txt") for index in range(8)),
        )

        messages = build_notification_messages(info, max_length=190)

        self.assertGreater(len(messages), 1)
        self.assertTrue(all("【Git 提交通知】" in message for message in messages))
        self.assertTrue(all(f"第 {index}/{len(messages)} 条" in message for index, message in enumerate(messages, 1)))

    def test_notify_head_sends_once_per_profile_and_sha(self) -> None:
        """A successful delivery should suppress a duplicate notification for the same HEAD."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _create_repository(root / "repo")
            config = ConfigStore(root / "config")
            secrets = SecretStore(root / "config")
            config.save_profile(Profile("development", "feishu_webhook"))
            set_local_config(repo, "git-lark.profile", "development")
            set_local_config(repo, "git-lark.enabled", "true")

            with patch("git_lark.notify.send_message") as send:
                notify_head(repo, config, secrets)
                notify_head(repo, config, secrets)

            send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
