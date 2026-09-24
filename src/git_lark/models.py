"""Shared immutable data models used by git-lark."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChangedFile:
    """Represent one path changed by a Git commit."""

    status: str
    path: str
    previous_path: str | None = None

    def display(self) -> str:
        """Return a concise line suitable for a text notification."""
        if self.previous_path is not None:
            return f"{self.status} {self.previous_path} -> {self.path}"
        return f"{self.status} {self.path}"


@dataclass(frozen=True)
class CommitInfo:
    """Contain all Git commit information rendered into notifications."""

    repository: str
    branch: str
    sha: str
    short_sha: str
    author: str
    authored_at: str
    message: str
    files: tuple[ChangedFile, ...]


@dataclass(frozen=True)
class Profile:
    """Describe one named notification provider configuration."""

    name: str
    provider: str
    options: dict[str, str] = field(default_factory=dict)
    secret_names: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialize the profile without exposing secret values."""
        return {
            "provider": self.provider,
            "options": dict(self.options),
            "secret_names": dict(self.secret_names),
        }

    @classmethod
    def from_dict(cls, name: str, value: object) -> "Profile":
        """Parse and validate a profile stored in the user configuration."""
        if not isinstance(value, dict):
            raise ValueError(f"Profile {name!r} must be an object")
        provider = value.get("provider")
        options = value.get("options", {})
        secret_names = value.get("secret_names", {})
        if not isinstance(provider, str) or not provider:
            raise ValueError(f"Profile {name!r} has no provider")
        if not isinstance(options, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in options.items()
        ):
            raise ValueError(f"Profile {name!r} options must be string pairs")
        if not isinstance(secret_names, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in secret_names.items()
        ):
            raise ValueError(f"Profile {name!r} secret names must be string pairs")
        return cls(name=name, provider=provider, options=dict(options), secret_names=dict(secret_names))
