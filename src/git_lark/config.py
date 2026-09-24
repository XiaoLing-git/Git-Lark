"""User-level profile configuration management."""

import json
import os
import re
import tempfile
from pathlib import Path

from .models import Profile

_PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def default_config_directory() -> Path:
    """Return the platform-appropriate user configuration directory."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "git-lark"
    return Path.home() / ".config" / "git-lark"


class ConfigStore:
    """Persist non-secret profile metadata as atomic JSON updates."""

    def __init__(self, directory: Path | None = None) -> None:
        """Initialize the store without creating files until data is saved."""
        self.directory = directory or default_config_directory()
        self.path = self.directory / "config.json"

    @staticmethod
    def validate_profile_name(name: str) -> str:
        """Validate and return a profile name safe for config keys and state files."""
        if not _PROFILE_NAME_PATTERN.fullmatch(name):
            raise ValueError("Profile names must use 1-64 letters, digits, dots, underscores, or hyphens")
        return name

    def _load_document(self) -> dict[str, object]:
        """Load and minimally validate the complete configuration document."""
        if not self.path.exists():
            return {"version": 1, "profiles": {}}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("profiles"), dict):
            raise ValueError(f"Invalid configuration file: {self.path}")
        return raw

    def _save_document(self, document: dict[str, object]) -> None:
        """Atomically replace the JSON document to avoid partial writes."""
        self.directory.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=self.directory)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
            temporary_path.replace(self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def list_profiles(self) -> tuple[Profile, ...]:
        """Return all profiles sorted by name."""
        profiles = self._load_document()["profiles"]
        assert isinstance(profiles, dict)
        return tuple(Profile.from_dict(name, profiles[name]) for name in sorted(profiles))

    def get_profile(self, name: str) -> Profile:
        """Return one profile or raise a clear lookup error."""
        self.validate_profile_name(name)
        profiles = self._load_document()["profiles"]
        assert isinstance(profiles, dict)
        if name not in profiles:
            raise KeyError(f"Unknown profile: {name}")
        return Profile.from_dict(name, profiles[name])

    def save_profile(self, profile: Profile, *, overwrite: bool = False) -> None:
        """Create or replace one profile without storing secret values."""
        self.validate_profile_name(profile.name)
        document = self._load_document()
        profiles = document["profiles"]
        assert isinstance(profiles, dict)
        if profile.name in profiles and not overwrite:
            raise ValueError(f"Profile already exists: {profile.name}; use --overwrite to replace it")
        profiles[profile.name] = profile.to_dict()
        self._save_document(document)

    def remove_profile(self, name: str) -> Profile:
        """Remove and return one profile so callers can also delete its secrets."""
        profile = self.get_profile(name)
        document = self._load_document()
        profiles = document["profiles"]
        assert isinstance(profiles, dict)
        del profiles[name]
        self._save_document(document)
        return profile
