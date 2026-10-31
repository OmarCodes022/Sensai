"""Reject requests that did not come from our own page on this machine.

The server only binds to loopback, but any website can still make the browser
send requests to localhost. Checking Host defeats DNS rebinding, and Origin /
Sec-Fetch-Site / Content-Type defeat cross-site form and fetch posts.
"""
from collections.abc import Mapping

from sensai_web.errors import ApiError

LOOPBACK = {"127.0.0.1": "127.0.0.1", "localhost": "localhost", "::1": "[::1]"}
SAFE_METHODS = ("GET", "HEAD")


def allowed_hosts(bind: str, port: int) -> frozenset[str]:
    """Host header values the page may use; "localhost" also covers 127.0.0.1."""
    if bind not in LOOPBACK:
        raise ValueError("the web interface only listens on 127.0.0.1, localhost or ::1")
    names = {LOOPBACK[bind]}
    if bind in ("127.0.0.1", "localhost"):
        names |= {"127.0.0.1", "localhost"}
    return frozenset(f"{name}:{port}" for name in names)


def check_request(method: str, headers: Mapping[str, str], hosts: frozenset[str],
                  has_body: bool) -> None:
    if headers.get("Host", "").lower() not in hosts:
        raise ApiError(403, "forbidden_host", "Unexpected Host header.")
    if method in SAFE_METHODS:
        return  # Reading is harmless: another site cannot read our answers (no CORS headers).
    if headers.get("Sec-Fetch-Site") == "cross-site":
        raise ApiError(403, "forbidden_origin", "Cross-site requests are not allowed.")
    origin = headers.get("Origin")
    if origin is not None and origin.lower() not in {f"http://{host}" for host in hosts}:
        raise ApiError(403, "forbidden_origin", "Requests must come from the Sensai page.")
    kind = headers.get("Content-Type", "").split(";")[0].strip().lower()
    if has_body and kind != "application/json":
        raise ApiError(415, "unsupported_media_type", "Send application/json.")
