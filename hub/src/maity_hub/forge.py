"""The forge the probe reads (docs/api.md §11): which host, whether a token is held, the reads.

The token comes from the operator's environment only (`Settings`) and lives in
one `Forge` object, which the app hands to whoever reads: the probe route, the
worker, readiness. It is not a process global and never in a `repr`. Nothing a
project member sets can change where it is sent. Requests go to the fixed API
host of the forge kind, and a redirect to any other host is refused, so the
token never leaves for a host the operator did not choose.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

HOSTS = {"github.com": "github"}  # host -> forge kind
API_HOST = "api.github.com"
TIMEOUT = 10.0


class ForgeUnavailableError(Exception):
    """The forge did not answer a read (network, timeout, 5xx, rate limit, bad token,
    a repository the token cannot see, an answer of an unexpected shape)."""

    def __init__(self, message: str, status: int | None = None, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.status = status  # the forge's HTTP status, when it answered with one
        self.rate_limited = rate_limited  # a 403/429 that says "later", not "never"


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
# (token digest, repository) -> when that token last saw it; the digest, not the token
_visible: dict[tuple[str, str], float] = {}


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
        return self._call(path)

    def _call(self, path: str, query: dict[str, Any] | None = None) -> Any | None:
        """A read on the forge API, with the token when the hub holds one and without it
        otherwise (a public repository). `query` makes it a GraphQL POST, which only reads."""
        data = None if query is None else json.dumps(query).encode()
        request = urllib.request.Request(f"https://{API_HOST}{path}", data=data)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token is not None:
            request.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", "maity-hub")
        try:
            with _opener.open(request, timeout=TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            headers: Any = error.headers or {}
            limited = error.code in (403, 429) and (
                headers.get("X-RateLimit-Remaining") == "0" or "Retry-After" in headers
            )
            raise ForgeUnavailableError(
                f"the forge answered {error.code}" + (" (rate limit)" if limited else ""),
                error.code,
                rate_limited=limited,
            ) from None
        except (OSError, ValueError, http.client.HTTPException) as error:
            # A protocol error (IncompleteRead, BadStatusLine, …) is a forge that did not
            # answer, like a timeout; never the error text, which may quote the request.
            raise ForgeUnavailableError(
                f"the forge did not answer: {type(error).__name__}"
            ) from None

    def _missing(self, repository: str) -> None:
        """A 404 for a ref is an answer only when the token can see the repository: GitHub
        answers 404 for a private repository the token has no access to, too."""
        key = (hashlib.sha256((self.token or "").encode()).hexdigest(), repository)
        seen = _visible.get(key)
        if seen is not None and time.monotonic() - seen < VISIBILITY_SECONDS:
            return
        if self._get(f"/repos/{repository}") is None:
            raise ForgeUnavailableError("the repository is not visible to the forge token")
        _visible[key] = time.monotonic()

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
            if error.status == 403 and not error.rate_limited:  # no checks/statuses permission
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

    # --- merges for the change ticker (docs/api.md §17.4) ------------------------------------

    def merged_pulls(
        self,
        repository: str,
        base: str,
        since: datetime,
        start: int = 1,
        pages: int = 20,
        merged_after: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """The pull requests closed against `base`, updated after `since` and merged after
        `merged_after` (default `since`), read most recently updated first from page
        `start` until a page reaches back before `since` (a merge also updates its pull
        request, so nothing older can follow), at most `pages` pages of 50. The second
        value is the page to go on from when that bound cut the scan, else None.

        Admitting by the update, not the merge: a pull request merged before `since` but
        updated after it may have moved past a scan's pages while that scan was cut, and
        would otherwise never be read again. The caller's dedupe keeps it to one item."""
        floor = merged_after if merged_after is not None else since
        found: list[dict[str, Any]] = []
        for page in range(start, start + pages):
            batch = self._get(
                f"/repos/{repository}/pulls?state=closed&base={urllib.parse.quote(base)}"
                f"&sort=updated&direction=desc&per_page=50&page={page}"
            )
            if batch is None:
                self._missing(repository)
                return found, None
            if not isinstance(batch, list):
                raise ForgeUnavailableError("the forge answered a list with no list")
            reached = False
            for pr in batch:
                if not isinstance(pr, dict):
                    continue
                updated = _moment(pr.get("updated_at"))
                if updated is not None and updated < since:
                    reached = True
                merged = _moment(pr.get("merged_at"))
                if merged is None or merged <= floor or (updated is not None and updated <= since):
                    continue
                found.append(
                    {
                        "number": pr["number"],
                        "title": pr.get("title") or "",
                        "url": pr.get("html_url"),
                        "merge_sha": pr.get("merge_commit_sha"),
                        "base": (pr.get("base") or {}).get("ref"),
                        "base_sha": (pr.get("base") or {}).get("sha"),
                        "head": (pr.get("head") or {}).get("ref"),
                        "merged_at": pr["merged_at"],
                        "author": (pr.get("user") or {}).get("login"),
                    }
                )
            if len(batch) < 50 or reached:
                return found, None
        return found, start + pages

    def pull_files(
        self, repository: str, number: int, cap: int = 300
    ) -> tuple[list[dict[str, Any]], bool]:
        """The changed files of a pull request in the forge's order, at most `cap`: each
        `{path, previous, patch}` (`patch` null when the forge sent none). The second value
        is whether the list is incomplete (over the cap, or cut short by the forge)."""
        files: list[dict[str, Any]] = []
        page = 1
        while len(files) < cap:
            batch = self._get(f"/repos/{repository}/pulls/{number}/files?per_page=100&page={page}")
            if batch is None:
                return files, True
            if not isinstance(batch, list):
                raise ForgeUnavailableError("the forge answered a list with no list")
            for f in batch:
                if isinstance(f, dict) and isinstance(f.get("filename"), str):
                    files.append(
                        {
                            "path": f["filename"],
                            "previous": f.get("previous_filename"),
                            "patch": f.get("patch") if isinstance(f.get("patch"), str) else None,
                        }
                    )
            if len(batch) < 100:
                return files[:cap], len(files) > cap
            page += 1
        return files[:cap], True

    def file_at(self, repository: str, path: str, ref: str, cap: int) -> bytes | None:
        """A file at a commit through the contents API; None when it is not there. Over
        `cap` bytes, or an answer that is not a file, is `ValueError`."""
        found = self._get(
            f"/repos/{repository}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}"
        )
        return _decoded(found, cap)

    # --- the repository's images (docs/api.md §11.2) ------------------------------------------

    def owner_avatar(self, repository: str) -> str | None:
        """The owner's avatar URL (GitHub has no repository avatar), read with the token
        where the hub holds one and without it for a public repository; None when the
        repository or the avatar is not there."""
        found = self._call(f"/repos/{repository}")
        url = ((found or {}).get("owner") or {}).get("avatar_url")
        return url if isinstance(url, str) else None

    def social_preview(self, repository: str) -> str | None:
        """The repository's own social preview image, only when it set one (GitHub's generated
        card is not a banner). GraphQL needs a token: without one there is no banner."""
        if self.token is None:
            return None
        owner, name = repository.split("/", 1)
        found = self._call(
            "/graphql",
            {
                "query": "query($owner: String!, $name: String!) { repository(owner: $owner, "
                "name: $name) { openGraphImageUrl usesCustomOpenGraphImage } }",
                "variables": {"owner": owner, "name": name},
            },
        )
        if not isinstance(found, dict):
            raise ForgeUnavailableError("the forge answered GraphQL with no object")
        repo = (found.get("data") or {}).get("repository")
        if repo is None:
            errors = found.get("errors") or []
            if all(isinstance(e, dict) and e.get("type") == "NOT_FOUND" for e in errors):
                return None
            raise ForgeUnavailableError("the forge answered GraphQL with errors")
        if repo.get("usesCustomOpenGraphImage") is not True:
            return None
        url = repo.get("openGraphImageUrl")
        return url if isinstance(url, str) else None

    # --- files on the default branch (docs/api.md §11.3) ------------------------------------

    def file(self, repository: str, path: str, cap: int) -> bytes | None:
        """A file on the default branch through the contents API, with the token where the
        hub holds one and without it for a public repository; None when it is not there.
        A file over `cap` bytes, or an answer that is not a file, is `ValueError`."""
        found = self._call(f"/repos/{repository}/contents/{urllib.parse.quote(path)}")
        return _decoded(found, cap)


def _moment(value: Any) -> datetime | None:
    """A forge timestamp (`2026-10-22T15:02:11Z`) as an aware datetime, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _decoded(found: Any, cap: int) -> bytes | None:
    """A contents-API answer as bytes; None for a 404, `ValueError` for anything that is
    not a file of at most `cap` bytes."""
    if found is None:
        return None
    if not isinstance(found, dict) or found.get("type") != "file":
        raise ValueError("not a file")
    size = found.get("size")
    if not isinstance(size, int) or size > cap:
        raise ValueError("too large")
    if found.get("encoding") != "base64" or not isinstance(found.get("content"), str):
        raise ValueError("no content")
    data = base64.b64decode(found["content"], validate=False)
    if len(data) > cap:
        raise ValueError("too large")
    return data
