"""The instance's GitHub App (docs/api.md §11.4): its settings, the App's own token,
the installations and the short-lived installation tokens.

The operator registers one App and sets five values in the environment, all or none.
The private key and the client secret come from a Secret: never logged, never in a
`repr`, never in an answer. The App's token (a JWT signed with the key) and the
installation tokens live in memory only. An installation token is kept until five
minutes before it expires, then minted again. Requests go through the forge's opener,
which follows no redirect (§11.4).
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from maity_hub import forge

SETTINGS = (
    "MAITY_FORGE_GITHUB_APP_ID",
    "MAITY_FORGE_GITHUB_APP_SLUG",
    "MAITY_FORGE_GITHUB_APP_PRIVATE_KEY",
    "MAITY_FORGE_GITHUB_APP_CLIENT_ID",
    "MAITY_FORGE_GITHUB_APP_CLIENT_SECRET",
)
OAUTH_HOST = "github.com"
JWT_SECONDS = 540  # GitHub takes at most 10 minutes; one minute back for clock skew
TOKEN_MARGIN = 300  # an installation token is minted again 5 minutes before it expires


class AppConfigError(ValueError):
    """The App's settings are incomplete or unusable; names the settings, never a value."""


class InstallationGoneError(forge.ForgeUnavailableError):
    """The forge refused to mint a token for an installation: `status` is `suspended`
    or `removed` (§11.4)."""

    def __init__(self, state: str) -> None:
        super().__init__(f"the installation is {state}")
        self.state = state


@dataclass(frozen=True)
class GitHubApp:
    app_id: str
    slug: str
    private_key: str = field(repr=False)
    client_id: str = ""
    client_secret: str = field(default="", repr=False)

    def install_url(self, state: str) -> str:
        """The App's installation page; GitHub sends the browser back to the App's setup
        URL with `installation_id`, `code` and this `state`."""
        query = urllib.parse.urlencode({"state": state})
        return (
            f"https://{OAUTH_HOST}/apps/{urllib.parse.quote(self.slug)}/installations/new?{query}"
        )

    def jwt(self, now: float | None = None) -> str:
        """The App's own token: RS256, issued a minute back, valid 9 minutes."""
        moment = int(time.time() if now is None else now)
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {"iat": moment - 60, "exp": moment + JWT_SECONDS, "iss": self.app_id}
        signing_input = f"{_b64(header)}.{_b64(payload)}".encode()
        key = _load_key(self.private_key)
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return (
            signing_input.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        )

    # --- the App's reads (with its JWT) --------------------------------------------------

    def installation(self, installation_id: int) -> dict[str, Any] | None:
        """The installation as the forge has it: `{id, account: {id, login, type},
        repository_selection, suspended}`; None when it is not there."""
        found = _call(f"/app/installations/{installation_id}", f"Bearer {self.jwt()}")
        if found is None:
            return None
        if not isinstance(found, dict) or not isinstance(found.get("account"), dict):
            raise forge.ForgeUnavailableError("the forge answered an installation of no shape")
        account = found["account"]
        return {
            "id": found.get("id"),
            "account": {
                "id": account.get("id"),
                "login": account.get("login"),
                "type": account.get("type"),
            },
            "repository_selection": found.get("repository_selection"),
            "suspended": found.get("suspended_at") is not None,
        }

    def installation_of(self, repository: str) -> int | None:
        """The App's installation that includes `owner/name`, or None (§11.4: the only
        one ever tried for that repository)."""
        found = _call(f"/repos/{repository}/installation", f"Bearer {self.jwt()}")
        if found is None:
            return None
        if not isinstance(found, dict) or not isinstance(found.get("id"), int):
            raise forge.ForgeUnavailableError("the forge answered an installation of no shape")
        installation_id: int = found["id"]
        return installation_id

    # --- the user who installed it (OAuth, once per link) --------------------------------

    def user_of_code(self, code: str) -> dict[str, Any]:
        """Exchange the OAuth `code` for a user token, read that user, discard the token:
        `{id, login}` (§11.4). The token is used for this one read and never stored."""
        body = urllib.parse.urlencode(
            {"client_id": self.client_id, "client_secret": self.client_secret, "code": code}
        ).encode()
        request = urllib.request.Request(
            f"https://{OAUTH_HOST}/login/oauth/access_token", data=body
        )
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "maity-hub")
        answer = _open(request)
        token = answer.get("access_token") if isinstance(answer, dict) else None
        if not isinstance(token, str) or not token:
            raise forge.ForgeUnavailableError("the forge exchanged no user token")
        user = _call("/user", f"Bearer {token}")
        del token
        if not isinstance(user, dict) or not isinstance(user.get("id"), int):
            raise forge.ForgeUnavailableError("the forge answered no user")
        return {"id": user["id"], "login": user.get("login")}

    # --- installation tokens (memory only) -----------------------------------------------

    def token(self, installation_id: int) -> str:
        """An installation token, minted when none is held or the held one expires within
        TOKEN_MARGIN. A mint the forge refuses because the installation was suspended or
        removed is `InstallationGoneError`."""
        with _tokens_lock:
            held = _tokens.get((self.app_id, installation_id))
            if held is not None and held[1] - time.time() > TOKEN_MARGIN:
                return held[0]
        try:
            minted = _call(
                f"/app/installations/{installation_id}/access_tokens",
                f"Bearer {self.jwt()}",
                post=True,
            )
        except forge.ForgeUnavailableError as error:
            if error.status == 403 and not error.rate_limited:
                raise InstallationGoneError("suspended") from None
            raise
        if minted is None:
            raise InstallationGoneError("removed")
        token = minted.get("token") if isinstance(minted, dict) else None
        expires = _expiry(minted.get("expires_at")) if isinstance(minted, dict) else None
        if not isinstance(token, str) or expires is None:
            raise forge.ForgeUnavailableError("the forge minted no installation token")
        with _tokens_lock:
            _tokens[(self.app_id, installation_id)] = (token, expires)
        return token

    def repositories(self, installation_id: int, limit: int = 100) -> list[str]:
        """At most `limit` full names the installation covers, read with its token."""
        found = _call(
            f"/installation/repositories?per_page={limit}",
            f"Bearer {self.token(installation_id)}",
        )
        repos = found.get("repositories") if isinstance(found, dict) else None
        if not isinstance(repos, list):
            return []
        return [r["full_name"] for r in repos if isinstance(r, dict) and "full_name" in r][:limit]


