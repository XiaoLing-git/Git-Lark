"""Feishu/Lark notification provider implementations using the standard library."""

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .models import Profile
from .secrets import SecretStore

_TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


class ProviderError(RuntimeError):
    """Report a rejected or malformed provider request."""


def _post_json(
    url: str, payload: dict[str, object], *, token: str | None = None, timeout: float = 5.0
) -> dict[str, Any]:
    """POST JSON and return a decoded object with useful HTTP errors."""
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise ProviderError(f"HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise ProviderError(f"Network error: {error.reason}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderError("Provider returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ProviderError("Provider returned a non-object JSON response")
    return value


def _secret(profile: Profile, secrets: SecretStore, key: str) -> str:
    """Resolve a required profile secret through its configured secret name."""
    secret_name = profile.secret_names.get(key)
    if not secret_name:
        raise ProviderError(f"Profile {profile.name!r} has no {key} secret mapping")
    try:
        return secrets.get(secret_name)
    except KeyError as error:
        raise ProviderError(str(error)) from error


def _webhook_signature(timestamp: int, secret: str) -> str:
    """Build the signature expected by signed Feishu custom webhooks."""
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def send_webhook(profile: Profile, text: str, secrets: SecretStore, timeout: float = 5.0) -> None:
    """Send text through a Feishu custom webhook profile."""
    webhook_url = _secret(profile, secrets, "webhook_url")
    payload: dict[str, object] = {"msg_type": "text", "content": {"text": text}}
    signing_name = profile.secret_names.get("signing_secret")
    if signing_name:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = _webhook_signature(timestamp, secrets.get(signing_name))
    response = _post_json(webhook_url, payload, timeout=timeout)
    code = response.get("code", response.get("StatusCode", 0))
    if code != 0:
        message = response.get("msg", response.get("StatusMessage", "unknown webhook error"))
        raise ProviderError(f"Feishu webhook rejected the message: code={code} msg={message}")


def send_app(profile: Profile, text: str, secrets: SecretStore, timeout: float = 5.0) -> None:
    """Send text through a Feishu enterprise application profile."""
    app_id = profile.options.get("app_id", "")
    recipient = profile.options.get("recipient", "")
    receive_id_type = profile.options.get("receive_id_type", "open_id")
    if not app_id or not recipient:
        raise ProviderError(f"Profile {profile.name!r} requires app_id and recipient")
    token_response = _post_json(
        _TENANT_TOKEN_URL,
        {"app_id": app_id, "app_secret": _secret(profile, secrets, "app_secret")},
        timeout=timeout,
    )
    if token_response.get("code", 0) != 0 or not token_response.get("tenant_access_token"):
        raise ProviderError(
            f"Failed to obtain tenant token: code={token_response.get('code')} msg={token_response.get('msg')}"
        )
    query = urllib.parse.urlencode({"receive_id_type": receive_id_type})
    response = _post_json(
        f"{_MESSAGE_URL}?{query}",
        {
            "receive_id": recipient,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        token=str(token_response["tenant_access_token"]),
        timeout=timeout,
    )
    if response.get("code", 0) != 0:
        raise ProviderError(f"Feishu app rejected the message: code={response.get('code')} msg={response.get('msg')}")


def send_message(profile: Profile, text: str, secrets: SecretStore, timeout: float = 5.0) -> None:
    """Dispatch a message through the provider selected by a profile."""
    if profile.provider == "feishu_webhook":
        send_webhook(profile, text, secrets, timeout)
        return
    if profile.provider == "feishu_app":
        send_app(profile, text, secrets, timeout)
        return
    raise ProviderError(f"Unsupported provider: {profile.provider}")
