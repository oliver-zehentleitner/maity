"""HTTP to the hub, standard library only."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from maity import __version__

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
USER_AGENT = f"maity-cli/{__version__}"


class HubError(Exception):
    """The hub could not be reached or answered with an error."""


def hub_base(url: str) -> str:
    """Reduce a join or hub URL to the hub's base URL; refuse anything but HTTPS off loopback.

    Credentials travel over TLS only; plain HTTP is accepted for a hub on this machine.
    """
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise HubError(f"not a hub URL: {url!r}")
    if parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS:
        raise HubError(f"refusing plain HTTP to {parts.hostname}; the hub must be served over TLS")
    if parts.username or parts.password:
        raise HubError("refusing a URL with credentials in it")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def get_text(url: str, timeout: float = 30.0) -> str:
    """GET `url`, which callers build from `hub_base()`, so its scheme is http(s) only."""
    headers = {"Accept": "text/markdown, text/plain", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body: bytes = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise HubError(f"{url} answered {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise HubError(f"cannot reach {url}: {reason}") from exc
