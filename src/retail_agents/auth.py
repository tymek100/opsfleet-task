"""Transport authentication; model arguments never select identity or authority."""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from retail_agent.contracts import DEMO_USERS


@dataclass(frozen=True)
class Principal:
    identity: str
    service: bool = False


def signed_headers(secret: str, body: bytes, identity: str, audience: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    digest = hashlib.sha256(body).hexdigest()
    signature = hmac.new(
        secret.encode(), f"{timestamp}:{identity}:{audience}:{digest}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "x-retail-identity": identity,
        "x-retail-time": timestamp,
        "x-retail-signature": signature,
        "x-retail-audience": audience,
    }


def authenticate(
    headers: dict, body: bytes, secret: str, demo_token: str, audience: str
) -> Principal:
    authorization = headers.get("authorization", "")
    if demo_token and hmac.compare_digest(authorization, f"Bearer {demo_token}"):
        return Principal("alice")
    identity = headers.get("x-retail-identity", "")
    timestamp = headers.get("x-retail-time", "")
    if (
        identity not in DEMO_USERS
        or headers.get("x-retail-audience") != audience
        or not timestamp.isdigit()
        or abs(time.time() - int(timestamp)) > 300
    ):
        raise ValueError("Unauthorized request")
    digest = hashlib.sha256(body).hexdigest()
    expected = hmac.new(
        secret.encode(), f"{timestamp}:{identity}:{audience}:{digest}".encode(), hashlib.sha256
    ).hexdigest()
    if not secret or not hmac.compare_digest(expected, headers.get("x-retail-signature", "")):
        raise ValueError("Unauthorized request")
    return Principal(identity, True)


def canonical_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
