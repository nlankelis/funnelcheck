"""A bounded, read-only client for the Roblox Analytics Query API."""

import re
import time
from collections.abc import Callable

import httpx

from .funnel import FunnelQuery


BASE_URL = "https://apis.roblox.com/analytics-query-api/"


class RobloxAPIError(RuntimeError):
    """A request or Roblox query operation failed."""


def fetch_rates(
    query: FunnelQuery,
    api_key: str,
    *,
    transport: httpx.BaseTransport | None = None,
    poll_interval: float = 2.0,
    max_polls: int = 15,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """POST once, then poll that operation. Tests inject a fake transport/sleep.

    No automatic resubmission after failures: a timeout doesn't prove the server
    stopped working. Polling limits bound attempts, not total wall-clock time.
    """
    if not api_key.strip():
        raise RobloxAPIError("API key cannot be empty.")
    if max_polls < 0 or poll_interval < 0:
        raise ValueError("Polling limits cannot be negative.")

    def read_response(response: httpx.Response) -> dict:
        if response.status_code not in (200, 202):
            hints = {
                400: "Check the metric, filters and date range.",
                401: "Check the key, its analytics permission and experience access.",
                403: "Check experience access and any key IP restrictions.",
                404: "Check the universe ID or operation path.",
                429: "The query hit a limit; reduce its size or try later.",
            }
            raise RobloxAPIError(f"Roblox HTTP {response.status_code}. " + hints.get(response.status_code, "Try again later."))
        try:
            body = response.json()
        except ValueError as exc:
            raise RobloxAPIError("Roblox returned invalid JSON.") from exc
        if not isinstance(body, dict) or type(body.get("done")) is not bool:
            raise RobloxAPIError("Roblox returned an unexpected query envelope.")
        if "error" in body:
            error = body["error"]
            if isinstance(error, dict):
                detail = f"{error.get('code', 'unknown')}: {error.get('message', 'No details')}"
                raise RobloxAPIError("Roblox query failed: " + detail.replace(api_key, "[redacted]"))
            raise RobloxAPIError("Roblox reported a query failure.")
        return body

    with httpx.Client(
        headers={"x-api-key": api_key}, timeout=15.0,
        follow_redirects=False, transport=transport,
    ) as client:
        try:
            result = read_response(client.post(
                BASE_URL + f"v1/universes/{query.universe_id}/metrics",
                json=query.payload(),
            ))
            if result["done"]:
                return result
            path = result.get("path")
            expected_path = rf"v1/universes/{query.universe_id}/operations/metrics/[A-Za-z0-9_-]+"
            # Never forward the key to a URL supplied unchecked by a response.
            if not isinstance(path, str) or not re.fullmatch(expected_path, path):
                raise RobloxAPIError("Roblox returned an unexpected polling path.")
            for _ in range(max_polls):
                sleep(poll_interval)
                result = read_response(client.get(BASE_URL + path))
                if result["done"]:
                    return result
            raise RobloxAPIError(f"Query still pending after {max_polls} polls. Resume with GET at {BASE_URL}{path}")
        except httpx.TimeoutException as exc:
            raise RobloxAPIError("The HTTP request timed out. Roblox may still be processing the query.") from exc
        except httpx.RequestError as exc:
            raise RobloxAPIError("Could not reach Roblox. Check your network connection.") from exc
