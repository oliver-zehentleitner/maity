"""The forge the probe reads (docs/api.md §11): which host, whether a token is held, the reads.

The token comes from the operator's environment only (`Settings`) and lives in
one `Forge` object, which the app hands to whoever reads: the probe route, the
worker, readiness. It is not a process global and never in a `repr`. Nothing a
project member sets can change where it is sent. Requests go to the fixed API
host of the forge kind, and a redirect to any other host is refused, so the
token never leaves for a host the operator did not choose.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

HOSTS = {"github.com": "github"}  # host -> forge kind
API_HOST = "api.github.com"
TIMEOUT = 10.0


class ForgeUnavailableError(Exception):
    """The forge did not answer a read (network, timeout, 5xx, rate limit, bad token,
    a repository the token cannot see, an answer of an unexpected shape)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # the forge's HTTP status, when it answered with one


def kind_of(url: str | None) -> str | None:
    if not url:
        return None
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    return HOSTS.get(host)


def repository_of(url: str) -> str:
    """`owner/name` of a repository URL on a configured forge."""
    path = url.split("://", 1)[-1].split("/", 1)[1]
    owner, name = path.strip("/").split("/")[:2]
    return f"{owner}/{name.removesuffix('.git')}"


class _SameHostOnly(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https://api.github.com on the default port: the
    Authorization header goes with it, so plain HTTP or another port would leak it."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        target = urllib.parse.urlsplit(newurl)
        try:
            port = target.port
        except ValueError:
            port = -1
        if target.scheme != "https" or target.hostname != API_HOST or port not in (None, 443):
            raise ForgeUnavailableError(f"the forge redirected elsewhere ({code})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SameHostOnly)


def _quote(ref: str) -> str:
    return urllib.parse.quote(ref, safe="")


# --- how check runs and commit statuses count ------------------------------------------------

FAILED = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "error"}
PENDING = {"pending", "stale"}  # stale: GitHub marked it outdated; it decides nothing yet
PAGE = 100
MAX_PAGES = 10  # 1000 check runs; past that the sum is `unknown`

VISIBILITY_SECONDS = 300
_visible: dict[str, float] = {}  # repository -> when the token last saw it


@dataclass(frozen=True)
class Forge:
    """The hub's access to its forge: the token, and the reads made with it."""

    token: str | None = field(default=None, repr=False)

    def configured_for(self, url: str | None) -> bool:
        """Whether the hub can observe this repository: a known forge and a token for it."""
        return kind_of(url) == "github" and self.token is not None

    def _get(self, path: str) -> Any | None:
        """GET on the forge API; `None` for 404, `ForgeUnavailableError` for anything else."""
        if self.token is None:
            raise ForgeUnavailableError("no forge token")
        request = urllib.request.Request(f"https://{API_HOST}{path}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("User-Agent", "maity-hub")
        try:
            with _opener.open(request, timeout=TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise ForgeUnavailableError(f"the forge answered {error.code}", error.code) from None
        except (OSError, ValueError, http.client.HTTPException) as error:
            # A protocol error (IncompleteRead, BadStatusLine, …) is a forge that did not
            # answer, like a timeout; never the error text, which may quote the request.
            raise ForgeUnavailableError(
                f"the forge did not answer: {type(error).__name__}"
            ) from None

    def _missing(self, repository: str) -> None:
        """A 404 for a ref is an answer only when the token can see the repository: GitHub
        answers 404 for a private repository the token has no access to, too."""
        seen = _visible.get(repository)
        if seen is not None and time.monotonic() - seen < VISIBILITY_SECONDS:
            return
        if self._get(f"/repos/{repository}") is None:
            raise ForgeUnavailableError("the repository is not visible to the forge token")
        _visible[repository] = time.monotonic()

    def _check_runs(self, repository: str, sha: str) -> list[dict[str, str]] | None:
        """Every check run on the commit; None when there are more than MAX_PAGES pages."""
        runs: list[dict[str, str]] = []
        for page in range(1, MAX_PAGES + 1):
            found = self._get(
                f"/repos/{repository}/commits/{_quote(sha)}/check-runs?per_page={PAGE}&page={page}"
            )
            batch = (found or {}).get("check_runs", [])
            runs += [{"name": r["name"], "status": r.get("conclusion") or "pending"} for r in batch]
            if len(batch) < PAGE or len(runs) >= (found or {}).get("total_count", 0):
                return runs
        return None

    def _statuses(self, repository: str, sha: str) -> list[dict[str, str]]:
        """The commit statuses (the API before check runs), latest per context."""
        found = self._get(f"/repos/{repository}/commits/{_quote(sha)}/status?per_page={PAGE}")
        return [
            {"name": item["context"], "status": item["state"]}
            for item in (found or {}).get("statuses", [])
        ]

    def checks(self, repository: str, sha: str) -> tuple[str, list[dict[str, str]]]:
        """Check runs and commit statuses on a commit, summed up: success, failure,
        pending, none, or unknown when they cannot all be read."""
        try:
            runs = self._check_runs(repository, sha)
            statuses = self._statuses(repository, sha)
        except ForgeUnavailableError as error:
            if error.status == 403:  # a token without the checks or statuses permission
                return "unknown", []
            raise
        if runs is None:
            return "unknown", statuses
        detail = runs + statuses
        if not detail:
            return "none", []
        states = {item["status"] for item in detail}
        if states & FAILED:
            return "failure", detail
        if states & PENDING:
            return "pending", detail
        return "success", detail

    def pull_request(self, repository: str, number: int) -> dict[str, Any]:
        pr = self._get(f"/repos/{repository}/pulls/{number}")
        if pr is None:
            self._missing(repository)
            return {"number": number, "found": False}
        merged = pr.get("merged_at") is not None
        mergeable = {True: "mergeable", False: "conflicting"}.get(pr.get("mergeable"), "unknown")
        if pr.get("mergeable_state") == "dirty":
            mergeable = "conflicting"
        head_sha = pr["head"]["sha"]
        summary, detail = self.checks(repository, head_sha)
        return {
            "number": number,
            "found": True,
            "url": pr.get("html_url"),
            "title": pr.get("title"),
            "state": "merged" if merged else pr.get("state"),
            "draft": bool(pr.get("draft")),
            "head_sha": head_sha,
            "base": pr["base"]["ref"],
            "mergeable": None if merged else mergeable,
            "checks": summary,
            "checks_detail": detail,
            "merged_at": pr.get("merged_at"),
            "merge_sha": pr.get("merge_commit_sha") if merged else None,
        }

    def branch(self, repository: str, name: str) -> dict[str, Any]:
        found = self._get(f"/repos/{repository}/branches/{_quote(name)}")
        if found is None:
            self._missing(repository)
            return {"name": name, "head_sha": None, "found": False}
        return {"name": name, "head_sha": found["commit"]["sha"], "found": True}

    def tag(self, repository: str, name: str) -> dict[str, Any]:
        ref = self._get(f"/repos/{repository}/git/ref/tags/{_quote(name)}")
        if ref is None or not isinstance(ref, dict):  # a list: no exact match, only prefixes
            if ref is None:
                self._missing(repository)
            return {"name": name, "sha": None, "found": False}
        target = ref["object"]
        sha = target["sha"]
        if target.get("type") == "tag":  # annotated: the commit it points at
            annotated = self._get(f"/repos/{repository}/git/tags/{sha}")
            sha = annotated["object"]["sha"] if annotated else sha
        return {"name": name, "sha": sha, "found": True}