# (app id, installation id) -> (token, when it expires as a Unix time); never stored
_tokens: dict[tuple[str, int], tuple[str, float]] = {}
_tokens_lock = threading.Lock()


def forget_token(app: GitHubApp, installation_id: int) -> None:
    with _tokens_lock:
        _tokens.pop((app.app_id, installation_id), None)


def parse(env: dict[str, str]) -> GitHubApp | None:
    """The five settings, all or none; a partial set, or a key that is no RSA private
    key, stops the hub (`AppConfigError`, naming settings only)."""
    values = {name: env.get(name, "").strip() for name in SETTINGS}
    given = [name for name, value in values.items() if value]
    if not given:
        return None
    missing = [name for name in SETTINGS if not values[name]]
    if missing:
        raise AppConfigError(
            "the GitHub App needs all five settings or none; missing: " + ", ".join(missing)
        )
    key = values["MAITY_FORGE_GITHUB_APP_PRIVATE_KEY"].replace("\\n", "\n")
    try:
        _load_key(key)
    except (ValueError, TypeError):
        raise AppConfigError("MAITY_FORGE_GITHUB_APP_PRIVATE_KEY is no RSA private key") from None
    return GitHubApp(
        app_id=values["MAITY_FORGE_GITHUB_APP_ID"],
        slug=values["MAITY_FORGE_GITHUB_APP_SLUG"],
        private_key=key,
        client_id=values["MAITY_FORGE_GITHUB_APP_CLIENT_ID"],
        client_secret=values["MAITY_FORGE_GITHUB_APP_CLIENT_SECRET"],
    )


def _load_key(pem: str) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("not an RSA key")
    return key


def _b64(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _expiry(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _call(path: str, authorization: str, post: bool = False) -> Any | None:
    """A read on the forge API with the given credential; None for a 404."""
    request = urllib.request.Request(
        f"https://{forge.API_HOST}{path}",
        data=b"" if post else None,
        method="POST" if post else "GET",
    )
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("Authorization", authorization)
    request.add_header("User-Agent", "maity-hub")
    return _open(request)


def _open(request: urllib.request.Request) -> Any | None:
    try:
        with forge._opener.open(request, timeout=forge.TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        headers: Any = error.headers or {}
        limited = error.code in (403, 429) and (
            headers.get("X-RateLimit-Remaining") == "0" or "Retry-After" in headers
        )
        raise forge.ForgeUnavailableError(
            f"the forge answered {error.code}", error.code, rate_limited=limited
        ) from None
    except (OSError, ValueError) as error:
        # Never the error text: it may quote the request, and the request carries a secret.
        raise forge.ForgeUnavailableError(
            f"the forge did not answer: {type(error).__name__}"
        ) from None
