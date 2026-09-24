"""Secret persistence with Windows DPAPI protection."""

import base64
import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

from .config import default_config_directory

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    """Match the Windows DATA_BLOB structure used by DPAPI."""

    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _to_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    """Create a DATA_BLOB while retaining ownership of its backing buffer."""
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(data), pointer), buffer


def _protect_windows(data: bytes) -> bytes:
    """Encrypt bytes for the current Windows user with DPAPI."""
    source, source_buffer = _to_blob(data)
    destination = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    success = crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(destination)
    )
    del source_buffer
    if not success:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


def _unprotect_windows(data: bytes) -> bytes:
    """Decrypt DPAPI bytes for the current Windows user."""
    source, source_buffer = _to_blob(data)
    destination = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    success = crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(destination)
    )
    del source_buffer
    if not success:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


class SecretStore:
    """Store named secrets separately from shareable profile metadata."""

    def __init__(self, directory: Path | None = None) -> None:
        """Initialize the secret store path."""
        self.directory = directory or default_config_directory()
        self.path = self.directory / "secrets.json"

    def _load(self) -> dict[str, str]:
        """Load the encoded secret mapping."""
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise ValueError(f"Invalid secret file: {self.path}")
        return dict(value)

    def _save(self, values: dict[str, str]) -> None:
        """Atomically save encoded secrets with restrictive permissions where supported."""
        self.directory.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix="secrets-", suffix=".tmp", dir=self.directory)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(values, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
            os.chmod(temporary_path, 0o600)
            temporary_path.replace(self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _encode(value: str) -> str:
        """Encode a value with DPAPI on Windows and an explicit fallback elsewhere."""
        raw = value.encode("utf-8")
        if os.name == "nt":
            return "dpapi:" + base64.b64encode(_protect_windows(raw)).decode("ascii")
        return "plain:" + base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _decode(value: str) -> str:
        """Decode a value and reject unknown storage formats."""
        if value.startswith("dpapi:"):
            if os.name != "nt":
                raise RuntimeError("Windows DPAPI secrets can only be opened by the owning Windows user")
            raw = _unprotect_windows(base64.b64decode(value.removeprefix("dpapi:")))
        elif value.startswith("plain:"):
            raw = base64.b64decode(value.removeprefix("plain:"))
        else:
            raise ValueError("Unknown secret encoding")
        return raw.decode("utf-8")

    def set(self, name: str, value: str) -> None:
        """Create or replace one non-empty secret."""
        if not name or not value:
            raise ValueError("Secret name and value must not be empty")
        values = self._load()
        values[name] = self._encode(value)
        self._save(values)

    def get(self, name: str) -> str:
        """Return one decrypted secret or raise a clear lookup error."""
        values = self._load()
        if name not in values:
            raise KeyError(f"Missing secret: {name}")
        return self._decode(values[name])

    def delete(self, name: str) -> None:
        """Delete one secret if present."""
        values = self._load()
        if name in values:
            del values[name]
            self._save(values)
