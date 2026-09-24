"""Command-line interface exposed as both git-lark and git lark."""

import argparse
import getpass
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import ConfigStore
from .git import get_local_config, repository_root, set_local_config, unset_local_config
from .hooks import backup_path, hook_path, install_hook, is_installed, uninstall_hook
from .models import Profile
from .notify import notify_head, notify_head_fail_open, selected_profile
from .providers import send_message
from .secrets import SecretStore


def _repo(value: str | None) -> Path:
    """Resolve an optional repository argument and verify it with Git."""
    return repository_root(Path(value).resolve() if value else Path.cwd())


def _stores() -> tuple[ConfigStore, SecretStore]:
    """Construct stores that share the same user configuration directory."""
    config = ConfigStore()
    return config, SecretStore(config.directory)


def _profile_for_repo(repo: Path, config: ConfigStore, explicit_name: str | None = None) -> Profile:
    """Resolve an explicit profile or the profile selected by a repository."""
    if explicit_name:
        return config.get_profile(explicit_name)
    return selected_profile(repo, config)


def _add_webhook(args: argparse.Namespace) -> int:
    """Create or replace a Feishu webhook profile."""
    config, secrets = _stores()
    name = ConfigStore.validate_profile_name(args.name)
    webhook_url = args.url or getpass.getpass("Feishu webhook URL: ")
    if not webhook_url.startswith(("https://", "http://")):
        raise ValueError("Webhook URL must start with http:// or https://")
    secret_names = {"webhook_url": f"profile:{name}:webhook_url"}
    signing_secret = args.signing_secret
    if args.signed and not signing_secret:
        signing_secret = getpass.getpass("Feishu webhook signing secret: ")
    if signing_secret:
        secret_names["signing_secret"] = f"profile:{name}:signing_secret"
    profile = Profile(name, "feishu_webhook", {}, secret_names)
    config.save_profile(profile, overwrite=args.overwrite)
    secrets.set(secret_names["webhook_url"], webhook_url)
    if signing_secret:
        secrets.set(secret_names["signing_secret"], signing_secret)
    print(f"Saved webhook profile: {name}")
    return 0


def _add_app(args: argparse.Namespace) -> int:
    """Create or replace a Feishu enterprise application profile."""
    config, secrets = _stores()
    name = ConfigStore.validate_profile_name(args.name)
    app_secret = args.app_secret or getpass.getpass("Feishu app secret: ")
    if not app_secret:
        raise ValueError("App secret must not be empty")
    secret_name = f"profile:{name}:app_secret"
    profile = Profile(
        name,
        "feishu_app",
        {
            "app_id": args.app_id,
            "recipient": args.recipient,
            "receive_id_type": args.receive_id_type,
        },
        {"app_secret": secret_name},
    )
    config.save_profile(profile, overwrite=args.overwrite)
    secrets.set(secret_name, app_secret)
    print(f"Saved enterprise app profile: {name}")
    return 0


def _profile_command(args: argparse.Namespace) -> int:
    """Dispatch profile management subcommands."""
    if args.profile_command == "add-webhook":
        return _add_webhook(args)
    if args.profile_command == "add-app":
        return _add_app(args)
    config, secrets = _stores()
    if args.profile_command == "list":
        profiles = config.list_profiles()
        if not profiles:
            print("No profiles configured.")
        for profile in profiles:
            print(f"{profile.name}\t{profile.provider}")
        return 0
    if args.profile_command == "show":
        profile = config.get_profile(args.name)
        print(f"name: {profile.name}")
        print(f"provider: {profile.provider}")
        for key, value in sorted(profile.options.items()):
            print(f"{key}: {value}")
        for key in sorted(profile.secret_names):
            print(f"{key}: <stored securely>")
        return 0
    if args.profile_command == "remove":
        profile = config.remove_profile(args.name)
        for secret_name in profile.secret_names.values():
            secrets.delete(secret_name)
        print(f"Removed profile: {profile.name}")
        return 0
    raise ValueError("A profile subcommand is required")


