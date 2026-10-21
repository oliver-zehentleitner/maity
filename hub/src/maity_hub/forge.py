"""The forge the probe reads (docs/api.md §11): which host, whether a token is held, the reads.

The token comes from the operator's environment only and is set here once at
startup; nothing a project member sets can change where it is sent. Requests
go to the fixed API host of the forge kind, and a redirect to any other host
is refused, so the token never leaves for a host the operator did not choose.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HOSTS = {"github.com": "github"}  # host -> forge kind
API_HOST = "api.github.com"
TIMEOUT = 10.0
_token: str | None = None


class ForgeUnavailableError(Exception):
    """The forge did not answer a read (network, timeout, 5xx, rate limit, bad token)."""


def configure(token: str | None) -> None:
    global _token
    _token = token or None


def token() -> str | None:
    return _token


def kind_of(url: str | None) -> str | None:
    if not url:
        return None
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    return HOSTS.get(host)


def configured_for(url: str | None) -> bool:
    """Whether the hub can observe this repository: a known forge and a token for it."""
    return kind_of(url) == "github" and _token is not None


def repository_of(url: str) -> str:
    """`owner/name` of a repository URL on a configured forge."""
    path = url.split("://", 1)[-1].split("/", 1)[1]
    owner, name = path.strip("/").split("/")[:2]
    return f"{owner}/{name.removesuffix('.git')}"


class _SameHostOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        if urllib.parse.urlsplit(newurl).hostname != API_HOST:
            raise ForgeUnavailableError(f"the forge redirected to another host ({code})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SameHostOnly)


def _get(path: str) -> Any | None:
    """GET on the forge API; `None` for 404, `ForgeUnavailableError` for anything else."""
    if _token is None:
        raise ForgeUnavailableError("no forge token")
    request = urllib.request.Request(f"https://{API_HOST}{path}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("Authorization", f"Bearer {_token}")
    request.add_header("User-Agent", "maity-hub")
    try:
        with _opener.open(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise ForgeUnavailableError(f"the forge answered {error.code}") from None
    except (OSError, ValueError) as error:
        raise ForgeUnavailableError(f"the forge did not answer: {type(error).__name__}") from None


def _quote(ref: str) -> str:
    return urllib.parse.quote(ref, safe="")


# --- the three reads; each returns the observation's data, without `observed_at` ------------

FAILED = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}


def checks(repository: str, sha: str) -> tuple[str, list[dict[str, str]]]:
    """The check runs on a commit, summed up: success, failure, pending or none."""
    found = _get(f"/repos/{repository}/commits/{_quote(sha)}/check-runs?per_page=100")
    runs = (found or {}).get("check_runs", [])
    detail = [{"name": run["name"], "status": run.get("conclusion") or "pending"} for run in runs]
    if not detail:
        return "none", []
    states = {item["status"] for item in detail}
    if states & FAILED:
        return "failure", detail
    if "pending" in states:
        return "pending", detail
    return "success", detail


def pull_request(repository: str, number: int) -> dict[str, Any]:
    pr = _get(f"/repos/{repository}/pulls/{number}")
    if pr is None:
        return {"number": number, "found": False}
    merged = pr.get("merged_at") is not None
    mergeable = {True: "mergeable", False: "conflicting"}.get(pr.get("mergeable"), "unknown")
    if pr.get("mergeable_state") == "dirty":
        mergeable = "conflicting"
    head_sha = pr["head"]["sha"]
    summary, detail = checks(repository, head_sha)
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


def branch(repository: str, name: str) -> dict[str, Any]:
    found = _get(f"/repos/{repository}/branches/{_quote(name)}")
    if found is None:
        return {"name": name, "head_sha": None, "found": False}
    return {"name": name, "head_sha": found["commit"]["sha"], "found": True}


def tag(repository: str, name: str) -> dict[str, Any]:
    ref = _get(f"/repos/{repository}/git/ref/tags/{_quote(name)}")
    if ref is None or not isinstance(ref, dict):  # a list: no exact match, only prefixes
        return {"name": name, "sha": None, "found": False}
    target = ref["object"]
    sha = target["sha"]
    if target.get("type") == "tag":  # annotated: the commit it points at
        annotated = _get(f"/repos/{repository}/git/tags/{sha}")
        sha = annotated["object"]["sha"] if annotated else sha
    return {"name": name, "sha": sha, "found": True}
