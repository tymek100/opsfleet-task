"""Bounded startup for the local Phoenix collector used by evaluation runs."""

import subprocess
import time
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from evaluation.settings import EvaluationSettings
from retail_agent.config import repository_root


class PhoenixUnavailable(RuntimeError):
    """Phoenix could not be prepared before model execution."""


def _ready(client: httpx.Client, url: str, deadline: float) -> bool:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    try:
        response = client.get(url + "/v1/projects", timeout=min(2, remaining))
        if response.status_code == 200:
            payload = response.json()
            return isinstance(payload, dict) and isinstance(payload.get("data"), list)
        if response.status_code in {401, 403}:
            raise PhoenixUnavailable(
                "Local Phoenix requires authentication; check its configuration."
            )
        return False
    except (httpx.TransportError, ValueError):
        return False


def ensure_phoenix(
    settings: EvaluationSettings,
    *,
    deadline: float,
    progress: Callable[[str], None] = print,
) -> None:
    """Reuse a reachable collector or start the repository's default Compose service."""
    startup_deadline = min(deadline, time.monotonic() + 60)
    if startup_deadline <= time.monotonic():
        raise PhoenixUnavailable("Evaluation deadline expired before Phoenix startup.")
    url = settings.phoenix_url
    with httpx.Client(follow_redirects=False, trust_env=False) as client:
        if _ready(client, url, startup_deadline):
            progress(f"Phoenix ready: {url}")
            return
        endpoint = urlparse(url)
        if (
            endpoint.scheme != "http"
            or endpoint.hostname not in {"localhost", "127.0.0.1"}
            or endpoint.port != 6006
            or endpoint.path not in {"", "/"}
        ):
            raise PhoenixUnavailable(
                "Configured Phoenix endpoint is unavailable. Automatic startup supports "
                "only http://127.0.0.1:6006; start the custom collector first."
            )
        progress("Starting local Phoenix with Docker Compose...")
        try:
            remaining = startup_deadline - time.monotonic()
            if remaining <= 0:
                raise PhoenixUnavailable("Evaluation deadline expired before Phoenix startup.")
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(repository_root() / "infra/phoenix/compose.yaml"),
                    "up",
                    "-d",
                ],
                cwd=repository_root(),
                capture_output=True,
                text=True,
                timeout=remaining,
                check=False,
            )
        except FileNotFoundError:
            raise PhoenixUnavailable(
                "Docker is not installed. Install and start Docker first."
            ) from None
        except subprocess.TimeoutExpired:
            raise PhoenixUnavailable("Phoenix startup exceeded the available deadline.") from None
        if result.returncode:
            raise PhoenixUnavailable(
                "Phoenix could not start. Check that Docker is running and port 6006 is available."
            )
        while time.monotonic() < startup_deadline:
            if _ready(client, url, startup_deadline):
                progress(f"Phoenix ready: {url}")
                return
            time.sleep(min(0.25, max(0, startup_deadline - time.monotonic())))
    raise PhoenixUnavailable("Phoenix did not become ready before the startup deadline.")