def _choose_profile(config: ConfigStore, repo: Path, requested: str | None) -> Profile:
    """Choose an explicit, previously selected, or sole configured profile."""
    if requested:
        return config.get_profile(requested)
    current = get_local_config(repo, "git-lark.profile")
    if current:
        return config.get_profile(current)
    profiles = config.list_profiles()
    if len(profiles) == 1:
        return profiles[0]
    raise ValueError("Select a profile with --profile NAME")


def _init_repository(args: argparse.Namespace) -> int:
    """Install the hook and select a notification profile for one repository."""
    repo = _repo(args.repo)
    config = ConfigStore()
    profile = _choose_profile(config, repo, args.profile)
    installed_path = install_hook(repo)
    set_local_config(repo, "git-lark.profile", profile.name)
    set_local_config(repo, "git-lark.enabled", "true")
    print(f"Installed hook: {installed_path}")
    print(f"Selected profile: {profile.name}")
    return 0


def _use_profile(args: argparse.Namespace) -> int:
    """Switch an initialized repository to another profile."""
    repo = _repo(args.repo)
    profile = ConfigStore().get_profile(args.name)
    set_local_config(repo, "git-lark.profile", profile.name)
    set_local_config(repo, "git-lark.enabled", "true")
    print(f"Selected profile: {profile.name}")
    return 0


def _test_profile(args: argparse.Namespace) -> int:
    """Send a direct test message without changing duplicate state."""
    repo = _repo(args.repo)
    config, secrets = _stores()
    profile = _profile_for_repo(repo, config, args.profile)
    message = (
        "【git-lark 测试】\n"
        f"仓库：{repo.name}\n"
        f"Profile：{profile.name}\n"
        f"时间：{datetime.now().astimezone().isoformat(timespec='seconds')}"
    )
    if args.dry_run:
        print(message)
    else:
        send_message(profile, message, secrets)
        print(f"Test message sent through profile: {profile.name}")
    return 0


def _status(args: argparse.Namespace) -> int:
    """Print repository integration and selected-profile status."""
    repo = _repo(args.repo)
    config = ConfigStore()
    profile_name = get_local_config(repo, "git-lark.profile")
    enabled = get_local_config(repo, "git-lark.enabled") or "true"
    print(f"repository: {repo}")
    print(f"enabled: {enabled}")
    print(f"hook: {'installed' if is_installed(repo) else 'not installed'} ({hook_path(repo)})")
    print(f"backup hook: {'present' if backup_path(repo).exists() else 'absent'}")
    print(f"profile: {profile_name or '<not selected>'}")
    if profile_name:
        try:
            print(f"provider: {config.get_profile(profile_name).provider}")
        except KeyError:
            print("provider: <profile missing>")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    """Validate hook, profile, and required secrets without sending a message."""
    repo = _repo(args.repo)
    config, secrets = _stores()
    problems: list[str] = []
    if not is_installed(repo):
        problems.append("post-commit hook is not installed")
    try:
        profile = selected_profile(repo, config)
        for key, secret_name in profile.secret_names.items():
            try:
                secrets.get(secret_name)
            except Exception as error:
                problems.append(f"secret {key!r} is unavailable: {error}")
    except Exception as error:
        problems.append(str(error))
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}")
        return 1
    print("OK: hook, profile, and secrets are ready")
    return 0


def _uninstall(args: argparse.Namespace) -> int:
    """Remove integration from a repository and restore its prior hook."""
    repo = _repo(args.repo)
    removed = uninstall_hook(repo)
    unset_local_config(repo, "git-lark.profile")
    unset_local_config(repo, "git-lark.enabled")
    print("Removed git-lark hook and restored its backup." if removed else "No managed git-lark hook was installed.")
    return 0


def _notify(args: argparse.Namespace) -> int:
    """Manually notify HEAD or render it without delivery."""
    repo = _repo(args.repo)
    _, messages = notify_head(repo, force=args.force, dry_run=args.dry_run)
    if args.dry_run:
        print("\n\n".join(messages))
    else:
        print("Commit notification delivered or already up to date.")
    return 0


def _hook(args: argparse.Namespace) -> int:
    """Run a fail-open hook entry point that never invalidates a commit."""
    if args.hook_command != "post-commit":
        return 0
    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    if not notify_head_fail_open(repo):
        print("git-lark warning: notification failed; see .git/git-lark/notify.log", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the complete command-line parser."""
    parser = argparse.ArgumentParser(prog="git-lark", description="Send Git commit notifications to Feishu/Lark")
    parser.add_argument("--version", action="version", version=f"git-lark {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    profile = commands.add_parser("profile", help="Manage bot profiles")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    webhook = profile_commands.add_parser("add-webhook", help="Add a custom webhook bot")
    webhook.add_argument("name")
    webhook.add_argument("--url", help="Webhook URL; omitted values are requested securely")
    webhook.add_argument("--signed", action="store_true", help="Prompt for a webhook signing secret")
    webhook.add_argument("--signing-secret", help="Webhook signing secret; prefer --signed to avoid shell history")
    webhook.add_argument("--overwrite", action="store_true")
    app = profile_commands.add_parser("add-app", help="Add an enterprise application bot")
    app.add_argument("name")
    app.add_argument("--app-id", required=True)
    app.add_argument("--app-secret", help="App secret; omitted values are requested securely")
    app.add_argument("--recipient", required=True)
    app.add_argument(
        "--receive-id-type",
        choices=("open_id", "chat_id", "user_id", "union_id"),
        default="open_id",
    )
    app.add_argument("--overwrite", action="store_true")
    profile_commands.add_parser("list", help="List profiles")
    show = profile_commands.add_parser("show", help="Show non-secret profile metadata")
    show.add_argument("name")
    remove = profile_commands.add_parser("remove", help="Remove a profile and its secrets")
    remove.add_argument("name")

    init = commands.add_parser("init", aliases=["install"], help="Install the current repository hook")
    init.add_argument("--profile")
    init.add_argument("--repo")
    use = commands.add_parser("use", help="Select a profile for the current repository")
    use.add_argument("name")
    use.add_argument("--repo")
    test = commands.add_parser("test", help="Send a test message")
    test.add_argument("--profile")
    test.add_argument("--repo")
    test.add_argument("--dry-run", action="store_true")
    status = commands.add_parser("status", help="Show repository integration status")
    status.add_argument("--repo")
    doctor = commands.add_parser("doctor", help="Validate the local installation")
    doctor.add_argument("--repo")
    uninstall = commands.add_parser("uninstall", help="Remove the current repository hook")
    uninstall.add_argument("--repo")
    notify = commands.add_parser("notify", help="Manually notify the current HEAD")
    notify.add_argument("--repo")
    notify.add_argument("--force", action="store_true")
    notify.add_argument("--dry-run", action="store_true")
    commands.add_parser("config-path", help="Print the user configuration directory")
    hook = commands.add_parser("hook", help="Internal Git hook entry point")
    hook_commands = hook.add_subparsers(dest="hook_command", required=True)
    post_commit = hook_commands.add_parser("post-commit")
    post_commit.add_argument("--repo")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one command and convert expected failures into concise stderr output."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "profile":
            return _profile_command(args)
        if args.command in {"init", "install"}:
            return _init_repository(args)
        if args.command == "use":
            return _use_profile(args)
        if args.command == "test":
            return _test_profile(args)
        if args.command == "status":
            return _status(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "uninstall":
            return _uninstall(args)
        if args.command == "notify":
            return _notify(args)
        if args.command == "hook":
            return _hook(args)
        if args.command == "config-path":
            print(ConfigStore().directory)
            return 0
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        print(f"git-lark: {error}", file=sys.stderr)
        return 1
    parser.error(f"Unknown command: {args.command}")
    return 2
