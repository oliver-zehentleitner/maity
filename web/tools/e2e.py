#!/usr/bin/env python3
"""End-to-end test of the dashboard in a real browser against a real hub.

The hub runs on its own loopback port with a throwaway SQLite file and
serves this checkout's web/. A human works the dashboard in headless
Chromium (Playwright); an agent works through the `maity` CLI in scratch
git clones. The path, one screenshot per step:

  owner created (maity-hub owner create) -> sign in -> empty state ->
  create a project -> join line -> the agent joins with the CLI ->
  it claims a card (board) -> it asks, blocking the card -> its `maity wait`
  runs -> the owner answers in the inbox -> the wait wakes with the answer
  -> the card is unblocked -> a second project, the same agent joins it
  and asks -> the project switcher and its counts -> the cross-project
  "needs you" view (/all) -> answered there.

Every browser console error, page error and failed API call (status >= 400,
apart from the signed-out session check) fails the run. Each view is also
checked with axe-core at 1280 and 390 px, and dark at 1280 px; a serious or critical violation
fails the run after the last step, and every finding is written to
a11y.json and a11y.txt in the artifacts.

Needs `maity-hub` and `maity` on PATH and Playwright for Python with its
Chromium (see web/README.md, "Browser end-to-end test"):

  pip install -e hub -e cli -r web/requirements/e2e.in
  python -m playwright install chromium
  python web/tools/e2e.py --artifacts /path/to/screenshots

Exit 0 = every step passed. The hub is the one process this script starts
and it is stopped by its own PID; nothing else is touched.
"""

from __future__ import annotations

import argparse
import base64
import collections
import email
import email.policy
import fcntl
import hashlib
import hmac
import io
import json
import os
import re
import shlex
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright

WEB = Path(__file__).resolve().parent.parent
OWNER = "owner"
OWNER_PASSWORD = "e2e owner password"
OWNER_EMAIL = "owner@e2e.example"  # `owner create --email` stores it as verified (§2.1)
TIMEOUT_MS = 25_000  # one step in the browser; the feed reads every 15 s
COUNTS_MS = 70_000  # counts of other projects: /me is re-read every 60 s
TRACE_ANSWERS = 12  # the page's latest API answers shown when a step fails
TRACE_BODY = 1500  # characters of each body
WAIT_S = 60  # the agent's `maity wait`

# axe-core, the accessibility engine: the npm package's tarball, pinned by the
# registry's sha512 integrity and read without npm (web/context/stack.md).
AXE_VERSION = "4.14.0"
AXE_URL = f"https://registry.npmjs.org/axe-core/-/axe-core-{AXE_VERSION}.tgz"
AXE_SHA512 = (
    "9WTZxEjsZ7b13TH8JPmbV2z8CHbl80/2hm3XPEG4JgNdQLK81IBRXmSxHfMAOkSqQeRxT/0dwNDz2GOm3zzpcQ=="
)
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
AXE_FAIL = {"serious", "critical"}
# Light at desktop and phone width, then dark at desktop width.
PASSES = ((1280, 900, "light"), (390, 844, "light"), (1280, 900, "dark"))


def clean_environment(environ) -> dict:
    """Drop the caller's own MAITY_* settings (a state dir, a forge token) from `environ` and
    return what is left, so no process this run starts can act on the real hub."""
    for name in [k for k in environ if k.startswith("MAITY_")]:
        del environ[name]
    return dict(environ)


CLEAN_ENV = clean_environment(os.environ)


class Run:
    def __init__(self, artifacts: Path, work: Path, base: str):
        self.artifacts = artifacts
        self.work = work
        self.base = base
        self.shots = 0
        self.problems: list[str] = []
        self.axe = ""
        self.a11y_findings: list[dict] = []
        # The page's latest API answers, read back when a step fails (report_failure()): what
        # the hub said is told apart from what the page drew of it.
        self.recent: collections.deque = collections.deque(maxlen=TRACE_ANSWERS)

    def a11y(self, page: Page, view: str) -> None:
        """axe-core on the page as it stands, in each pass; after them the page is back at the
        viewport and colour scheme the step had (tsk-7eq8y3gymek2: it went to 1280 px, light, so a
        phone check after an a11y pass measured the desktop)."""
        size = page.viewport_size or {"width": 1280, "height": 900}
        dark = page.evaluate("matchMedia('(prefers-color-scheme: dark)').matches")
        # The restore is in a finally, so a pass that fails (axe throwing) still leaves the page as it
        # was; the error goes on (#1614 review).
        try:
            for width, height, scheme in PASSES:
                page.set_viewport_size({"width": width, "height": height})
                page.emulate_media(color_scheme=scheme)
                # From the page's top: content scrolled under the sticky header by an
                # earlier step would be measured against the header's links.
                page.evaluate("window.scrollTo(0, 0)")
                # Evaluated through the DevTools protocol, so the hub's CSP stays as it is.
                if not page.evaluate("typeof window.axe === 'object'"):
                    page.evaluate(self.axe)
                result = page.evaluate(
                    "tags => axe.run(document, {runOnly: {type: 'tag', values: tags},"
                    " resultTypes: ['violations']})",
                    AXE_TAGS,
                )
                for v in result["violations"]:
                    self.a11y_findings.append(
                        {
                            "view": view,
                            "width": width,
                            "scheme": scheme,
                            "id": v["id"],
                            "impact": v["impact"],
                            "help": v["help"],
                            "url": v["helpUrl"],
                            "nodes": [n["target"] for n in v["nodes"]][:10],
                            "count": len(v["nodes"]),
                            # axe's own words for the first node: which check failed and against what.
                            "why": v["nodes"][0].get("failureSummary", "") if v["nodes"] else "",
                            # ...and the elements it was measured against (a neighbour, an overlap).
                            "related": [
                                r["target"]
                                for c in (v["nodes"][0].get("any", []) + v["nodes"][0].get("all", []) if v["nodes"] else [])
                                for r in c.get("relatedNodes", [])
                            ][:5],
                        }
                    )
        finally:
            page.set_viewport_size({"width": size["width"], "height": size["height"]})
            page.emulate_media(color_scheme="dark" if dark else "light")
        print(f"   a11y {view}: 1280 and 390 px light, 1280 px dark", flush=True)

    def a11y_report(self) -> list[dict]:
        """Write every finding; return the ones that fail the run."""
        (self.artifacts / "a11y.json").write_text(json.dumps(self.a11y_findings, indent=2) + "\n")
        order = sorted(
            self.a11y_findings, key=lambda f: (f["impact"] not in AXE_FAIL, f["id"], f["view"])
        )
        lines = [
            f"{f['impact']:<8} {f['id']:<28} {f['view']} @ {f['width']} px {f['scheme']}:"
            f" {f['help']} ({f['count']} node(s), e.g. {f['nodes'][:3]})"
            for f in order
        ]
        (self.artifacts / "a11y.txt").write_text(
            f"axe-core {AXE_VERSION}, tags {', '.join(AXE_TAGS)}\n"
            + ("\n".join(lines) or "no findings")
            + "\n"
        )
        return [f for f in self.a11y_findings if f["impact"] in AXE_FAIL]

    def step(self, text: str) -> None:
        print(f"\n== {text}", flush=True)

    def shot(self, page: Page, name: str) -> None:
        self.shots += 1
        path = self.artifacts / f"{self.shots:02d}-{name}.png"
        # The sticky header would land mid-page in a full-page shot of a
        # scrolled page; from the top it stays where it belongs.
        page.evaluate("window.scrollTo(0, 0)")
        # The artifacts are public: the join line (URL and code) is painted over.
        page.screenshot(path=str(path), full_page=True, mask=[page.locator(".paste-line")])
        print(f"   screenshot {path.name}", flush=True)

    # The agent side: the maity CLI in one scratch clone per project.
    def maity(self, clone: Path, *args: str, stdin: str | None = None) -> str:
        done = subprocess.run(
            ["maity", *args],
            check=False,
            cwd=clone,
            env=CLEAN_ENV,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if done.returncode != 0:
            # A join code is single-use, but it still stays out of the log.
            shown = ["***" if i and args[i - 1] == "--code" else a for i, a in enumerate(args)]
            raise AssertionError(
                f"maity {' '.join(shown)} exited {done.returncode}:\n{done.stdout}{done.stderr}"
            )
        return done.stdout

    def maity_refused(self, clone: Path, *args: str, stdin: str | None = None) -> str:
        """Run a maity command that must fail; returns what it printed."""
        done = subprocess.run(
            ["maity", *args],
            check=False,
            cwd=clone,
            env=CLEAN_ENV,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert done.returncode != 0, f"maity {' '.join(args)} was expected to fail:\n{done.stdout}"
        return done.stdout + done.stderr

    def wait_start(self, clone: Path) -> subprocess.Popen:
        """The agent's `maity wait`, started after its own events (resume first)."""
        self.maity(clone, "resume")
        return subprocess.Popen(
            ["maity", "wait", "--one", "--timeout", str(WAIT_S)],
            cwd=clone,
            env=CLEAN_ENV,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    @staticmethod
    def wait_event(wait: subprocess.Popen) -> dict:
        try:
            out, err = wait.communicate(timeout=WAIT_S + 15)
        finally:
            if wait.poll() is None:
                wait.kill()
                wait.wait()
        assert wait.returncode == 0, f"maity wait exited {wait.returncode}: {out}{err}"
        return json.loads(out)

    def api(
        self, clone: Path, method: str, path: str, body: object | None = None, **query: object
    ) -> dict:
        args = ["api", method, path]
        for key, value in query.items():
            args[1:1] = ["--query", f"{key}={value}"]
        if body is not None:
            args[1:1] = ["--json", "-"]
        out = self.maity(clone, *args, stdin=None if body is None else json.dumps(body))
        return json.loads(out) if out.strip() else {}

    def clone(self, name: str) -> Path:
        path = self.work / name
        subprocess.run(["git", "init", "-q", str(path)], check=True, env=CLEAN_ENV)
        return path


def axe_source(cache: Path) -> str:
    """axe.min.js from the pinned tarball, downloaded once and checked every time."""
    tgz = cache / f"axe-core-{AXE_VERSION}.tgz"
    if not tgz.exists():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(AXE_URL, timeout=60) as response:
            data = response.read()
        part = tgz.with_suffix(".part")
        part.write_bytes(data)
        part.rename(tgz)
    data = tgz.read_bytes()
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != AXE_SHA512:
        raise SystemExit(f"e2e: {tgz} does not match the pinned sha512 of axe-core {AXE_VERSION}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        member = tar.extractfile("package/axe.min.js")  # read in memory, nothing extracted
        if member is None:
            raise SystemExit("e2e: the axe-core tarball has no package/axe.min.js")
        return member.read().decode("utf-8")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_taken(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
        return False


# One browser run at a time on a machine: agents share it, and two runs together ran it out of
# memory. A kernel lock goes with its process, however that ends; no stale file blocks anyone.
LOCK_PATH = Path("/tmp/maity-e2e.lock")
_machine_lock = None


def open_lock_file(path: Path) -> int:
    """The lock file, whichever user came first. Never O_CREAT on a file that exists: in sticky
    /tmp, fs.protected_regular refuses that for another user's file, whatever its mode."""
    while True:
        try:
            return os.open(path, os.O_RDWR)
        except FileNotFoundError:
            pass
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue  # another run made it just now
        os.fchmod(descriptor, 0o666)  # the mode above passes through the umask; holds no secret
        return descriptor


def take_machine_lock(path: Path = LOCK_PATH, say=print, every: float = 60, pause: float = 1) -> None:
    """Hold the machine's e2e lock until this process ends, waiting for it as long as it takes.
    In start_hub, not main, so that a script of a few lines borrowing the hub waits too."""
    global _machine_lock
    if _machine_lock is not None:  # a run starts several hubs
        return
    descriptor = open_lock_file(path)
    told = 0.0
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() - told >= every:
                told = time.monotonic()
                holder = os.pread(descriptor, 32, 0).decode(errors="replace").strip() or "?"
                say(f"another e2e holds {path} (pid {holder}); waiting", flush=True)
            time.sleep(pause)
    os.ftruncate(descriptor, 0)
    os.pwrite(descriptor, str(os.getpid()).encode(), 0)
    _machine_lock = descriptor


def start_hub(
    work: Path, logs: Path, port: int, extra: dict[str, str] | None = None, log_name: str = "hub.log"
) -> subprocess.Popen:
    """Migrate, create the owner and serve, with `extra` in the environment; every output goes
    to logs/<log_name>."""
    take_machine_lock()
    base = f"http://127.0.0.1:{port}"
    # A local store for attachments (§8.7), so the attachments step uploads for real:
    # messages name their attachments since E's #474, and the sent image is read back
    # from the hub.
    attachments = work / "attachments"
    attachments.mkdir(exist_ok=True)
    env = dict(
        CLEAN_ENV,
        MAITY_DATABASE_URL=f"sqlite:///{work / 'hub.db'}",
        MAITY_BIND=f"127.0.0.1:{port}",
        MAITY_PUBLIC_URL=base,
        MAITY_WEB_DIR=str(WEB),
        MAITY_ATTACHMENT_DIR=str(attachments),
        MAITY_PUBLIC_PAGES="on",
        **(extra or {}),
    )
    log_path = logs / log_name
    with open(log_path, "w") as log:  # the hub keeps its own copy of the descriptor
        for args, stdin in (
            (["migrate"], None),
            (
                [
                    "owner", "create", "--handle", OWNER, "--display-name", "Owner",
                    "--email", OWNER_EMAIL,
                ],  # fmt: skip
                OWNER_PASSWORD + "\n",
            ),
        ):
            log.write(f"$ maity-hub {' '.join(args)}\n")
            log.flush()
            done = subprocess.run(
                ["maity-hub", *args],
                env=env,
                input=stdin,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if done.returncode != 0:
                raise SystemExit(f"e2e: maity-hub {args[0]} failed:\n" + log_path.read_text())
        log.write("$ maity-hub serve\n")
        log.flush()
        hub = subprocess.Popen(
            ["maity-hub", "serve"], env=env, stdout=log, stderr=subprocess.STDOUT
        )
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/v1/health", timeout=1)
            except OSError:
                if hub.poll() is not None:
                    break
                time.sleep(0.2)
                continue
            # Answered, but by this hub? Another server on --port would also answer.
            if hub.poll() is None:
                return hub
            break
    except BaseException:  # Ctrl-C while waiting: the hub must not outlive the script
        stop_hub(hub)
        raise
    stop_hub(hub)
    raise SystemExit("e2e: the hub did not come up:\n" + log_path.read_text())


class MailCatcher:
    """A plain SMTP listener on 127.0.0.1 that keeps what it receives, so a round reads the
    mail the real hub sent. The standard library's has gone (`smtpd`, Python 3.12), and this
    is little enough not to add a dependency to the e2e."""

    def __init__(self) -> None:
        self.mails: list[tuple[list[str], EmailMessage]] = []
        catcher = self

        class Session(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                self.say("220 e2e catcher")
                rcpt: list[str] = []
                while line := self.rfile.readline():
                    verb = line[:4].upper()
                    if verb == b"QUIT":
                        self.say("221 bye")
                        return
                    if verb == b"RCPT":
                        rcpt.append(line.decode().split(":", 1)[1].strip().strip("<>"))
                    if verb == b"DATA":
                        self.say("354 go on")
                        raw = bytearray()
                        while (part := self.rfile.readline()) not in (b".\r\n", b""):
                            raw += part[1:] if part.startswith(b".") else part
                        catcher.mails.append(
                            (rcpt, email.message_from_bytes(bytes(raw), policy=email.policy.default))
                        )
                        rcpt = []
                    self.say("250 ok")

            def say(self, text: str) -> None:
                self.wfile.write(text.encode() + b"\r\n")

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Session)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def wait_for(self, to: str, timeout: float = 20) -> EmailMessage:
        """The first mail to `to`; fails the run when none comes in time."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for rcpt, message in self.mails:
                if to in rcpt:
                    return message
            time.sleep(0.1)
        raise AssertionError(f"no mail to {to} within {timeout} s; got {len(self.mails)}")

    def link_in(self, to: str, path: str, timeout: float = 20) -> str:
        """The first link under `path` in a mail to `to`, whichever mail carries it."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for rcpt, message in self.mails:
                body = message.get_body(("plain",))
                found = to in rcpt and body and re.search(r"https?://\S*" + path + r"\S+", body.get_content())
                if found:
                    return found.group(0)
            time.sleep(0.1)
        raise AssertionError(f"no {path} link to {to} within {timeout} s")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def totp_code(secret: str, step: int) -> str:
    """RFC 6238 from the secret the hub hands out, on purpose not the hub's own code."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), "sha1").digest()
    start = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[start : start + 4])[0] & 0x7FFFFFFF
    return str(value % 10**6).zfill(6)


def stop_hub(hub: subprocess.Popen) -> None:
    if hub.poll() is None:
        hub.terminate()  # exactly the PID this script started
        try:
            hub.wait(timeout=10)
        except subprocess.TimeoutExpired:
            hub.kill()
            hub.wait()


def watch_page(run: Run, page: Page) -> None:
    def console(msg) -> None:
        # Chromium logs every answer of 400 or more as "Failed to load
        # resource: the server responded with a status of …"; those are judged
        # by response() below, by their path. Network errors are not.
        if msg.type == "error" and "the server responded with a status of" not in msg.text:
            run.problems.append(f"console error: {msg.text}")

    def request_failed(req) -> None:
        # A navigation or a re-render may cancel a request the page no longer needs.
        if req.failure != "net::ERR_ABORTED":
            run.problems.append(f"{req.method} {req.url} failed: {req.failure}")

    def response(resp) -> None:
        path = resp.url.split(run.base, 1)[-1]
        if path.startswith("/api/v1/"):
            run.recent.append(resp)
        # Signed out, the page asks /auth/session first and expects 401.
        if resp.status >= 400 and not (
            resp.status == 401 and path.startswith("/api/v1/auth/session")
        ):
            run.problems.append(f"{resp.request.method} {path} answered {resp.status}")

    page.on("console", console)
    page.on("pageerror", lambda err: run.problems.append(f"page error: {err}"))
    page.on("response", response)
    page.on("requestfailed", request_failed)


def view_tab(page: Page, name: str):
    """A project view's tab. Its name carries a count while anything is open or
    unread ("Inbox 1 open", "Chat 2 unread"); otherwise it is the view's name alone."""
    pattern = re.compile(rf"^{re.escape(name)}( \d+ (open|unread))?$")
    return page.locator("nav.views").get_by_role("link", name=pattern)


def expect_inbox_empty(page: Page) -> None:
    """The empty inbox says "No open requests."."""
    # Not anchored: the empty entry also holds a hint.
    expect(page.get_by_text("No open requests.")).to_be_visible()


def project_settings(page: Page) -> None:
    """Opens the project's Settings tab (its last tab), drawn afresh."""
    view_tab(page, "Settings").click()
    expect(page).to_have_url(re.compile(r"/[^/]+/[^/]+/settings$"))
    expect(page.locator("#project-panel")).to_be_visible()


# What the trace of a failed step may show. It goes to a public artifact and to the Actions log, so
# every part is a closed set: a path keeps only the static route words below and shows every other
# segment (ids, tokens, codes, slugs, in any spelling) as `{}`; a body shows only the listed fields,
# each only with a value from its set, anything else as `?`. Nothing is copied by its shape.
TRACE_ROUTE = {
    "api", "v1", "me", "runners", "enrollments", "revoke", "pair", "join", "projects", "agents",
    "humans", "members", "tasks", "messages", "events", "attachments", "notifications", "invitations",
}
TRACE_ENUMS = {
    "credential_state": {"active", "revoked", "none", "pending", "expired"},
    "presence": {"online", "offline", "listening", "away", "busy"},
    "state": {"active", "revoked", "pending", "expired", "used", "removed"},
}
TRACE_CODES = {
    "forbidden", "not_found", "conflict", "unauthenticated", "unauthorized", "revoked", "rate_limited",
    "validation_error", "attachments_not_configured",
}
TRACE_ID = re.compile(r"(rnr|enr|agt|hum|prj|org)-[a-z0-9]{6,24}")


def trace_path(path: str) -> str:
    """The route without its query: static route words as they are, every other segment as `{}`."""
    parts = path.split("?", 1)[0].split("/")
    return "/".join(p if p in TRACE_ROUTE or not p else "{}" for p in parts)


def trace_data(value: object) -> object:
    """What of a JSON body may be shown: for the object or each of its `items`, the `id` (only a
    known prefix), `credential_state`, `presence` and `state` (only listed values); for an error,
    its `code` (only a listed one). Every other key and value is dropped."""
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return [trace_data(item) for item in value["items"][:5]]
    if not isinstance(value, dict):
        return None
    out: dict = {}
    item_id = value.get("id")
    if isinstance(item_id, str):
        out["id"] = item_id if TRACE_ID.fullmatch(item_id) else "?"
    for key, allowed in TRACE_ENUMS.items():
        if key in value:
            shown = value[key]
            out[key] = shown if isinstance(shown, str) and shown in allowed else "?"
    error = value.get("error")
    if isinstance(error, dict) and "code" in error:
        code = error["code"]
        out["error"] = {"code": code if isinstance(code, str) and code in TRACE_CODES else "?"}
    return out


def trace_line(method: str, path: str, status: int, text: str | None) -> str:
    """One answer: method, safe path, status and the allowlisted part of a JSON body."""
    try:
        if not text:
            raise ValueError("no body")
        data = trace_data(json.loads(text))
        shown = json.dumps(data, separators=(",", ":"), sort_keys=True)[:TRACE_BODY]
    except Exception:  # not JSON, or gone: not copied
        shown = "(body not shown)"
    return f"{method} {trace_path(path)} {status} {shown}"


def report_failure(answers: list, base: str, artifacts: Path) -> str:
    """Said when a step fails: the page's latest API answers, to `api-trace.txt` and to stderr.
    Both get the same text, built only by trace_line()."""
    lines = []
    for resp in answers:
        try:
            text = resp.text()
        except Exception:
            text = None
        lines.append(trace_line(resp.request.method, resp.url.split(base, 1)[-1], resp.status, text))
    trace = "\n".join(lines)
    (artifacts / "api-trace.txt").write_text(trace + "\n")
    print(f"\nthe page's last API answers (api-trace.txt):\n{trace}", file=sys.stderr)
    return trace


def no_problems(run: Run, where: str) -> None:
    if run.problems:
        raise AssertionError(f"{where}:\n  " + "\n  ".join(run.problems))


def create_project(run: Run, page: Page, name: str, slug: str) -> None:
    expect(page.get_by_role("heading", name="Create a project", exact=True)).to_be_visible()
    page.get_by_label("Name").fill(name)
    expect(page.get_by_label("Slug")).to_have_value(slug)  # proposed from the name
    page.get_by_role("button", name="Create project", exact=True).click()
    expect(page).to_have_url(re.compile(rf"/{OWNER}/{slug}/agents$"))
    expect(page.locator("header .project")).to_have_text(name)
    expect(page.locator(".project-created-page")).to_contain_text("This project is public")


def join_line(
    run: Run,
    page: Page,
    slug: str,
    handle: str | None,
    display: str = "E2E Agent",
    role: str = "coder",
    takes_over: str | None = None,
    handover: str | None = None,
    reports_to: str | None = None,
) -> tuple[str, str]:
    """Create a join line in the join panel on Agents; a new profile when handle is given.
    takes_over: the label of the agent member whose work the new one continues (§3.1).
    reports_to: the member id the new agent reports to (tsk-nbadjbr9zpg7); left out, nobody."""
    view_tab(page, "Agents").click()
    expect(page).to_have_url(re.compile(rf"/{OWNER}/{slug}/agents$"))
    # A project without an agent of one's own opens the panel itself;
    # otherwise the button at the head does. The panel is read beside the list, after it: wait
    # for one of the two, since the count line is drawn before either, and an
    # instant look could see neither and click a button that stays hidden.
    panel = page.locator(".join-panel")
    add = page.get_by_role("button", name="Join an agent", exact=True)
    expect(panel.or_(add).first).to_be_visible()
    if not panel.is_visible():
        add.click()
    expect(panel).to_be_visible()
    if handle:
        page.locator("#join-agent").select_option("")  # "A new agent profile…"
        expect(page.locator("#join-handle")).to_be_visible()
        page.locator("#join-handle").fill(handle)
        page.locator("#join-display").fill(display)
    else:
        # The existing profile is preselected.
        expect(page.locator("#join-agent")).not_to_have_value("")
    # The form's grid (tsk-t1xz7a1xq8ph): a row's fields start level at one height, and a
    # long option or hint stays in its column.
    if page.locator("#join-trust").is_visible():
        trust, chosen = page.locator("#join-trust").bounding_box(), page.locator("#join-role").bounding_box()
        assert abs(trust["y"] - chosen["y"]) < 1 and abs(trust["height"] - chosen["height"]) < 1, (trust, chosen)
    outside = page.evaluate(
        """() => Array.from(document.querySelectorAll('.join-fields .field')).filter((f) => f.offsetParent)
        .flatMap((f) => Array.from(f.children).filter((c) => c.offsetParent
          && c.getBoundingClientRect().right > f.getBoundingClientRect().right + 1).map((c) => c.id || c.tagName))"""
    )
    assert not outside, outside
    page.locator("#join-role").select_option(role)
    page.locator("#join-areas").fill("web/")
    expect(page.locator("#join-reports")).to_have_value("")
    if reports_to:
        page.locator("#join-reports").select_option(reports_to)
    if takes_over:
        page.locator("#join-takes-over").select_option(label=takes_over)
    if handover:
        page.locator("#join-handover").fill(handover)
    page.get_by_role("button", name="Create join line", exact=True).click()
    line = page.locator(".paste-line")
    expect(line).to_be_visible()
    # The new join is an open seat at the front of the grid.
    expect(page.locator("article.seat", has_text=display).first).to_contain_text(role)
    words = shlex.split(line.inner_text())
    if handle:
        # The new profile is offered and selected at once, without a reload: Join another shows it.
        page.locator(".join-result").get_by_role("button", name="Join another", exact=True).click()
        expect(page.locator("#join-agent option:checked")).to_contain_text(f"(@{handle})")
        panel.get_by_role("button", name="Close", exact=True).click()
    # The install line and the join in one command (§3.2): `<install> && maity join <url> --code <code>`.
    assert words[-6:-3] == ["&&", "maity", "join"] and words[-2] == "--code", words
    return words[-3], words[-1]


# The number of line boxes of each matching element's text.
ONE_LINE_JS = """sel => Array.from(document.querySelectorAll(sel)).map(el => {
  const range = document.createRange();
  range.selectNodeContents(el);
  return new Set(Array.from(range.getClientRects()).map(r => Math.round(r.top))).size;
})"""


# Each tab row's current tab, whether it lies fully inside the row's box.
CURRENT_SHOWN_JS = """() => Array.from(document.querySelectorAll("header nav")).map(nav => {
  const cur = nav.querySelector('[aria-current="page"]');
  if (!cur) return [nav.className, true];
  const n = nav.getBoundingClientRect(), c = cur.getBoundingClientRect();
  return [nav.className, c.left >= n.left - 1 && c.right <= n.right + 1];
})"""


def board_card(page: Page, title: str):
    return page.locator("article.card", has=page.get_by_text(title, exact=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--artifacts", type=Path, help="directory for the screenshots (default: a temp dir)"
    )
    parser.add_argument("--port", type=int, help="the hub's port (default: a free one)")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument(
        "--axe-cache",
        type=Path,
        default=Path(tempfile.gettempdir()) / "maity-e2e-axe",
        help="where the axe-core tarball is kept between runs",
    )
    args = parser.parse_args()

    for tool in ("maity-hub", "maity", "git"):
        if not shutil.which(tool):
            raise SystemExit(f"e2e: {tool} is not on PATH")

    port = args.port or free_port()
    if port == 8090:
        raise SystemExit("e2e: 8090 is the dogfood hub's port; pick another")
    if port_taken(port):
        raise SystemExit(f"e2e: something already listens on 127.0.0.1:{port}; pick another port")
    work = Path(tempfile.mkdtemp(prefix="maity-e2e-"))
    artifacts = args.artifacts or work / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{port}"
    run = Run(artifacts, work, base)
    run.axe = axe_source(args.axe_cache)
    run.step(f"hub on {base}, SQLite in {work}")
    hub = start_hub(work, artifacts, port)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            try:
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                context.set_default_timeout(TIMEOUT_MS)
                expect.set_options(timeout=TIMEOUT_MS)  # expect() has its own 5-s default
                page = context.new_page()
                watch_page(run, page)
                try:
                    scenario(run, page)
                    # Inside the same report: a failure in a later round shows its trace too (review of #997).
                    fixture_views(run, browser)
                    join_reports_layout(run, browser)
                    profile_public_link_layout(run, browser)
                    chat_height_views(run, browser)
                    chat_phone_views(run, browser)
                    chat_phone_head(run, browser)
                    paths_views(run, browser)
                    notification_sessions_layout(run, browser)
                    account_tabs_layout(run, browser)
                    jour_fixe_settings_layout(run, browser)
                    switch_busy_layout(run, browser)
                    second_hub_round(run, browser, work, artifacts)
                    security_round(run, browser, work, artifacts)
                    mail_factor_round(run, browser, work, artifacts)
                except Exception:
                    report_failure(list(run.recent), base, artifacts)
                    # What the page itself said before the step failed: its errors explain more than a missing element.
                    for problem in run.problems:
                        print("  page: " + problem)
                    raise
            finally:
                browser.close()
                failing = run.a11y_report()
        if failing:
            raise AssertionError(
                f"{len(failing)} serious or critical accessibility finding(s); see a11y.txt:\n  "
                + "\n  ".join(
                    f"{f['impact']} {f['id']} {f['view']} @ {f['width']} px {f['scheme']}"
                    for f in failing
                )
            )
    except Exception:
        print(
            f"\ne2e: FAILED; screenshots and hub.log in {artifacts}",
            file=sys.stderr,
        )
        raise
    finally:
        stop_hub(hub)
    print(f"\ne2e: every step passed; {run.shots} screenshots in {artifacts}")
    if not args.artifacts:
        print(f"   (work dir {work} kept for the screenshots)")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


def scenario(run: Run, page: Page) -> None:
    run.step("sign in as the owner created with maity-hub owner create")
    page.goto(run.base + "/")
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
    # The landing page's header and footer around it (§16.7.5), laid out by the hub's two stylesheets.
    expect(page.locator("header.site-header .signin")).to_have_text("Sign in")
    expect(page.locator("footer.site-footer nav.foot-col").first).to_be_visible()
    expect(page.locator("#header")).to_be_hidden()
    assert page.locator(".door-page").evaluate("e => getComputedStyle(e).display") == "grid"
    run.shot(page, "sign-in")
    run.a11y(page, "sign-in")
    page.locator("#login-email").fill(OWNER_EMAIL)
    page.locator("#login-password").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="No projects yet", exact=True)).to_be_visible()
    expect(page.locator("header .me")).to_contain_text("Owner")
    # Signed in, the frame is gone and its stylesheets off: landing.css would restyle the whole app.
    expect(page.locator("header.site-header, footer.site-footer")).to_have_count(0)
    on = "() => [...document.styleSheets].filter((s) => s.href && s.href.includes('/assets/landing/') && !s.disabled).length"
    assert page.evaluate(on) == 0
    run.shot(page, "empty-state")
    run.a11y(page, "empty state (/all, no projects)")
    no_problems(run, "sign-in")

    run.step("create a project")
    page.get_by_role("link", name="Create a project", exact=True).click()
    create_project(run, page, "E2E Alpha", "e2e-alpha")
    # At 1280 px the rows fit: no scroll cue.
    for nav in ("nav.views", "nav.switcher"):
        cls = page.locator(nav).get_attribute("class") or ""
        assert "more-" not in cls, f"{nav} shows a scroll cue at 1280 px ({cls!r})"
    run.shot(page, "project-created")
    run.a11y(page, "agents, empty")
    no_problems(run, "create a project")

    run.step("join line in the dashboard, the agent joins with the CLI")
    url, code = join_line(run, page, "e2e-alpha", "e2e-agent")
    run.shot(page, "join-line")
    run.a11y(page, "join with a paste line")
    alpha = run.clone("clone-alpha")
    out = run.maity(
        alpha,
        "join",
        url,
        "--code",
        code,
        "--harness",
        "e2e",
        "--model",
        "none",
        "--no-pointer",
        "--json",
    )
    agent_id = re.search(r"agt-[0-9a-z]+", out).group(0)
    print(f"   joined as {agent_id}")
    view_tab(page, "Team").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/team$"))
    agents = page.locator("main .members-agents")
    expect(agents).to_contain_text("@e2e-agent")
    expect(agents).to_contain_text("member")
    expect(agents).to_contain_text("Online")
    run.shot(page, "agent-joined")
    run.a11y(page, "agents")
    no_problems(run, "join")

    run.step("the agent claims a card; the open board offers a reload")
    view_tab(page, "Board").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/board$"))
    # The view has read the event head once its columns are drawn; what the
    # agent does from here on is offered as a reload.
    expect(page.get_by_role("region", name="Proposed")).to_be_visible()
    expect(page.locator("main .first-hint")).to_contain_text("No cards yet")
    task = run.api(
        alpha, "POST", "/projects/owner/e2e-alpha/tasks", {"title": "E2E card", "area": "web/"}
    )
    run.api(alpha, "POST", f"/projects/owner/e2e-alpha/tasks/{task['id']}/claim", {})
    reload = page.locator(".notice").get_by_role("button", name="Reload", exact=True)
    expect(page.get_by_text("The board changed.")).to_be_visible()
    run.shot(page, "board-changed")
    reload.click()
    card = board_card(page, "E2E card")
    expect(card).to_contain_text("Claimed by")
    # The holder by handle; the full name is its tooltip.
    expect(card.locator("p.claim strong")).to_have_attribute("title", "E2E Agent")
    run.shot(page, "card-claimed")
    run.a11y(page, "board")
    no_problems(run, "board")

    run.step("the agent asks, blocking its card; its maity wait runs")
    view_tab(page, "Inbox").click()
    expect_inbox_empty(page)
    out = run.maity(
        alpha,
        "ask",
        "Ship the e2e card?\nThe test asks this.",
        "--to",
        "human",
        "--class",
        "decision",
        "--option",
        "Ship it",
        "--option",
        "Hold it",
        "--task",
        task["id"],
        "--wait",
    )
    request_id = re.search(r"req-[0-9a-z]+", out).group(0)
    print(f"   asked {request_id}")
    run.maity(alpha, "resume")  # the wait starts after the agent's own events
    wait = subprocess.Popen(
        ["maity", "wait", "--one", "--timeout", str(WAIT_S)],
        cwd=alpha,
        env=CLEAN_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # The list was empty, so nothing was being read: it reloads on its own.
        entry = page.locator("li.entry.current")
        expect(entry).to_be_visible()
        expect(page.get_by_text("What waits for you changed")).to_have_count(0)
        expect(page.locator("main .notice[role=status]")).to_contain_text("1 new request.")
        expect(page.locator("nav.switcher a", has_text="E2E Alpha").locator(".count")).to_have_text(
            "1"
        )
        expect(entry).to_contain_text("Ship the e2e card?")
        expect(entry).to_contain_text("The test asks this.")
        run.shot(page, "inbox-request")
        run.a11y(page, "inbox with an open request")
        view_tab(page, "Board").click()
        expect(board_card(page, "E2E card")).to_contain_text(request_id)
        run.shot(page, "card-blocked")

        run.step("the owner answers in the inbox; the agent's wait wakes")
        view_tab(page, "Inbox").click()
        # The @ picker in the free text, open, under axe; then cleared again.
        free = page.locator("li.entry.current .free-text textarea")
        free.fill("@e2e")
        picker = page.locator("li.entry.current .mention-list")
        expect(picker.locator("li.mention-option").first).to_contain_text("@e2e-agent")
        expect(free).to_have_attribute("aria-activedescendant", re.compile(r"^mention-list-\d+-0$"))
        run.a11y(page, "inbox, @ picker open")
        free.press("Escape")
        expect(picker).to_be_hidden()
        # The one field stands above the buttons; a reply takes its text along (§7).
        # Talk beside the replies (the owner's agent asked), and Send for the words alone: disabled
        # while the field is empty.
        current = page.locator("li.entry.current")
        expect(current.get_by_role("button", name="Talk", exact=True)).to_be_enabled()
        free.fill("")
        expect(current.get_by_role("button", name="Send", exact=True)).to_be_disabled()
        free.fill("Ship it, with this note.")
        current.get_by_role("button", name="Ship it", exact=True).click()
        expect_inbox_empty(page)
        expect(
            page.locator("nav.switcher a", has_text="E2E Alpha").locator(".count")
        ).to_have_count(0)
        run.shot(page, "inbox-answered")
        stdout, stderr = wait.communicate(timeout=WAIT_S + 15)
    finally:
        if wait.poll() is None:
            wait.kill()
            wait.wait()
    assert wait.returncode == 0, f"maity wait exited {wait.returncode}: {stdout}{stderr}"
    event = json.loads(stdout)
    print(f"   maity wait woke on {event.get('kind')} for {event.get('subject')}")
    assert event.get("kind") == "request_answered", event
    assert event.get("subject") == {"type": "request", "id": request_id}, event
    answer = (event.get("payload") or {}).get("answer", {})
    assert answer.get("reply_id") == "o1", event
    assert answer.get("text") == "Ship it, with this note.", event
    view_tab(page, "Board").click()
    card = board_card(page, "E2E card")
    expect(card).to_contain_text("Claimed by")
    expect(card).not_to_contain_text(request_id)
    run.shot(page, "card-unblocked")
    no_problems(run, "answer")

    run.step("a second project, the same agent joins it and asks")
    # A new project is in the "+" menu; the row of tabs has none (tsk-hp9gq9rmrdq2).
    expect(page.locator("nav.switcher a[href='/new']")).to_have_count(0)
    page.locator("header").get_by_role("button", name="Add an agent, a person, a runner or a project", exact=True).click()
    page.get_by_role("menuitem", name="Project", exact=True).click()
    create_project(run, page, "E2E Beta", "e2e-beta")
    url, code = join_line(run, page, "e2e-beta", None)
    beta = run.clone("clone-beta")
    run.maity(
        beta, "join", url, "--code", code, "--harness", "e2e", "--model", "none", "--no-pointer"
    )
    run.maity(beta, "ask", "May the beta agent tag 0.1.0?", "--to", "human", "--class", "consent")
    run.maity(
        alpha,
        "ask",
        "Which colour for alpha?",
        "--to",
        "human",
        "--class",
        "info",
        "--priority",
        "high",
    )
    no_problems(run, "second project")

    run.step("the project switcher and its counts")
    switcher = page.locator("nav.switcher")
    expect(switcher.locator("a", has_text="E2E Beta").locator(".count")).to_have_text(
        "1", timeout=COUNTS_MS
    )
    expect(switcher.locator("a", has_text="E2E Alpha").locator(".count")).to_have_text(
        "1", timeout=COUNTS_MS
    )
    expect(
        switcher.get_by_role("link", name=re.compile("^All projects")).locator(".count")
    ).to_have_text("2")
    run.shot(page, "switcher-counts")
    switcher.locator("a", has_text="E2E Alpha").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/"))
    expect(page.locator("header .project")).to_have_text("E2E Alpha")
    expect(page.locator("li.entry.current")).to_contain_text("Which colour for alpha?")
    run.shot(page, "switched-to-alpha")
    no_problems(run, "switcher")

    run.step("everything waiting, across projects (/all)")
    switcher.get_by_role("link", name=re.compile("^All projects")).click()
    expect(page).to_have_url(re.compile(r"/all$"))
    entries = page.locator("li.entry")
    expect(entries).to_have_count(2)
    expect(entries.nth(0)).to_contain_text("E2E Alpha")  # high before normal
    expect(entries.nth(0)).to_contain_text("Which colour for alpha?")
    expect(entries.nth(1)).to_contain_text("E2E Beta")
    # Each entry's project as a link before it; a project filter; grouping by project.
    badge = entries.nth(0).locator("a.project-label")
    expect(badge).to_contain_text("E2E Alpha")
    expect(badge).to_have_attribute("href", "/owner/e2e-alpha/inbox")
    expect(entries.nth(0).locator(".entry-head")).to_have_accessible_name(re.compile(r"^E2E Alpha: "))
    page.locator("#inbox-project").select_option(f"{OWNER}/e2e-beta")
    expect(entries).to_have_count(1)
    expect(entries.nth(0)).to_contain_text("E2E Beta")
    page.locator("#inbox-project").select_option("")
    page.locator("#inbox-group").check()
    # One section per project, its heading and its own list of entries.
    groups = page.locator("section.entry-group")
    expect(groups).to_have_count(2)
    expect(groups.nth(0).get_by_role("heading")).to_contain_text("E2E Alpha")
    expect(groups.nth(0).locator("ol.entries > li.entry")).to_have_count(1)
    run.a11y(page, "/all grouped by project")
    page.locator("#inbox-group").uncheck()
    expect(entries).to_have_count(2)
    run.shot(page, "all-projects")
    run.a11y(page, "/all with requests")
    current = page.locator("li.entry.current")
    current.locator("textarea").fill("Blue.")
    current.get_by_role("button", name="Send", exact=True).click()
    expect(page.locator("li.entry.current")).to_contain_text("May the beta agent tag 0.1.0?")
    page.locator("li.entry.current").get_by_role("button", name="go", exact=True).click()
    expect_inbox_empty(page)
    expect(switcher.locator(".count")).to_have_count(0)
    run.shot(page, "all-answered")
    replies = run.maity(beta, "resume", "--json")
    got = json.loads(replies)["requests"]["answered_since_cursor"]
    assert [r.get("answer", {}).get("reply_id") for r in got] == ["go"], got
    no_problems(run, "all projects")

    id_links_step(run, page, alpha, task["id"])
    asker_links_step(run, page, alpha)
    send_talk_step(run, page, alpha)
    wide_lines_step(run, page, alpha, task["id"])
    note_edit_survives_redraw_step(run, page, alpha, task["id"])
    chat_pause_state(run, page, alpha, agent_id)
    group_chat_form_step(run, page)
    direct_removal_step(run, page, agent_id)
    attachments_step(run, page, agent_id)
    members_step(run, page)
    dormant_step(run, page)
    my_settings_step(run, page)
    project_tabs_step(run, page)
    invitations_step(run, page)
    agents_page_step(run, page)
    handle_hints_step(run, page)
    message_step(run, page, alpha, agent_id)
    release_contract(run, page, alpha, agent_id, task["id"])
    signing_step(run, page, alpha, agent_id)
    images_step(run, page, alpha)
    board_cards_step(run, page, alpha)

    why_step(run, page, alpha)
    runners_step(run, page)
    availability_step(run, page, alpha)
    agent_owners_step(run, page)
    isolate_step(run, page)
    memory_provider_step(run, page, alpha)

    run.step("phone width: no view scrolls sideways")
    run.maity(alpha, "ask", "Phone check?", "--to", "human", "--class", "consent")
    # 360 px as well, where a wrap shows whatever the fonts (tsk-et029v5k73f1); the a11y pass once.
    for phone, tall in ((390, 844), (360, 780)):
        suffix = "" if phone == 390 else f"-{phone}"
        page.set_viewport_size({"width": phone, "height": tall})
        page.goto(f"{run.base}/owner/e2e-alpha/inbox")
        # The text beside the logo is hidden from sight only: still in the page for a screen reader.
        expect(page.locator("header .bar > .project")).to_have_count(1)
        box = page.locator("header .bar > .project").bounding_box()
        assert box and box["width"] <= 1 and box["height"] <= 1, f"the header's text beside the logo shows at {phone} px: {box}"
        # Each view through its tab: the tab row scrolls sideways on its own, so
        # every tab has to stay reachable there.
        tabs = (
            ("inbox", "Inbox"),
            ("board", "Board"),
            ("overview", "Overview"),
            ("team", "Team"),
            ("agents", "Agents"),
        )
        # Why, where the hub offers it (its 409 ktw_not_configured is expected here).
        if view_tab(page, "Why").count():
            tabs += (("why", "Why"),)
        # Runners has no tab of its own any more (the maintainer, 2026-10-31): Settings links it.
        expect(view_tab(page, "Runners")).to_have_count(0)
        for view, tab in tabs:
            view_tab(page, tab).click()
            expect(page.locator(f"main section.view-{view}")).to_be_visible()
            if view == "inbox":
                expect(page.locator("li.entry.current")).to_contain_text("Phone check?")
            expect(page.locator("main .send-status.failed, main .error, main .page-failed")).to_have_count(0)
            width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            assert width[0] <= width[1], f"/owner/e2e-alpha/{view} is {width[0]} px wide at {width[1]} px"
            # The views row is wider than the phone; it shows a fade where more tabs are.
            cue = page.locator("nav.views").get_attribute("class") or ""
            assert "more-after" in cue or "more-before" in cue, f"{view}: no scroll cue ({cue!r})"
            # The current tab and project chip are scrolled into their rows.
            hidden = [cls for cls, shown in page.evaluate(CURRENT_SHOWN_JS) if not shown]
            assert not hidden, f"{view}: the current entry of nav.{hidden} is scrolled out of view"
            # Revoke keeps its label on one line: one line box for its text.
            lines = page.evaluate(ONE_LINE_JS, ".credentials button, .seat-actions button")
            assert all(n == 1 for n in lines), f"{view}: a Revoke label wraps ({lines} lines)"
            run.shot(page, f"phone-{view}{suffix}")
            run.problems = [p for p in run.problems if not ("/keep-the-why" in p and "answered 409" in p)]
        # The create form: its preset select has long option labels.
        page.locator("header").get_by_role("button", name="Add an agent, a person, a runner or a project", exact=True).click()
        page.get_by_role("menuitem", name="Project", exact=True).click()
        expect(page.locator("main section.view-new")).to_be_visible()
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert width[0] <= width[1], f"/new is {width[0]} px wide at {width[1]} px"
        run.shot(page, f"phone-new{suffix}")
        if phone == 390:
            run.a11y(page, "create a project")
            page.set_viewport_size({"width": phone, "height": tall})  # a11y ends at 1280x900; Runners is measured at phone width
        # The Runners view: the pairing form and its long install line; reached from the gear menu.
        page.locator("header").get_by_role("button", name="Settings", exact=True).click()
        page.get_by_role("menuitem", name="Runners", exact=True).click()
        expect(page.locator("main section.view-runners")).to_be_visible()
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert width[0] <= width[1], f"/runners is {width[0]} px wide at {width[1]} px"
        run.shot(page, f"phone-runners{suffix}")
    page.set_viewport_size({"width": 1280, "height": 900})  # where the a11y pass above left the steps below before 360 px was added
    no_problems(run, "phone width")

    users_step(run, page)
    registration_admin_step(run, page)
    reports_admin_step(run, page, alpha)
    forge_access_step(run, page)
    landing_json_step(run, page)
    start_page_step(run, page)
    legal_json_step(run, page)
    auth_pages_step(run, page)
    site_json_step(run, page)
    landing_variants_step(run, page)
    jour_fixe_step(run, page)
    project_links_step(run, page)
    join_expiry_step(run, page)
    change_password(run, page)
    picture_step(run, page)


def asker_links_step(run: Run, page: Page, alpha: Path) -> None:
    """Who asked, as links (tsk-3re8qp89hc18, docs/api.md §7): in the inbox of all projects too, the
    asker's handle leads to the member's page in the request's project, the #instance beside it to
    that instance on it, chosen."""
    run.step("inbox: Asked by links to the member and the instance, across projects too")
    out = run.maity(alpha, "ask", "Who asked this?\nThe asker's links are the point.", "--to", "human", "--class", "info")
    request_id = re.search(r"req-[0-9a-z]+", out).group(0)
    asked = run.api(alpha, "GET", f"/projects/owner/e2e-alpha/requests/{request_id}")["asked_by"]
    member_id, instance = asked["member_id"], asked.get("instance")
    assert instance, f"the request names no instance: {asked}"
    for inbox in ("/all", "/owner/e2e-alpha/inbox"):
        page.goto(f"{run.base}{inbox}")
        entry = page.locator(f"li.entry[data-request='{request_id}']")
        if entry.locator(".entry-body").count() == 0:
            entry.locator(".entry-head").first.click()
        facts = entry.locator(".entry-body dd").filter(has=page.locator(f"a.member-ref[data-member='{member_id}']")).first
        handle = facts.locator(f"a.member-ref[data-member='{member_id}']")
        expect(handle).to_have_attribute("href", f"/owner/e2e-alpha/team/{member_id}")
        mark = facts.locator("a.member-instance")
        expect(mark).to_have_text(f"#{instance}")
        if inbox == "/all":
            run.shot(page, "inbox-asker-links")
            # The project's link and the asker's in the rows one above the other: 24 px apart (WCAG 2.2).
            run.a11y(page, "/all, the asker's links under the project's")
        handle.click()
        expect(page).to_have_url(re.compile(rf"/owner/e2e-alpha/team/{member_id}$"))
        expect(page.locator(".member-head")).to_contain_text("E2E Agent")
        page.go_back()
        entry = page.locator(f"li.entry[data-request='{request_id}']")
        if entry.locator(".entry-body").count() == 0:
            entry.locator(".entry-head").first.click()
        entry.locator(".entry-body a.member-instance").first.click()
        expect(page).to_have_url(re.compile(rf"/owner/e2e-alpha/team/{member_id}/sessions/{instance}$"))
        expect(page.locator(f"#member-instance-{instance}")).to_have_attribute("aria-current", "true")
    page.goto(f"{run.base}/owner/e2e-alpha/inbox/{request_id}")
    current = page.locator("li.entry.current")
    current.locator("textarea").fill("Seen.")
    current.get_by_role("button", name="Send", exact=True).click()
    expect(page.locator(f"li.entry[data-request='{request_id}']")).to_have_count(0)
    no_problems(run, "asker links")


def send_talk_step(run: Run, page: Page, alpha: Path) -> None:
    """Send and Talk on every request one can answer (docs/api.md §7, tsk-nx6hm8qjzm3z): on a decision
    with options Send takes the words alone, Ctrl+Enter the same, and is disabled while the field is
    empty; on a consent it stays disabled and says why, the words go only with a reply. Talk for the
    owner's own agent. Wide and light, narrow and dark."""
    run.step("inbox: Send beside the options takes the words alone; a consent's Send says why it cannot")
    try:
        for width, height, scheme in ((1280, 900, "light"), (390, 844, "dark")):
            page.set_viewport_size({"width": width, "height": height})
            page.emulate_media(color_scheme=scheme)
            where = f"{width} px {scheme}"
            out = run.maity(
                alpha, "ask", f"Which name at {width} px?\nTwo to choose from, or your own.",
                "--to", "human", "--class", "decision", "--option", "Maity", "--option", "Hub",
            )
            request_id = re.search(r"req-[0-9a-z]+", out).group(0)
            page.goto(f"{run.base}/owner/e2e-alpha/inbox/{request_id}")
            current = page.locator("li.entry.current")
            expect(current).to_contain_text(f"Which name at {width} px?")
            send = current.get_by_role("button", name="Send", exact=True)
            expect(send).to_be_disabled()
            expect(current.get_by_role("button", name="Talk", exact=True)).to_be_enabled()
            expect(current.locator(".reply-hint")).to_have_count(0)
            free = current.locator(".free-text textarea")
            free.fill("Neither: maity-hub.")
            expect(send).to_be_enabled()
            run.shot(page, f"send-beside-options-{width}-{scheme}")
            free.press("Control+Enter")
            expect(page.locator(f"li.entry[data-request='{request_id}']")).to_have_count(0)
            got = run.api(alpha, "GET", f"/projects/owner/e2e-alpha/requests/{request_id}")
            answer = got.get("answer") or {}
            assert answer.get("text") == "Neither: maity-hub." and not answer.get("reply_id") and not answer.get("talk"), (
                f"{where}: Ctrl+Enter sends the words alone {answer}"
            )

        # A consent: the words alone would read as No (§15.6), so Send stays disabled and says why.
        out = run.maity(alpha, "ask", "May the alpha agent tag 0.2.0?", "--to", "human", "--class", "consent")
        request_id = re.search(r"req-[0-9a-z]+", out).group(0)
        page.goto(f"{run.base}/owner/e2e-alpha/inbox/{request_id}")
        current = page.locator("li.entry.current")
        expect(current).to_contain_text("May the alpha agent tag 0.2.0?")
        send = current.get_by_role("button", name="Send", exact=True)
        hint = current.locator(".reply-hint")
        expect(hint).to_contain_text("Choose one of the answers")
        expect(send).to_have_attribute("aria-describedby", hint.get_attribute("id") or "")
        free = current.locator(".free-text textarea")
        free.fill("Tag it after the notes.")
        expect(send).to_be_disabled()
        free.press("Control+Enter")
        expect(page.locator(f"li.entry[data-request='{request_id}']")).to_have_count(1)
        run.shot(page, "send-consent-disabled")
        run.a11y(page, "inbox, a consent with Send disabled and its reason")
        page.locator("li.entry.current").get_by_role("button", name="go", exact=True).click()
        expect_inbox_empty(page)
        got = run.api(alpha, "GET", f"/projects/owner/e2e-alpha/requests/{request_id}")
        answer = got.get("answer") or {}
        assert answer.get("reply_id") == "go" and answer.get("text") == "Tag it after the notes.", answer

        # The inbox reads its open requests first (tsk-y8gkq1kvt63c): the answered consent is
        # read alone by its link and opened among the answered, and Show -> all lists it, read then.
        lists: list[str] = []
        page.on("request", lambda r: lists.append(r.url.split("?", 1)[1]) if "/projects/owner/e2e-alpha/requests?" in r.url else None)
        page.goto(f"{run.base}/owner/e2e-alpha/inbox/{request_id}")
        current = page.locator("li.entry.current")
        expect(current).to_have_attribute("data-request", request_id)
        expect(current).to_have_class(re.compile(r"\bdone\b"))
        page.goto(f"{run.base}/owner/e2e-alpha/inbox")
        page.locator("#inbox-show").select_option("open")
        expect(page.locator(f"li.entry[data-request='{request_id}']")).to_have_count(0)
        page.locator("#inbox-show").select_option("all")
        expect(page.locator(f"li.entry[data-request='{request_id}']")).to_have_count(1)
        page.locator("#inbox-show").select_option("open")
        assert lists and all(q.startswith("status=open") or q.startswith("status=answered%2Cwithdrawn") or q.startswith("status=answered,withdrawn") for q in lists), lists
        assert not any(q.startswith("status=all") for q in lists), f"the inbox read the whole history: {lists}"
    finally:
        page.set_viewport_size({"width": 1280, "height": 900})
        page.emulate_media(color_scheme="light")
    no_problems(run, "send and talk")


def wide_lines_step(run: Run, page: Page, alpha: Path, card_id: str) -> None:
    """A long unbroken line keeps the page inside the window (tsk-6bn80bppb5e5): a request with a
    600-character code line and long card links, open in the inbox of all projects above a collapsed
    one, a card note and a project message with the same text, and a card link of 300 characters. The
    code scrolls in its own block, the links wrap, every row keeps the page's width; desktop and phone,
    light and dark."""
    run.step("a long line in a request and in a card note stays inside the window")
    line = ("for f in $(git ls-files 'web/i18n/*.json'); do " + "python3 -m json.tool \"$f\" >/dev/null && " * 20)[:600]
    links = " ".join(f"{run.base}/owner/e2e-alpha/tasks/{card_id}?from={'x' * 60}{i}" for i in range(4))
    text = f"Run this first:\n\n```sh\n{line}\n```\n\nThe cards: {links}"
    asked = [
        re.search(r"req-[0-9a-z]+", run.maity(alpha, "ask", title + "\n" + text, "--to", "human", "--class", "info")).group(0)
        for title in ("A request with a long line", "A short one below it")
    ]
    run.maity(alpha, "note", "add", card_id, text)
    run.maity(alpha, "say", "all", text, "--type", "notice")
    # A link without a label shows its URL: 300 characters with no place to break.
    long_url = f"https://github.com/owner/e2e-alpha/blob/main/{'x' * 255}"
    link = run.api(alpha, "POST", f"/projects/owner/e2e-alpha/tasks/{card_id}/links", {"kind": "url", "url": long_url})

    def inside(where: str) -> None:
        sw, iw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert sw <= iw, f"{where}: the page is {sw} px wide in a {iw} px window"

    try:
        for width, height, scheme in ((1280, 900, "light"), (2560, 1200, "dark"), (390, 844, "light"), (390, 844, "dark"), (360, 780, "light")):
            page.set_viewport_size({"width": width, "height": height})
            page.emulate_media(color_scheme=scheme)
            where = f"{width} px {scheme}"
            page.goto(f"{run.base}/all")
            wide = page.locator(f"li.entry[data-request='{asked[0]}']")
            expect(wide).to_be_visible()
            wide.locator(".entry-head").first.click()
            block = wide.locator(".entry-body .md-code")
            expect(block).to_be_visible()
            inside(f"the inbox at {where}")
            rows = page.evaluate("Array.from(document.querySelectorAll('li.entry')).map((e) => e.getBoundingClientRect().right)")
            assert rows and max(rows) <= width, f"the inbox at {where}: rows end at {max(rows)} px"
            client, scroll = block.evaluate("(b) => [b.clientWidth, b.scrollWidth]")
            assert scroll > client, f"the inbox at {where}: the code line does not scroll in its block ({client}/{scroll})"
            wider = wide.evaluate(
                "(r) => Array.from(r.querySelectorAll('.entry-body p')).filter((e) => !e.closest('.md-code'))"
                ".filter((e) => e.scrollWidth > e.clientWidth).map((e) => [e.clientWidth, e.scrollWidth])"
            )
            assert not wider, f"the inbox at {where}: text wider than its box {wider}"
            if width < 1280:
                run.shot(page, f"inbox-long-line-{scheme}" + ("" if width == 390 else f"-{width}"))

            page.goto(f"{run.base}/owner/e2e-alpha/tasks/{card_id}")
            note = page.locator("aside.card-panel .card-note-list li").filter(has_text="Run this first").first
            expect(note.locator(".md-code")).to_be_visible()
            expect(page.locator(f"aside.card-panel .card-links a[href='{long_url}']")).to_be_visible()
            inside(f"the card's notes at {where}")
            right = note.evaluate("(n) => n.querySelector('.md-code').getBoundingClientRect().right")
            assert right <= width, f"the card's notes at {where}: the code block ends at {right} px"
            # The links wrap: no text of the note but its code block wider than its box, the panel unscrolled.
            wider = note.evaluate(
                "(n) => Array.from(n.querySelectorAll('p, li')).filter((e) => !e.closest('.md-code'))"
                ".filter((e) => e.scrollWidth > e.clientWidth).map((e) => [e.tagName, e.clientWidth, e.scrollWidth])"
            )
            assert not wider, f"the card's notes at {where}: text wider than its box {wider}"
            panel = page.evaluate("(() => { const p = document.querySelector('aside.card-panel'); return [p.clientWidth, p.scrollWidth]; })()")
            assert panel[1] <= panel[0], f"the card panel at {where} scrolls sideways ({panel[0]}/{panel[1]})"

            # The project's messages: the same text, no panel around it to hide a wide line.
            page.goto(f"{run.base}/owner/e2e-alpha/messages")
            said = page.locator("li.pmsg").filter(has_text="Run this first").first
            expect(said.locator(".md-code")).to_be_visible()
            inside(f"the project's messages at {where}")
        run.a11y(page, "card notes, a long code line")
    finally:
        page.set_viewport_size({"width": 1280, "height": 900})
        page.emulate_media(color_scheme="light")
        run.api(alpha, "DELETE", f"/projects/owner/e2e-alpha/tasks/{card_id}/links/{link['id']}")
    for request_id in asked:
        page.goto(f"{run.base}/owner/e2e-alpha/inbox/{request_id}")
        current = page.locator("li.entry.current")
        current.locator("textarea").fill("Seen.")
        current.get_by_role("button", name="Send", exact=True).click()
        expect(page.locator(f"li.entry[data-request='{request_id}']")).to_have_count(0)
    expect_inbox_empty(page)
    no_problems(run, "long lines")


def note_edit_survives_redraw_step(run: Run, page: Page, alpha: Path, card_id: str) -> None:
    """An open note edit keeps its form, typed text, focus and caret when the notes list is drawn
    again (tsk-wvf8s7f44vz7): a post from Add a note redraws the list; Cancel still ends the edit.
    Desktop and phone, light — the state after load, not a layout fit."""
    run.step("an open note edit survives a post's redraw of the notes list")
    seed = "A note whose edit outlives a redraw"
    run.maity(alpha, "note", "add", card_id, seed)
    try:
        for width, height, scheme in ((1280, 900, "light"), (390, 844, "light")):
            page.set_viewport_size({"width": width, "height": height})
            page.emulate_media(color_scheme=scheme)
            where = f"{width} px {scheme}"
            page.goto(f"{run.base}/owner/e2e-alpha/tasks/{card_id}")
            panel = page.locator("aside.card-panel")
            expect(panel).to_be_visible()
            # Pin the note by id before Edit: once the form is open the body text is gone
            # (only the textarea holds it), so a has_text filter would miss the row.
            seeded = panel.locator("li.card-note").filter(has_text=seed).first
            expect(seeded).to_be_visible()
            note_id = seeded.get_attribute("data-note")
            assert note_id, f"{where}: the seed note has no data-note"
            note = panel.locator(f'li.card-note[data-note="{note_id}"]')
            note.locator("button.card-note-edit").click()
            form = note.locator("form.card-note-edit-form")
            expect(form).to_be_visible()
            field = form.locator("textarea")
            typed = f"typed across the redraw at {width}"
            field.fill(typed)
            field_node = field.evaluate_handle("(el) => el")
            posted = f"A post that redraws the list at {width}"
            add = panel.locator("form.card-note-form")
            add_body = add.locator("#card-note-body")
            # Set the post text without focusing Add a note, then leave focus and a caret
            # in the edit and submit: a button click would move focus off the edit before
            # the redraw, which is not the interaction under test.
            add_body.evaluate("(el, v) => { el.value = v; }", posted)
            field.evaluate(
                "(el) => { el.focus(); el.setSelectionRange(6, 11); }"
            )
            expect(field).to_be_focused()
            add.evaluate("(form) => form.requestSubmit()")
            expect(panel.locator("li.card-note").filter(has_text=posted)).to_be_visible()
            expect(form).to_be_visible()
            expect(field).to_have_value(typed)
            # Same DOM node, and document.activeElement is that node (not a fresh locator):
            # detach/reinsert must not hand focus to Add a note.
            assert field.evaluate(
                "(el, prev) => el === prev && el.isConnected", field_node
            ), f"{where}: the edit field was replaced"
            assert page.evaluate(
                "(prev) => document.activeElement === prev", field_node
            ), f"{where}: document.activeElement is not the kept edit node"
            assert field.evaluate(
                "(el) => [el.selectionStart, el.selectionEnd]"
            ) == [6, 11], f"{where}: the caret was not restored"
            assert add_body.evaluate(
                "(el) => document.activeElement !== el"
            ), f"{where}: focus moved to Add a note"
            form.get_by_role("button", name="Cancel", exact=True).click()
            expect(note.locator("form.card-note-edit-form")).to_have_count(0)
            expect(note.locator("button.card-note-edit")).to_be_visible()
            if width == 390:
                run.shot(page, "note-edit-survives-redraw-phone")
        run.a11y(page, "card panel, an open note edit after a post")
    finally:
        page.set_viewport_size({"width": 1280, "height": 900})
        page.emulate_media(color_scheme="light")
    no_problems(run, "note edit survives redraw")


def id_links_step(run: Run, page: Page, alpha: Path, card_id: str) -> None:
    """A card id in a request's text is a link to that card on the board."""
    run.step("an id in a request's text links to the card")
    out = run.maity(
        alpha, "ask", f"Which order after {card_id}?\nIt follows {card_id}.", "--to", "human",
        "--class", "info",
    )
    request_id = re.search(r"req-[0-9a-z]+", out).group(0)
    page.goto(f"{run.base}/owner/e2e-alpha/inbox/{request_id}")
    entry = page.locator("li.entry.current")
    expect(entry).to_contain_text(f"Which order after {card_id}?")
    link = entry.locator(".summary a.id-ref")
    expect(link).to_have_text(card_id)
    expect(link).to_have_attribute("href", f"/owner/e2e-alpha/tasks/{card_id}")
    expect(entry.locator(".title-refs a.id-ref")).to_have_text(card_id)
    run.a11y(page, "inbox, an id in the text as a link")
    link.click()
    expect(page).to_have_url(re.compile(rf"/owner/e2e-alpha/tasks/{card_id}$"))
    expect(page.locator(f'article.card.wanted[data-card="{card_id}"]')).to_be_visible()
    expect(
        view_tab(page, "Board")
    ).to_have_attribute("aria-current", "page")
    run.shot(page, "card-from-id-link")
    # The link opened the card's panel: its body, notes and history; on a
    # phone full width above the columns, nothing wider than the screen.
    panel = page.locator("aside.card-panel")
    expect(panel).to_be_visible()
    # The panel is the card: its id in the bar, its title the heading.
    expect(panel.locator(".card-panel-head .card-id")).to_have_text(card_id)
    expect(panel.locator("#card-panel-title")).to_be_focused()
    expect(panel.locator(".card-history-list li").first).to_contain_text("created the card")
    run.a11y(page, "board, a card's panel")
    # 360 px as well, where a wrap shows whatever the fonts (tsk-et029v5k73f1).
    for phone_width, phone_height in ((390, 844), (360, 780)):
        page.set_viewport_size({"width": phone_width, "height": phone_height})
        box = panel.bounding_box()
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert box and box["width"] >= 300 and width[0] <= width[1], f"the card's panel at {phone_width} px: {box}, page {width}"
        run.shot(page, "card-panel-phone" + ("" if phone_width == 390 else f"-{phone_width}"))
    panel.locator("#card-panel-title").press("Escape")
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/board$"))
    expect(panel).to_have_count(0)
    expect(page.locator(f'article.card.wanted[data-card="{card_id}"] a.card-open')).to_be_focused()
    page.set_viewport_size({"width": 1280, "height": 900})
    # On a phone (touch, 390 px) the card opens by a tap on its title.
    phone = page.context.browser.new_context(storage_state=page.context.storage_state(),
                                             viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    try:
        tapping = phone.new_page()
        tapping.goto(f"{run.base}/owner/e2e-alpha/board")
        tapping.locator(f'section.column article.card[data-card="{card_id}"] a.card-open').tap()
        expect(tapping.locator("aside.card-panel")).to_be_visible()
        expect(tapping).to_have_url(re.compile(rf"/owner/e2e-alpha/tasks/{card_id}$"))
        tapping.locator("aside.card-panel").get_by_role("button", name="Close", exact=True).tap()
        expect(tapping.locator("aside.card-panel")).to_have_count(0)
    finally:
        phone.close()
    page.goto(f"{run.base}/owner/e2e-alpha/inbox/{request_id}")
    current = page.locator("li.entry.current")
    current.locator("textarea").fill("After the release.")
    current.get_by_role("button", name="Send", exact=True).click()
    expect_inbox_empty(page)
    no_problems(run, "id links")


def attachments_step(run: Run, page: Page, agent_id: str) -> None:
    """§8.7: a file attached to a direct chat message; an image shown inline from the hub's own path."""
    page.goto(f"{run.base}/owner/e2e-alpha/chat/{agent_id}")
    # start_hub gives the hub a local store (MAITY_ATTACHMENT_DIR), so the real upload is
    # required: a hub that has them off or refuses the file is a broken store wiring here,
    # never a case to pass quietly. The off case is the smoke's (fixture mode, ?attachments=off).
    probe = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha/attachments?status=pending&limit=200")
    if probe.status != 200:
        code = (probe.json().get("error") or {}).get("code") if probe.headers.get("content-type", "").startswith("application/json") else None
        raise AssertionError(f"attachments: the hub runs with a store but answers its pending list {probe.status} {code}")
    page.locator("#chat-files").set_input_files(
        files=[{"name": "e2e-shot.png", "mimeType": "image/png", "buffer": tiny_png(32, 32, (40, 160, 90))}]
    )
    pending = page.locator(".attach-pending li", has_text="e2e-shot.png")
    # Uploaded once its Remove is there (the hub answered); a refusal is a failure here.
    expect(pending.get_by_role("button", name="Remove e2e-shot.png", exact=True)).to_be_visible()
    run.step("attachments: the owner sends an image to the agent; it shows inline from the hub")
    page.locator("#chat-text").fill("a picture")
    page.locator("form.compose").get_by_role("button", name="Send", exact=True).click()
    img = page.locator("ol.messages li.msg.out img.attach-image").last
    expect(img).to_have_attribute("src", re.compile(r"^/api/v1/projects/owner/e2e-alpha/attachments/[A-Za-z0-9_-]+/content$"))
    page.wait_for_function("() => { const i = [...document.querySelectorAll('img.attach-image')].pop(); return i && i.complete; }")
    assert page.evaluate("() => [...document.querySelectorAll('img.attach-image')].pop().naturalWidth") > 0
    run.a11y(page, "chat with an attachment")
    no_problems(run, "attachments")


def direct_removal_step(run: Run, page: Page, agent_id: str) -> None:
    """§8.5: the human party removes a message of its direct chat, with a reason; it reads as removed after a reload."""
    run.step("direct chat: the owner removes the agent's message with a reason; after a reload it still reads as removed")
    page.goto(f"{run.base}/owner/e2e-alpha/chat/{agent_id}")
    incoming = page.locator("ol.messages li.msg.in").first
    expect(incoming).to_be_visible()
    seq = incoming.get_attribute("data-seq")
    page.once("dialog", lambda d: d.accept("e2e: removed on purpose"))
    incoming.get_by_role("button", name="Remove this message for everyone", exact=True).click()
    removed = page.locator(f'ol.messages li.msg[data-seq="{seq}"]')
    expect(removed).to_contain_text("This message was removed by")
    expect(removed).to_contain_text("e2e: removed on purpose")
    page.reload()
    expect(page.locator(f'ol.messages li.msg[data-seq="{seq}"]')).to_contain_text("This message was removed")
    expect(page.locator(f'ol.messages li.msg[data-seq="{seq}"]').get_by_role("button", name="Quote this message")).to_have_count(0)
    no_problems(run, "direct removal")


def group_chat_form_step(run: Run, page: Page) -> None:
    """Group chats (docs/api.md §9.2): the create form, and one's own agent alone pointed to the direct chat."""
    page.goto(f"{run.base}/owner/e2e-alpha/chat")
    run.step("group chat: the owner opens New group chat; their own agent alone is the direct chat, said before anything is sent")
    page.locator(".chat-list-pane").get_by_role("link", name="New group chat", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/chat/new$"))
    form = page.locator("form.group-form")
    expect(form).to_be_visible()
    run.a11y(page, "new group chat")
    form.locator("fieldset.group-people input[type=checkbox]").first.check()
    form.get_by_role("button", name="Create", exact=True).click()
    error = page.locator("#group-people-error")
    if form.locator("fieldset.group-people input[type=checkbox]").count() == 1:
        expect(error).to_contain_text("That is your direct chat with")
        expect(error.get_by_role("link", name="open it")).to_have_attribute("href", re.compile(r"^/owner/e2e-alpha/chat/"))
    run.shot(page, "group-chat-new")
    no_problems(run, "group chat form")


def chat_pause_state(run: Run, page: Page, alpha: Path, agent_id: str) -> None:
    owner_id = json.loads(run.maity(alpha, "resume", "--json"))["me"]["owner"]["id"]

    run.step("chat: the agent writes with maity say human, the owner answers in the dashboard")
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    view_tab(page, "Chat").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/chat$"))
    page.locator("main section.view-chat").get_by_role("link", name=re.compile("E2E Agent")).click()
    expect(page).to_have_url(re.compile(rf"/owner/e2e-alpha/chat/{agent_id}$"))
    expect(page.get_by_role("heading", name="Chat with E2E Agent", exact=True)).to_be_visible()
    # The list stays beside the open chat and follows it.
    entry = page.locator(".chat-list a.conv", has_text="E2E Agent")
    expect(entry).to_have_attribute("aria-current", "page")
    run.maity(alpha, "say", "human", "Hello from the agent.")
    expect(page.locator("ol.messages li.msg.in")).to_contain_text("Hello from the agent.")
    # A short message is as tall as its text, not a share of the pane's height.
    first = page.locator("ol.messages li.msg.in").first.bounding_box()
    assert first is not None and first["height"] < 160, first
    # Markdown as the agent writes it: strong, inline code, a fenced block with Copy; raw HTML as text.
    run.maity(alpha, "say", "human", "**Done**: see `make check`.\n\n```sh\nmake smoke\n```\n<b>not bold</b>")
    last = page.locator("ol.messages li.msg.in").last
    expect(last.locator(".md strong")).to_have_text("Done")
    expect(last.locator(".md p code").first).to_have_text("make check")
    expect(last.locator(".md pre code")).to_have_text("make smoke")
    # Each Copy is named after its block, so several in one chat stay apart.
    expect(last.get_by_role("button", name=re.compile(r"^Copy Code \(sh\), block \d+$"))).to_be_visible()
    expect(last.get_by_role("region", name=re.compile(r"^Code \(sh\), block \d+$"))).to_be_visible()
    expect(last).to_contain_text("<b>not bold</b>")
    expect(last.locator("b")).to_have_count(0)
    # The preview needs the hub's last_message (docs/api.md §9); without it, none.
    listed = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha/conversations").json()
    if any("last_message" in c for c in listed["items"]):
        # The newest message: the Markdown one, its source as text.
        expect(entry.locator(".preview")).to_contain_text("**Done**: see `make check`.")
    else:
        expect(entry.locator(".preview")).to_have_count(0)
    wait = run.wait_start(alpha)
    page.locator("#chat-text").fill("Hello back from the owner.")
    page.locator("form.compose").get_by_role("button", name="Send", exact=True).click()
    expect(page.locator("ol.messages li.msg.out")).to_contain_text("Hello back from the owner.")
    run.shot(page, "chat")
    run.a11y(page, "chat")
    event = run.wait_event(wait)
    print(f"   maity wait woke on {event.get('kind')}: {(event.get('payload') or {}).get('body')}")
    assert event.get("kind") == "message", event
    assert event["payload"].get("body") == "Hello back from the owner.", event
    assert event["payload"].get("conversation_id") == agent_id, event
    # No event says the message reached the session; the agent's next event
    # (its resume emits session_started) makes the open chat re-read it.
    out_msg = page.locator("ol.messages li.msg.out").last
    expect(out_msg).to_contain_text("not picked up yet")
    run.maity(alpha, "resume")
    expect(out_msg).to_contain_text("reached a session")
    # The composer stays at the bottom: a growing history scrolls, it does not move.
    compose = page.locator("form.compose")
    before = compose.bounding_box()
    for n in range(12):
        run.maity(alpha, "say", "human", f"Line {n} of a longer history.")
    expect(page.locator("ol.messages li.msg.in").last).to_contain_text("Line 11 of a longer history.")
    after = compose.bounding_box()
    assert abs(after["y"] - before["y"]) < 1 and abs(after["height"] - before["height"]) < 1, (before, after)
    history = page.evaluate(
        "(() => { const m = document.querySelector('ol.messages');"
        " return [m.scrollHeight > m.clientHeight, m.scrollHeight - m.scrollTop - m.clientHeight]; })()"
    )
    assert history[0] and history[1] < 48, f"the history does not scroll or is not at its end: {history}"
    run.shot(page, "chat-long")
    # On a phone the list is one screen and the chat another.
    def fits(where: str) -> None:
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert width[0] <= width[1], f"{where} is {width[0]} px wide at {width[1]} px"

    for phone in (390, 360):
        page.set_viewport_size({"width": phone, "height": 780})
        expect(page.locator(".chat-list-pane")).to_be_hidden()
        page.get_by_role("link", name="← Conversations", exact=True).click()
        expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/chat$"))
        expect(entry).to_be_visible()
        fits(f"the chat list at {phone} px")
        run.shot(page, f"phone-{phone}-chat-list")
        entry.click()
        heading = page.get_by_role("heading", name="Chat with E2E Agent", exact=True)
        expect(heading).to_be_focused()
        expect(page.locator(".chat-list-pane")).to_be_hidden()
        fits(f"the chat at {phone} px")
        box = compose.bounding_box()
        assert box["y"] + box["height"] <= 780 + 1, f"the composer is below the screen at {phone} px: {box}"
        run.shot(page, f"phone-{phone}-chat")
        if phone == 390:
            # The composer folds away for reading (tsk-k6nakahy6fnj): the history gets its room.
            history = page.locator("ol.messages")
            reading = history.bounding_box()["height"]
            compose.get_by_role("button", name="Hide the composer", exact=True).click()
            expect(page.locator("#chat-text")).to_be_hidden()
            grown = history.bounding_box()["height"]
            assert grown >= reading * 1.5, f"hiding the composer left the history at {grown} px from {reading} px"
            run.shot(page, "phone-390-chat-composer-hidden")
            run.a11y(page, "chat, the composer hidden")
            # The check ends at its last width: back to the phone, where the button is.
            page.set_viewport_size({"width": phone, "height": 780})
            compose.get_by_role("button", name="Write a message", exact=True).click()
            expect(page.locator("#chat-text")).to_be_focused()
    page.set_viewport_size({"width": 1280, "height": 900})
    # On a wide screen the field grows to three times its height and back; no empty
    # band between it and its buttons.
    field = page.locator("#chat-text")
    one = field.bounding_box()["height"]
    actions = compose.locator(".compose-actions").bounding_box()
    gap = actions["y"] - (field.bounding_box()["y"] + one)
    assert gap <= 16, f"{gap} px between the message field and its buttons"
    compose.locator(".compose-size").get_by_role("button", name="3×", exact=True).click()
    three = field.bounding_box()["height"]
    assert three >= one * 2.5, f"3× made the field {three} px from {one} px"
    expect(compose.locator(".compose-size").get_by_role("button", name="3×", exact=True)).to_have_attribute("aria-pressed", "true")
    run.shot(page, "chat-composer-3x")
    compose.locator(".compose-size").get_by_role("button", name="1×", exact=True).click()
    assert abs(field.bounding_box()["height"] - one) < 2

    # The list's heading and its two actions as icons in one row (tsk-qgy2tb3w3x93): light and
    # dark, 390 and 1280 px, with and without the unread count on the Chat tab; the text is the
    # name and the tooltip; the focus ring shows on the keyboard's focus.
    def heading_row(where: str) -> None:
        row = page.evaluate(
            "(() => { const t = document.querySelector('.chat-list-pane .toolbar'), h = t.querySelector('h2');"
            " const box = (e) => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; };"
            " return { bar: box(t), h: box(h), icons: Array.from(t.querySelectorAll('a.icon-button')).map(box) }; })()"
        )
        h, icons = row["h"], row["icons"]
        assert len(icons) == 2, f"{where}: {len(icons)} icon actions in the heading's row"
        for left, top, right, bottom in icons:
            middle = (top + bottom) / 2
            assert h[1] <= middle <= h[3], f"{where}: an icon at {top}-{bottom} px is not in the heading's row {h[1]}-{h[3]}"
            assert left >= h[2] - 0.5 and right <= row["bar"][2] + 0.5, f"{where}: an icon at {left}-{right} px, heading ends {h[2]}"
            assert right - left >= 32 and bottom - top >= 32, f"{where}: an icon target of {right - left}×{bottom - top} px"
        fits(where)

    run.step("chat list: its two actions are icons beside the heading at every width")
    tab = view_tab(page, "Chat")
    try:
        for unread in (False, True):
            if unread:
                run.maity(alpha, "say", "human", "An unread line for the Chat tab's count.")
            for width, height, scheme in ((1280, 900, "light"), (1280, 900, "dark"), (390, 844, "light"), (390, 844, "dark")):
                page.set_viewport_size({"width": width, "height": height})
                page.emulate_media(color_scheme=scheme)
                page.goto(f"{run.base}/owner/e2e-alpha/chat")
                listing = page.locator(".chat-list-pane")
                expect(listing.locator(".toolbar h2")).to_have_text("Chat")
                expect(tab).to_have_accessible_name(re.compile(r"^Chat 1 unread$") if unread else "Chat")
                for name in ("New group chat", "Message the project"):
                    action = listing.get_by_role("link", name=name, exact=True)
                    expect(action).to_have_attribute("title", name)
                    expect(action).to_have_text("")
                where = f"the chat list at {width} px {scheme}{', unread' if unread else ''}"
                heading_row(where)
                run.shot(page, f"chat-list-icons-{width}-{scheme}{'-unread' if unread else ''}")
        # The keyboard reaches both, with the ring every focusable element has.
        listing.locator("a.new-group").focus()
        page.keyboard.press("Tab")
        ring = page.evaluate(
            "(() => { const a = document.activeElement, s = getComputedStyle(a);"
            " return [a.classList.contains('message-project'), a.matches(':focus-visible'), s.outlineStyle, parseFloat(s.outlineWidth)]; })()"
        )
        assert ring[0] and ring[1] and ring[2] == "solid" and ring[3] >= 2, f"the focus after New group chat: {ring}"
        run.shot(page, "chat-list-icons-focus")
        run.a11y(page, "chat list, its actions as icons")
    finally:
        page.emulate_media(color_scheme="light")
        page.set_viewport_size({"width": 1280, "height": 900})
    # Back to the conversation: reading it takes the count off the tab again.
    page.goto(f"{run.base}/owner/e2e-alpha/chat/{agent_id}")
    expect(page.get_by_role("heading", name="Chat with E2E Agent", exact=True)).to_be_visible()
    expect(page.locator("ol.messages li.msg.in").last).to_contain_text("An unread line for the Chat tab's count.")

    # The meat-proxy switch of this chat (§9.3, tsk-n872zkxmwbec): switched here, kept by the hub, given back to the profile.
    meat = compose.locator("button.meat-chat-toggle")
    follow = compose.get_by_role("button", name="Follow my profile", exact=True)
    expect(meat).to_have_attribute("aria-pressed", "false")
    expect(follow).to_be_hidden()
    meat.click()
    expect(meat).to_have_attribute("aria-pressed", "true")
    expect(follow).to_be_visible()
    convs = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha/conversations").json()["items"]
    entry = next(p for c in convs if (c.get("agent_id") or c["id"]) == agent_id for p in c["participants"] if p["kind"] == "human")
    assert entry["meat_proxy"] is True and entry["meat_proxy_chat"] is True and entry.get("meat_proxy_note"), entry
    assert entry["meat_proxy_lead"] is True and entry["meat_proxy_hands"] is False, entry
    follow.click()
    expect(meat).to_have_attribute("aria-pressed", "false")
    expect(follow).to_be_hidden()
    convs = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha/conversations").json()["items"]
    entry = next(p for c in convs if (c.get("agent_id") or c["id"]) == agent_id for p in c["participants"] if p["kind"] == "human")
    assert entry["meat_proxy_chat"] is None, entry
    no_problems(run, "chat")

    run.step("global chat: /chats has every project's chats and opens one in place")
    page.locator("header a.chat-button").click()
    expect(page).to_have_url(re.compile(r"/chats$"))
    # The hash changes before the view: wait for the global list, not the project's that is still there.
    expect(page.locator(".chat-list-pane h2")).to_have_text("Chats")
    g_entry = page.locator(".chat-list a.conv.with-project", has_text="E2E Agent").first
    expect(g_entry).to_have_attribute("href", re.compile(rf"^/chats/owner/e2e-alpha/{agent_id}$"))
    expect(g_entry).to_contain_text("in ")
    g_entry.click()
    expect(page).to_have_url(re.compile(rf"/chats/owner/e2e-alpha/{agent_id}$"))
    expect(page.get_by_role("heading", name="Chat with E2E Agent", exact=True)).to_be_visible()
    expect(page.locator(".chat-list a.conv[aria-current=page]")).to_have_count(1)
    # A pin (§9.3, tsk-645p1nw2v7y4): kept by the hub, shown as a mark, the button pressed; then taken off again.
    # The pin buttons are hidden until the toggle in the heading row shows them (tsk-4nf344w4c52c).
    column = page.locator(".chat-list-pane button.pin-column-toggle")
    expect(column).to_have_attribute("aria-pressed", "false")
    expect(page.locator(".chat-list button.pin-toggle")).to_have_count(0)
    column.click()
    expect(column).to_have_attribute("aria-pressed", "true")
    pin = page.locator(".chat-list li").filter(has_text="E2E Agent").first.locator("button.pin-toggle")
    expect(pin).to_have_attribute("aria-pressed", "false")
    pin.click()
    expect(pin).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".chat-list a.conv.with-project", has_text="E2E Agent").first.locator(".pin-mark")).to_be_visible()
    mine = page.request.get(f"{run.base}/api/v1/me/conversations").json()["items"]
    assert any(c["id"] == agent_id and c["pinned"] for c in mine), mine
    pin.click()
    expect(pin).to_have_attribute("aria-pressed", "false")
    mine = page.request.get(f"{run.base}/api/v1/me/conversations").json()["items"]
    assert not any(c["pinned"] for c in mine), mine
    column.click()
    expect(page.locator(".chat-list button.pin-toggle")).to_have_count(0)
    page.locator("#chat-text").fill("Hello from the global chat.")
    page.locator("form.compose").get_by_role("button", name="Send", exact=True).click()
    expect(page.locator("ol.messages li.msg.out").last).to_contain_text("Hello from the global chat.")
    # No project feed here: the notifications stream brings the agent's answer in.
    run.maity(alpha, "say", "human", "A reply seen in the global chat.")
    expect(page.locator("ol.messages li.msg.in").last).to_contain_text("A reply seen in the global chat.", timeout=20000)
    run.a11y(page, "global chat")
    page.set_viewport_size({"width": 390, "height": 780})
    expect(page.locator(".chat-list-pane")).to_be_hidden()
    page.get_by_role("link", name="← Conversations", exact=True).click()
    expect(page).to_have_url(re.compile(r"/chats$"))
    expect(page.locator(".chat-list-pane")).to_be_visible()
    fits("the global chat list at 390 px")
    # The toggle stays on screen beside the heading's row on a phone, shown or not, light and dark.
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        for shown in ("false", "true"):
            toggle = page.locator(".chat-list-pane button.pin-column-toggle")
            if toggle.get_attribute("aria-pressed") != shown:
                toggle.click()
            box = toggle.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, f"the pin toggle leaves the screen at 390 px {scheme}: {box}"
            fits(f"the global chat list at 390 px, {scheme}, pin buttons {'shown' if shown == 'true' else 'hidden'}")
    if page.locator(".chat-list-pane button.pin-column-toggle").get_attribute("aria-pressed") == "true":
        page.locator(".chat-list-pane button.pin-column-toggle").click()
    page.emulate_media(color_scheme="light")
    # 360 px as well, where a wrap shows whatever the fonts (tsk-et029v5k73f1).
    page.set_viewport_size({"width": 360, "height": 780})
    expect(page.locator(".chat-list-pane")).to_be_visible()
    fits("the global chat list at 360 px")
    page.set_viewport_size({"width": 1280, "height": 900})
    no_problems(run, "global chat")
    # Back where the chat step left the page: the project's chat with the agent.
    page.goto(f"{run.base}/owner/e2e-alpha/chat/{agent_id}")
    expect(page.get_by_role("heading", name="Chat with E2E Agent", exact=True)).to_be_visible()

    run.step("pause: the owner pauses the agent; the agent cannot lift it itself")
    # The pause is in the agent's row on Members (tsk-7v2snhk002ak), once.
    view_tab(page, "Team").click()
    agents = page.locator("main .members-agents")
    agents.get_by_role("button", name="Manage E2E Agent", exact=True).click()
    form = agents.locator("form.member-pause")
    expect(form).to_contain_text(
        "A pause tells the agent at once and refuses it new work (claims, new cards)"
    )
    page.locator(f"#member-pause-{agent_id}").fill("e2e: hold on")
    form.get_by_role("button", name="Pause", exact=True).click()
    expect(agents).to_contain_text("paused by Owner")
    expect(agents).to_contain_text("e2e: hold on")
    expect(agents).to_contain_text("The agent was told at once and gets no new work")
    expect(agents.get_by_role("button", name="Clear pause", exact=True)).to_be_visible()
    run.shot(page, "paused")
    run.a11y(page, "agents with a human pause")
    out = run.maity_refused(alpha, "api", "--json", "-", "PATCH", "/me", stdin='{"paused": null}')
    assert "forbidden" in out and "a human paused you" in out, out
    # A resume clears the agent's own pause, never a human's; the packet
    # tells the agent about it (membership.paused, docs/api.md §5.2).
    packet = json.loads(run.maity(alpha, "resume", "--json"))
    paused = packet["membership"].get("paused") or {}
    assert paused.get("by") == owner_id and paused.get("reason") == "e2e: hold on", packet[
        "membership"
    ]
    page.reload()
    expect(agents).to_contain_text("e2e: hold on")  # still paused after its resume
    agents.get_by_role("button", name="Manage E2E Agent", exact=True).click()
    agents.get_by_role("button", name="Clear pause", exact=True).click()
    # Cleared: no Clear pause, the pause form offered again in the row.
    expect(agents.get_by_role("button", name="Clear pause", exact=True)).to_have_count(0)
    expect(agents.locator("form.member-pause")).to_be_visible()
    agents.get_by_role("button", name="Done managing E2E Agent", exact=True).click()

    def own_pause() -> dict | None:
        # The agent's own pause is its instance's (§6.17); the membership's stays clear.
        members = run.api(alpha, "GET", "/projects/owner/e2e-alpha/members")["items"]
        member = next(m for m in members if m["id"] == agent_id)
        assert member.get("paused") is None, member
        (instance,) = member["instances"]  # the one CLI agent of this run
        return instance.get("paused")

    assert own_pause() is None, own_pause()
    run.api(alpha, "PATCH", "/me", {"paused": {"reason": "e2e: out of quota"}})
    mine = own_pause()
    assert mine and mine["by"] == agent_id and mine["reason"] == "e2e: out of quota", mine
    run.api(alpha, "PATCH", "/me", {"paused": None})  # its own pause, it may lift
    assert own_pause() is None, own_pause()
    no_problems(run, "pause")

    briefing_step(run, page, alpha, agent_id)

    run.step("state and absence: the owner moves the project to review; the agent's resume shows it")
    cursor = run.api(alpha, "GET", "/projects/owner/e2e-alpha/events", after="latest", wait=0)["cursor"]
    project_settings(page)
    page.locator("#state-select").select_option("review")
    page.locator("#state-note").fill("e2e review: fixes only")
    page.locator("#state-reason").fill("e2e: release candidate")
    page.get_by_role("button", name="Change state", exact=True).click()
    expect(page.locator("header .state")).to_have_text("Review")
    expect(page.locator("header .state-note")).to_have_text("e2e review: fixes only")
    project_settings(page)
    # Availability caps an absence at 90 days. Choose next week in the browser's
    # local timezone so this scenario remains valid as the calendar moves on.
    absence = page.evaluate("""() => {
      const until = new Date();
      until.setDate(until.getDate() + 7);
      until.setHours(10, 0, 0, 0);
      const pad = n => String(n).padStart(2, "0");
      return {
        input: `${until.getFullYear()}-${pad(until.getMonth() + 1)}-${pad(until.getDate())}T10:00`,
        iso: until.toISOString(),
        date: until.toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" }),
      };
    }""")
    page.locator("#absence-until").fill(absence["input"])
    page.locator("#absence-scope").fill("e2e: the admins decide merges")
    page.get_by_role("button", name="Set absence", exact=True).click()
    expect(page.locator("header .absence")).to_contain_text("e2e: the admins decide merges")
    expect(page.locator("header .project-state .away")).to_contain_text(
        re.compile(r"Away until " + re.escape(absence["date"]) + r", 10:00")
    )
    # The state block sits at the projects' right, in their row, behind a separator;
    # on a phone it goes under them, and nothing scrolls sideways.
    chips = page.locator("header nav.switcher").bounding_box()
    block = page.locator("header .project-state").bounding_box()
    assert block["x"] >= chips["x"] + chips["width"] and abs(block["y"] - chips["y"]) < chips["height"], (chips, block)
    page.set_viewport_size({"width": 360, "height": 780})
    block = page.locator("header .project-state").bounding_box()
    assert block["x"] >= 0 and block["x"] + block["width"] <= 361, block
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1], f"the header is {width[0]} px wide at {width[1]} px"
    # The profile menu at 360 px: on screen, closed by Escape, the focus back on its button.
    profile = page.locator("header").get_by_role("button", name=re.compile(r"^Your profile: "))
    profile.click()
    menu = page.get_by_role("menu", name=re.compile(r"^Your profile: "))
    expect(menu).to_be_visible()
    box = menu.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 361, f"the profile menu leaves the screen: {box}"
    run.a11y(page, "header, profile menu open")
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(profile).to_be_focused()
    page.set_viewport_size({"width": 1280, "height": 900})
    # The switcher's state dot: Alpha in review differs from Beta, which builds.
    dots = page.evaluate("""() => ["E2E Alpha", "E2E Beta"].map(name => {
      const chip = Array.from(document.querySelectorAll("nav.switcher a")).find(a => a.textContent.includes(name));
      return getComputedStyle(chip.querySelector(".dot")).backgroundColor;
    })""")
    assert dots[0] != dots[1], f"the switcher shows one colour for review and build: {dots}"
    run.shot(page, "review-absence")
    run.a11y(page, "header in review with absence")
    view_tab(page, "Team").click()
    page.locator("main nav.team-tabs").get_by_role("link", name="Organisation", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/organisation$"))
    expect(page.locator("main .org-tree")).to_be_visible()
    run.a11y(page, "team page, organisation tab")
    project = json.loads(run.maity(alpha, "resume", "--json"))["project"]
    print(f"   resume: state {project['state']}, absence {project['absence']}")
    assert project["state"] == "review" and project["state_note"] == "e2e review: fixes only", (
        project
    )
    assert (project.get("absence") or {}).get("scope") == "e2e: the admins decide merges", project
    assert project["absence"]["until"] == absence["iso"].replace(".000Z", "Z"), project
    log = run.api(alpha, "GET", "/projects/owner/e2e-alpha/events", after=cursor, wait=0)["items"]
    change = next((e for e in log if e["kind"] == "state_changed"), None)
    assert change, log
    payload = change["payload"]
    assert (payload["old"], payload["new"], payload["reason"]) == (
        "build",
        "review",
        "e2e: release candidate",
    ), change
    project_settings(page)
    page.get_by_role("button", name="I am back", exact=True).click()
    expect(page.locator("header .absence")).to_have_count(0)
    project_settings(page)
    page.locator("#state-select").select_option("build")
    page.locator("#state-reason").fill("e2e: back to building")
    page.get_by_role("button", name="Change state", exact=True).click()
    expect(page.locator("header .state")).to_have_text("Build")
    project = json.loads(run.maity(alpha, "resume", "--json"))["project"]
    assert project["state"] == "build" and project["absence"] is None, project
    no_problems(run, "state and absence")


def tiny_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A one-colour PNG, built here so the test needs no image file."""
    row = b"\x00" + bytes(rgb) * width
    raw = zlib.compress(row * height, 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def images_step(run: Run, page: Page, alpha: Path) -> None:
    """The project's logo and banner (docs/api.md §11.2)."""
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    chip = page.locator("nav.switcher a", has_text="E2E Alpha")
    run.step("images: the owner uploads a logo and a banner, then removes the logo")
    expect(chip.locator(".project-mark.monogram")).to_have_text(
        "EA"
    )  # no repository, no forge image
    project_settings(page)
    page.locator("#upload-logo").set_input_files(
        files=[{"name": "notes.txt", "mimeType": "image/png", "buffer": b"not an image at all"}]
    )
    expect(page.locator("#project-panel")).to_contain_text(
        "Logo not uploaded: not a PNG, JPEG or WebP image"
    )
    page.locator("#upload-logo").set_input_files(
        files=[
            {
                "name": "logo.png",
                "mimeType": "image/png",
                "buffer": tiny_png(64, 64, (26, 102, 217)),
            }
        ]
    )
    mark = page.locator("header .bar img.project-mark")
    expect(mark).to_have_attribute("src", re.compile(r"^/api/v1/projects/owner/e2e-alpha/logo\?v="))
    expect(chip.locator("img.project-mark")).to_be_visible()
    # The src is set before the image has arrived: wait until the browser is
    # done with it (loaded, or failed with naturalWidth 0), then judge.
    page.wait_for_function(
        "() => { const i = document.querySelector('header .bar img.project-mark'); return i && i.complete; }"
    )
    assert (
        page.evaluate("() => document.querySelector('header .bar img.project-mark').naturalWidth")
        == 64
    ), "the logo did not load from the hub"
    # The tab's icon follows each header render (one may still carry the
    # project view from before the upload): wait for it, never read it once.
    expect(page.locator("head link[rel=icon]")).to_have_attribute(
        "href", re.compile(r"/api/v1/projects/owner/e2e-alpha/logo\?v=")
    )
    # The panel opened again by itself to say the logo was uploaded.
    expect(page.locator("#project-panel")).to_contain_text("Logo uploaded.")
    page.locator("#upload-banner").set_input_files(
        files=[
            {
                "name": "banner.png",
                "mimeType": "image/png",
                "buffer": tiny_png(640, 320, (122, 63, 196)),
            }
        ]
    )
    expect(page.locator("#project-panel")).to_contain_text("Banner uploaded.")
    view_tab(page, "Inbox").click()
    banner = page.locator("main img.project-banner")
    expect(banner).to_have_attribute("src", re.compile(r"^/api/v1/projects/owner/e2e-alpha/banner\?v="))
    expect(banner).to_be_visible()
    shown = run.api(alpha, "GET", "/projects/owner/e2e-alpha")
    assert shown["logo"]["source"] == "uploaded" and shown["banner"]["source"] == "uploaded", shown
    run.shot(page, "logo-and-banner")
    run.a11y(page, "inbox with a logo and a banner")
    project_settings(page)
    run.a11y(page, "project settings with images")
    # The restricted-access list open (§6.1): each member's box is a target of its own (WCAG 2.2).
    page.select_option("#restricted-mode", "nobody_except")
    expect(page.locator("fieldset.restricted-members")).to_be_visible()
    run.a11y(page, "project settings, the restricted-access member list open")
    page.select_option("#restricted-mode", "")
    page.get_by_role("button", name="Remove the uploaded logo", exact=True).click()
    expect(page.locator("header .bar .project-mark.monogram")).to_have_text("EA")
    expect(page.locator("#project-panel")).to_contain_text("Uploaded logo removed")
    project_settings(page)
    assert run.api(alpha, "GET", "/projects/owner/e2e-alpha")["logo"]["available"] is False
    no_problems(run, "images")


def security_round(run: Run, browser, work: Path, artifacts: Path) -> None:
    """The setup of the second factor in the page, against the real hub (§2.8.5, §2.8.7): as the
    one page of a session that must enrol, and on the account, each on a hub of its own policy."""
    first_base = run.base
    try:
        for policy, walk in (("required_admins", enrolment_page), ("optional", security_section)):
            home = work / f"hub-{policy}"
            home.mkdir()
            port = free_port()
            run.base = f"http://127.0.0.1:{port}"
            run.step(f"hub on {run.base} with the second factor {policy}")
            extra = {
                "MAITY_SECRET_KEY": base64.b64encode(os.urandom(32)).decode(),
                "MAITY_SIGN_IN_SECOND_FACTOR": policy,
            }
            hub = start_hub(home, artifacts, port, extra, f"hub-{policy}.log")
            try:
                walk(run, browser)
            finally:
                stop_hub(hub)
    finally:
        run.base = first_base


def signed_in_page(run: Run, browser):
    """The first factor only: what comes next is the hub's to say."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.set_default_timeout(TIMEOUT_MS)
    page = context.new_page()
    watch_page(run, page)
    page.goto(run.base + "/")
    page.locator("#login-email").fill(OWNER_EMAIL)
    page.locator("#login-password").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    return context, page


def set_up_factor(page: Page) -> str:
    """To the code: the QR is drawn and the key is readable. The key, for the code."""
    page.get_by_role("button", name="Set up two-factor sign-in", exact=True).click()
    expect(page.locator(".qr-box svg")).to_be_visible()
    return page.locator(".security-key").inner_text()


def turn_on(page: Page, code: str) -> None:
    page.locator("#security-code").fill(code)
    page.get_by_role("button", name="Turn on", exact=True).click()


def enrolment_page(run: Run, browser) -> None:
    run.step("must enrol: the setup is the page, the codes download, then the dashboard")
    context, page = signed_in_page(run, browser)
    expect(page.get_by_role("heading", name="Set up two-factor sign-in", exact=True)).to_be_visible()
    run.a11y(page, "must enrol: the setup")
    secret = set_up_factor(page)
    run.shot(page, "enrol-qr")
    run.a11y(page, "must enrol: QR and key")
    turn_on(page, totp_code(secret, int(time.time() // 30)))
    expect(page.locator(".security-code-list li")).to_have_count(10)
    run.shot(page, "enrol-codes")
    run.a11y(page, "must enrol: the recovery codes")
    with page.expect_download() as saved:
        page.get_by_role("button", name="Download", exact=True).click()
    assert len(Path(saved.value.path()).read_text().split()) == 10, "the codes in the file"
    page.get_by_role("button", name="I have saved them", exact=True).click()
    expect(page.locator("header .me")).to_contain_text("Owner")
    page.goto(run.base + "/account/security")
    expect(page.locator("section.security")).to_contain_text("recovery codes left")
    expect(page.get_by_role("button", name="Turn off", exact=True)).to_have_count(0)
    page.get_by_role("button", name="New recovery codes", exact=True).click()
    expect(page.locator(".security-code-list li")).to_have_count(10)
    page.get_by_role("button", name="I have saved them", exact=True).click()
    expect(page.locator("section.security")).to_contain_text("New recovery codes are in place")
    no_problems(run, "must enrol")
    context.close()


def security_section(run: Run, browser) -> None:
    run.step("Security on the account: off, a wrong code said, on, off again")
    context, page = signed_in_page(run, browser)
    expect(page.locator("header .me")).to_contain_text("Owner")
    page.locator("header .profile-menu").click()
    page.get_by_role("menuitem", name="Security", exact=True).click()
    section = page.locator("section.security")
    expect(section).to_contain_text("Off.")
    run.a11y(page, "security: off")
    secret = set_up_factor(page)
    step = int(time.time() // 30)
    turn_on(page, "000000")
    expect(section).to_contain_text("That code is not valid.")
    turn_on(page, totp_code(secret, step))
    expect(page.locator(".security-code-list li")).to_have_count(10)
    page.get_by_role("button", name="I have saved them", exact=True).click()
    expect(section).to_contain_text("Two-factor sign-in is on.")
    run.shot(page, "security-on")
    run.a11y(page, "security: on")
    page.get_by_role("button", name="Turn off", exact=True).click()
    expect(section).to_contain_text("Two-factor sign-in is off.")
    # The wrong code above, expected here.
    run.problems = [p for p in run.problems if "/totp/confirm answered 403" not in p]
    no_problems(run, "security on the account")
    context.close()


def sign_in(run: Run, browser):
    """A context of its own, signed in as the owner, and its page."""
    context, page = signed_in_page(run, browser)
    expect(page.locator("header .me")).to_contain_text("Owner")
    return context, page


def second_hub_round(run: Run, browser, work: Path, artifacts: Path) -> None:
    """A second hub with an instance key and a mail catcher (§2.8, §16.2). The first hub stays
    without either, as the forge step checks exactly that absence (`secret_key_missing`)."""
    second = work / "second-hub"
    second.mkdir()
    port = free_port()
    catcher = MailCatcher()
    extra = {
        "MAITY_SECRET_KEY": base64.b64encode(os.urandom(32)).decode(),
        "MAITY_MAIL_SIGNING_KEY": base64.b64encode(os.urandom(32)).decode(),
        "MAITY_SMTP_HOST": "127.0.0.1",
        "MAITY_SMTP_PORT": str(catcher.port),
        "MAITY_SMTP_TLS": "none",
        "MAITY_SMTP_ALLOW_PLAINTEXT": "1",
        "MAITY_SMTP_FROM": "hub@e2e.example",
    }
    first_base = run.base
    run.base = f"http://127.0.0.1:{port}"
    run.step(f"second hub on {run.base}, with an instance key and a mail catcher")
    hub = start_hub(second, artifacts, port, extra, "hub-second.log")
    try:
        mail_reaches_the_catcher(run, browser, catcher)
        secret, used = step_up_with_totp(run, browser)
        context, page = sign_in_with_totp(run, browser, secret, used)
        reset_by_mail(run, browser, catcher, page)
        context.close()
        language_choice_step(run, browser)
    finally:
        stop_hub(hub)
        catcher.close()
        run.base = first_base


def language_choice_step(run: Run, browser) -> None:
    """The page's language chosen on /login and /register before sign-in (§6.2) stays the
    choice, also where the address came with another ?lang=, and across a reload."""
    run.step("signed out: the language chosen on login and register stays, also after a reload")
    for path, picker, field in (
        ("/login", "#login-interface", "#login-email"),
        ("/register", "#register-interface", "#register-address"),
    ):
        context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="de-DE")
        context.set_default_timeout(TIMEOUT_MS)
        page = context.new_page()
        watch_page(run, page)
        page.goto(f"{run.base}{path}?lang=de")
        expect(page.locator("html")).to_have_attribute("lang", "de")
        page.locator(field).fill("kim@e2e.example")
        page.locator(picker).select_option("fr")
        expect(page.locator("html")).to_have_attribute("lang", "fr")
        expect(page.locator(picker)).to_have_value("fr")
        expect(page.locator(field)).to_have_value("kim@e2e.example")
        assert page.url.endswith(f"{path}?lang=fr"), page.url
        page.reload()
        expect(page.locator("html")).to_have_attribute("lang", "fr")
        expect(page.locator(picker)).to_have_value("fr")
        no_problems(run, f"the language on {path}")
        context.close()


def mail_reaches_the_catcher(run: Run, browser, catcher: MailCatcher) -> None:
    run.step("second hub: the instance's test mail arrives, sent by the real hub")
    context, page = sign_in(run, browser)
    page.evaluate(
        """() => window.Maity.api.post("/admin/settings/mail/test", { to: "owner@e2e.example" })"""
    )
    mail = catcher.wait_for("owner@e2e.example")
    assert mail["From"] and "hub@e2e.example" in mail["From"], mail["From"]
    no_problems(run, "the test mail")
    context.close()


def step_up_with_totp(run: Run, browser) -> tuple[str, int]:
    """A session from before the enrolment has not given the factor, so the page must ask.
    Returns the secret and the last step the hub took, for the sign-in that follows."""
    run.step("second hub: enrol TOTP; an older session's export and runner pairing ask for the code")
    older_context, older = sign_in(run, browser)
    # A third session from before the enrolment pairs a runner: Oliver's case (tsk-6dk86ej9s0fq).
    pairing_context, pairing = sign_in(run, browser)
    context, page = sign_in(run, browser)
    started = page.evaluate("""() => window.Maity.api.post("/auth/second-factor/totp", {})""")
    secret = started["secret"]
    step = int(time.time() // 30)
    enrolled = page.evaluate(
        """(code) => window.Maity.api.post("/auth/second-factor/totp/confirm", { code })""",
        totp_code(secret, step),
    )
    context.close()

    older.goto(run.base + "/account/data")
    older.get_by_role("button", name="Export my data", exact=True).click()
    code = older.locator("#step-up-step_up_required")
    expect(code).to_be_visible()
    run.shot(older, "second-hub-step-up")
    run.a11y(older, "second hub: the step-up question")
    code.fill("000000")
    older.locator("form.step-up").get_by_role("button", name="Confirm", exact=True).click()
    expect(older.locator("#step-up-step_up_required-error")).to_have_text("That code is not valid.")
    # A step after the enrolment's, which is used up; the hub takes only now ± 1 step, so after a
    # slow screenshot or axe run the current step (review of #997).
    used = max(step + 1, int(time.time() // 30))
    code.fill(totp_code(secret, used))
    with older.expect_download() as saved:
        older.locator("form.step-up").get_by_role("button", name="Confirm", exact=True).click()
    assert json.loads(Path(saved.value.path()).read_text()).get("exported_at"), "an empty export"
    expect(older.locator(".data-export")).to_contain_text("Your export was saved.")
    # Pairing a runner mints a credential (§2.8.4): the page asks, a recovery code answers, the line comes.
    pairing.goto(run.base + "/runners")
    pairing.locator("#pair-name").fill("e2e-step-up")
    pairing.get_by_role("button", name="Create the pairing line", exact=True).click()
    asked = pairing.locator("form.step-up")
    expect(asked).to_contain_text("Pairing a runner needs your second factor")
    expect(pairing.locator(".pair-steps")).to_have_count(0)
    run.shot(pairing, "second-hub-step-up-runner")
    pairing.locator("#step-up-step_up_required").fill(enrolled["recovery_codes"][0])
    asked.get_by_role("button", name="Confirm", exact=True).click()
    expect(pairing.locator(".pair-steps")).to_contain_text("maity runner pair")
    expect(pairing.locator("form.step-up")).to_have_count(0)
    pairing_context.close()
    # What the question answers: the first refusal and the wrong code, both expected here.
    run.problems = [
        p
        for p in run.problems
        if "/me/export answered 403" not in p
        and "/second-factor/verify answered 403" not in p
        and "/runners/enrollments answered 403" not in p
    ]
    no_problems(run, "step-up with TOTP")
    older_context.close()
    return secret, used


def sign_in_with_totp(run: Run, browser, secret: str, used: int) -> None:
    """The second step of a sign-in (§2.8.2, tsk-73kkzr3x6exy): after the password the page
    asks for the app's code and nothing else, then the dashboard."""
    run.step("second hub: a sign-in asks for the app's code before anything else")
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.set_default_timeout(TIMEOUT_MS)
    page = context.new_page()
    watch_page(run, page)
    page.goto(run.base + "/")
    page.locator("#login-email").fill(OWNER_EMAIL)
    page.locator("#login-password").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    step = page.locator("form.second-factor")
    expect(step).to_contain_text("Enter the code from your authenticator app")
    # Nobody is shown as signed in yet (the header keeps only the brand and the theme).
    expect(page.locator("header .me-name")).to_have_count(0)
    run.shot(page, "second-hub-sign-in-totp")
    run.a11y(page, "second hub: the sign-in step with TOTP")
    # The hub takes only a step newer than the last one used, within one step of skew.
    while int(time.time() // 30) < used:
        time.sleep(1)
    # Taken right before the fill: a slow screenshot or axe run can outlast the hub's skew.
    page.locator("#sf-code").fill(totp_code(secret, max(used + 1, int(time.time() // 30))))
    step.get_by_role("button", name="Verify", exact=True).click()
    expect(page.locator("header .me")).to_contain_text("Owner")
    expect(step).to_have_count(0)
    page.goto(run.base + "/account/sessions")
    expect(page.locator("li.session.current")).to_contain_text("second factor passed")
    no_problems(run, "sign-in with TOTP")
    return context, page


def reset_by_mail(run: Run, browser, catcher: MailCatcher, owner: Page) -> None:
    """Admin → Users (§2.8.3, §2.8.7): the admin's press only sends a mail; the person's press on
    the mail's page resets, ends their sessions, and the next sign-in starts with the setup."""
    run.step("second hub: an admin resets a person's two-factor sign-in, which that person confirms by mail")
    address, handle, password = "ada@e2e.example", "ada", "ada-e2e-password-1"
    owner.evaluate("""() => window.Maity.api.patch("/admin/settings/registration", { mode: "open", approval: "automatic" })""")
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.set_default_timeout(TIMEOUT_MS)
    page = context.new_page()
    watch_page(run, page)
    page.goto(run.base + "/")
    page.evaluate(
        """([address, password]) => window.Maity.api.post("/auth/register", { address, password })""",
        [address, password],
    )
    page.goto(catcher.link_in(address, "/mail/register/"))
    page.locator("#password").fill(password)
    page.locator("#handle").fill(handle)
    page.locator("#display_name").fill("Ada")
    page.locator("form button[type=submit]").click()
    # A new account's first page is not the question here; the form is gone once the session is set.
    page.wait_for_function("() => window.Maity && window.Maity.api")
    assert page.evaluate("""() => window.Maity.api.get("/me")""")["member"]["handle"] == handle
    started = page.evaluate("""() => window.Maity.api.post("/auth/second-factor/totp", {})""")
    page.evaluate(
        """(code) => window.Maity.api.post("/auth/second-factor/totp/confirm", { code })""",
        totp_code(started["secret"], int(time.time() // 30)),
    )

    owner.goto(run.base + "/admin")
    owner.locator("nav.admin-nav").get_by_role("button", name="Users", exact=True).click()
    row = owner.locator("table.users tbody tr").filter(has_text="@" + handle)
    row.get_by_role("button", name="Reset two-factor sign-in of Ada", exact=True).click()
    form = owner.locator("form.user-reset")
    expect(form).to_contain_text("by another channel first")
    owner.locator("#user-reset-reason").fill("Ada lost the phone, we spoke on the telephone")
    run.shot(owner, "user-reset")
    run.a11y(owner, "Admin, Users: reset two-factor sign-in")
    form.get_by_role("button", name="Send the mail", exact=True).click()
    expect(form).to_contain_text("is on its way")
    # Nothing has changed yet: Ada is still signed in, with the factor.
    factor = page.evaluate("""() => window.Maity.api.get("/auth/second-factor")""")
    assert factor["enrolled"], f"the factor went before the person pressed: {factor}"

    other = browser.new_context(viewport={"width": 1280, "height": 900})
    other.set_default_timeout(TIMEOUT_MS)
    mail_page = other.new_page()
    mail_page.goto(catcher.link_in(address, "/mail/second-factor-reset/"))
    expect(mail_page.locator("body")).to_contain_text("Ada lost the phone")
    mail_page.get_by_role("button", name="Reset my two-factor sign-in", exact=True).click()
    expect(mail_page.locator("body")).to_contain_text("session")
    other.close()

    page.goto(run.base + "/")
    page.locator("#login-email").fill(address)
    page.locator("#login-password").fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="Set up two-factor sign-in", exact=True)).to_be_visible()
    # The page's own 401 once the sessions ended is what the reset does, not a problem here.
    run.problems = [p for p in run.problems if "answered 401" not in p]
    no_problems(run, "the reset by mail")
    context.close()


MAIL_ADDRESS = OWNER_EMAIL


def newest_mail(catcher: MailCatcher, to: str, seen: int, timeout: float = 20) -> str:
    """The text of the first mail to `to` after the first `seen` the catcher holds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for rcpt, message in catcher.mails[seen:]:
            if to in rcpt:
                return message.get_body(preferencelist=("plain",)).get_content()
        time.sleep(0.1)
    raise AssertionError(f"no new mail to {to} within {timeout} s; got {len(catcher.mails) - seen}")


def password_sign_in(run: Run, browser, offers_link: bool):
    """A fresh context at the login page after the password, and its page: what follows is the
    hub's (a second step, or the dashboard). The page offers the mail's sign-in link, or not."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.set_default_timeout(TIMEOUT_MS)
    page = context.new_page()
    watch_page(run, page)
    page.goto(run.base + "/")
    expect(page.get_by_role("button", name="Email me a sign-in link", exact=True)).to_have_count(1 if offers_link else 0)
    page.locator("#login-email").fill(OWNER_EMAIL)
    page.locator("#login-password").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    return context, page


def verify_address(run: Run, page, catcher: MailCatcher) -> None:
    """The owner's own address, the one `owner create --email` stored as verified (§2.1): the
    account's Mail section shows it, and the code of the switch goes there."""
    page.goto(f"{run.base}/account/notifications")
    settings = page.evaluate("""() => window.Maity.api.get("/me/notification-settings")""")
    assert settings["email"]["address_status"] == "verified", settings["email"]
    assert settings["email"]["address"] == MAIL_ADDRESS, settings["email"]
    expect(page.locator("section.mail-address .mail-address-state")).to_have_text(f"Mail goes to {MAIL_ADDRESS}.")


def turn_on_mail_factor(run: Run, page, catcher: MailCatcher) -> None:
    """Admin → Sign-in: the admin's own switch, on only with the mailed code (§2.8.8)."""
    page.goto(run.base + "/admin")
    page.get_by_role("button", name="Sign-in methods", exact=True).click()
    section = page.locator("#admin-sign-in")
    choice = section.locator("#admin-sign-in-second_factor")
    expect(choice.locator("option[value=email]")).to_have_count(1)
    choice.select_option("email")
    expect(section).to_contain_text("Saving this mails you a code first")
    run.shot(page, "admin-sign-in")
    run.a11y(page, "Admin, Sign-in: Mail for everyone chosen")
    seen = len(catcher.mails)
    section.get_by_role("button", name="Save", exact=True).click()
    code = section.locator("#admin-sign-in-code")
    expect(code).to_be_visible()
    run.shot(page, "admin-sign-in-code")
    mailed = re.search(r"(\d{3} \d{3})", newest_mail(catcher, MAIL_ADDRESS, seen))
    assert mailed, "no code in the mail"
    # Nothing has changed until the code is typed, and a wrong one is said.
    assert page.evaluate("""() => window.Maity.api.get("/admin/settings/sign-in")""")["second_factor"]["value"] == "optional"
    wrong = "000 001" if mailed.group(1) != "000 001" else "000 002"
    code.fill(wrong)
    section.get_by_role("button", name="Turn on", exact=True).click()
    expect(section.locator("#admin-sign-in-code-error")).to_have_text("That code is wrong or was used.")
    run.problems = [p for p in run.problems if "second-factor-email/confirm answered 403" not in p]
    code.fill(mailed.group(1))
    section.get_by_role("button", name="Turn on", exact=True).click()
    expect(section).to_contain_text("Mail for everyone is on.")
    expect(section).to_contain_text("one mailbox is not two factors")
    expect(section.locator("#admin-sign-in-second_factor")).to_have_value("email")
    no_problems(run, "mail factor: the admin's switch")


def mail_factor_join(run: Run, page, catcher: MailCatcher) -> None:
    """tsk-trb99kkhv1rk: creating a join is a sensitive call (§2.8.4). Under Mail for everyone
    the join form asks for the mailed code itself and then creates the join, instead of ending
    in a refusal; the panel names the project the join is for."""
    page.goto(run.base + f"/{OWNER}/e2e-mail/agents")
    panel = page.locator(".join-panel")
    add = page.get_by_role("button", name="Join an agent", exact=True)
    expect(panel.or_(add).first).to_be_visible()
    if not panel.is_visible():
        add.click()
    expect(panel.locator(".join-project")).to_contain_text(f"Joins into the project E2E Mail ({OWNER}/e2e-mail)")
    create = page.get_by_role("button", name="Create join line", exact=True)
    question = panel.locator("form.step-up")
    # Closing the panel while the code is asked ends that submission (#1399 review): reopened,
    # no question is left, the button is free, and only the fields then shown make the join.
    page.locator("#join-agent").select_option("")  # "A new agent profile…"
    page.locator("#join-handle").fill("e2e-mail-cancelled")
    page.locator("#join-display").fill("E2E Mail Cancelled")
    seen = len(catcher.mails)
    create.click()
    expect(question).to_contain_text("Confirm with a code by mail")
    # Its mail is in before the next question asks for one of its own.
    newest_mail(catcher, MAIL_ADDRESS, seen)
    panel.locator(".join-form .actions").get_by_role("button", name="Cancel", exact=True).click()
    expect(panel).to_be_hidden()
    add.click()
    expect(question).to_have_count(0)
    expect(create).to_be_enabled()
    # A project's full name may be one long word: at phone width the panel's line wraps it.
    # 360 px as well, where a wrap shows whatever the fonts (tsk-et029v5k73f1).
    long_slug = "p" * 63
    for phone_width, phone_height in ((390, 844), (360, 780)):
        page.set_viewport_size({"width": phone_width, "height": phone_height})
        widths = panel.locator(".join-project").evaluate(
            "(el, label) => { const was = el.textContent; el.textContent = label;"
            " const w = [document.documentElement.scrollWidth, document.documentElement.clientWidth];"
            " el.textContent = was; return w; }",
            f"Joins into the project {long_slug} ({OWNER}/{long_slug})",
        )
        assert widths[0] <= widths[1], f"a 63-character project name widens the page at {phone_width}px: {widths}"
    page.set_viewport_size({"width": 1280, "height": 900})
    page.locator("#join-agent").select_option("")
    page.locator("#join-handle").fill("e2e-mail-agent")
    page.locator("#join-display").fill("E2E Mail Agent")
    page.locator("#join-role").select_option("coder")
    seen = len(catcher.mails)
    create.click()
    expect(question).to_contain_text("Confirm with a code by mail")
    expect(panel.locator(".join-result")).to_have_count(0)
    run.shot(page, "mail-factor-join-step-up")
    run.a11y(page, "mail factor: Join an agent asks for the mailed code")
    code = re.search(r"(\d{3} ?\d{3})", newest_mail(catcher, MAIL_ADDRESS, seen))
    assert code, "no step-up code in the mail"
    page.locator("#step-up-step_up_mail").fill(code.group(1))
    question.get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator(".paste-line")).to_be_visible()
    expect(question).to_have_count(0)
    expect(page.locator("article.seat", has_text="E2E Mail Agent").first).to_contain_text("coder")
    expect(page.locator("article.seat", has_text="E2E Mail Cancelled")).to_have_count(0)
    # The join's first refusal is what opens the question.
    run.problems = [p for p in run.problems if "/joins answered 403" not in p]
    no_problems(run, "mail factor: Join an agent with the mailed code")


def mail_factor_round(run: Run, browser, work: Path, artifacts: Path) -> None:
    """Mail for everyone (§2.8.7, §2.8.8) on a hub of its own: the owner verifies an address and
    turns it on in Admin → Sign-in, and the page signs in by the mail's link and by its code,
    says where to open the link in another browser, no longer offers the sign-in link by mail,
    and a session from before the switch is asked for a mailed code at its next sensitive call."""
    third = work / "mail-factor-hub"
    third.mkdir()
    port = free_port()
    catcher = MailCatcher()
    extra = {
        "MAITY_SECRET_KEY": base64.b64encode(os.urandom(32)).decode(),
        "MAITY_MAIL_SIGNING_KEY": base64.b64encode(os.urandom(32)).decode(),
        "MAITY_SMTP_HOST": "127.0.0.1",
        "MAITY_SMTP_PORT": str(catcher.port),
        "MAITY_SMTP_TLS": "none",
        "MAITY_SMTP_ALLOW_PLAINTEXT": "1",
        "MAITY_SMTP_FROM": "hub@e2e.example",
    }
    first_base = run.base
    run.base = f"http://127.0.0.1:{port}"
    run.step(f"mail factor hub on {run.base}: the admin verifies an address and turns it on")
    hub = start_hub(third, artifacts, port, extra, "hub-mail-factor.log")
    older_context = joiner_context = None
    try:
        older_context, older = sign_in(run, browser)
        verify_address(run, older, catcher)
        # A second session from before the switch, for the join: the export's step-up below
        # must not have passed on it (the factor counts for 10 minutes on its session, §2.8.4).
        joiner_context, joiner = sign_in(run, browser)
        joiner.get_by_role("link", name="Create a project", exact=True).click()
        create_project(run, joiner, "E2E Mail", "e2e-mail")
        # Before the switch the login page offers the link by mail.
        first, _ = password_sign_in(run, browser, offers_link=True)
        first.close()
        admin_context, admin = sign_in(run, browser)
        turn_on_mail_factor(run, admin, catcher)
        admin_context.close()

        run.step("mail factor: the page says the mail went out; the link elsewhere, then here")
        seen = len(catcher.mails)
        context, page = password_sign_in(run, browser, offers_link=False)
        step = page.locator("form.second-factor")
        expect(step).to_contain_text("We sent a link and a code to")
        expect(step.get_by_role("button", name="Send again", exact=True)).to_be_visible()
        run.shot(page, "mail-factor-step")
        run.a11y(page, "mail factor: the sign-in step")
        link = re.search(r"(http\S+/sign-in/second-factor/email#[A-Za-z0-9_-]+)", newest_mail(catcher, MAIL_ADDRESS, seen))
        assert link, "no sign-in link in the mail"
        # Another browser holds no session for it: it completes nothing and says where to open it.
        other = browser.new_context(viewport={"width": 1280, "height": 900})
        other_page = other.new_page()
        other_page.goto(link.group(1))
        expect(other_page.locator(".second-factor-elsewhere")).to_contain_text(
            "Open this link in the browser where you signed in, or type the code from this mail there."
        )
        other.close()
        page.goto(link.group(1))
        expect(page.locator("header .me")).to_contain_text("Owner")
        expect(page.locator(".second-factor-elsewhere")).to_have_count(0)
        assert "#" not in page.url, page.url
        no_problems(run, "mail factor: the link")
        context.close()

        run.step("mail factor: the code from the mail signs in as well")
        seen = len(catcher.mails)
        context, page = password_sign_in(run, browser, offers_link=False)
        code = re.search(r"code there: (\d{3} ?\d{3})", newest_mail(catcher, MAIL_ADDRESS, seen))
        assert code, "no code in the mail"
        page.locator("#sf-code").fill(code.group(1))
        page.locator("form.second-factor").get_by_role("button", name="Verify", exact=True).click()
        expect(page.locator("header .me")).to_contain_text("Owner")
        no_problems(run, "mail factor: the code")
        context.close()

        run.step("mail factor: a session from before the switch is asked for a mailed code")
        seen = len(catcher.mails)
        older.goto(run.base + "/account/data")
        older.get_by_role("button", name="Export my data", exact=True).click()
        question = older.locator("form.step-up")
        expect(question).to_contain_text("Confirm with a code by mail")
        run.a11y(older, "mail factor: the step-up question")
        step_code = re.search(r"(\d{3} ?\d{3})", newest_mail(catcher, MAIL_ADDRESS, seen))
        assert step_code, "no step-up code in the mail"
        older.locator("#step-up-step_up_mail").fill(step_code.group(1))
        with older.expect_download() as saved:
            question.get_by_role("button", name="Confirm", exact=True).click()
        assert json.loads(Path(saved.value.path()).read_text()).get("exported_at"), "an empty export"
        # The export's first refusal is what opens the question.
        run.problems = [p for p in run.problems if "/me/export answered 403" not in p]
        no_problems(run, "mail factor: the step-up")

        run.step("mail factor: Join an agent asks for the mailed code in its form, then creates the join")
        mail_factor_join(run, joiner, catcher)
    finally:
        if joiner_context is not None:
            joiner_context.close()
        if older_context is not None:
            older_context.close()
        stop_hub(hub)
        catcher.close()
        run.base = first_base


def fixture_views(run: Run, browser) -> None:
    """Views whose richer states the hub here cannot reach, in fixture mode (file://):
    the Why view with the published maity.dev family, one part failing, the root unreadable."""
    run.step("fixtures: the Why view mounts the Keep the Why views, and says when the export is unreadable")
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    index = (WEB / "index.html").as_uri()
    try:
        # The library itself, loaded on the first visit (js/ktw-host.js): the overview, the graph
        # on its canvas, a topic with its entries, all in mounts marked translate="no".
        page.goto(f"{index}#/maintainer/maity/why")
        main = page.locator("main .why-main.ktw-root")
        expect(main).to_be_visible()
        expect(main).to_have_attribute("translate", "no")
        expect(main).not_to_be_empty()
        assert page.evaluate("!!(window.KeepTheWhy && window.KeepTheWhy.views.pages)")
        assert not errors, errors
        run.shot(page, "fixtures-why")
        run.a11y(page, "fixtures: why")
        errors.clear()
        page.goto(f"{index}#/maintainer/maity/why/graph")
        expect(page.locator("main .why-main canvas")).to_have_count(1)
        page.goto(f"{index}#/maintainer/maity/why/topic/api.md")
        expect(page.locator("main .why-main")).to_contain_text("The API is versioned in the path")
        assert not errors, errors
        run.shot(page, "fixtures-why-topic")
        errors.clear()
        # The timeline's selected controls are the library's white on the accent, which Maity
        # writes in its own text for the accent (css/app.css); axe checks them in both themes.
        page.goto(f"{index}#/maintainer/maity/why/timeline")
        expect(page.locator("main .why-main .ktw-stage-seg button.ktw-on").first).to_be_visible()
        assert not errors, errors
        run.shot(page, "fixtures-why-timeline")
        run.a11y(page, "fixtures: why timeline")
        errors.clear()
        # Thoughts reads its graph before it draws and gave up when its box was not yet in the
        # page (js/ktw-host.js drawWhenShown): its chains show, no "Loading…" for good.
        page.goto(f"{index}#/maintainer/maity/why/thoughts")
        expect(page.locator("main .why-main .ktw-thoughts-page .ktw-stats")).to_be_visible()
        assert not errors, errors
        page.goto(f"{index}?ktw=unavailable#/maintainer/maity/why")
        expect(page.locator("main")).to_contain_text("shown is its last good read")
        expect(page.locator("main .why-main")).not_to_be_empty()
        run.shot(page, "fixtures-why-last-good")
        errors.clear()
        # The view at phone width: nothing wider than the screen. 360 px as well, where a wrap shows
        # whatever the fonts (tsk-et029v5k73f1).
        for phone, tall in ((390, 844), (360, 780)):
            page.set_viewport_size({"width": phone, "height": tall})
            page.goto(f"{index}#/maintainer/maity/why")
            expect(page.locator("main .why-main")).not_to_be_empty()
            width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            assert width[0] <= width[1], f"the Why view is {width[0]} px wide at {width[1]} px"
            assert not errors, errors
            run.shot(page, "fixtures-why-phone" + ("" if phone == 390 else f"-{phone}"))
    finally:
        context.close()


PATHS_TEAM = (
    [{"id": "o", "kind": "human", "display_name": "oliver", "trust": "owner", "role": "manager"},
     {"id": "w", "kind": "human", "display_name": "wolfgang", "trust": "member", "role": "manager"},
     {"id": "l", "kind": "agent", "display_name": "lotse", "trust": "admin", "role": "manager", "reports_to": "o", "owner_id": "o",
      "instances": [{"id": "a"}, {"id": "b"}]},
     {"id": "rl", "kind": "agent", "display_name": "review-team-lead", "trust": "admin", "role": "manager", "reports_to": "o", "owner_id": "o"},
     {"id": "mh", "kind": "agent", "display_name": "marketing-head", "trust": "member", "role": "manager", "reports_to": "o", "owner_id": "o"}]
    + [{"id": f"c{i}", "kind": "agent", "display_name": f"maity-coder-claude-{i:03d}", "trust": "member", "role": "coder",
        "reports_to": "l", "owner_id": "o"} for i in range(1, 14)]
    + [{"id": k, "kind": "agent", "display_name": k, "trust": "member", "role": role, "reports_to": lead, "owner_id": "o"}
       for k, role, lead in (("ops", "ops", "l"), ("test-team", "tester", "l"), ("grok", "reviewer", "rl"), ("chatgpt", "reviewer", "rl"),
                             ("antigravity", "reviewer", "rl"), ("designer", "designer", "mh"), ("writer", "writer", "mh"),
                             # a project's own role whose name is an inherited property of an object
                             ("x-bridge", "constructor", "mh"))]
)

# The Paths face against the window: page width, boxes that overlap or leave the canvas, a name
# wider than its box, the panel under the drawing, the phone's cards.
PATHS_MEASURE = """() => {
  const r = (el) => el.getBoundingClientRect();
  const wide = document.querySelector('main .paths-wide');
  const narrow = document.querySelector('main .paths-narrow');
  const out = { page: [document.documentElement.scrollWidth, window.innerWidth], wideShown: !!(wide && wide.offsetParent),
    narrowShown: !!(narrow && narrow.offsetParent), overlaps: [], outside: [], clipped: [], chipsOut: [], cardsOut: [],
    reports: document.querySelectorAll('main .paths-lines path.paths-report').length,
    nodes: document.querySelectorAll('main .paths-canvas .paths-node').length,
    groups: document.querySelectorAll('main .paths-canvas .paths-group').length };
  document.querySelectorAll('main .paths-chip').forEach((c) => { if (r(c).right > window.innerWidth + 0.5) out.chipsOut.push(c.textContent); });
  if (out.wideShown) {
    const canvas = r(document.querySelector('main .paths-canvas'));
    const nodes = Array.from(document.querySelectorAll('main .paths-canvas .paths-node'));
    nodes.forEach((n, i) => {
      const a = r(n);
      if (a.left < canvas.left - 0.5 || a.right > canvas.right + 0.5 || a.top < canvas.top - 0.5 || a.bottom > canvas.bottom + 0.5) out.outside.push(n.dataset.id);
      nodes.slice(i + 1).forEach((m) => { const b = r(m);
        if (a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5) out.overlaps.push(n.dataset.id + '/' + m.dataset.id); });
      // Every part meant to stay visible lies inside its box on all four sides (the box clips).
      n.querySelectorAll('.paths-shape, .paths-count, .paths-name, .paths-sub, .paths-group-label, .paths-tiles').forEach((t) => {
        const b = r(t);
        if ((t.matches('.paths-name, .paths-sub, .paths-group-label') && t.scrollWidth > t.clientWidth + 1) || b.left < a.left - 0.5 || b.right > a.right + 0.5 || b.top < a.top - 0.5 || b.bottom > a.bottom + 0.5)
          out.clipped.push(n.dataset.id + ':' + (t.className || '') + ':' + t.textContent); });
    });
    out.panelBelow = r(document.querySelector('main .paths-panel')).top >= r(document.querySelector('main .paths-scroll')).bottom - 0.5;
    out.scrollFits = r(document.querySelector('main .paths-scroll')).right <= window.innerWidth + 0.5;
  }
  if (out.narrowShown) document.querySelectorAll('main .paths-card').forEach((c) => { if (r(c).right > window.innerWidth + 0.5 || r(c).left < -0.5) out.cardsOut.push(c.dataset.id); });
  return out;
}"""


def paths_views(run: Run, browser) -> None:
    """The Organisation tab's Paths face (tsk-j9ktmj7e4fxq) in fixture mode, every state the layout
    has: 2560, 1280, 390 and 360 px wide; with and without the sign-in banner; the fixture team and a
    team shaped like Maity's (26 members, 13 coders under one lead, one role of its own) folded
    and opened; the reporting lines on and off. Nothing overlaps, leaves the canvas or the window, no name is wider
    than its box, and the panel stands under the drawing."""
    run.step("fixtures: the Paths face fits at every width, with or without the banner, folded and opened")
    index = (WEB / "index.html").as_uri()
    for width, height in ((2560, 1200), (1280, 900), (390, 844), (360, 780)):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        try:
            for team in ("fixture", "maity"):
                for banner in (True, False):
                    page.goto("about:blank")
                    page.goto(f"{index}?lang=en#/maintainer/maity/organisation")
                    page.locator("main .org-faces").get_by_role("button", name="Paths", exact=True).click()
                    if team == "maity":
                        page.evaluate("""(members) => {
                          const M = window.Maity; const c = { members, memberById: {}, link: (...p) => '/maintainer/maity/' + p.join('/'), nameOf: (id) => id };
                          members.forEach((m) => { c.memberById[m.id] = m; });
                          const box = document.querySelector('main .org-box'); while (box.firstChild) box.removeChild(box.firstChild);
                          box.appendChild(M.paths.draw(c, { chip: null, selected: null, open: new Set(), lines: true }));
                        }""", PATHS_TEAM)
                    if not banner:
                        page.evaluate("() => { const b = document.querySelector('main .signin-banner'); if (b) b.remove(); }")
                    page.locator("main .paths-chips").get_by_role("button", name="Card assigned", exact=True).click()
                    states = [("folded", None)]
                    if team == "maity" and width > 700:
                        states.append(("opened", "main .paths-canvas .paths-group"))
                    for state, opener in states:
                        if opener:
                            page.locator(opener).click()
                        for lines in (True, False):
                            if not lines:
                                page.locator("main .paths-chips").get_by_role("button", name="Reporting lines", exact=True).click()
                            m = page.evaluate(PATHS_MEASURE)
                            where = f"{team} team, {state}, lines {'on' if lines else 'off'}, at {width}x{height}" + (" with the banner" if banner else "")
                            assert not errors, f"{where}: {errors}"
                            assert m["page"][0] <= m["page"][1], f"{where}: the page is {m['page'][0]} px wide"
                            assert not m["chipsOut"], f"{where}: chips past the window {m['chipsOut']}"
                            if width > 700:
                                assert m["wideShown"] and not m["narrowShown"], f"{where}: the drawing is not the face shown"
                                assert not m["overlaps"], f"{where}: boxes overlap {m['overlaps']}"
                                assert not m["outside"], f"{where}: boxes leave the canvas {m['outside']}"
                                assert not m["clipped"], f"{where}: parts outside their box or text wider than it {m['clipped']}"
                                assert m["panelBelow"] and m["scrollFits"], f"{where}: the panel is not under the drawing, or the drawing's frame leaves the window"
                                assert (m["reports"] > 0) == lines, f"{where}: {m['reports']} reporting lines drawn"
                                if team == "maity":
                                    assert (m["groups"], m["nodes"]) == ((1, 14) if state == "folded" else (0, 26)), f"{where}: {m['groups']} boxes, {m['nodes']} in all"
                            else:
                                assert m["narrowShown"] and not m["wideShown"], f"{where}: the list is not the face shown"
                                assert not m["cardsOut"], f"{where}: cards past the window {m['cardsOut']}"
                            if not lines:
                                page.locator("main .paths-chips").get_by_role("button", name="Reporting lines", exact=True).click()
                    run.shot(page, f"fixtures-paths-{team}-{width}" + ("-banner" if banner else ""))
            if width == 1280:
                run.a11y(page, "fixtures: organisation paths")
            page.goto(f"{index}?lang=en#/maintainer/maity/organisation")
            page.locator("main .org-faces").get_by_role("button", name="Tree", exact=True).click()
        finally:
            context.close()


CHAT_MEASURE = """() => {
  const box = (sel) => { const el = document.querySelector(sel); if (!el) return null;
    const b = el.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, height: b.height }; };
  return { overflow: document.scrollingElement.scrollHeight - window.innerHeight,
    history: box('.chat-layout.open .chat-pane .messages'), compose: box('.chat-layout.open .chat-pane .compose'),
    footer: box('#product-line'), errors: window.__errors.slice() };
}"""


def chat_height_views(run: Run, browser) -> None:
    """The open chat against the window (tsk-j10w2hsm1h90), in fixture mode: on a project's Chat
    tab and on Chats, direct and group, at 1280 x 800, 390 x 844 and 375 x 667; and after the pane
    grew or shrank inside (the composer folded, shown, three times its rows, a group's Manage opened). Without the sign-in banner the
    page ends at the window's bottom edge; with it (a phone has no room then) the page scrolls, but
    the history keeps some height and the composer never runs under the product line. A
    ResizeObserver loop is reported on window only, so a collector there counts it as an error."""
    run.step("fixtures: the open chat ends at the window's bottom edge, the composer above the product line")
    index = (WEB / "index.html").as_uri()
    # 375 x 667 is too small for a composer and 60 px of history: there the page scrolls, never overlaps.
    for width, height, fits in ((1280, 800, True), (390, 844, True), (375, 667, False)):
        context = browser.new_context(viewport={"width": width, "height": height})
        context.add_init_script(
            "window.__errors = []; window.addEventListener('error', (e) => window.__errors.push(String(e.message)));"
        )
        # The elements the chat's fitting observer (the one on the body) watches, connected or not.
        context.add_init_script("""(() => { const R = window.ResizeObserver; if (!R) return; const all = [];
          window.ResizeObserver = class extends R {
            constructor(cb) { super(cb); this.__t = new Set(); all.push(this); }
            observe(t, o) { this.__t.add(t); super.observe(t, o); }
            unobserve(t) { this.__t.delete(t); super.unobserve(t); }
            disconnect() { this.__t.clear(); super.disconnect(); } };
          window.__fitTargets = () => all.filter((o) => o.__t.has(document.body))
            .map((o) => ({ all: o.__t.size, gone: Array.from(o.__t).filter((t) => !t.isConnected).length })); })();""")
        page = context.new_page()
        errors: list[str] = []
        # Page errors only: on file:// Chromium refuses the pictures the page loads (CORS) and says so on the console.
        page.on("pageerror", lambda err: errors.append(str(err)))
        try:
            for route in (
                "#/maintainer/maity/chat/agt-a",
                "#/maintainer/maity/chat/cnv-0007",
                "#/chats/maintainer/maity/agt-a",
                "#/chats/maintainer/maity/cnv-0007",
            ):
                for banner in (True, False):
                    page.goto("about:blank")
                    page.goto(f"{index}?lang=en{route}")
                    page.locator(".chat-layout.open .chat-pane .compose").wait_for()
                    page.wait_for_timeout(800)
                    if not banner:
                        page.evaluate("() => { const b = document.querySelector('main .signin-banner'); if (b) b.remove(); }")
                        page.wait_for_timeout(300)
                    m = page.evaluate(CHAT_MEASURE)
                    where = f"{route} at {width}x{height}" + (" with the sign-in banner" if banner else "")
                    assert not m["errors"] and not errors, f"{where}: {m['errors'] + errors}"
                    assert m["history"]["height"] >= 56, f"{where}: the history is {m['history']['height']:.0f} px tall"
                    assert m["compose"]["bottom"] <= m["footer"]["top"] + 0.5, (
                        f"{where}: the composer ends at {m['compose']['bottom']:.0f}, the product line starts at {m['footer']['top']:.0f}"
                    )
                    if fits and not banner:
                        assert m["overflow"] <= 1, f"{where}: the page scrolls {m['overflow']} px past the window"
                    toggle = page.locator(".chat-layout.open .chat-pane .compose-toggle")
                    if toggle.is_visible():
                        # Folding the composer changes the pane's fixed part, not the body: measured again.
                        toggle.click()
                        page.wait_for_timeout(300)
                        folded = page.evaluate(CHAT_MEASURE)
                        toggle.click()  # kept by the browser for every chat: open again for the next case
                        page.wait_for_timeout(300)
                        assert folded["overflow"] <= max(1, m["overflow"] - 100), (
                            f"{where}, composer folded: the page scrolls {folded['overflow']} px past the window"
                        )
                        unfolded = page.evaluate(CHAT_MEASURE)
                        assert unfolded["history"]["height"] >= 56 and unfolded["compose"]["bottom"] <= unfolded["footer"]["top"] + 0.5, (
                            f"{where}, composer folded and shown again: {unfolded}"
                        )
                    # What grows inside the pane after it was fitted: the composer three times its
                    # rows (a wide screen), a group's "Manage or leave" opened.
                    grown = []
                    three = page.locator(".chat-layout.open .chat-pane .compose-size button[data-size='3']")
                    if three.is_visible():
                        three.click()
                        grown.append(("composer 3x", lambda: page.locator(".chat-layout.open .chat-pane .compose-size button[data-size='1']").click()))
                    manage = page.locator(".chat-layout.open .chat-pane details.group-manage > summary")
                    if manage.count() and manage.first.is_visible():
                        manage.first.click()
                        grown.append(("Manage or leave opened", lambda: manage.first.click()))
                    if grown:
                        page.wait_for_timeout(300)
                        g = page.evaluate(CHAT_MEASURE)
                        for _, undo in grown:
                            undo()
                        page.wait_for_timeout(300)
                        back = page.evaluate(CHAT_MEASURE)
                        what = ", ".join(n for n, _ in grown)
                        assert g["history"]["height"] >= 56 and g["compose"]["bottom"] <= g["footer"]["top"] + 0.5, f"{where}, {what}: {g}"
                        # And back: the pane shrinks again by itself, as a fresh fit (a window resize) would size it.
                        page.evaluate("() => window.dispatchEvent(new Event('resize'))")
                        page.wait_for_timeout(300)
                        fresh = page.evaluate(CHAT_MEASURE)
                        assert abs(back["overflow"] - fresh["overflow"]) <= 1, (
                            f"{where}, {what} undone: the page scrolls {back['overflow']} px, a fresh fit {fresh['overflow']}"
                        )
            # On Chats a group chat takes the place of a direct one in the same layout.
            page.goto("about:blank")
            page.goto(f"{index}?lang=en#/chats/maintainer/maity/agt-a")
            page.locator(".chat-layout.open .chat-pane .compose").wait_for()
            page.wait_for_timeout(500)
            page.evaluate("() => { location.hash = '#/chats/maintainer/maity/cnv-0007'; }")
            page.locator(".chat-layout.open .chat-pane.group-chat .compose").wait_for()
            page.wait_for_timeout(800)
            m = page.evaluate(CHAT_MEASURE)
            where = f"Chats with the sign-in banner, agt-a then cnv-0007, at {width}x{height}"
            assert not m["errors"] and not errors, f"{where}: {m['errors'] + errors}"
            assert m["history"]["height"] >= 56 and m["compose"]["bottom"] <= m["footer"]["top"] + 0.5, f"{where}: {m}"
            page.evaluate("() => window.dispatchEvent(new Event('resize'))")
            page.wait_for_timeout(300)
            fresh = page.evaluate(CHAT_MEASURE)
            assert abs(m["overflow"] - fresh["overflow"]) <= 1, f"{where}: the page scrolls {m['overflow']} px, a fresh fit {fresh['overflow']}"
            # Switching back and forth: the observer watches the current pane's parts, not every pane's.
            for chat in ("agt-a", "cnv-0007") * 5:
                page.evaluate(f"() => {{ location.hash = '#/chats/maintainer/maity/{chat}'; }}")
                page.wait_for_timeout(250)
            page.wait_for_timeout(500)
            targets = page.evaluate("() => window.__fitTargets()")
            assert len(targets) == 1 and targets[0]["gone"] == 0 and targets[0]["all"] <= 16, f"{where}, ten switches: {targets}"
            run.shot(page, f"fixtures-chat-{width}")
        finally:
            context.close()


def chat_phone_head(run: Run, browser) -> None:
    """The owner's feedback on the full-screen chat (tsk-2a56j80p3p9h), in fixture mode, in a direct
    and a group chat, light and dark. On a phone (390 x 844) the full-screen button is at the top
    right of the chat head, on the back link's row, under the top bar's last entry, also while full,
    and the agent's session line is not shown. At 1280 x 800 the button stays beside the heading and
    the session line shows. The button keeps its name and is reached by Tab after the heading. In
    every size the project tabs' menu ("…") stays on the tabs' row inside the window; on a phone the
    tabs overflow and scroll instead."""
    run.step("fixtures: on a phone the full-screen button is at the chat head's top right, no session line, the tabs menu in its row")
    index = (WEB / "index.html").as_uri()
    box = "(el) => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }"
    for chat, kind in (("agt-a", ".chat-pane:not(.group-chat)"), ("cnv-0007", ".chat-pane.group-chat")):
        for width, height in ((1280, 800), (390, 844)):
            phone = width <= 720
            for scheme in ("light", "dark"):
                context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
                page = context.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                where = f"{chat} at {width}x{height}, {scheme}"
                try:
                    page.goto(f"{index}?lang=en#/maintainer/maity/chat/{chat}")
                    pane = page.locator(f".chat-layout.open {kind}")
                    pane.locator(".compose").wait_for()
                    page.wait_for_timeout(300)
                    toggle = pane.get_by_role("button", name="Read in full screen", exact=True)
                    heading = pane.locator(".toolbar h2")
                    at, head = toggle.evaluate(box), heading.evaluate(box)
                    session = pane.locator(".chat-session")
                    if chat == "agt-a":
                        assert session.count() == 1 and session.is_visible() is not phone, f"{where}: session shown {session.is_visible()}"
                    if phone:
                        back = pane.locator("a.chat-back").evaluate(box)
                        assert at[2] >= width - 24 and at[1] < head[1], f"{where}: the button {at}, heading {head}"
                        assert abs(at[1] - back[1]) <= 1 and back[2] <= at[0] + 0.5, f"{where}: not on the back link's row {at} {back}"
                    else:
                        assert abs((at[1] + at[3]) / 2 - (head[1] + head[3]) / 2) < 20 and at[0] >= head[2], f"{where}: beside the heading {at} {head}"
                    tabs = page.locator(".switcher-row nav.switcher")
                    tabs_at, menu = tabs.evaluate(box), page.locator(".switcher-row .tabs-menu-box").evaluate(box)
                    assert abs((menu[1] + menu[3]) / 2 - (tabs_at[1] + tabs_at[3]) / 2) < 8 and menu[0] >= tabs_at[2], f"{where}: tabs menu {menu}, tabs {tabs_at}"
                    assert menu[2] <= width, f"{where}: tabs menu past the window {menu}"
                    if phone:
                        assert tabs.evaluate("(el) => el.scrollWidth > el.clientWidth"), f"{where}: the tabs do not overflow, nothing tested"
                        assert menu[2] >= width - 24, f"{where}: the tabs menu is not at the row's right end {menu}"
                    # Tab from the heading reaches the button next, past the heading's own links, wherever it is drawn.
                    heading.focus()
                    for _ in range(4):
                        page.keyboard.press("Tab")
                        if not heading.evaluate("(el) => el.contains(document.activeElement)"):
                            break
                    assert page.evaluate("() => document.activeElement.classList.contains('chat-full-toggle')"), f"{where}: Tab after the heading"
                    toggle.click()
                    leave = pane.get_by_role("button", name="Leave full screen", exact=True)
                    expect(leave).to_have_attribute("aria-pressed", "true")
                    if phone:
                        full = leave.evaluate(box)
                        assert abs(full[1] - 8) <= 1 and abs(full[2] - (width - 12)) <= 1, f"{where}: full screen button {full}"
                        if chat == "cnv-0007":
                            run.shot(page, f"chat-head-full-{scheme}")
                    page.keyboard.press("Escape")
                    expect(page.locator("html.chat-full")).to_have_count(0)
                    if phone:
                        run.shot(page, f"chat-head-{chat}-{scheme}")
                    assert not errors, f"{where}: {errors}"
                finally:
                    context.close()


def chat_phone_views(run: Run, browser) -> None:
    """The owner's request for phones (tsk-fnch2yxp2kk1), in fixture mode, in a group chat at
    1280 x 800, 390 x 844 and 360 x 780, light and dark. At phone width the product line is only
    "Maity 2026" on one row (§16.13), the "In it:" line is not shown, and the composer's label is
    out of sight but still names the field. In every size the full screen covers the window with the
    chat, nothing scrolls sideways, and the button, Escape and the browser's back end it, back
    without drawing the chat again."""
    run.step("fixtures: a chat on a phone, the product line, the hint lines and the full screen")
    index = (WEB / "index.html").as_uri()
    for width, height in ((1280, 800), (390, 844), (360, 780)):
        phone = width <= 600
        for scheme in ("light", "dark"):
            context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            where = f"cnv-0007 at {width}x{height}, {scheme}"
            try:
                page.goto(f"{index}?lang=en#/maintainer/maity/chat/cnv-0007")
                pane = page.locator(".chat-layout.open .chat-pane.group-chat")
                pane.locator(".compose").wait_for()
                page.wait_for_timeout(500)
                parts = page.evaluate(
                    "() => Array.from(document.querySelectorAll('#product-line > *')).filter((el) => el.getClientRects().length)"
                    ".map((el) => el.textContent.trim())"
                )
                line = page.locator("#product-line").bounding_box()
                if phone:
                    assert len(parts) == 1 and parts[0].startswith("Maity ") and line and line["height"] < 48, f"{where}: {parts} {line}"
                else:
                    assert len(parts) == 7, f"{where}: the product line shows {parts}"
                people = pane.locator(".group-people-line")
                assert people.count() == 1 and people.is_visible() is not phone, f"{where}: In it: shown {people.is_visible()}"
                label = pane.locator(".compose-head label[for='chat-text']")
                box = label.bounding_box()
                assert (box is not None and box["width"] <= 1) if phone else label.is_visible(), f"{where}: the label {box}"
                expect(page.get_by_role("textbox", name=re.compile(r"^Message \("))).to_have_count(1)
                # The full screen: the button, Escape, the button again, then the browser's back.
                page.evaluate("() => { window.__drawn = document.querySelector('.chat-pane.group-chat'); }")
                toggle = pane.get_by_role("button", name="Read in full screen", exact=True)
                toggle.click()
                expect(pane.get_by_role("button", name="Leave full screen", exact=True)).to_have_attribute("aria-pressed", "true")
                full = page.evaluate(
                    "() => { const r = document.querySelector('.chat-pane.group-chat').getBoundingClientRect();"
                    " return [r.left, r.top, r.width, r.height, window.innerWidth, window.innerHeight,"
                    " document.documentElement.scrollWidth, document.querySelector('.chat-pane .compose').getBoundingClientRect().bottom]; }"
                )
                assert abs(full[0]) <= 0.5 and abs(full[1]) <= 0.5 and abs(full[2] - full[4]) <= 1 and abs(full[3] - full[5]) <= 1, f"{where}: full screen {full}"
                assert full[6] <= full[4] and full[7] <= full[5] + 0.5, f"{where}: sideways or the composer below the window {full}"
                if width == 390:
                    run.shot(page, f"chat-full-{scheme}")
                    run.a11y(page, f"chat full screen, {scheme} system theme")
                    page.set_viewport_size({"width": width, "height": height})  # a11y ends at 1280x900
                page.keyboard.press("Escape")
                expect(pane.get_by_role("button", name="Read in full screen", exact=True)).to_have_attribute("aria-pressed", "false")
                expect(page.locator("html.chat-full")).to_have_count(0)
                toggle.click()
                expect(page.locator("html.chat-full")).to_have_count(1)
                page.go_back()
                expect(page.locator("html.chat-full")).to_have_count(0)
                same = page.evaluate("() => window.__drawn === document.querySelector('.chat-pane.group-chat') && window.__drawn.isConnected")
                assert same, f"{where}: back drew the chat again"
                # While full, Tab never reaches the covered page (fmzu at #1525): the rest is inert.
                toggle.click()
                expect(page.locator("html.chat-full")).to_have_count(1)
                outside = []
                for _ in range(40):
                    page.keyboard.press("Tab")
                    at = page.evaluate("() => { const el = document.activeElement; const pane = document.querySelector('.chat-pane.group-chat');"
                                       " return !el || el === document.body || pane.contains(el) ? '' : el.tagName + '.' + el.className; }")
                    if at:
                        outside.append(at)
                assert not outside, f"{where}: Tab left the full-screen chat for {outside[:3]}"
                page.keyboard.press("Escape")
                expect(page.locator("html.chat-full")).to_have_count(0)
                # Leaving by a link while full (Back to the list on a phone) takes the layer's entry: one Back
                # returns to the chat, not to a second stop at it (fmzu, e5kk at #1525).
                if width <= 720:
                    toggle.click()
                    expect(page.locator("html.chat-full")).to_have_count(1)
                    stops = page.evaluate("() => history.length")
                    pane.locator("a.chat-back").click()
                    expect(page).to_have_url(re.compile(r"#/maintainer/maity/chat$"))
                    expect(page.locator("html.chat-full")).to_have_count(0)
                    assert page.evaluate("() => history.length") == stops, f"{where}: leaving by a link left the layer's entry behind"
                    page.go_back()
                    expect(page).to_have_url(re.compile(r"#/maintainer/maity/chat/cnv-0007$"))
                    expect(page.locator("html.chat-full")).to_have_count(0)
                assert not errors, f"{where}: {errors}"
            finally:
                context.close()


# Every element in the lines of `selector` (the Current sessions box, the bell's pinned block):
# inside its line and the window, no two parts of a line over each other, and every link and
# button a 24 px target, or one whose 24 px circle meets no other target (WCAG 2.5.8); a badge
# 2 px at least from the text beside it.
LINES_MEASURE = """(selector) => {
  const problems = [], vw = document.documentElement.clientWidth, eps = 0.5;
  const name = (el) => el.tagName.toLowerCase() + (el.className ? "." + String(el.className).trim().split(/\\s+/).join(".") : "")
    + " '" + (el.textContent || "").trim().slice(0, 40) + "'";
  if (document.documentElement.scrollWidth > window.innerWidth) problems.push("the page is " + document.documentElement.scrollWidth + " px wide");
  const boxes = Array.from(document.querySelectorAll(selector));
  if (!boxes.length) problems.push("no " + selector);
  const targets = [];
  for (const box of boxes) {
    const b = box.getBoundingClientRect();
    if (b.left < -eps || b.right > vw + eps) problems.push(name(box) + " leaves the window: " + b.left + ".." + b.right);
    for (const el of box.querySelectorAll("*")) {
      for (const r of el.getClientRects()) {
        if (r.width === 0 && r.height === 0) continue;
        if (r.left < b.left - eps || r.right > b.right + eps) problems.push(name(el) + " runs out of " + name(box));
      }
      if (el.matches("a[href], button")) targets.push(el);
    }
    for (const li of box.querySelectorAll("li")) {
      const l = li.getBoundingClientRect();
      const parts = Array.from(li.children).map((el) => [el, Array.from(el.getClientRects())]);
      for (const [el, rects] of parts) for (const r of rects)
        if (r.left < l.left - eps || r.right > l.right + eps || r.top < l.top - eps || r.bottom > l.bottom + eps) problems.push(name(el) + " runs out of its line");
      for (let i = 0; i < parts.length; i++) for (let j = i + 1; j < parts.length; j++)
        for (const p of parts[i][1]) for (const q of parts[j][1]) {
          const w = Math.min(p.right, q.right) - Math.max(p.left, q.left), h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
          if (w > eps && h > eps) problems.push(name(parts[i][0]) + " and " + name(parts[j][0]) + " overlap");
          // A badge's pill never touches the text beside it on its line: 2 px at least.
          else if (h > eps && w > -2 && (parts[i][0].matches(".badge") || parts[j][0].matches(".badge")))
            problems.push(name(parts[i][0]) + " and " + name(parts[j][0]) + " touch");
        }
    }
  }
  const rects = targets.map((el) => [el, el.getBoundingClientRect()]);
  const centre = (r) => [(r.left + r.right) / 2, (r.top + r.bottom) / 2];
  for (const [el, r] of rects) {
    if (r.width >= 24 && r.height >= 24) continue;
    const [x, y] = centre(r);
    for (const [other, s] of rects) {
      if (other === el) continue;
      const small = s.width < 24 || s.height < 24;
      const [ox, oy] = centre(s);
      const dx = Math.max(s.left - x, 0, x - s.right), dy = Math.max(s.top - y, 0, y - s.bottom);
      const near = small ? Math.hypot(ox - x, oy - y) < 24 - eps : Math.hypot(dx, dy) < 12 - eps;
      if (near) problems.push(name(el) + " is " + Math.round(r.width) + "x" + Math.round(r.height) + " px and too close to " + name(other));
    }
  }
  return { problems, shown: boxes.map((box) => box.querySelectorAll("li").length) };
}"""

# The fixtures the page reads (fixtures/fixtures.js sets window.MAITY_FIXTURES), changed before
# any script reads them: the active sessions kept (all, or the tab's own alone, or seven more),
# and unread security alerts added for the bell's pinned block.
SESSIONS_FIXTURE = """(() => { let f; Object.defineProperty(window, "MAITY_FIXTURES", { configurable: true,
  get() { return f; },
  set(v) { f = v; const want = %s; const s = f["sessions.json"];
    if (want.sessions === "one") s.items = s.items.filter((x) => x.id === s.current || x.ended_at);
    if (want.sessions === "many") for (let i = 0; i < 7; i++) s.items.push(Object.assign({}, s.items[1], { id: "hss-e2e" + i,
      created_at: "2026-10-2" + i + "T09:00:00Z", browser: i %% 2 ? "Firefox Developer Edition" : "Chrome", os: "Windows 11 Pro for Workstations",
      good_standing: i !== 3 }));
    if (want.alerts) f["notifications.json"].items.unshift(
      { id: "ntf-acr-e2e1", record: "acr-e2e1", kind: "security", at: "2026-10-22T13:30:00Z", project: null, actor: null,
        title: "Your sign-in address was changed to a.very.long.address.for.this.test@example.org", target: { type: "settings", id: "notifications" },
        url: null, read: false, redacted: false, open_matter: false },
      { id: "ntf-acr-e2e2", record: "acr-e2e2", kind: "security", at: "2026-10-22T13:25:00Z", project: null, actor: null,
        title: "Your address was changed", target: { type: "settings", id: "notifications" },
        url: null, read: false, redacted: false, open_matter: false });
  } }); })();"""


def notification_sessions_layout(run: Run, browser) -> None:
    """The Notifications page's Current sessions box and the bell's pinned block (tsk-0baaez2895sb),
    in fixture mode, at 1280 x 900, 390 x 844 and 360 x 780: the box with the tab's own session alone, with the
    fixtures' three active ones (the mail sign-in banner on, and removed) and with ten (five shown,
    the rest counted; long browser and system names); the bell opened and closed again, with two
    unread security alerts pinned (one with a long title) and with none. Every element of the box's
    lines and of the pinned rows is measured (LINES_MEASURE), the page never wider than the window,
    the banner never over the box. The page folds nothing else here: the bell's panel is its one
    fold."""
    run.step("fixtures: Current sessions and the bell's pinned block at 1280, 390 and 360 px, banner on and off")
    index = (WEB / "index.html").as_uri()
    for width, height in ((1280, 900), (390, 844), (360, 780)):
        for sessions, alerts in (("one", False), ("all", True), ("many", True), ("many", False)):
            context = browser.new_context(viewport={"width": width, "height": height})
            context.add_init_script(SESSIONS_FIXTURE % json.dumps({"sessions": sessions, "alerts": alerts}))
            page = context.new_page()
            errors: list[str] = []
            # Page errors only: on file:// Chromium refuses the pictures the page loads (CORS) and says so on the console.
            page.on("pageerror", lambda err: errors.append(str(err)))
            try:
                page.goto(f"{index}?lang=en#/notifications")
                box = page.locator("main section.current-sessions")
                expect(box.locator("li").first).to_be_visible()
                rows = {"one": 1, "all": 3, "many": 6}[sessions]
                expect(box.locator("li")).to_have_count(rows)
                banner = page.locator("main .signin-banner")
                for with_banner in (True, False) if sessions != "one" else (False,):
                    where = f"{sessions} session(s), alerts {alerts}, at {width}x{height}" + (" with the sign-in banner" if with_banner else "")
                    if with_banner:
                        expect(banner).to_be_visible()
                        b, s = banner.bounding_box(), box.bounding_box()
                        assert b and s and b["y"] + b["height"] <= s["y"] + 0.5, f"{where}: the banner {b} runs over the box {s}"
                    else:
                        page.evaluate("() => { const b = document.querySelector('main .signin-banner'); if (b) b.remove(); }")
                        expect(banner).to_have_count(0)
                    m = page.evaluate(LINES_MEASURE, "main section.current-sessions")
                    assert not m["problems"] and not errors, f"{where}, the box: {m['problems'] + errors}"
                    # The link to Sessions stands alone on its line, so the spacing rule alone would pass a
                    # 19 px link: the box keeps it a full 24 px target (WCAG 2.5.8's size, not its exception).
                    link = box.locator(".hint a").bounding_box()
                    assert link and link["height"] >= 23.5, f"{where}: the link to Sessions is {link} high, under 24 px"
                    run.shot(page, f"fixtures-current-sessions-{sessions}-{width}" + ("-banner" if with_banner else ""))
                    bell = page.locator("#header button.bell")
                    bell.click()
                    expect(bell).to_have_attribute("aria-expanded", "true")
                    pinned = page.locator("#bell-panel .bell-pinned li")
                    if alerts:
                        expect(pinned).to_have_count(2)
                        expect(pinned.first.locator("button")).to_have_text("Mark read")
                        m = page.evaluate(LINES_MEASURE, "#bell-panel .bell-pinned")
                        assert not m["problems"] and not errors, f"{where}, the pinned block: {m['problems'] + errors}"
                    else:
                        expect(page.locator("#bell-panel .bell-pinned")).to_have_count(0)
                    m = page.evaluate(LINES_MEASURE, "#bell-panel")
                    assert not m["problems"] and not errors, f"{where}, the bell: {m['problems'] + errors}"
                    run.shot(page, f"fixtures-bell-pinned-{sessions}-{width}" + ("-banner" if with_banner else ""))
                    # Folded again (Escape: at 390 px the open panel covers the bell), the box measured the same.
                    page.keyboard.press("Escape")
                    expect(bell).to_have_attribute("aria-expanded", "false")
                    m = page.evaluate(LINES_MEASURE, "main section.current-sessions")
                    assert not m["problems"] and not errors, f"{where}, the bell folded again: {m['problems'] + errors}"
                if sessions == "many" and alerts and width == 1280:
                    run.a11y(page, "fixtures: notifications with current sessions")
            finally:
                context.close()


# The account's tab rows (tsk-3banvfzv3nvs): each row inside the window and on one line, every tab a
# 24 px target with its text inside it, no two tabs over each other, the current one in sight in
# its row, the fade on a row that scrolls and on no other, the heading above the row, the row
# above the tab's first part, and the sign-in banner, if shown, above all of it.
TABS_MEASURE = """() => {
  const problems = [], eps = 0.5, vw = document.documentElement.clientWidth;
  const name = (el) => el.tagName.toLowerCase() + "." + String(el.className).trim().split(/\\s+/).join(".") + " '" + el.textContent.trim().slice(0, 30) + "'";
  if (document.documentElement.scrollWidth > window.innerWidth) problems.push("the page is " + document.documentElement.scrollWidth + " px wide");
  const rows = Array.from(document.querySelectorAll("main nav.account-tabs"));
  if (!rows.length) problems.push("no tab row");
  const heading = rows.length && rows[0].previousElementSibling && rows[0].previousElementSibling.matches("h2") ? rows[0].previousElementSibling : null;
  const banner = document.querySelector("main .signin-banner");
  let above = heading ? heading.getBoundingClientRect().bottom : null;
  if (!heading) problems.push("no heading");
  if (banner && heading && banner.getBoundingClientRect().bottom > heading.getBoundingClientRect().top + eps) problems.push("the banner runs over the heading");
  for (const nav of rows) {
    const n = nav.getBoundingClientRect();
    if (n.left < -eps || n.right > vw + eps) problems.push(name(nav) + " leaves the window: " + n.left + ".." + n.right);
    if (above !== null && n.top < above - eps) problems.push(name(nav) + " starts above what stands before it");
    above = n.bottom;
    const tabs = Array.from(nav.children);
    const tops = new Set(tabs.map((t) => Math.round(t.getBoundingClientRect().top + nav.scrollTop)));
    if (tops.size > 1) problems.push(name(nav) + " wraps onto " + tops.size + " lines");
    for (const t of tabs) {
      const r = t.getBoundingClientRect();
      if (r.height < 24 - eps || r.width < 24 - eps) problems.push(name(t) + " is " + Math.round(r.width) + "x" + Math.round(r.height));
      if (t.scrollWidth > t.clientWidth + 1) problems.push(name(t) + "'s text is wider than the tab");
    }
    for (let i = 0; i + 1 < tabs.length; i++) {
      const a = tabs[i].getBoundingClientRect(), b = tabs[i + 1].getBoundingClientRect();
      if (b.left < a.right - eps) problems.push(name(tabs[i]) + " and " + name(tabs[i + 1]) + " overlap");
    }
    const cur = nav.querySelector('[aria-current="page"]');
    if (!cur) problems.push(name(nav) + " marks no tab");
    else {
      const c = cur.getBoundingClientRect();
      if (c.left < n.left - eps || c.right > n.right + eps) problems.push(name(cur) + " is out of sight in its row");
    }
    const scrolls = nav.scrollWidth > nav.clientWidth + 1;
    const faded = nav.classList.contains("more-after") || nav.classList.contains("more-before");
    if (scrolls !== faded) problems.push(name(nav) + (scrolls ? " scrolls without the fade" : " fades without scrolling"));
  }
  const last = rows[rows.length - 1];
  const next = last && last.nextElementSibling;
  if (next && next.getBoundingClientRect().top < last.getBoundingClientRect().bottom - eps) problems.push(name(next) + " runs over the tab row");
  return { problems, scrollY: window.scrollY,
    tabs: rows.map((nav) => Array.from(nav.children).map((t) => (t.getAttribute("aria-current") ? "*" : "") + t.textContent.trim())) };
}"""

ACCOUNT_TABS = (
    ("/account", "Profile", None, "Your picture"),
    ("/account/settings", "Settings", None, "Theme"),
    ("/account/notifications", "Notifications", None, "When mail goes out"),
    ("/account/security", "Security", "Sign-in", "Change password"),
    ("/account/security/sessions", "Security", "Sessions", "Sessions"),
    ("/account/security/device", "Security", "Another device", "Sign in another device"),
    ("/account/security/forge", "Security", "Forge access", "Forge access"),
    ("/account/security/data", "Security", "Your data", "Your data"),
    ("/account/orgs", "Organisations", None, "Organisations"),
    # The setup's return (§11.4, §16.11): Forge access at its own address, no redirect.
    ("/settings/forge", "Security", "Forge access", "Forge access"),
)
# The addresses before the tabs (the menu's, the hub's mails and redirects, §11.4): where each
# leads, in place of it in the history, and the heading focused there; None, none.
ACCOUNT_MOVED = (
    ("/account/picture", "/account", "Your picture"),
    ("/account/preferences", "/account/settings", "Your preferences"),
    ("/account/theme", "/account/settings", "Theme"),
    ("/account/password", "/account/security", "Change password"),
    ("/account/sessions", "/account/security/sessions", "Sessions"),
    ("/account/sign-in-device", "/account/security/device", "Sign in another device"),
    ("/account/forge", "/account/security/forge", "Forge access"),
    ("/account/data", "/account/security/data", "Your data"),
    ("/account/unknown", "/account", None),
    ("/account/security/unknown", "/account/security", None),
)


SWITCH_MEASURE = """() => {
  const main = document.getElementById("main"), header = document.getElementById("header");
  const cs = getComputedStyle(main), bar = getComputedStyle(main, "::before");
  const box = main.getBoundingClientRect(), banner = main.querySelector(".signin-banner");
  const first = main.children[0];
  const top = box.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop) + (parseFloat(bar.marginTop) || 0);
  return {
    content: bar.content, position: bar.position, height: parseFloat(bar.height) || 0, background: bar.backgroundColor,
    animation: bar.animationName, barTop: top, barBottom: top + (parseFloat(bar.height) || 0),
    headerBottom: header.getBoundingClientRect().bottom, bannerTop: banner ? banner.getBoundingClientRect().top : null,
    firstTop: first ? first.getBoundingClientRect().top : null, mainTop: box.top, mainHeight: box.height,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    left: Array.from(main.children).filter((n) => n.hasAttribute("inert"))
      .map((n) => ({ busy: n.getAttribute("aria-busy"), opacity: getComputedStyle(n).opacity })),
  };
}"""

# The view's own first read held: a page switch inside the project stands busy until released.
SWITCH_HOLD = """() => {
  const get = window.Maity.api.get, held = [];
  window.Maity.api.get = (p, ...r) => (p.includes("/events?after=latest")
    ? new Promise((resolve, reject) => held.push(() => get(p, ...r).then(resolve, reject))) : get(p, ...r));
  window.__switchRelease = () => { window.Maity.api.get = get; held.splice(0).forEach((go) => go()); };
}"""


def switch_busy_layout(run: Run, browser) -> None:
    """A page switch while the next view loads (tsk-hn2wa8a7e2eq) in fixture mode: at 1280x900,
    390x844 and 360x780, light and dark, the sign-in banner on and off; with reduced motion at 1280 (light, banner)
    and 390 (dark, no banner) only. The bar stands
    in main's top padding, 3 px, under the header and above the banner or the view, and moves
    nothing; the view being left is dimmed and busy; nothing overflows sideways; all of it is gone
    once the next view stands."""
    run.step("fixtures: a page switch's bar and dimmed view at 1280, 390 and 360 px, light and dark, banner on and off, reduced motion")
    index = (WEB / "index.html").as_uri()
    cases = [(w, h, scheme, banner, False) for (w, h) in ((1280, 900), (390, 844), (360, 780))
             for scheme in ("light", "dark") for banner in (True, False)]  # fmt: skip
    cases += [(1280, 900, "light", True, True), (390, 844, "dark", False, True)]
    for width, height, scheme, banner, reduced in cases:
        where = f"{width}x{height} {scheme}" + (" with the banner" if banner else "") + (", reduced motion" if reduced else "")
        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme,
                                      reduced_motion="reduce" if reduced else "no-preference")  # fmt: skip
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        try:
            page.goto(f"{index}?lang=en#/maintainer/maity/board")
            expect(page.locator("main section.view-board")).to_be_visible()
            expect(page.locator("main .signin-banner")).to_be_visible()
            if not banner:
                page.evaluate("() => document.querySelector('main .signin-banner').remove()")
            still = page.evaluate(SWITCH_MEASURE)
            assert still["content"] in ("none", "normal") and not still["left"], f"{where}: a bar before any switch {still}"
            page.evaluate(SWITCH_HOLD)
            page.evaluate("() => window.Maity.route.go('/maintainer/maity/inbox')")
            page.wait_for_function("() => Array.from(document.getElementById('main').children).some((n) => n.hasAttribute('inert'))")
            page.wait_for_timeout(300)  # the dimming's transition
            busy = page.evaluate(SWITCH_MEASURE)
            problems = []
            if busy["height"] != 3 or busy["position"] != "sticky" or busy["background"] in ("", "rgba(0, 0, 0, 0)"):
                problems.append(f"the bar is not a 3 px sticky bar in the accent: {busy}")
            if busy["barTop"] < busy["headerBottom"] - 0.5:
                problems.append(f"the bar covers the header: top {busy['barTop']}, header ends at {busy['headerBottom']}")
            if busy["bannerTop"] is not None and busy["barBottom"] > busy["bannerTop"] + 0.5:
                problems.append(f"the bar covers the banner: ends at {busy['barBottom']}, banner at {busy['bannerTop']}")
            if busy["firstTop"] is not None and busy["barBottom"] > busy["firstTop"] + 0.5:
                problems.append(f"the bar covers the view: ends at {busy['barBottom']}, first child at {busy['firstTop']}")
            if abs(busy["firstTop"] - still["firstTop"]) > 0.5 or abs(busy["mainTop"] - still["mainTop"]) > 0.5:
                problems.append(f"the page moved: first child {still['firstTop']} -> {busy['firstTop']}, main {still['mainTop']} -> {busy['mainTop']}")
            if not busy["left"] or any(v["busy"] != "true" or abs(float(v["opacity"]) - 0.6) > 0.01 for v in busy["left"]):
                problems.append(f"the view being left is not busy and dimmed: {busy['left']}")
            if busy["overflow"] > 0:
                problems.append(f"{busy['overflow']} px wider than the window")
            if (busy["animation"] == "none") != reduced:
                problems.append(f"animation {busy['animation']} with reduced motion {reduced}")
            assert not problems and not errors, f"{where}: {problems + errors}"
            run.shot(page, f"fixtures-switch-busy-{width}-{scheme}" + ("-banner" if banner else "") + ("-reduced" if reduced else ""))
            page.evaluate("() => window.__switchRelease()")
            expect(page.locator("main section.view-inbox")).to_be_visible()
            done = page.evaluate(SWITCH_MEASURE)
            assert done["content"] in ("none", "normal") and not done["left"] and done["overflow"] <= 0 and not errors, \
                f"{where}: after the switch {done} {errors}"
        finally:
            context.close()


# Before any script reads the fixtures: the theme chosen, and for a reader who keeps no series the
# project's trust lowered to member, so the jour fixe page has no settings of the series.
JOUR_FIXE_FIXTURE = """(() => { try { localStorage.setItem("maity.theme", %s); } catch (e) {}
  if (!%s) return; let f; Object.defineProperty(window, "MAITY_FIXTURES", { configurable: true,
  get() { return f; },
  set(v) { f = v; f["me.json"].projects.forEach((p) => { if (p.full_name === "maintainer/maity") p.trust = "member"; }); } }); })();"""


def jour_fixe_settings_layout(run: Run, browser) -> None:
    """The jour fixe series' settings at the top of the jour fixe page (tsk-3526xb7mqg9r) in fixture
    mode, every state the layout has, at 1280 x 900, 390 x 844 and 360 x 780, light and dark, with the sign-in
    banner and without: for a keeper the link in Project settings, the section folded, opened and
    with the form for a new series (LINES_MEASURE on each); for a member who keeps no series the
    page without the section."""
    run.step("fixtures: the jour fixe series' settings folded, opened and with the form, keeper and not, light and dark, banner on and off")
    index = (WEB / "index.html").as_uri()
    for width, height in ((1280, 900), (390, 844), (360, 780)):
        for scheme in ("light", "dark"):
            for keeper in (True, False):
                context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
                context.add_init_script(JOUR_FIXE_FIXTURE % (json.dumps(scheme), "false" if keeper else "true"))
                page = context.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                who = "keeper" if keeper else "member"
                try:
                    for banner in (True, False):
                        where = f"{who} at {width}x{height} {scheme}" + (" with the banner" if banner else "")
                        tag = f"-{who}-{width}-{scheme}" + ("-banner" if banner else "")

                        def measure(selector: str, state: str) -> None:
                            if not banner:
                                page.evaluate("() => { const b = document.querySelector('main .signin-banner'); if (b) b.remove(); }")
                            assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == scheme, f"{where}: the theme"
                            m = page.evaluate(LINES_MEASURE, selector)
                            assert not m["problems"] and not errors, f"{where}, {state}: {m['problems'] + errors}"

                        if keeper:
                            page.goto("about:blank")
                            page.goto(f"{index}?lang=en#/maintainer/maity/settings")
                            moved = page.locator("main section.jf-series-moved")
                            expect(moved.get_by_role("link", name="Jour fixe", exact=True)).to_be_visible()
                            expect(page.locator("main li.jf-series")).to_have_count(0)
                            measure("main section.jf-series-moved", "Project settings")
                            run.shot(page, "fixtures-jour-fixe-settings-link" + tag)
                        page.goto("about:blank")
                        page.goto(f"{index}?lang=en#/maintainer/maity/jour-fixe")
                        expect(page.locator("main section.jf-series-block").first).to_be_visible()
                        expect(page.locator("main .signin-banner")).to_be_visible()
                        # A round's date link is a 24 px target (WCAG 2.5.8, nte-ynsymv950zq4).
                        tall = page.evaluate("() => Array.from(document.querySelectorAll('main ul.jf-rounds a')).map((a) => Math.round(a.getBoundingClientRect().height))")
                        assert tall and min(tall) >= 24, f"{where}: a round's date link is under 24 px high: {tall}"
                        fold = page.locator("main details.jf-series-settings")
                        if not keeper:
                            # What this state changes is the section's absence: the page stays inside the window.
                            # (The rounds' own lines are not this case's: they are as before.)
                            expect(fold).to_have_count(0)
                            if not banner:
                                page.evaluate("() => { const b = document.querySelector('main .signin-banner'); if (b) b.remove(); }")
                            wide = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                            assert wide <= 0 and not errors, f"{where}, no settings: {wide} px too wide, {errors}"
                            run.shot(page, "fixtures-jour-fixe" + tag)
                            continue
                        expect(fold).not_to_have_attribute("open", "")
                        expect(fold.locator("li.jf-series")).to_have_count(0)
                        measure("main details.jf-series-settings", "folded")
                        run.shot(page, "fixtures-jour-fixe-folded" + tag)
                        fold.locator("summary").click()
                        expect(fold.locator("li.jf-series")).to_have_count(2)
                        measure("main details.jf-series-settings", "opened")
                        run.shot(page, "fixtures-jour-fixe-opened" + tag)
                        fold.get_by_role("button", name="New series", exact=True).click()
                        expect(fold.locator("#jfs-enabled-hint")).to_be_visible()
                        measure("main details.jf-series-settings", "with the form")
                        run.shot(page, "fixtures-jour-fixe-form" + tag)
                        if width == 1280 and banner:
                            run.a11y(page, f"fixtures: jour fixe settings, {scheme}")
                finally:
                    context.close()


def account_tabs_layout(run: Run, browser) -> None:
    """The account's tabs (tsk-3banvfzv3nvs) in fixture mode, every state the layout has: each tab
    and each of Security's own at 2560, 1280, 390 and 360 px, with the sign-in banner and without
    (TABS_MEASURE on every row and tab); switching by a click (the address, the marked tab, the
    page's top, the history); the profile menu, folded and opened, naming the tabs; and every
    address before the tabs leading to its tab, its heading focused, in place of it in the history."""
    run.step("fixtures: the account's tabs at 2560, 1280, 390 and 360 px, banner on and off, switched, the old addresses led on")
    index = (WEB / "index.html").as_uri()
    for width, height in ((2560, 1200), (1280, 900), (390, 844), (360, 780)):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        try:
            for path, tab, sub, part in ACCOUNT_TABS:
                page.goto("about:blank")
                page.goto(f"{index}?lang=en#{path}")
                expect(page.locator("main h3", has_text=part).first).to_be_visible()
                expect(page.locator("main .signin-banner")).to_be_visible()
                if path == "/account/security":
                    # The hub's mail and bell item about the second factor lead here: it comes first.
                    expect(page.locator("main h3").first).to_have_text("Two-factor sign-in")
                for banner in (True, False):
                    if not banner:
                        page.evaluate("() => { const b = document.querySelector('main .signin-banner'); if (b) b.remove(); }")
                    where = f"{path} at {width}x{height}" + (" with the banner" if banner else "")
                    m = page.evaluate(TABS_MEASURE)
                    assert not m["problems"] and not errors, f"{where}: {m['problems'] + errors}"
                    want = [t if t != tab else "*" + t for t in ("Profile", "Settings", "Notifications", "Security", "Organisations", "Linked accounts")]
                    assert m["tabs"][0] == want, f"{where}: the tabs are {m['tabs'][0]}"
                    if sub:
                        assert "*" + sub in m["tabs"][1] and len(m["tabs"]) == 2, f"{where}: Security's tabs are {m['tabs'][1:]}"
                    else:
                        assert len(m["tabs"]) == 1, f"{where}: {len(m['tabs'])} tab rows"
                    run.shot(page, "fixtures-account-tabs" + path.replace("/", "-") + f"-{width}" + ("-banner" if banner else ""))
                # The focus ring of a tab whole, inside its row, which clips what stands outside it.
                page.locator("main nav.account-tabs a.view-tab").first.focus()
                ring = page.evaluate("""() => { const a = document.activeElement, nav = a.closest('nav');
                  const cs = getComputedStyle(a), out = parseFloat(cs.outlineWidth) + parseFloat(cs.outlineOffset);
                  const r = a.getBoundingClientRect(), n = nav.getBoundingClientRect();
                  return { style: cs.outlineStyle, top: r.top - out - n.top, bottom: n.top + nav.clientHeight - (r.bottom + out) }; }""")
                assert ring["style"] != "none" and ring["top"] >= -0.5 and ring["bottom"] >= -0.5, f"{path} at {width}: the focus ring is cut by its row {ring}"
                if width == 1280 and path in ("/account", "/account/security/sessions"):
                    run.a11y(page, f"fixtures: account {path}")
            # Switching: from far down a tab, a click on another shows it from its top, a new entry in the history.
            page.goto(f"{index}?lang=en#/account/settings")
            expect(page.locator("main h3", has_text="Theme")).to_be_visible()
            page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
            row = page.locator("main nav.account-tabs").first
            for path, tab, sub, part in ACCOUNT_TABS:
                if path == "/settings/forge":
                    continue  # reached from the hub, not by a tab
                if sub not in (None, "Sign-in"):
                    page.locator("main nav.security-tabs").get_by_role("link", name=sub, exact=True).click()
                else:
                    row.get_by_role("link", name=tab, exact=True).click()
                expect(page.locator("main h3", has_text=part).first).to_be_visible()
                assert page.url.endswith("#" + path), f"switched to {tab}/{sub} at {width}: {page.url}"
                m = page.evaluate(TABS_MEASURE)
                assert not m["problems"] and not errors and m["scrollY"] == 0, f"switched to {path} at {width}: {m['problems'] + errors}, scrollY {m['scrollY']}"
                page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
            page.go_back()
            expect(page.locator("main h3", has_text="Your data")).to_be_visible()
            assert page.url.endswith("#/account/security/data"), f"back at {width}: {page.url}"
            # The profile menu, folded and opened: the tabs, Linked accounts to come, then Sign out.
            menu = page.locator("#header .profile-menu")
            menu.click()
            items = page.locator("#header ul.menu:visible .menu-item")
            expect(items).to_have_text(["Profile", "Settings", "Notifications", "Security", "Organisations", "Linked accounts · later", "Sign out"])
            m = page.evaluate(LINES_MEASURE, "#header ul.menu:not([hidden])")
            assert not m["problems"] and not errors, f"the profile menu at {width}: {m['problems'] + errors}"
            run.shot(page, f"fixtures-account-menu-{width}")
            items.nth(2).click()
            expect(page.locator("main h3", has_text="When mail goes out")).to_be_visible()
            m = page.evaluate(TABS_MEASURE)
            assert not m["problems"] and "*Notifications" in m["tabs"][0], f"the menu's Notifications at {width}: {m}"
            # Answers that take time, as a hub's do (the fixtures answer at once): the view is put in
            # the page only once its parts are read, so the rows are measured, the current tab
            # brought into sight and a heading focused after that, not before (review of #1409).
            page.goto(f"{index}?lang=en#/all")
            page.evaluate("""() => { const api = window.Maity.api;
              for (const name of ["get", "post"]) { const call = api[name];
                api[name] = (...a) => new Promise((ok) => window.setTimeout(ok, 150)).then(() => call.apply(api, a)); } }""")
            for path, tab, sub, part in ACCOUNT_TABS:
                page.evaluate("(p) => { location.hash = '#' + p; }", path)
                expect(page.locator("main h3", has_text=part).first).to_be_visible()
                m = page.evaluate(TABS_MEASURE)
                assert not m["problems"] and not errors, f"{path} at {width}, slow answers: {m['problems'] + errors}"
            for old, new, focused in ACCOUNT_MOVED:
                page.evaluate("() => { location.hash = '#/all'; }")
                expect(page.locator("main nav.account-tabs")).to_have_count(0)
                page.evaluate("(p) => { location.hash = '#' + p; }", old)
                page.wait_for_function("(p) => location.hash === '#' + p", arg=new)
                expect(page.locator("main nav.account-tabs").first).to_be_visible()
                if focused:
                    expect(page.locator("main h3:focus")).to_have_text(focused)
                # In place of the old address in the history: Back leads to the page before it.
                page.go_back()
                page.wait_for_function("() => location.hash === '#/all'")
            # The addresses before the tabs.
            for old, new, focused in ACCOUNT_MOVED:
                page.goto("about:blank")
                page.goto(f"{index}?lang=en#{old}")
                page.wait_for_function("(p) => location.hash === '#' + p", arg=new)
                expect(page.locator("main nav.account-tabs").first).to_be_visible()
                if focused:
                    expect(page.locator("main h3:focus")).to_have_text(focused)
                m = page.evaluate(TABS_MEASURE)
                assert not m["problems"] and not errors, f"{old} at {width}: {m['problems'] + errors}"
                page.go_back()
                page.wait_for_function("() => location.href === 'about:blank'")
        finally:
            context.close()


PROFILE_LINK_MEASURE = """() => {
  const facts = document.querySelector("main dl.facts"), p = document.querySelector("main p.public-profile-link");
  const a = p && p.querySelector("a"), r = (el) => el ? el.getBoundingClientRect() : null;
  const f = r(facts), l = r(p);
  return { next: !!(facts && p && facts.nextElementSibling === p), in_form: !!(p && p.closest("form")),
           display: p ? getComputedStyle(p).display : null, gap: f && l ? l.top - f.bottom : null,
           text: a ? a.textContent : null, href: a ? a.getAttribute("href") : null, target: a ? a.target : null,
           theme: document.documentElement.getAttribute("data-theme") };
}"""


def profile_public_link_layout(run: Run, browser) -> None:
    """The account's Profile tab (tsk-4e17b8xnp8eq) in fixture mode: "View public page" right under
    the name and handle (`dl.facts`), never under the public-profile form. At 1280 x 900,
    390 x 844 and 360 x 780, light and dark, with the sign-in banner and without, and with the page served and not
    (`page_served: false` from GET /people/{handle}): the link is the facts' next sibling and outside
    the form, a gap of at most 16 px under the facts while served, `display: none` while not; the
    facts and the link measured by LINES_MEASURE, the page never wider than the window."""
    run.step("fixtures: View public page under the name and handle at 1280, 390 and 360 px, light and dark, banner on and off, served and not")
    index = (WEB / "index.html").as_uri()
    for width, height in ((1280, 900), (390, 844), (360, 780)):
        for scheme in ("light", "dark"):
            context = browser.new_context(viewport={"width": width, "height": height}, locale="en-US", color_scheme=scheme)
            context.add_init_script(f"try {{ localStorage.setItem('maity.theme', '{scheme}'); }} catch (e) {{}}")
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            try:
                for served in (True, False):
                    page.goto("about:blank")
                    page.goto(f"{index}?lang=en#/account")
                    expect(page.locator("main dl.facts")).to_be_visible()
                    if not served:
                        # The hub no longer serves the page: the tab drawn again reads it anew.
                        page.evaluate("""() => { const api = window.Maity.api, get = api.get;
                          api.get = (p, ...rest) => p === '/people/maintainer'
                            ? get.call(api, p, ...rest).then((x) => ({ ...x, page_served: false })) : get.call(api, p, ...rest); }""")
                        page.locator("main nav.account-tabs").get_by_role("link", name="Settings", exact=True).click()
                        expect(page.locator("main h3", has_text="Theme")).to_be_visible()
                        page.locator("main nav.account-tabs").get_by_role("link", name="Profile", exact=True).click()
                        expect(page.locator("main dl.facts")).to_be_visible()
                        expect(page.locator("main form.public-profile-form")).to_be_visible()
                    else:
                        expect(page.locator("main p.public-profile-link a")).to_be_visible()
                    expect(page.locator("main .signin-banner")).to_be_visible()
                    for banner in (True, False):
                        if not banner:
                            page.evaluate("() => { const b = document.querySelector('main .signin-banner'); if (b) b.remove(); }")
                        where = f"the Profile tab at {width}x{height} {scheme}, {'served' if served else 'not served'}" + (", with the banner" if banner else "")
                        m = page.evaluate(PROFILE_LINK_MEASURE)
                        lines = page.evaluate(LINES_MEASURE, "main dl.facts, main p.public-profile-link")
                        assert not lines["problems"] and not errors, f"{where}: {lines['problems'] + errors}"
                        assert m["theme"] == scheme, f"{where}: the theme is {m['theme']}"
                        assert m["next"] and not m["in_form"], f"{where}: the link is not right under the name and handle: {m}"
                        if served:
                            assert m["display"] != "none" and 0 <= m["gap"] <= 16, f"{where}: {m}"
                            assert (m["text"], m["href"], m["target"]) == ("View public page", "#/maintainer?as=public", "_blank"), f"{where}: {m}"
                        else:
                            assert m["display"] == "none" and m["text"] is None, f"{where}: {m}"
                        run.shot(page, f"fixtures-profile-link-{width}-{scheme}-{'served' if served else 'none'}" + ("-banner" if banner else ""))
            finally:
                context.close()


JOIN_REPORTS_MEASURE = """() => {
  const shown = (el) => !!el && !!el.offsetParent;
  const field = (sel) => { const el = document.querySelector(sel); return el && el.closest(".field"); };
  const box = (el) => el ? el.getBoundingClientRect() : null;
  const fields = document.querySelector(".join-panel .join-fields"), f = box(fields);
  const out = Array.from(document.querySelectorAll(".join-panel .join-fields .field")).filter(shown)
    .flatMap((x) => Array.from(x.children).filter((c) => shown(c) && (box(c).right > box(x).right + 1 || box(c).left < f.left - 1)).map((c) => c.id || c.tagName));
  return { reports: shown(document.querySelector("#join-reports")), member: shown(document.querySelector("#join-member-reports")),
           member_hint: shown(document.querySelector("#join-member-reports-hint")), out,
           member_field_in: fields && field("#join-member-reports") ? fields.contains(field("#join-member-reports")) : null,
           theme: document.documentElement.getAttribute("data-theme") };
}"""


def join_reports_layout(run: Run, browser) -> None:
    """The join panel's Reports to (tsk-nbadjbr9zpg7) in fixture mode, at 1280 x 900, 390 x 844
    and 360 x 780, light and dark, with the sign-in banner and without: for a new agent the select
    among the membership's fields, for an agent already here its own field with the current boss
    and its hint; each field and its children inside the form's column (LINES_MEASURE over the
    fields, the page never wider than the window)."""
    run.step("fixtures: Reports to in the join panel at 1280, 390 and 360 px, light and dark, banner on and off, new agent and member")
    index = (WEB / "index.html").as_uri()
    # 360 px as well: there the profile's two links wrap whatever the fonts (at 390 only with CI's).
    for width, height in ((1280, 900), (390, 844), (360, 780)):
        for scheme in ("light", "dark"):
            context = browser.new_context(viewport={"width": width, "height": height}, locale="en-US", color_scheme=scheme)
            context.add_init_script(f"try {{ localStorage.setItem('maity.theme', '{scheme}'); }} catch (e) {{}}")
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            try:
                for agent, kind in (("", "new"), ("agt-b", "member")):
                    page.goto("about:blank")
                    page.goto(f"{index}?lang=en#/maintainer/maity/agents/join")
                    expect(page.locator(".join-panel #join-agent")).to_be_visible()
                    page.locator("#join-agent").select_option(agent)
                    if kind == "member":
                        expect(page.locator("#join-member-reports")).to_have_value("agt-a")
                    expect(page.locator("main .signin-banner")).to_be_visible()
                    for banner in (True, False):
                        if not banner:
                            page.evaluate("() => { const b = document.querySelector('main .signin-banner'); if (b) b.remove(); }")
                        where = f"the join panel at {width}x{height} {scheme}, {kind}" + (", with the banner" if banner else "")
                        m = page.evaluate(JOIN_REPORTS_MEASURE)
                        lines = page.evaluate(LINES_MEASURE, ".join-panel .join-fields")
                        assert not lines["problems"] and not errors, f"{where}: {lines['problems'] + errors}"
                        assert m["theme"] == scheme and not m["out"], f"{where}: {m}"
                        if kind == "new":
                            assert m["reports"] and not m["member"], f"{where}: {m}"
                        else:
                            assert m["member"] and m["member_hint"] and m["member_field_in"] and not m["reports"], f"{where}: {m}"
                        page.locator(".join-panel #join-member-reports" if kind == "member" else ".join-panel #join-reports").scroll_into_view_if_needed()
                        run.shot(page, f"fixtures-join-reports-{width}-{scheme}-{kind}" + ("-banner" if banner else ""))
            finally:
                context.close()


def pair_exchange(run: Run, pair_line: str) -> tuple[int, dict, str]:
    """What `maity runner pair` does on the runner host: the exchange of §15.2."""
    words = shlex.split(pair_line)
    assert words[:3] == ["maity", "runner", "pair"] and words[4] == "--code", words
    token = words[3].rstrip("/").rsplit("/", 1)[-1]
    request = urllib.request.Request(
        run.base + "/api/v1/runners/pair/" + token,
        data=json.dumps({"code": words[5], "client": "maity-e2e/1"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        # Header names in lower case: HTTP names are case-insensitive.
        headers = {k.lower(): v for k, v in response.headers.items()}
        return response.status, headers, response.read().decode()


def runners_step(run: Run, page: Page) -> None:
    """The instance-level Runners view (docs/api.md §15.2, §15.3) against the hub."""
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    # A hash-only goto returns before the page renders anew, and that render
    # replaces the header: a menu opened on the old one is gone mid-click.
    expect(page.locator("main section.view-team")).to_be_visible()
    # Runners are the person's: in the gear menu, not the project row (tsk-cb6myw32def0).
    expect(page.locator("nav.switcher").get_by_role("link", name="Runners", exact=True)).to_have_count(0)
    page.locator("header").get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("menuitem", name="Runners", exact=True).click()
    expect(page).to_have_url(re.compile(r"/runners$"))
    view = page.locator("main section.view-runners")
    expect(view).to_be_visible()
    expect(page.locator("main .error")).to_have_count(0)
    run.step(
        "runners: pair a runner from the dashboard, exchange the line, rename, re-pair, revoke, remove"
    )
    expect(view).to_contain_text("No runner yet.")
    page.locator("#pair-name").fill("e2e-runner")
    page.get_by_role("button", name="Create the pairing line", exact=True).click()
    steps = page.locator(".pair-steps")
    expect(steps).to_contain_text("maity runner pair")
    config = page.locator(".runner-config").inner_text()
    assert f'url = "{run.base}"' in config and '"owner/e2e-alpha"' in config and '"owner/e2e-beta"' in config, (
        config
    )
    pair_line = steps.locator("pre.paste-line").nth(1).inner_text()
    assert pair_line.startswith("maity runner pair ") and pair_line not in config, pair_line
    run.shot(page, "runners-pairing")
    run.a11y(page, "runners, pairing")
    status, headers, credential = pair_exchange(run, pair_line)
    assert status == 201 and credential.startswith("mty1.rcrd-"), (status, credential[:12])
    assert headers.get("maity-runner-id", "").startswith("rnr-"), headers
    # The panel's 30-s re-read sees the runner paired; it is offline until it serves.
    expect(page.locator(".pair-wait")).to_contain_text(
        "e2e-runner is paired", timeout=COUNTS_MS + 15_000
    )
    card = page.locator("article.runner", has=page.get_by_role("heading", name="e2e-runner"))
    expect(card).to_contain_text("offline, never connected")
    expect(card).to_contain_text("It has not reported what it can do yet")
    first_credential = headers["maity-credential-id"]
    expect(card).to_contain_text(first_credential)
    run.a11y(page, "runners, one paired")
    card.locator("input[id^=runner-name-]").fill("e2e-renamed")
    card.get_by_role("button", name="Rename", exact=True).click()
    card = page.locator("article.runner", has=page.get_by_role("heading", name="e2e-renamed"))
    expect(card).to_be_visible()
    project_runners_step(run, page, "e2e-renamed")
    page.goto(f"{run.base}/runners")
    card = page.locator("article.runner", has=page.get_by_role("heading", name="e2e-renamed"))
    card.get_by_role("button", name="Re-pair", exact=True).click()
    expect(page.locator(".pair-steps")).to_contain_text("Keep your existing configuration")
    repair = page.locator(".pair-steps pre.paste-line").nth(1).inner_text()
    status, headers2, _ = pair_exchange(run, repair)
    assert status == 201 and headers2["maity-runner-id"] == headers["maity-runner-id"], headers2
    page.goto(f"{run.base}/all")
    # A hash change only: the Runners view from before (already showing the new
    # credential) stays until /all is drawn. Without this wait the Revoke below can
    # land on that old view, while the new one draws a read from before the revoke.
    expect(page.locator("main section.view-all")).to_be_visible()
    page.goto(f"{run.base}/runners")
    card = page.locator("article.runner", has=page.get_by_role("heading", name="e2e-renamed"))
    expect(card).to_contain_text(headers2["maity-credential-id"])  # the old one was replaced
    page.once("dialog", lambda d: d.accept())
    card.get_by_role("button", name="Revoke", exact=True).click()
    expect(card).to_contain_text("revoked")
    page.once("dialog", lambda d: d.accept())
    card.get_by_role("button", name="Remove", exact=True).click()
    expect(page.locator("main")).to_contain_text("e2e-renamed was removed.")
    expect(page.locator("main")).to_contain_text("Nothing was running on it.")
    expect(page.locator("article.runner")).to_have_count(0)
    run.shot(page, "runners-removed")
    no_problems(run, "runners")


def board_cards_step(run: Run, page: Page, alpha: Path) -> None:
    """Cards from the board (docs/api.md §6.4): create, move by menu and by dragging."""
    run.step("board: the owner writes a card, moves it with the menu, drags it to a refused and an allowed column")
    page.goto(f"{run.base}/owner/e2e-alpha/board")
    page.get_by_role("button", name="New card", exact=True).click()
    page.locator("#new-card-title").fill("E2E: a card from the board")
    page.locator("#new-card-area").fill("web/")
    page.locator("#new-card-status").select_option("proposed")
    page.locator("#new-card-needs").select_option("tester")
    run.a11y(page, "board, new card")
    page.locator("form.new-card").get_by_role("button", name="Create card", exact=True).click()
    view = page.locator("main section.view-board")
    expect(view.locator(".send-status").first).to_contain_text("created in proposed")
    card = page.locator("article.card", has_text="E2E: a card from the board")
    # needs (§6.4): shown on the card and filtered by the hub's own value.
    expect(card.locator(".card-needs")).to_have_text("Needs: Tester")
    page.locator("#board-needs").select_option("tester")
    expect(card).to_be_visible()
    page.locator("#board-needs").select_option("")
    proposed = page.locator('section.column[data-status="proposed"]')
    expect(proposed.locator("article.card", has_text="E2E: a card from the board")).to_be_visible()
    # The status menu, the keyboard's way: proposed to open, the focus stays on the menu.
    card.locator(".card-move .menu-button").click()
    card.locator(".card-move").get_by_role("menuitem", name="Move to Open", exact=True).click()
    opened = page.locator('section.column[data-status="open"]').locator("article.card", has_text="E2E: a card from the board")
    expect(opened).to_be_visible()
    expect(opened.locator(".card-move .menu-button")).to_be_focused()
    # Dragging, as the browser's drag events: the page's handlers in a real
    # browser, without a mouse drag across columns that may lie off screen.
    def drag(target: str, drop: bool) -> None:
        moving = page.locator("article.card", has_text="E2E: a card from the board")
        column = page.locator(f'section.column[data-status="{target}"]')
        dt = page.evaluate_handle("() => new DataTransfer()")
        moving.dispatch_event("dragstart", {"dataTransfer": dt})
        column.dispatch_event("dragenter", {"dataTransfer": dt})
        column.dispatch_event("dragover", {"dataTransfer": dt})
        if drop:
            column.dispatch_event("drop", {"dataTransfer": dt})
        page.locator("article.card", has_text="E2E: a card from the board").dispatch_event("dragend", {"dataTransfer": dt})

    # Let go over a column it may not go to: refused, and nothing is sent.
    drag("done", drop=False)
    expect(view.locator(".send-status").first).to_contain_text("cannot go to Done")
    expect(page.locator('section.column[data-status="open"]').locator("article.card", has_text="E2E: a card from the board")).to_be_visible()
    # Dropped on one it may go to: cancelled.
    drag("cancelled", drop=True)
    expect(page.locator('section.column[data-status="cancelled"]').locator("article.card", has_text="E2E: a card from the board")).to_be_visible()
    run.shot(page, "board-cards")
    no_problems(run, "board cards")
    two_signatures_step(run, page)
    public_page_step(run, page)
    request_action_step(run, page)
    board_order_step(run, page)
    overview_step(run, page)
    ticker_step(run, page)
    notifications_step(run, page, alpha)


def request_action_step(run: Run, page: Page) -> None:
    """§2.3 in the browser, for how the call looks: the hub's list is answered from here, as this
    run has no proxy to file one. The hub's own tests (test_proxy_go.py) cover filing and using."""
    run.step("inbox: a proxy's action request shows the whole call to the owner")
    body = json.dumps({"policy": {"signing": "required"}, "reason": "a long reason " * 20})
    entry = {
        "id": "req-action",
        "class": "consent",
        "title": "E2E: go for one call",
        "summary": "The proxy asks.",
        "status": "open",
        "priority": "normal",
        "to": "owner",
        "created_at": "2026-11-01T10:00:00Z",
        "asked_by": None,
        "options": [],
        "replies": [{"id": "go", "label": "Go"}, {"id": "no", "label": "No"}],
        "action": {
            "method": "PATCH",
            "path": "/projects/owner/e2e-alpha",
            "query": None,
            "body": body,
            "body_sha256": "0" * 64,
            "used_at": None,
            "used_seq": None,
        },
    }
    # The inbox reads the open requests alone (tsk-y8gkq1kvt63c); this one is open.
    pattern = re.compile(r"/api/v1/projects/owner/e2e-alpha/requests\?status=open")

    def answer(route) -> None:
        route.fulfill(json={"items": [entry], "next_cursor": None})

    page.route(pattern, answer)
    try:
        page.goto(f"{run.base}/owner/e2e-alpha/inbox/req-action")
        call = page.locator(".request-action")
        expect(call).to_contain_text("The call this go allows")
        expect(call).to_contain_text("/projects/owner/e2e-alpha")
        expect(call.locator("pre.request-action-body").first).to_contain_text('"signing": "required"')
        call.get_by_text("Exactly as sent", exact=True).click()
        expect(call.locator("pre.request-action-body").nth(1)).to_have_text(body)
        expect(page.locator(".entry-body .replies").get_by_role("button", name="Go", exact=True)).to_be_visible()
        # A long line in the body wraps; unwrapped it once stretched the whole page.
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        run.a11y(page, "inbox, action request")
        run.shot(page, "inbox-action-request")
        # A body that parsing changes and a character nobody sees: said, and readable at both widths.
        entry["action"] = dict(entry["action"], path="/projects/owner/e2e\u202e-alpha", body='{"n": 9007199254740993}')
        page.goto(f"{run.base}/owner/e2e-alpha/settings")
        page.goto(f"{run.base}/owner/e2e-alpha/inbox/req-action")
        expect(call.locator(".request-action-warning")).to_have_count(2)
        expect(call.locator("mark.hidden-char")).to_have_text("[U+202E]")
        expect(call.locator("details pre")).to_be_visible()
        expect(call.locator("details pre")).to_contain_text("9007199254740993")
        run.a11y(page, "inbox, action request that warns")
    finally:
        page.unroute(pattern, answer)


def two_signatures_step(run: Run, page: Page) -> None:
    """§6.4 against the hub: under reviewer_and_tester the owner signs one place, says which, and
    the card stays in review. The second signature needs a second member: the hub's own tests."""
    run.step("board: two signatures, the owner signs the review and the card stays in review")
    base = "/projects/owner/e2e-alpha"

    def api(method: str, path: str, body: dict | None = None):
        return page.evaluate("([m, p, b]) => window.Maity.api[m](p, b)", [method, base + path, body])

    # Set in Settings (§6.1), as a person would, and back in the end whatever happens between.
    def authority(value: str, reason: str) -> None:
        page.goto(f"{run.base}/owner/e2e-alpha/settings")
        form = page.locator("form.done-authority-form")
        form.locator("#done-authority-select").select_option(value)
        form.locator("#done-authority-reason").fill(reason)
        form.get_by_role("button", name="Save", exact=True).click()
        expect(page.locator("main")).to_contain_text("Who closes a card saved.")
        expect(page.locator("#done-authority-select")).to_have_value(value)

    before = api("get", "")["policy"]["done_authority"]
    authority("reviewer_and_tester", "e2e: two signatures")
    try:
        made = api("post", "/tasks", {"title": "E2E: two signatures", "status": "open"})
        api("post", f"/tasks/{made['id']}/claim", {})
        sha = "d91e294c" + "0" * 32
        report = {
            "summary": "Done for the signatures.",
            "head": sha,
            "branch": "agent-e2e/signatures",
            "upstream": "origin/agent-e2e/signatures",
            "remote_head": sha,
            "pr": None,
            "pr_status": "none",
            "pr_unknown_reason": None,
            "why": {"none": "a test report, nothing to keep"},
        }
        api("post", f"/tasks/{made['id']}/report", report)
        page.goto(f"{run.base}/owner/e2e-alpha/board")
        card = page.locator("article.card", has_text="E2E: two signatures")
        approvals = card.locator(".card-approvals")
        expect(approvals).to_contain_text("Review: not signed yet")
        expect(approvals).to_contain_text("Test: not signed yet")
        card.locator(".card-move .menu-button").click()
        card.locator(".card-move").get_by_role("menuitem", name="Sign the review", exact=True).click()
        expect(page.locator("main section.view-board .send-status").first).to_contain_text("signature saved")
        card = page.locator('section.column[data-status="review"]').locator("article.card", has_text="E2E: two signatures")
        expect(card.locator(".card-approvals")).to_contain_text("Review: signed by")
        expect(card.locator(".card-approvals")).to_contain_text("Test: not signed yet")
        run.shot(page, "board-two-signatures")
        card.locator(".card-move .menu-button").click()
        expect(card.locator(".card-move").get_by_role("menuitem", name="Sign the test", exact=True)).to_have_count(0)
        page.keyboard.press("Escape")
        # A rework clears them (§6.4).
        api("patch", f"/tasks/{made['id']}", {"status": "in_progress"})
        assert api("get", f"/tasks/{made['id']}")["approvals"] is None
        api("patch", f"/tasks/{made['id']}", {"status": "cancelled"})
    finally:
        authority(before, "e2e: back")
    no_problems(run, "two signatures")


def visitor_step(run: Run, page: Page) -> None:
    """A browser without a session never ends at the login on a public address (tsk-jj1tfre7n6zb)."""
    run.step("public pages: a visitor reaches them, a dashboard address links them from the login")
    form = page.locator("form.public-page-form")
    page.goto(f"{run.base}/owner/e2e-alpha/settings")
    was_on = form.locator("#public-page").is_checked()
    if not was_on:
        form.locator("#public-page").set_checked(True)
        form.get_by_role("button", name="Save", exact=True).click()
        expect(page.locator("main")).to_contain_text("Public page saved.")
    assert page.request.get(f"{run.base}/owner/e2e-alpha?as=public").headers.get("etag"), "no public page served"
    context = page.context.browser.new_context()
    guest = context.new_page()
    # An address that shows nothing (tsk-h1e5zmq1wnhj): "not found" in the frame, no sign-in form.
    # Its "Public projects" is the hub's page: a page load, not a route change (tsk-mg681fdn8p6m).
    guest.goto(f"{run.base}/no-such-page-here")
    not_found = guest.locator("section.view-not-found")
    expect(not_found).to_be_visible()
    expect(guest.locator("#login-email")).to_have_count(0)
    not_found.get_by_role("link", name="Public projects", exact=True).click()
    expect(guest).to_have_url(f"{run.base}/explore")
    expect(guest.locator("h1")).to_have_text("Public projects")
    assert not guest.evaluate("!!(window.Maity && window.Maity.route)"), "/explore: still the dashboard"
    guest.goto(f"{run.base}/explore")
    expect(guest.locator("h1")).to_have_text("Public projects")
    guest.locator('a[href="/owner/e2e-alpha"]').click()
    expect(guest).to_have_url(f"{run.base}/owner/e2e-alpha")
    expect(guest.locator("#login-email")).to_have_count(0)
    # The dashboard draws the page, read-only, with the way to sign in.
    expect(guest.locator("section.view-visitor")).to_be_visible()
    expect(guest.locator("section.view-visitor button")).to_have_count(0)
    expect(guest.locator(".visitor-sign-in")).to_be_visible()
    guest.get_by_role("link", name="Board", exact=True).click()
    expect(guest).to_have_url(f"{run.base}/owner/e2e-alpha/board")
    expect(guest.locator('section.view-visitor[data-kind="board"]')).to_be_visible()
    # The way to sign in leads to the form, and the address it came from is kept.
    guest.locator(".visitor-sign-in").click()
    expect(guest.locator("#login-email")).to_be_visible()
    assert "next=" in guest.url, guest.url
    # A hub page whose data cannot be read stays readable, with its links working.
    guest.route("**/api/v1/public/pages/**", lambda route: route.abort())
    guest.goto(f"{run.base}/owner/e2e-alpha/board")
    expect(guest.locator("#login-email")).to_have_count(0)
    expect(guest.locator("#main h1")).to_be_visible()
    assert guest.locator("#main > [inert]").count() == 0
    guest.unroute("**/api/v1/public/pages/**")
    served = page.request.get(f"{run.base}/owner/e2e-alpha/board", headers={"Cookie": ""})
    assert "x-robots-tag" not in served.headers, served.headers
    guest.goto(f"{run.base}/owner/e2e-alpha/")
    expect(guest).to_have_url(f"{run.base}/owner/e2e-alpha")
    expect(guest.locator("#login-email")).to_have_count(0)
    guest.goto(f"{run.base}/owner/e2e-alpha/inbox")
    expect(guest.locator("#login-email")).to_be_visible()
    guest.locator(".public-page-link a").click()
    expect(guest).to_have_url(f"{run.base}/owner/e2e-alpha")
    # What the dashboard reads for someone who is no member: the same answer without a session.
    read = guest.request.get(f"{run.base}/api/v1/public/pages/owner/e2e-alpha/board")
    assert read.status == 200 and read.json()["kind"] == "board", read.status
    context.close()
    if not was_on:
        page.goto(f"{run.base}/owner/e2e-alpha/settings")
        form.locator("#public-page").set_checked(False)
        form.get_by_role("button", name="Save", exact=True).click()
        expect(page.locator("main")).to_contain_text("Public page saved.")


def public_page_step(run: Run, page: Page) -> None:
    """§16.9 against the hub: the namespace owner switches the project's page and writes its text,
    and turns on their own profile; each is read back through the API."""
    run.step("public page: the namespace owner sets the project's page, and their own profile")
    page.goto(f"{run.base}/owner/e2e-alpha/settings")
    form = page.locator("form.public-page-form")
    expect(form).to_contain_text("Never public")
    was_on = form.locator("#public-page").is_checked()
    run.a11y(page, "settings, public page")
    form.locator("#public-about").fill("# E2E Alpha")
    form.locator("#public-page").set_checked(not was_on)
    form.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("main")).to_contain_text("Public page saved.")
    read = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha").json()
    assert read["public_about"] == "# E2E Alpha" and read["public_page"] == ("off" if was_on else "on"), read
    form = page.locator("form.public-page-form")
    form.locator("#public-about").fill("")
    form.locator("#public-page").set_checked(was_on)
    # "Saved" still stands from the first save, and the emptied field reads empty before anything
    # is sent: only the hub's answer says this one arrived.
    with page.expect_response(lambda r: r.request.method == "PATCH" and r.url.endswith("/projects/owner/e2e-alpha")) as saved:
        form.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    read = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha").json()
    assert read["public_about"] is None and read["public_page"] == ("on" if was_on else "off"), read
    expect(page.locator("form.public-page-form #public-about")).to_have_value("")
    expect(page.locator("#public-page")).to_be_checked(checked=was_on)
    visitor_step(run, page)
    page.goto(f"{run.base}/account")
    profile = page.locator("form.public-profile-form")
    run.a11y(page, "account, public profile")
    profile.locator("#public-profile").check()
    profile.locator("#public-bio").fill("Builds things in e2e.")
    profile.get_by_role("button", name="Save", exact=True).click()
    expect(profile).to_contain_text("Saved.")
    member = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    assert member["public_profile"] is True and member["public_bio"] == "Builds things in e2e.", member
    # The links: the hub's refusal stands at its field, in words; then what it stored comes back.
    profile.locator("#public-github").fill("https://github.com/owner")
    profile.get_by_role("button", name="Save", exact=True).click()
    expect(profile.locator("#public-github-error")).to_contain_text("Give the name, not a link.")
    run.problems = [p for p in run.problems if "PATCH /api/v1/me answered 400" not in p]  # the refusal asked for
    profile.locator("#public-github").fill("e2e-owner")
    profile.locator("#public-website").fill("https://example.org/e2e")
    profile.locator("#public-mastodon").fill("@Owner@Mastodon.Social")
    profile.locator("#public-links-visible").select_option("everyone")
    with page.expect_response(lambda r: r.request.method == "PATCH" and r.url.endswith("/api/v1/me")) as saved:
        profile.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    expect(profile.locator("#public-mastodon")).to_have_value("@Owner@mastodon.social")
    expect(profile.locator("#public-github-error")).to_be_empty()
    member = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    assert member["website"] == "https://example.org/e2e" and member["links_visible"] == "everyone", member
    assert member["social"] == {"github": "e2e-owner", "mastodon": "@Owner@mastodon.social"}, member
    run.a11y(page, "account, public profile with links")
    run.shot(page, "account-public-profile")
    profile.locator("#public-github").fill("")
    profile.locator("#public-mastodon").fill("")
    profile.locator("#public-website").fill("")
    profile.locator("#public-links-visible").select_option("private")
    profile.locator("#public-profile").uncheck()
    profile.locator("#public-bio").fill("")
    with page.expect_response(lambda r: r.request.method == "PATCH" and r.url.endswith("/api/v1/me")) as saved:
        profile.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    expect(profile.locator("#public-bio")).to_have_value("")
    member = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    assert member["public_profile"] is False and member["public_bio"] is None, member
    assert member["website"] is None and member["social"] == {} and member["links_visible"] == "private", member
    no_problems(run, "public page")


def board_order_step(run: Run, page: Page) -> None:
    """Card order within a column (docs/api.md §6.4): Place and dragging, by tasks:admin."""
    page.goto(f"{run.base}/owner/e2e-alpha/board")
    view = page.locator("main section.view-board")
    for title in ("E2E order: first", "E2E order: second"):
        page.get_by_role("button", name="New card", exact=True).click()
        page.locator("#new-card-title").fill(title)
        if title.endswith("first"):
            # The @ picker on a card's text.
            page.locator("#new-card-body").press_sequentially("for @e2e-ag")
            expect(page.locator("form.new-card .mention-list li").first).to_be_visible()
            page.locator("#new-card-body").press("Enter")
            expect(page.locator("#new-card-body")).to_have_value("for @e2e-agent ")
        page.locator("#new-card-status").select_option("open")
        page.locator("form.new-card").get_by_role("button", name="Create card", exact=True).click()
        expect(view.locator(".send-status").first).to_contain_text("created in open")
    column = page.locator('section.column[data-status="open"]')
    titles = column.locator("article.card h3").filter(has_text=re.compile(r"^E2E order: "))
    # Two cards made in the same second have no rank yet and tie on
    # created_at, so their id decides (§6.4): read the order, never assume it.
    expect(titles).to_have_count(2)
    upper, lower = titles.all_inner_texts()
    lower_card = column.locator("article.card", has_text=lower)
    # The lower one goes up, with its Move up arrow.
    lower_card.locator(".card-order").get_by_role("button", name="Move up", exact=True).click()
    expect(view.locator(".send-status").first).to_contain_text(re.compile(r"is now (above|at the top)"))
    run.step("board order: the owner moves a card up with its arrow, then drags it back below")
    # The status line speaks before the board is read again: wait for the order itself.
    expect(titles).to_have_text([lower, upper])
    # The focus stays on one of the moved card's arrows (Move up, or one still enabled at the top).
    moved = column.locator("article.card", has_text=lower)
    expect(moved.locator(".card-order button:focus")).to_have_count(1)
    dt = page.evaluate_handle("() => new DataTransfer()")
    moving = column.locator("article.card", has_text=lower)
    target = column.locator("article.card", has_text=upper)
    box = target.bounding_box()
    moving.dispatch_event("dragstart", {"dataTransfer": dt})
    target.dispatch_event("dragover", {"dataTransfer": dt, "clientY": box["y"] + box["height"] - 2})
    target.dispatch_event("drop", {"dataTransfer": dt, "clientY": box["y"] + box["height"] - 2})
    moving.dispatch_event("dragend", {"dataTransfer": dt})
    expect(view.locator(".send-status").first).to_contain_text("is now below")
    expect(titles).to_have_text([upper, lower])
    run.a11y(page, "board, order")
    no_problems(run, "board order")


def ticker_step(run: Run, page: Page) -> None:
    """The change ticker (docs/api.md §17)."""
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    view_tab(page, "Ticker").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/ticker$"))
    main = page.locator("main section.view-ticker")
    expect(main.locator("h2")).to_have_text("Ticker")
    run.step("ticker: the owner posts a note, finds it under Everything, mutes notes and stops again")
    form = main.locator("form.ticker-post")
    form.locator("#ticker-post-text").fill("e2e: staging is down for an hour")
    form.locator("#ticker-post-areas").fill("/")
    form.get_by_role("button", name="Post", exact=True).click()
    expect(form).to_contain_text("Posted.")
    main.locator(".ticker-tabs").get_by_role("button", name="Everything", exact=True).click()
    expect(main.locator("li.ticker-item").first).to_contain_text("e2e: staging is down for an hour")
    sub = main.locator("section.ticker-sub")
    sub.locator("#ticker-sub-list").select_option("mute")
    sub.locator("#ticker-sub-kind").select_option("types")
    sub.locator("#ticker-sub-value").fill("note")
    sub.get_by_role("button", name="Add", exact=True).click()
    expect(sub).to_contain_text("Muting note.")
    sub.get_by_role("button", name="Stop muting note", exact=True).click()
    expect(sub).to_contain_text("No longer muting note.")
    run.a11y(page, "ticker")
    no_problems(run, "ticker")


def overview_step(run: Run, page: Page) -> None:
    """The project at a glance (docs/api.md §6.11): links, members, counts that link on."""
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    view_tab(page, "Overview").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/overview$"))
    main = page.locator("main")
    expect(main.locator("section.overview-part").first).to_be_visible()
    run.a11y(page, "overview")
    run.step("overview: the owner sees the project at a glance; a column count opens the board")
    counts = main.locator(".overview-counts li")
    expect(counts).to_have_count(7)
    expect(main.locator('.overview-counts li[data-status="cancelled"]')).not_to_have_text(re.compile(r"^0 "))
    run.shot(page, "overview")
    run.step("overview: the tabs Swarm and Project, each at its own address")
    tabs = main.locator("nav.overview-tabs")
    tabs.get_by_role("link", name="Swarm", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/overview/swarm$"))
    expect(main.locator("section.overview-swarm")).to_be_visible()
    expect(main.locator(".overview-counts")).to_have_count(0)
    run.a11y(page, "overview, swarm tab")
    tabs.get_by_role("link", name="Project", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/overview/project$"))
    expect(main.locator('section.overview-part[aria-labelledby="overview-links"]')).to_be_visible()
    expect(main.locator('section.overview-part[aria-labelledby="overview-badge"]')).to_be_visible()
    run.a11y(page, "overview, project tab")
    run.shot(page, "overview-project")
    tabs.get_by_role("link", name="Summary", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/overview$"))
    main.locator('.overview-counts li[data-status="open"] a').click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/board$"))
    no_problems(run, "overview")


def message_step(run: Run, page: Page, alpha: Path, agent_id: str) -> None:
    """Message the project (docs/api.md §8.4): the owner writes to everyone; the agent's wait has it."""
    run.step("message: the owner writes to the project from the Chat tab; the agent's maity wait gets it")
    page.goto(f"{run.base}/owner/e2e-alpha/chat")
    page.locator(".chat-list-pane").get_by_role("link", name="Message the project", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/message$"))
    wait = run.wait_start(alpha)
    page.locator("#message-type").select_option("notice")
    page.locator("#message-body").fill("The board is yours today, @e2e-agent.")
    run.a11y(page, "message the project")
    page.locator("form.message-form").get_by_role("button", name="Send", exact=True).click()
    expect(page.locator(".message-result")).to_contain_text("Sent to everyone")
    event = run.wait_event(wait)
    assert event.get("kind") == "message", event
    payload = event.get("payload") or {}
    assert payload.get("type") == "notice" and payload.get("body") == "The board is yours today, @e2e-agent.", payload
    # Where the hub resolves mentions (§8.6), the page says whom it told, and a
    # mention reaches a member the message is not addressed to.
    resolves = bool(payload.get("mentions"))
    if resolves:
        assert [m.get("handle") for m in payload["mentions"]] == ["e2e-agent"], payload["mentions"]
        expect(page.locator(".message-result")).to_contain_text("mentioned and notified: E2E Agent")
        wait = run.wait_start(alpha)
        page.locator("#message-to").select_option("role:reviewer")
        page.locator("#message-body").fill("Reviewers: @e2e-agent has the join path.")
        page.locator("form.message-form").get_by_role("button", name="Send", exact=True).click()
        expect(page.locator(".message-result")).to_contain_text("Sent to every reviewer; mentioned and notified: E2E Agent")
        event = run.wait_event(wait)
        assert event.get("kind") == "message" and event["payload"].get("to") == "role:reviewer", event
    run.shot(page, "message-the-project")
    # An agent's instance (tsk-bczgjkfpw1wg): after "#" the @ picker offers its instances; Enter puts
    # the address in, and the address's #id leads to the member page's Sessions with that instance marked.
    body = page.locator("#message-body")
    body.fill("")
    body.press_sequentially("Hi @e2e-agent#")
    option = page.locator(".mention-list li").first
    expect(option.locator(".mention-handle")).to_have_text(re.compile(r"^@e2e-agent#[2-9a-hjkmnp-z]{4,5}$"))
    address = option.locator(".mention-handle").inner_text()
    body.press("Enter")
    expect(body).to_have_value(f"Hi {address} ")
    instance = address.split("#", 1)[1]
    body.fill("")
    page.goto(f"{run.base}/owner/e2e-alpha/team/{agent_id}/sessions/{instance}")
    chosen = page.locator(f"#member-instance-{instance}")
    expect(chosen).to_have_attribute("aria-current", "true")
    expect(chosen).to_be_focused()
    run.a11y(page, "member page, an instance chosen")
    # In a private chat an @name tells nobody: the hub resolves nothing there.
    wait = run.wait_start(alpha)
    page.goto(f"{run.base}/owner/e2e-alpha/chat/{agent_id}")
    # The @ picker as in the inbox; a pick reaches the hint below.
    page.locator("#chat-text").press_sequentially("Ask @e2e-ag")
    expect(page.locator("form.compose .mention-list li").first.locator(".mention-handle")).to_have_text("@e2e-agent")
    run.a11y(page, "chat, the @ list open")
    page.locator("#chat-text").press("Enter")
    expect(page.locator("#chat-text")).to_have_value("Ask @e2e-agent ")
    expect(page.locator(".mention-hint")).to_contain_text("In this chat @e2e-agent notifies nobody.")
    page.locator("#chat-text").fill("Ask @e2e-agent about it later.")
    hint = page.locator(".mention-hint")
    expect(hint).to_contain_text("In this chat @e2e-agent notifies nobody.")
    expect(hint.get_by_role("link")).to_have_attribute("href", "/owner/e2e-alpha/message/%40e2e-agent")
    page.locator("form.compose").get_by_role("button", name="Send", exact=True).click()
    event = run.wait_event(wait)
    assert event.get("kind") == "message" and event["payload"].get("type") == "chat", event
    assert not event["payload"].get("mentions"), event["payload"]
    no_problems(run, "message")


def project_runners_step(run: Run, page: Page, name: str) -> None:
    """Project → Runners (docs/api.md §15.4): allow and detach a paired runner."""
    page.goto(f"{run.base}/owner/e2e-alpha/settings")
    page.get_by_role("link", name="This project's runners", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/runners$"))
    view = page.locator("main section.view-runners")
    expect(view.locator("h2").first).to_be_visible()
    run.step("project runners: allow the paired runner in a project and detach it")
    card = view.locator("article.runner", has=page.get_by_role("heading", name=name))

    def detach() -> None:
        asked: list[str] = []
        page.once("dialog", lambda d: (asked.append(d.message), d.accept()))
        card.get_by_role("button", name="Detach", exact=True).click()
        expect(card).to_have_count(0)
        assert asked == [f"Detach {name} from E2E Alpha? Nothing runs on it here."], asked

    # Allowed while pairing.
    expect(card).to_contain_text("no agent running here")
    detach()
    # An option is the runner's name alone (its presence changes, the form should not).
    option = page.locator("#allow-runner option", has_text=re.compile("^" + re.escape(name) + "$"))
    page.locator("#allow-runner").select_option(value=option.get_attribute("value"))
    view.get_by_role("button", name="Allow it here", exact=True).click()
    expect(card).to_contain_text("no agent running here")
    expect(card).to_contain_text("It has not reported what it can do yet")
    run.shot(page, "project-runners")
    run.a11y(page, "project runners")
    start_on_runner_form(run, page, name)
    page.goto(f"{run.base}/owner/e2e-alpha/runners")
    expect(card).to_contain_text("no agent running here")
    detach()
    expect(view).to_contain_text("No runner is allowed in this project yet.")
    no_problems(run, "project runners")


def start_on_runner_form(run: Run, page: Page, name: str) -> None:
    """Agents → Start an agent on a runner (docs/api.md §15.6, tsk-dsp6htj4c686) against the hub:
    E2E Alpha has no repository, so no runner can start an agent in it and no form is offered
    (tsk-wn6qp27090qy). For the form itself the project's read is answered with a repository and
    the runner's with it among its repositories: the paired runner allowed here is offered; it has
    not reported what it can do, so there is no tool to choose and nothing to send."""
    run.step("placements: without a repository no form; with one the paired runner allowed here is offered, no tool yet")
    page.goto(f"{run.base}/owner/e2e-alpha/agents")
    section = page.locator("main section.placements")
    expect(section.locator(".placement-new-none")).to_have_text(
        "A runner starts an agent in a clone of the project's repository, and this project has none.")
    open_form = section.get_by_role("button", name="Start an agent on a runner", exact=True)
    expect(open_form).to_have_count(0)
    project_read = re.compile(r"/api/v1/projects/owner/e2e-alpha(\?|$)")
    runners_read = re.compile(r"/api/v1/projects/owner/e2e-alpha/runners(\?|$)")

    def with_repository(route) -> None:
        body = route.fetch().json()
        body["repository"] = {"url": "https://github.com/owner/e2e-alpha", "default_branch": "main", "required_check": None,
                              "forge": "github", "probe_configured": False, "probe_via": None, "owner_confirmed": False, "confirmed_by": None}
        route.fulfill(json=body)

    def offering_it(route) -> None:
        body = route.fetch().json()
        for item in body.get("items", []):
            item["runner"]["capabilities"] = {**(item["runner"].get("capabilities") or {}), "repositories": ["github.com/owner/*"]}
        route.fulfill(json=body)

    page.route(project_read, with_repository)
    page.route(runners_read, offering_it)
    try:
        start_on_runner_open(run, page, name, section, open_form)
    finally:
        page.unroute(project_read, with_repository)
        page.unroute(runners_read, offering_it)
    no_problems(run, "start on a runner")


def start_on_runner_open(run: Run, page: Page, name: str, section, open_form) -> None:
    """The form opened over the answers start_on_runner_form gives the project's and runners' reads."""
    page.reload()
    expect(open_form).to_be_visible()
    open_form.click()
    form = section.locator("form.placement-new")
    expect(form).to_be_visible()
    runner_options = form.locator("#placement-new-runner option")
    expect(runner_options).to_have_count(1)
    expect(runner_options.first).to_contain_text(name + " · offline")
    expect(form.locator("#placement-new-tool option")).to_have_count(0)
    expect(form).to_contain_text("The runner offers no tool there that is installed.")
    expect(form.get_by_role("button", name="Start on the runner", exact=True)).to_be_disabled()
    run.shot(page, "placements-start-form")
    run.a11y(page, "placements, start on a runner")
    # The browser's own constraint validation (review of #1558): a handle the pattern refuses,
    # typed for a new profile, stops counting once one of one's agents here is chosen instead.
    form.locator("#placement-new-handle").fill("INVALID")
    assert not page.evaluate("document.querySelector('form.placement-new').checkValidity()"), "an invalid new handle passes validation"
    agents = form.locator("#placement-new-agent option")
    assert agents.count() >= 2, f"no agent of one's own offered: {agents.all_text_contents()}"
    form.locator("#placement-new-agent").select_option(index=1)
    expect(form.locator("fieldset.placement-new-profile")).to_be_hidden()
    assert page.evaluate("document.querySelector('form.placement-new').checkValidity()"), "a hidden new-profile handle still blocks the form"
    # On a phone the open form stays within the page's width (review of #1558: 451 px at 390).
    page.set_viewport_size({"width": 390, "height": 844})
    widths = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    assert widths[0] <= widths[1], f"the form widens the page on a phone: {widths}"
    page.set_viewport_size({"width": 1280, "height": 900})
    form.get_by_role("button", name="Cancel", exact=True).click()
    expect(form).to_have_count(0)
    expect(open_form).to_be_focused()


def notifications_step(run: Run, page: Page, alpha: Path) -> None:
    """Notifications, stage 1 (docs/api.md §18.2): the bell, its list, its keyboard."""
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    expect(page.locator("main section.view-inbox")).to_be_visible()
    bell = page.locator("header button.bell")
    # The header's right block (the maintainer, 2026-10-31, 2026-11-01): the Lead button where there
    # is a lead to reach, Chat, "+", the gear, Notifications, the profile, in one row also on a phone.
    order = page.evaluate("Array.from(document.querySelectorAll('header .me > *')).map((e) => e.className + (e.querySelector('.add-menu') ? ' add' : '') + (e.querySelector('.profile-menu') ? ' profile' : ''))")
    lead = 1 if "lead-button" in order[0] else 0
    assert (len(order) == 5 + lead and "chat-button" in order[lead] and "add" in order[1 + lead]
            and "bell-box" in order[3 + lead] and "profile" in order[4 + lead]), f"header order: {order}"
    # One row with the logo: every shown button's vertical middle within the others' height and the
    # logo's (a pixel of alignment is no wrap). The Lead is hidden there; the Chats page carries it
    # (the maintainer, tsk-m9ew7v609fq0). 360 px as well, where a wrap shows whatever the fonts
    # (tsk-et029v5k73f1).
    for phone_width, phone_height in ((390, 844), (360, 780)):
        page.set_viewport_size({"width": phone_width, "height": phone_height})
        boxes = page.evaluate("Array.from(document.querySelectorAll('header .me > *, header .bar .brand')).filter((e) => e.offsetParent).map((e) => { const r = e.getBoundingClientRect(); return [r.top, r.bottom]; })")
        middles = [(top + bottom) / 2 for top, bottom in boxes]
        assert all(top <= m <= bottom for top, bottom in boxes for m in middles), f"the header's buttons wrap under the logo at {phone_width} px: {boxes}"
        assert page.evaluate("!Array.from(document.querySelectorAll('header .me > *')).some((e) => e.offsetParent && /lead-button/.test(e.className))"), f"the Lead is hidden in the header at {phone_width} px"
    page.set_viewport_size({"width": 1280, "height": 900})
    run.step("chats: the Chat button opens every chat across the projects")
    page.locator("header a.chat-button").click()
    expect(page).to_have_url(re.compile(r"/chats$"))
    expect(page.locator("main section.view-chats h2")).to_have_text("Chats")
    # On a phone the Chats page carries the Lead the header hides there. The scenario's agents are
    # members, so no project has a lead to reach: the members list of E2E Alpha is answered with its
    # agents as admins for this check alone, which gives the header a Lead (spq4 at #1271).
    members = re.compile(r"/api/v1/projects/owner/e2e-alpha/members(\?|$)")

    def as_admins(route) -> None:
        body = route.fetch().json()
        for item in body.get("items", []):
            if item.get("kind") == "agent" and item.get("role") != "proxy":
                item["trust"] = "admin"
        route.fulfill(json=body)

    page.route(members, as_admins)
    try:
        page.reload()
        expect(page.locator("header .me .lead-button")).to_be_visible()
        for phone_width, phone_height in ((390, 844), (360, 780)):  # 360 px as well (tsk-et029v5k73f1)
            page.set_viewport_size({"width": phone_width, "height": phone_height})
            expect(page.locator("header .me .lead-button")).to_be_hidden()
            expect(page.locator("main .chats-lead .lead-button")).to_be_visible()
            # The global list keeps its plain toolbar (#1483 left it alone): the heading takes the full
            # row and the lead control sits under it at the left edge, so a later shared toolbar rule
            # that wraps or moves it shows here (nte-9ezzv8khdtsz).
            row = page.evaluate("""() => {
              const bar = document.querySelector('main section.view-chats .toolbar');
              const box = (e) => e.getBoundingClientRect();
              const b = box(bar), cs = getComputedStyle(bar), h = box(bar.querySelector('h2'));
              const l = box(bar.querySelector('.chats-lead .lead-button'));
              const inner = b.left + parseFloat(cs.paddingLeft), right = b.right - parseFloat(cs.paddingRight);
              return { headLeft: h.left - inner, headRight: right - h.right, below: l.top - h.bottom, leadLeft: l.left - inner };
            }""")
            assert abs(row["headLeft"]) <= 1 and abs(row["headRight"]) <= 1 and row["below"] >= 0 and abs(row["leadLeft"]) <= 1, (
                f"the Chats toolbar at {phone_width} px: the heading the full row, the lead under it at the left edge: {row}")
            # Several leads are a menu; under the heading at the left edge it opens from that edge, on
            # screen (e5kk at #1271). Drawn with a second lead beside the real one.
            box = page.evaluate("""() => new Promise((ok) => {
              const ctx = document.getElementById('header').chatCtx; const t = ctx.chatFound.list[0];
              const two = { list: [t, { ...t, member: { ...t.member, id: t.member.id + '-2', display_name: 'Second lead' } }], multiProject: false };
              const slot = document.querySelector('main .chats-lead');
              const before = slot.firstChild; slot.replaceChildren(window.Maity.leadChat.leadControl(ctx, two));
              slot.querySelector('button').click();
              setTimeout(() => { const r = slot.querySelector('.menu').getBoundingClientRect(); slot.replaceChildren(before); ok([r.left, r.right, innerWidth]); }, 100);
            })""")
            assert box[0] >= 0 and box[1] <= box[2], f"the Chats page's lead menu leaves the screen at {phone_width} px: {box}"
        page.set_viewport_size({"width": 1280, "height": 900})
        expect(page.locator("main .chats-lead .lead-button")).to_be_hidden()
    finally:
        page.unroute(members, as_admins)
    page.reload()
    expect(page.locator("main section.view-chats h2")).to_have_text("Chats")
    run.a11y(page, "chats across projects")
    run.step("all projects: Inbox, Chats and Agents lead its pages; Inbox leads back to the requests")
    pages = page.locator("header nav.views a")
    expect(pages).to_have_count(5)
    expect(pages.nth(1)).to_have_attribute("aria-current", "page")
    expect(page.locator("header nav.switcher a[href='/all']")).to_have_attribute("aria-current", "page")
    pages.nth(0).click()
    expect(page).to_have_url(re.compile(r"/all$"))
    expect(page.locator("header nav.views a").nth(0)).to_have_attribute("aria-current", "page")
    expect(page.locator("main section.view-all")).to_be_visible()
    run.shot(page, "all-projects-pages")
    run.step("all projects: Jour fixe and Why, a section per project, read from the real hub")
    for index, name in ((3, "jour-fixe"), (4, "why")):
        page.locator("header nav.views a").nth(index).click()
        expect(page).to_have_url(re.compile(r"/all/" + name + "$"))
        expect(page.locator("header nav.views a").nth(index)).to_have_attribute("aria-current", "page")
        view = page.locator("main section.view-all-" + name)
        expect(view.locator("section.all-project").first).to_be_visible()
        expect(view).not_to_contain_text("Reading…")
        expect(view).not_to_contain_text("Could not read this project")
        run.a11y(page, "all projects, " + name)
    # These projects have no Keep the Why export: the hub says so with a 409, and the page says it too.
    expect(page.locator("main section.view-all-why")).to_contain_text("publishes no Keep the Why export")
    run.problems = [p for p in run.problems if not ("/keep-the-why" in p and "answered 409" in p)]
    page.locator("header nav.views a").nth(0).click()
    expect(page).to_have_url(re.compile(r"/all$"))
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    expect(page.locator("main section.view-inbox")).to_be_visible()
    run.step("notifications: the owner opens the bell, reads the list, closes it with Escape")
    bell.click()
    panel = page.locator("header .bell-panel")
    expect(panel).to_be_visible()
    run.a11y(page, "notifications bell")
    run.shot(page, "notifications-bell")
    page.keyboard.press("Escape")  # the focus is on the bell after the click
    expect(panel).to_be_hidden()
    expect(bell).to_be_focused()
    # A mention of the owner (nte-nkwh5y6n4ve2): the unread line beside the project's tabs and the
    # filtered All notifications page it leads to, each under axe; Mark all read there marks the
    # mentions of that project only, and the line goes. "@owner" is a group word, never a member
    # (§8.6), so the agent names the owner by the alias handle_hints_step left (LONG_OWNER).
    run.step("notifications: a mention of the owner shows its line beside the tabs and the filtered list, both under axe")
    cursor = run.api(alpha, "GET", "/projects/owner/e2e-alpha/events", after="latest", wait=0)["cursor"]
    run.maity(alpha, "say", "all", f"A mention for @{LONG_OWNER} in the e2e run.", "--type", "notice")
    said = [e for e in run.api(alpha, "GET", "/projects/owner/e2e-alpha/events", after=cursor, wait=0)["items"]
            if e.get("kind") == "message"]
    assert len(said) == 1 and len(said[0]["payload"].get("mentions") or []) == 1, said  # the alias resolved to the owner
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    line = page.locator("header p.mention-note a")
    expect(line).to_be_visible(timeout=20000)
    expect(line).to_have_attribute("href", "/notifications?kind=mention&project=owner%2Fe2e-alpha")
    run.a11y(page, "the unread mention line")
    # Not on the Chat tab, the maintainer's choice, where the list shows chat mentions as an @ (tsk-sesdq48m9ewk); back on the
    # inbox the line is there again.
    page.goto(f"{run.base}/owner/e2e-alpha/chat")
    expect(page.locator(".chat-list-pane")).to_be_visible()
    expect(page.locator("header p.mention-note")).to_have_count(0)
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    expect(line).to_be_visible(timeout=20000)
    line.click()
    expect(page).to_have_url(re.compile(r"/notifications\?kind=mention&project=owner%2Fe2e-alpha$"))
    mark_all = page.get_by_role("button", name="Mark all read", exact=True)
    expect(mark_all).to_be_enabled(timeout=10000)  # the unread mention is listed
    run.a11y(page, "notifications filtered to mentions in a project")
    mark_all.click()
    expect(mark_all).to_be_disabled()
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    expect(page.locator("main section.view-inbox")).to_be_visible()
    expect(page.locator("header p.mention-note")).to_be_hidden(timeout=20000)
    no_problems(run, "notifications")


def why_step(run: Run, page: Page, alpha: Path) -> None:
    """The Keep the Why export (docs/api.md §11.3)."""
    project = run.api(alpha, "GET", "/projects/owner/e2e-alpha")
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    tab = view_tab(page, "Why")
    # The e2e project has no repository: the export is not configured.
    run.step("why: the project has no repository, so the Why view says what it needs")
    assert project["keep_the_why_export"] is None, project["keep_the_why_export"]
    tab.click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/why$"))
    expect(page.locator("main")).to_contain_text(
        "This project publishes no Keep the Why dashboard yet."
    )
    expect(page.locator("main")).to_contain_text("It needs a repository first")
    # The hub's 409 ktw_not_configured is the expected answer here.
    run.problems = [p for p in run.problems if not ("/keep-the-why" in p and "answered 409" in p)]
    run.shot(page, "why-not-configured")
    run.a11y(page, "why, not configured")
    no_problems(run, "why")


def agents_fleet_step(run: Run, page: Page, agent_id: str) -> None:
    """One's own fleet on the Agents page's Organisation tab (tsk-q989pagmk2x9): the owner on top,
    E2E Agent under them, E2E Reviewer (which reports to it) under that; each agent's instances
    as dots linking to their sessions; light and dark at 1280 and 390 px, nothing wider than the window."""
    run.step("agents: the Organisation tab shows one's own agents as a tree under oneself")
    members = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha/members").json()["items"]
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    reviewer = next(m for m in members if m.get("handle") == "e2e-reviewer")
    assert reviewer["reports_to"] == agent_id, reviewer
    # A project name of one unbroken 63-character word wraps in the Agents hint rather than widening the page
    # (nte-fk0fzcsma0e7). The e2e project's name is short, so its read is answered with such a name for this check.
    long_name = "E2E" + "x" * 60
    assert len(long_name) == 63
    project_read = re.compile(r"/api/v1/projects/owner/e2e-alpha$")

    def with_long_name(route) -> None:
        body = route.fetch().json()
        body["name"] = long_name
        route.fulfill(json=body)

    page.route(project_read, with_long_name)
    try:
        for width in (390, 360):
            page.set_viewport_size({"width": width, "height": 844})
            page.goto(f"{run.base}/owner/e2e-alpha/agents")
            expect(page.locator("main p.agents-project-hint")).to_contain_text(long_name)
            wide = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            assert wide[0] <= wide[1], f"Agents with a 63-character project name is {wide[0]} px wide at {width} px"
    finally:
        page.unroute(project_read, with_long_name)
        page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{run.base}/owner/e2e-alpha/agents")
    tabs = page.locator("main nav.agents-tabs")
    expect(tabs.get_by_role("link", name="Agents", exact=True)).to_have_attribute("aria-current", "page")
    tabs.get_by_role("link", name="Organisation", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/agents/organisation$"))
    expect(page.get_by_role("heading", name="Organisation of your agents", exact=True)).to_be_visible()
    tree = page.locator("ul.fleet-tree")
    node = lambda mid: tree.locator(f"li.fleet-member[data-member='{mid}']")
    expect(node(me["id"])).to_have_count(1)
    expect(node(me["id"]).locator(f"li.fleet-member[data-member='{agent_id}']")).to_have_count(1)
    expect(node(agent_id).locator(f"li.fleet-member[data-member='{reviewer['id']}']")).to_have_count(1)
    owned = {m["id"] for m in members if m["kind"] == "agent" and m.get("owner_id") == me["id"]}
    shown = set(tree.locator("li.fleet-member").evaluate_all("(all) => all.map((li) => li.dataset.member)"))
    assert shown == owned | {me["id"]}, (shown, owned)
    dots = node(agent_id).locator(":scope > .fleet-node a.fleet-dot")
    live = [i for i in next(m for m in members if m["id"] == agent_id)["instances"] if not i.get("revoked_at")]
    expect(dots).to_have_count(len(live))
    expect(dots.first).to_have_attribute("href", re.compile(rf"/owner/e2e-alpha/team/{agent_id}/sessions/"))
    try:
        for width, height, scheme in ((1280, 900, "light"), (1280, 900, "dark"), (390, 844, "light"), (390, 844, "dark")):
            page.set_viewport_size({"width": width, "height": height})
            page.emulate_media(color_scheme=scheme)
            page.reload()
            expect(node(reviewer["id"])).to_be_visible()
            wide = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            assert wide[0] <= wide[1], f"the fleet at {width} px {scheme} is {wide[0]} px wide"
            size = dots.first.bounding_box()
            assert size and size["width"] >= 24 and size["height"] >= 24, f"a dot's target at {width} px: {size}"
            run.shot(page, f"agents-fleet-{width}-{scheme}")
        run.a11y(page, "agents, the Organisation tab")
        # Each state's dot differs in shape or size, not in colour alone (WCAG 1.4.1, nte-s2dqhn1n4bez): one probe
        # dot per state in the page's own stylesheet, compared with the colours left out; shown at 390 px for the PR.
        probe = """(states) => {
          const box = document.createElement('span'); box.className = 'fleet-dots fleet-probe';
          document.querySelector('ul.fleet-tree').before(box);
          return states.map((st) => { const a = document.createElement('a'); a.className = 'fleet-dot ' + st; box.appendChild(a);
            const b = getComputedStyle(a, '::before');
            return [st, b.width, b.height, b.borderTopWidth, b.borderLeftWidth, b.backgroundImage === 'none' ? 'none' : 'image', b.backgroundColor === 'rgba(0, 0, 0, 0)' ? 'clear' : 'filled'];
          }); }"""
        states = ["online", "away", "offline", "dormant", "online lead"]
        # Forced colours too (#1598 review): there the browser would drop a gradient, a background colour and a
        # shadow, so the check runs with forced-colors active as well, and the lead keeps its ring.
        for forced in ("none", "active"):
            for scheme in ("light", "dark"):
                page.set_viewport_size({"width": 390, "height": 844})
                page.emulate_media(color_scheme=scheme, forced_colors=forced)
                page.reload()
                expect(node(reviewer["id"])).to_be_visible()
                shapes = page.evaluate(probe, states)
                plain = [x for x in shapes if x[0] != "online lead"]
                assert len({tuple(x[1:]) for x in plain}) == len(plain), f"two dot states look alike ({scheme}, forced colours {forced}): {shapes}"
                ring = page.evaluate("""() => { const b = getComputedStyle(document.querySelector('.fleet-probe .fleet-dot.lead'), '::before');
                  return [b.boxShadow, b.outlineStyle]; }""")
                assert ring[0] != "none" or ring[1] not in ("none", ""), f"the lead dot has no ring ({scheme}, forced colours {forced}): {ring}"
                run.shot(page, f"agents-fleet-states-390-{scheme}" + ("-forced" if forced == "active" else ""))
                page.evaluate("() => document.querySelectorAll('.fleet-probe').forEach((e) => e.remove())")
                print(f"   fleet dots, {scheme}, forced colours {forced}: four shapes {plain}, lead ring kept")
        page.emulate_media(forced_colors="none")
        # A stack of pictures overlaps whether a picture is generated or loaded (nte-b3pfhm2bp0vt (b)): every picture
        # after the first moves 10 px under the one before, mixed kinds included, so the stack keeps its width.
        overlap = page.evaluate("""() => {
          const pairs = [['avatar-svg', 'avatar-img'], ['avatar-img', 'avatar-svg'], ['avatar-svg', 'avatar-svg'], ['avatar-img', 'avatar-img']];
          return pairs.map(([a, b]) => { const box = document.createElement('span'); box.className = 'avatars';
            const one = document.createElement(a === 'avatar-img' ? 'img' : 'span'); one.className = a;
            const two = document.createElement(b === 'avatar-img' ? 'img' : 'span'); two.className = b;
            box.append(one, two); document.body.appendChild(box);
            const m = getComputedStyle(two).marginInlineStart; box.remove(); return [a + '+' + b, m]; }); }""")
        assert all(m == "-10px" for _, m in overlap), f"a stack of mixed pictures does not overlap: {overlap}"
    finally:
        page.emulate_media(color_scheme="light")
        page.set_viewport_size({"width": 1280, "height": 900})

    # Drawn with a boss of someone else's and a lead instance, as the hub would send them (the run
    # has one owner): the stub is the boss's handle as text, nothing else of theirs is on the page.
    listing = re.compile(r"/api/v1/projects/owner/e2e-alpha/members(\?|$)")
    foreign = {"id": "agt-e2eforeign01", "kind": "agent", "handle": "e2e-foreign-boss", "display_name": "Foreign Boss E2E",
               "owner_id": "hum-e2eelsewhere", "trust": "member", "role": "manager", "areas": ["/"], "presence": "online",
               "instances": [{"id": "zi0l", "presence": "online", "lead": True, "claims": 4}]}
    # Found only as a whole word ("#zi0l", "/zi0l", ">zi0l<"). An avatar's hash in the tree is random hex
    # and may hold any hex run, so the id has letters no hash has ("z", "i", "l"), and is not looked
    # for inside a word. An owned instance's id is random too, so the id also has characters the hub's
    # generator never draws ("i", "0", "l"): no instance of one's own can be "zi0l".
    alphabet = re.search(r'^INSTANCE_ALPHABET = "([^"]+)"$', (WEB.parent / "hub/src/maity_hub/ids.py").read_text(), re.M)
    assert alphabet and not set("zi0l") <= set(alphabet[1]), alphabet
    foreign_instance = re.compile(r"(?<![0-9A-Za-z])zi0l(?![0-9A-Za-z])")

    def with_foreign_boss(route) -> None:
        body = route.fetch().json()
        for item in body.get("items", []):
            if item["id"] == agent_id:
                item["reports_to"] = foreign["id"]
                for n, inst in enumerate(i for i in item.get("instances", []) if not i.get("revoked_at")):
                    inst["lead"] = n == 0
        body["items"].append(foreign)
        route.fulfill(json=body)

    page.route(listing, with_foreign_boss)
    try:
        for width, height, scheme in ((1280, 900, "light"), (390, 844, "dark")):
            page.set_viewport_size({"width": width, "height": height})
            page.emulate_media(color_scheme=scheme)
            page.reload()
            stub = node(agent_id).locator(":scope > p.fleet-stub")
            expect(stub).to_have_text("reports to @e2e-foreign-boss")
            expect(stub.locator("a, span")).to_have_count(0)
            expect(node(foreign["id"])).to_have_count(0)
            html = tree.evaluate("(t) => t.outerHTML")
            assert "Foreign Boss E2E" not in html and foreign["id"] not in html and not foreign_instance.search(html), html
            expect(node(agent_id).locator(":scope > .fleet-node a.fleet-dot.lead")).to_have_count(1)
            expect(node(reviewer["id"])).to_be_visible()
            run.shot(page, f"agents-fleet-foreign-boss-{width}-{scheme}")
    finally:
        page.unroute(listing, with_foreign_boss)
        page.emulate_media(color_scheme="light")
        page.set_viewport_size({"width": 1280, "height": 900})
    no_problems(run, "agents organisation")


def join_reports_to_step(run: Run, page: Page, agent_id: str) -> None:
    """Whom an agent reports to, chosen in the join panel (tsk-nbadjbr9zpg7, §3.1, §2.3): the
    first agent joined without one reports to nobody, the reviewer joined with the first agent as
    its boss reports to it after the exchange; an agent already here gets a new boss in the panel,
    sent as its owner's PATCH before the join, said beside the new line and read back from the hub."""
    run.step("reports to: chosen in the join panel, for a new agent and for one already here")
    members_path = f"{run.base}/api/v1/projects/owner/e2e-alpha/members"
    by_handle = lambda: {m.get("handle"): m for m in page.request.get(members_path).json()["items"]}
    found = by_handle()
    assert found["e2e-agent"]["reports_to"] is None, found["e2e-agent"]
    assert found["e2e-reviewer"]["reports_to"] == agent_id, found["e2e-reviewer"]
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    page.goto(f"{run.base}/owner/e2e-alpha/agents/join?agent={agent_id}")
    expect(page.locator(".join-panel")).to_be_visible()
    expect(page.locator("#join-agent")).to_have_value(agent_id)
    pick = page.locator("#join-member-reports")
    expect(pick).to_be_visible()
    expect(pick).to_have_value("")
    # The agent itself is never offered, nor the reviewer below it (a circle).
    values = pick.locator("option").evaluate_all("(all) => all.map((o) => o.value)")
    assert agent_id not in values and found["e2e-reviewer"]["id"] not in values and me["id"] in values, values
    pick.select_option(me["id"])
    page.get_by_role("button", name="Create join line", exact=True).click()
    # An instance's line comes with its state-dir line, also a .paste-line.
    expect(page.locator(".join-result .paste-line:not(.state-dir-line)")).to_be_visible()
    expect(page.locator(".join-result p.join-reports-said")).to_have_text(f"E2E Agent now reports to {me['display_name']}.")
    assert by_handle()["e2e-agent"]["reports_to"] == me["id"]
    run.shot(page, "join-reports-to-member")
    no_problems(run, "reports to in the join panel")
    # The line is not used: revoked, so no open join of this step counts later; and the boss
    # undone on the agent's card (its owner's own form, §2.3), as the later steps expect it.
    page.locator(".join-result").get_by_role("button", name="Done", exact=True).click()
    # The button's name is its label, which names the agent.
    revoke = page.get_by_role("button", name="Revoke the join for E2E Agent", exact=True)
    seat = page.locator("article.seat").filter(has=revoke)
    expect(seat).to_have_count(1)
    seat.get_by_role("button", name="Revoke the join for E2E Agent", exact=True).click()
    expect(seat).to_have_count(0)
    page.goto(f"{run.base}/owner/e2e-alpha/agents/{agent_id}")
    own = page.locator(f"#owner-reports-{agent_id}")
    expect(own).to_have_value(me["id"])
    own.select_option("")
    page.locator("form.owner-reports", has=own).get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("main")).to_contain_text("E2E Agent now reports to nobody.")
    assert by_handle()["e2e-agent"]["reports_to"] is None


def release_contract(run: Run, page: Page, alpha: Path, agent_id: str, card_id: str) -> None:
    run.step("release: a reviewer joins and opens a release; the hub has no forge probe here")
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    # It takes over from the first agent, the hand-over on its card (§3.1).
    url, code = join_line(
        run,
        page,
        "e2e-alpha",
        "e2e-reviewer",
        "E2E Reviewer",
        "reviewer",
        takes_over="E2E Agent (@e2e-agent)",
        handover=card_id,
        reports_to=agent_id,
    )
    rev = run.clone("clone-reviewer")
    run.maity(
        rev, "join", url, "--code", code, "--harness", "e2e", "--model", "none", "--no-pointer"
    )
    agents_fleet_step(run, page, agent_id)
    join_reports_to_step(run, page, agent_id)
    view_tab(page, "Team").click()
    over = page.locator("tr.member", has_text="E2E Reviewer").locator(".member-takes-over")
    expect(over).to_have_text(f"Takes over from @e2e-agent; the hand-over is in {card_id}.")
    expect(over.get_by_role("link", name=card_id)).to_have_attribute(
        "href", re.compile(rf"/owner/e2e-alpha/tasks/{card_id}$")
    )
    partner = run.api(
        rev,
        "POST",
        "/projects/owner/e2e-alpha/tasks",
        {"title": "E2E partner", "area": "web/", "ships_with": [card_id]},
    )
    rel = run.api(
        rev,
        "POST",
        "/projects/owner/e2e-alpha/tasks",
        {
            "kind": "release",
            "title": "0.1.0 — e2e",
            "area": "/",
            "release": {"version": "0.1.0"},
            "depends_on": [card_id, partner["id"]],
        },
    )
    run.api(
        rev,
        "PATCH",
        f"/projects/owner/e2e-alpha/tasks/{rel['id']}",
        {"release": {"pull_requests_typed": [{"number": 7, "state": "merged"}]}},
    )
    contract = run.api(
        rev,
        "POST",
        "/projects/owner/e2e-alpha/tasks",
        {"kind": "contract", "title": "E2E contract", "contract": {"watchers": [agent_id]}},
    )
    print(f"   release {rel['id']}, partner {partner['id']}, contract {contract['id']}")
    view_tab(page, "Board").click()
    card = page.locator("article.card", has=page.get_by_role("heading", name="0.1.0 — e2e"))
    expect(card).to_contain_text("Release 0.1.0")
    row = card.locator("tr", has_text="#7")
    expect(row).to_contain_text("unverified · typed as merged")  # a claim, not a fact
    expect(row.locator(".pr-merged")).to_have_count(0)
    expect(card.locator(".readiness")).to_contain_text(
        "Not ready: the hub observes nothing for this project (no forge probe)"
    )
    expect(card).to_contain_text("it can be cancelled but not marked done")
    # The hub lists a group's ids sorted; random ids decide the order.
    expect(card.locator(".groups")).to_contain_text(f"{card_id} (in progress)")
    expect(card.locator(".groups")).to_contain_text(f"{partner['id']} ({partner['status']})")
    # Without a probe the hub says nothing about the group: neither green nor amber.
    expect(card.locator(".groups li.unknown")).to_have_count(1)
    expect(card).to_contain_text("Tag v0.1.0: not observed")
    view = run.api(rev, "GET", f"/projects/owner/e2e-alpha/tasks/{rel['id']}")["release"]
    assert view["readiness"] == {"ready": False, "blocking": [{"reason": "probe_not_configured"}]}
    assert view["pull_requests"][0]["observed_at"] is None, view
    ctr = page.locator("article.card", has=page.get_by_role("heading", name="E2E contract"))
    expect(ctr).to_contain_text("watched by E2E Agent")
    expect(ctr).to_contain_text("Contract proposed · arbiter ")
    run.shot(page, "release-open")
    run.a11y(page, "board with a release and a contract")
    no_problems(run, "release open")

    run.step("release: the owner edits it on the board — a checklist item, its tick, a typed PR")
    owner_id = json.loads(run.maity(alpha, "resume", "--json"))["me"]["owner"]["id"]
    card.get_by_role("button", name="Edit checklist", exact=True).click()
    form = card.locator("form.rows-form")
    form.get_by_role("button", name="Add", exact=True).click()
    form.locator("input.item-text").last.fill("e2e: announce it")
    form.get_by_role("button", name="Save", exact=True).click()
    item = card.locator("ul.checklist li", has_text="e2e: announce it")
    expect(item).to_be_visible()
    item.locator("input[type=checkbox]").check()
    expect(item).to_contain_text("e2e: announce it · Owner")
    card.get_by_role("button", name="Typed pull requests", exact=True).click()
    form = card.locator("form.rows-form")
    form.get_by_role("button", name="Add", exact=True).click()
    form.locator("input.pr-number").last.fill("8")
    form.locator("select.pr-claim").last.select_option("open")
    form.get_by_role("button", name="Save", exact=True).click()
    expect(card.locator("tr", has_text="#8")).to_contain_text("unverified · typed as open")
    expect(card.locator("tr", has_text="#7")).to_contain_text("unverified · typed as merged")
    view = run.api(rev, "GET", f"/projects/owner/e2e-alpha/tasks/{rel['id']}")["release"]
    ticked = next(i for i in view["checklist"] if i["text"] == "e2e: announce it")
    assert ticked["done"] and ticked["by"] == owner_id, view["checklist"]
    # The contract's core point: saving the list again keeps an item's id, and
    # with the id its tick (docs/api.md §6.7).
    card.get_by_role("button", name="Edit checklist", exact=True).click()
    form = card.locator("form.rows-form")
    form.locator("input.item-text").last.fill("e2e: announce it on the list")
    form.get_by_role("button", name="Save", exact=True).click()
    expect(
        card.locator("ul.checklist li", has_text="e2e: announce it on the list")
    ).to_contain_text("· Owner")
    again = run.api(rev, "GET", f"/projects/owner/e2e-alpha/tasks/{rel['id']}")["release"]["checklist"]
    kept = next(i for i in again if i["id"] == ticked["id"])
    assert kept["text"] == "e2e: announce it on the list", again
    assert (kept["done"], kept["by"], kept["at"]) == (True, owner_id, ticked["at"]), again
    assert view["pull_requests_typed"] == [
        {"number": 7, "state": "merged"},
        {"number": 8, "state": "open"},
    ], view["pull_requests_typed"]
    run.shot(page, "release-edited")
    run.a11y(page, "board, release edited")
    # The same release in the card panel, whose ground is --surface-2: its warning text
    # (an unmet dependency, "Not ready") must read there too (tsk-sg1tdmwdy09z).
    page.goto(f"{run.base}/owner/e2e-alpha/tasks/{rel['id']}")
    panel = page.locator(".card-panel")
    expect(panel.locator(".readiness.not-ready")).to_be_visible()
    expect(panel.locator(".deps li.unmet").first).to_be_visible()
    run.shot(page, "release-in-panel")
    run.a11y(page, "card panel, a release not ready")
    page.keyboard.press("Escape")
    expect(page.locator(".card-panel")).to_have_count(0)
    expect(card).to_be_visible()
    # One open editor at phone width: it stays inside the screen.
    page.set_viewport_size({"width": 390, "height": 844})
    card.get_by_role("button", name="Typed pull requests", exact=True).click()
    expect(card.locator("form.rows-form input.pr-number")).to_have_count(2)
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1], f"the open editor is {width[0]} px wide at {width[1]} px"
    card.scroll_into_view_if_needed()
    page.screenshot(path=str(run.artifacts / f"{run.shots + 1:02d}-phone-release-editor.png"))
    run.shots += 1
    print(f"   screenshot {run.shots:02d}-phone-release-editor.png", flush=True)
    run.a11y(page, "board, typed-PR editor open")
    # 360 px as well, where a wrap shows whatever the fonts (tsk-et029v5k73f1).
    page.set_viewport_size({"width": 360, "height": 780})
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1], f"the open editor is {width[0]} px wide at {width[1]} px"
    card.scroll_into_view_if_needed()
    page.screenshot(path=str(run.artifacts / f"{run.shots + 1:02d}-phone-release-editor-360.png"))
    run.shots += 1
    print(f"   screenshot {run.shots:02d}-phone-release-editor-360.png", flush=True)
    card.get_by_role("button", name="Cancel", exact=True).click()
    page.set_viewport_size({"width": 1280, "height": 900})
    no_problems(run, "release edited")

    run.step("release: cancelled, it is shown as the record frozen at its close")
    run.api(rev, "PATCH", f"/projects/owner/e2e-alpha/tasks/{rel['id']}", {"status": "cancelled"})
    page.reload()
    card = page.locator("article.card", has=page.get_by_role("heading", name="0.1.0 — e2e"))
    expect(page.get_by_role("region", name="Cancelled")).to_contain_text("0.1.0 — e2e")
    expect(card).to_contain_text("are the record frozen when it closed")
    expect(card).not_to_contain_text("it can be cancelled but not marked done")
    expect(card.locator(".groups")).not_to_contain_text(
        "(in progress)"
    )  # no live status in a record
    # A closed release offers no editing, and the hub refuses one anyway.
    expect(card.get_by_role("button", name="Edit checklist", exact=True)).to_have_count(0)
    expect(card.locator("input[type=checkbox]")).to_have_count(0)
    out = run.maity_refused(
        rev,
        "api",
        "--json",
        "-",
        "PATCH",
        f"/projects/owner/e2e-alpha/tasks/{rel['id']}",
        stdin=json.dumps({"release": {"pull_requests_typed": [{"number": 9}]}}),
    )
    assert "invalid_transition" in out, out
    run.shot(page, "release-cancelled")
    no_problems(run, "release cancelled")


def bearer_get(run: Run, clone: Path, path: str) -> tuple[int, dict]:
    """One call with the clone's credential as a bare bearer token, as curl would make it."""
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=clone,
        env=CLEAN_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    secret = (clone / common / "maity" / "credential").read_text().strip()
    request = urllib.request.Request(
        run.base + "/api/v1" + path, headers={"Authorization": "Bearer " + secret}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def signing_step(run: Run, page: Page, alpha: Path, agent_id: str) -> None:
    """policy.signing (docs/api.md §2.2, §6.1)."""
    run.step(
        "signing: an agent calls with a bearer token; the switch names it before requiring signing"
    )
    status, _ = bearer_get(run, alpha, "/me")
    assert status == 200, status
    # The credentials are in the agent's row on Members (tsk-7v2snhk002ak).
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    page.locator("main .members-agents").get_by_role("button", name="Manage E2E Agent", exact=True).click()
    expect(page.locator("main tr.member-manage")).to_contain_text("(bearer token)")
    # Its bridges (§2.3, tsk-x0krjnw8p78t): the owner connects the reviewer (one owner behind
    # both, so at once), the hub's member views carry it on both sides, then End ends it. Read
    # with the owner's session: a CLI call would sign with the agent's credential and change
    # the bearer use the signing check below reads.
    bridges = page.locator("main tr.member-manage .member-bridges")
    expect(bridges).to_contain_text("No bridges.")
    bridges.get_by_label("Agent that lends its hands").select_option(label="E2E Reviewer (@e2e-reviewer)")
    bridges.get_by_label("What for").fill("git for the reviewer's files")
    bridges.get_by_role("button", name="Connect with a bridge", exact=True).click()
    expect(bridges.locator("ul.bridges-serving-this li.bridge")).to_contain_text("lends its hands: git for the reviewer's files")
    members = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha/members").json()["items"]
    served = next(m for m in members if m["handle"] == "e2e-agent")
    bridge = next(m for m in members if m["handle"] == "e2e-reviewer")
    assert [c["member_id"] for c in served["bridges"]] == [bridge["id"]], served["bridges"]
    assert [c["member_id"] for c in bridge["bridging_for"]] == [served["id"]], bridge["bridging_for"]
    run.a11y(page, "members, a bridge connected")
    bridges.get_by_role("button", name="End the bridge for git for the reviewer's files", exact=True).click()
    expect(bridges).to_contain_text("No bridges.")
    members = page.request.get(f"{run.base}/api/v1/projects/owner/e2e-alpha/members").json()["items"]
    assert not next(m for m in members if m["handle"] == "e2e-agent")["bridges"], "the bridge is still there"
    project_settings(page)
    page.locator("#signing-select").select_option("required")
    impact = page.locator(".signing-impact")
    expect(impact).to_contain_text("would be refused (signature_required)")
    expect(impact).to_contain_text("E2E Agent")
    page.locator("#signing-reason").fill("e2e: every agent runs the CLI")
    page.get_by_role("button", name="Change signing", exact=True).click()
    expect(page.locator("#signing-confirm")).to_be_focused()  # not sent unconfirmed
    page.locator("#signing-confirm").check()
    page.get_by_role("button", name="Change signing", exact=True).click()
    # Saved: the Settings tab is drawn afresh (its reason field empty) and stays.
    expect(page.locator("#signing-reason")).to_have_value("")
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/settings$"))
    expect(page.locator("#signing-select")).to_have_value("required")
    assert run.api(alpha, "GET", "/projects/owner/e2e-alpha")["policy"]["signing"] == "required"
    status, body = bearer_get(run, alpha, "/me")
    assert status == 403 and body["error"]["code"] == "signature_required", (status, body)
    run.maity(alpha, "resume")  # the CLI signs, so it still works
    run.a11y(page, "settings, signing required")
    project_settings(page)
    page.locator("#signing-select").select_option("optional")
    page.locator("#signing-reason").fill("e2e: back to optional")
    page.get_by_role("button", name="Change signing", exact=True).click()
    expect(page.locator("#signing-reason")).to_have_value("")
    expect(page.locator("#signing-select")).to_have_value("optional")
    status, _ = bearer_get(run, alpha, "/me")
    assert status == 200, status
    no_problems(run, "signing")


def users_step(run: Run, page: Page) -> None:
    """Users of this hub (docs/api.md §16.1), where the hub names an instance admin."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    page.goto(f"{run.base}/all")
    # A hash change only: wait for the new header before using its gear.
    expect(page.locator("header .project")).to_have_text("Everything waiting for you")
    page.locator("header").get_by_role("button", name="Settings", exact=True).click()
    link = page.get_by_role("menuitem", name="Instance administration", exact=True)
    run.step("users: the instance admin lists the hub's humans")
    assert me["instance_admin"] is True, me  # the first human, made by maity-hub owner create
    link.click()
    expect(page).to_have_url(re.compile(r"/admin$"))
    # One section at a time: the page opens on Statistics, Users is picked.
    page.locator("nav.admin-nav").get_by_role("button", name="Users", exact=True).click()
    owner = page.locator("table.users tbody tr", has_text="(you)")
    expect(owner).to_contain_text("instance admin")
    expect(owner).to_contain_text("@" + OWNER)
    page.locator("#users-q").fill("nobody-by-this-name")
    expect(page.locator("main")).to_contain_text("No account matches.")
    page.locator("#users-q").fill(OWNER)
    expect(owner).to_be_visible()
    run.shot(page, "users")
    run.a11y(page, "users")
    no_problems(run, "users")


def registration_admin_step(run: Run, page: Page) -> None:
    """Instance administration → Registration (docs/api.md §16.4): the mode needs mail."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("registration: the admin opens the settings; allowlist needs mail, a list is saved")
    page.goto(f"{run.base}/admin")
    page.locator("nav.admin-nav").get_by_role("button", name="Registration", exact=True).click()
    section = page.locator("section.admin-section[aria-label='Registration']")
    expect(section.locator(".reg-effective")).to_have_text("Registration now: closed.")
    form = section.locator("form.reg-form")
    # This hub has no mail: the hub refuses the mode, said at its field.
    page.locator("#reg-mode").select_option("allowlist")
    form.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#reg-mode-error")).to_have_text("needs complete, enabled mail (Mail settings)")
    # That refusal is the expected answer here, not a problem of the page.
    refused = "PATCH /api/v1/admin/settings/registration answered 400"
    run.problems = [p for p in run.problems if p != refused]
    page.locator("#reg-mode").select_option("closed")
    page.locator("#reg-domains").fill("@example.com")
    form.get_by_role("button", name="Save", exact=True).click()
    expect(form).to_contain_text("Saved.")
    expect(page.locator("#reg-domains")).to_have_value("@example.com")
    run.shot(page, "registration-admin")
    run.a11y(page, "registration admin")
    no_problems(run, "registration admin")


def project_links_step(run: Run, page: Page) -> None:
    """The project's own links (docs/api.md §6.11): set in Project settings against the real
    hub, shown beside the state in the header, refused at the field where the hub refuses them."""
    run.step("links: an issues link set in Project settings, shown in the header; a port refused at its field")
    page.goto(f"{run.base}/owner/e2e-alpha/settings")
    form = page.locator("form.links-form")
    expect(form).to_be_visible()
    page.locator("#link-wiki").fill("https://wiki.example.org:8443/e2e")
    form.get_by_role("button", name="Save the links", exact=True).click()
    expect(page.locator("#link-wiki-error")).to_have_text("Not an https address on a DNS name without a port or user name.")
    refused = "PATCH /api/v1/projects/owner/e2e-alpha answered 400"
    run.problems = [p for p in run.problems if p != refused]
    page.locator("#link-wiki").fill("")
    page.locator("#link-issues").fill("https://issues.example.org/e2e")
    form.get_by_role("button", name="Save the links", exact=True).click()
    expect(page.locator("main")).to_contain_text("Links saved.")
    issues = page.locator("header .project-state a.header-link", has_text="Issues")
    expect(issues).to_have_attribute("href", "https://issues.example.org/e2e")
    expect(issues).to_have_attribute("rel", "noopener noreferrer")
    # On a phone the links are one row that scrolls sideways; the state stays in sight beside it,
    # scrolled to either end (the maintainer, tsk-m9ew7v609fq0).
    page.set_viewport_size({"width": 360, "height": 780})
    tops = page.evaluate("Array.from(document.querySelectorAll('header .project-links > a')).map((a) => Math.round(a.getBoundingClientRect().top))")
    assert len(set(tops)) == 1, f"the project's links wrap at 360 px: {tops}"
    # With a GitHub repository the row holds Repository, Actions and Pull Requests before the own
    # links (tsk-kdkdy864q11r). The e2e project has none, so the project's read is answered with
    # one for this check alone; still one row at 390 and 360 px, light and dark.
    project_read = re.compile(r"/api/v1/projects/owner/e2e-alpha$")

    def with_repo(route) -> None:
        body = route.fetch().json()
        body["repository"] = {**(body.get("repository") or {}), "url": "https://github.com/owner/e2e-alpha", "forge": "github"}
        route.fulfill(json=body)

    page.route(project_read, with_repo)
    try:
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            for width in (390, 360):
                page.set_viewport_size({"width": width, "height": 780})
                page.reload()
                actions = page.locator("header .project-links a.header-link", has_text="Actions")
                expect(actions).to_have_attribute("href", "https://github.com/owner/e2e-alpha/actions")
                expect(actions).to_have_attribute("aria-label", "Actions on GitHub (opens in a new tab)")
                row = page.evaluate("""() => Array.from(document.querySelectorAll('header .project-links > a'))
                  .map((a) => [a.textContent.trim(), Math.round(a.getBoundingClientRect().top)])""")
                assert [t for t, _ in row][:4] == ["Repository", "Actions", "Pull Requests", "Issues"], f"the links' order at {width} px {scheme}: {row}"
                assert len({top for _, top in row}) == 1, f"the project's links wrap at {width} px {scheme}: {row}"
                width_now = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
                assert width_now[0] <= width_now[1], f"the page scrolls sideways at {width} px {scheme}: {width_now}"
        run.shot(page, "project-links-actions-phone")
        run.a11y(page, "project links with Actions")
    finally:
        page.unroute(project_read, with_repo)
        page.emulate_media(color_scheme="light")
        page.set_viewport_size({"width": 360, "height": 780})
        page.reload()
    # With an absence beside the state it needs more room than the row leaves, so it wraps under
    # the row; the row keeps a usable width and nothing scrolls the page sideways (spq4 at #1271).
    # The absence is set here and ended after the check, so the steps after see none.
    page.set_viewport_size({"width": 1280, "height": 900})
    until = page.evaluate("""() => { const d = new Date(); d.setDate(d.getDate() + 7); d.setHours(10, 0, 0, 0);
      const pad = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T10:00`; }""")
    page.locator("#absence-until").fill(until)
    page.locator("#absence-scope").fill("e2e: links beside an absence")
    page.get_by_role("button", name="Set absence", exact=True).click()
    expect(page.locator("header .project-state > .state.away")).to_have_count(1)
    page.set_viewport_size({"width": 360, "height": 780})
    row = page.locator("header .project-links").bounding_box()
    assert row and row["width"] >= 140, f"the link row is squeezed to {row} at 360 px"
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1], f"the page is {width[0]} px wide at {width[1]} px with an absence"
    for end in (0, 9999):
        page.locator("header .project-links").evaluate("(e, x) => { e.scrollLeft = x; }", end)
        parts = page.evaluate("Array.from(document.querySelectorAll('header .project-state > :not(.project-links)')).map((e) => { const r = e.getBoundingClientRect(); return [e.className, r.left, r.right]; })")
        assert parts and all(left >= 0 and right <= 361 for _, left, right in parts), f"the state leaves the screen at scroll {end}: {parts}"
    run.shot(page, "project-links-phone")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.get_by_role("button", name="I am back", exact=True).click()
    expect(page.locator("header .project-state > .state.away")).to_have_count(0)
    run.shot(page, "project-links")
    run.a11y(page, "project links")
    no_problems(run, "project links")
    page.goto(f"{run.base}/all")
    expect(page.locator("header .project")).to_have_text("Everything waiting for you")


def jour_fixe_step(run: Run, page: Page) -> None:
    """The jour fixe (docs/api.md §20): a series kept at the top of the jour fixe page against the
    real hub (Project settings link there), the owner granted the right to moderate it, the view
    says its next slot and the member's part, and a start by hand opens a round of that series or
    says why not."""
    run.step("jour fixe: a series saved on the jour fixe page, a moderator granted, a start by hand")
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    page.goto(f"{run.base}/owner/e2e-alpha/settings")
    page.locator("section.jf-series-moved").get_by_role("link", name="Jour fixe", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/jour-fixe$"))
    fold = page.locator("details.jf-series-settings")
    expect(fold).not_to_have_attribute("open", "")
    fold.locator("summary").click()
    page.get_by_role("button", name="New series", exact=True).click()
    form = page.locator("form.jf-series-form")
    expect(form).to_be_visible()
    page.locator("#jfs-topic").fill("e2e: how we work")
    page.locator("#jfs-enabled").check()
    page.locator("#jfs-time").fill("10:00")
    page.locator("#jfs-timezone").fill("Europe/Vienna")
    page.locator("#jfs-day-mon").check()
    page.locator("#jfs-reason").fill("e2e: a weekly look back")
    form.get_by_role("button", name="Save the series", exact=True).click()
    expect(page.locator("main")).to_contain_text("The series is saved.")
    row = page.locator("li.jf-series", has_text="e2e: how we work")
    expect(row).to_contain_text("Weekly on Monday at 10:00 (Europe/Vienna)")
    # The owner grants the right to themselves: a keeper's own grant takes effect at once.
    row.locator("select.jfs-grant-member").select_option(value=me["id"])
    row.locator("input[id^=jfs-reason-]").fill("e2e: the owner moderates")
    row.get_by_role("button", name="Grant", exact=True).click()
    expect(row.locator("ul.jf-moderators-list li")).to_have_count(1)
    # The series' block below is drawn again after each change, the settings staying open.
    block = page.locator("section.jf-series-block", has_text="e2e: how we work")
    expect(block).to_contain_text("Next round:")
    expect(fold).to_have_attribute("open", "")
    # Opting out and back in, as the member's own part in the series (§20.2).
    block.locator("li.jf-part .jf-optout").first.click()
    expect(block.locator("li.jf-part").first).to_contain_text("opted out")
    block.locator("li.jf-part .jf-optout").first.click()
    expect(block.locator("li.jf-part").first).to_contain_text("taking part")
    block.locator("input[id^=jf-start-reason-]").fill("e2e: before the launch")
    block.locator("form.jf-start").get_by_role("button", name="Start a round now", exact=True).click()
    opened = re.compile(r"/owner/e2e-alpha/jour-fixe/jfx-")
    expect(page.locator("main")).to_contain_text(re.compile(r"Not started: |answering"))
    if opened.search(page.url):
        expect(page.locator("main")).to_contain_text("answering")
        # The owner is a participant: an answer by name, read back from the real hub.
        page.locator("#jfa-went_well").fill("e2e: the board is clear")
        page.locator("form.jfa-answer-form").get_by_role("button", name="Send my answer", exact=True).click()
        expect(page.locator("section.jfa-answer")).to_contain_text("Your answer, by name.")
    else:
        # The hub's refusal (409: nobody to moderate, too few in the circle) is the expected answer here.
        run.problems = [p for p in run.problems if not (p.startswith("POST /api/v1/projects/owner/e2e-alpha/jour-fixe/series/") and p.endswith("/rounds answered 409"))]
    run.shot(page, "jour-fixe")
    run.a11y(page, "jour fixe")
    no_problems(run, "jour fixe")
    page.goto(f"{run.base}/all")
    expect(page.locator("header .project")).to_have_text("Everything waiting for you")


def landing_json_step(run: Run, page: Page) -> None:
    """Instance administration → Landing page (docs/api.md §16.7, tsk-36d575f5yybz): a draft
    imported as JSON, checked by the hub's preview call, saved only by Save."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("landing page: the admin imports a page as JSON, the hub checks it, then it is saved")
    page.goto(f"{run.base}/admin/pages/landing")
    io = page.locator("details.lp-json")
    io.locator("summary").click()
    # No footer, as a prepared landing file: the editor's footer stays (§16.7, #808's review).
    body = {
        "enabled": False,
        "default_language": "en",
        "pages": {"en": {"title": "E2E landing", "description": "Imported by the e2e run.",
                         "sections": [{"type": "text", "enabled": True, "markdown": "Hello from **e2e**."}]}},
    }
    page.locator("#lp-json").fill(json.dumps(body))
    asked = []
    page.once("dialog", lambda d: (asked.append(d.message), d.accept()))
    io.get_by_role("button", name="Load into the editor", exact=True).click()
    section = page.locator("#admin-landing-page")
    expect(section.locator(".send-status").first).to_contain_text("checked by the hub")
    assert asked and asked[0].startswith("Replace the whole draft"), asked
    expect(page.locator("#lp-pages-en-title")).to_have_value("E2E landing")
    expect(page.locator("#lp-pages-en-sections-0-markdown")).to_have_value("Hello from **e2e**.")
    saved_before = page.request.get(f"{run.base}/api/v1/admin/settings/landing").json()
    assert (saved_before.get("pages") or {}).get("en", {}).get("title") != "E2E landing", "the import saved before Save"
    run.a11y(page, "landing page, a JSON import")
    page.locator("form.lp-form").get_by_role("button", name="Save the landing page", exact=True).click()
    expect(section.locator(".send-status").first).to_contain_text("Saved. Visitors see it within a minute.")
    saved = page.request.get(f"{run.base}/api/v1/admin/settings/landing").json()
    assert saved["pages"]["en"]["title"] == "E2E landing", saved
    assert saved["footer"] == saved_before["footer"], (saved["footer"], saved_before["footer"])
    io.get_by_role("button", name="Export the draft", exact=True).click()
    assert json.loads(page.locator("#lp-json").input_value())["pages"]["en"]["title"] == "E2E landing"
    # A prepared landing file with every section: the real hub's check refuses nothing.
    # Its landing part, from the one site file (tsk-xw8a2hd84x3a).
    # The footer's one placeholder takes a value here, as the site import would.
    v3 = json.dumps(
        {
            **(landing := json.loads((WEB / "tools" / "site-fixture.json").read_text(encoding="utf-8"))["landing"]),
            "footer": {**landing["footer"], "operator": "Example operator"},
        }
    )
    page.locator("#lp-json").fill(v3)
    page.once("dialog", lambda d: d.accept())
    io.get_by_role("button", name="Load into the editor", exact=True).click()
    expect(section.locator(".send-status").first).to_contain_text("checked by the hub")
    expect(page.locator("li.lp-section")).to_have_count(len(json.loads(v3)["pages"][json.loads(v3)["default_language"]]["sections"]))
    run.shot(page, "landing-json")
    no_problems(run, "landing JSON")


def site_json_step(run: Run, page: Page) -> None:
    """The whole site as one JSON (maity-site/1, tsk-xw8a2hd84x3a) on the real hub: the test file with every language
    is checked, saved in one go, and exported again unchanged."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("whole site: the test file imported in one go, then exported unchanged")
    template = json.loads((WEB / "tools" / "site-fixture.json").read_text(encoding="utf-8"))
    # Off for this run: a landing page that is on would greet the signed-out steps after this one.
    template["landing"]["enabled"] = False
    page.goto(f"{run.base}/admin/pages/site")
    section = page.locator("#admin-whole-site")
    io = section.locator("details.json-io")
    io.locator("summary").click()

    # Export reads the settings again first, so the field is filled once the hub has answered.
    def export() -> dict:
        page.locator("#site-json").fill("")
        io.get_by_role("button", name="Export", exact=True).click()
        expect(page.locator("#site-json")).not_to_have_value("")
        return json.loads(page.locator("#site-json").input_value())

    # The template carries no registration: what the instance has stays.
    before = export()
    # Its placeholders first have no value and block the save (§16.7.3); then the values, made up here.
    page.locator("#site-json").fill(json.dumps(template))
    io.get_by_role("button", name="Check the file", exact=True).click()
    expect(section.locator("ul.site-placeholders li[data-replaced='false']")).to_have_count(7)
    expect(section.get_by_role("button", name="Save all changes", exact=True)).to_be_disabled()
    values = {name: f"Example {name}" for name in ("name", "address", "email", "operator", "date", "hosting_provider", "mail_provider")}
    for index, (name, value) in enumerate(values.items()):
        section.get_by_role("button", name="Add a value", exact=True).click()
        page.locator(f"#site-value-{index}-name").fill(name)
        page.locator(f"#site-value-{index}-value").fill(value)
    section.get_by_role("button", name="Save the values", exact=True).click()
    expect(section).to_contain_text("Check the file again")
    io.get_by_role("button", name="Check the file", exact=True).click()
    expect(section.locator("ul.site-placeholders li[data-replaced='true']")).to_have_count(7)
    expect(section.locator("li.site-part")).to_have_count(5)
    expect(section.locator("li.site-refused")).to_have_count(0)
    section.get_by_role("button", name="Save all changes", exact=True).click()
    expect(section.locator(".send-status").last).to_contain_text("Saved:")
    run.a11y(page, "whole site, saved")
    out = export()
    assert out["format"] == "maity-site/1", out.get("format")
    assert out["landing"]["pages"] == template["landing"]["pages"], "the landing pages differ after the round trip"
    assert out["sign_in"] == template["sign_in"] and out["sign_up"] == template["sign_up"], "sign-in or sign-up differ"
    seen_pitch = page.request.get(f"{run.base}/api/v1/auth/pages/sign_in?lang=de").json()
    assert seen_pitch == {"language": "de", "texts": template["sign_in"]["de"]}, seen_pitch
    # Every language on the public pages, as a visitor without a session gets it: nothing refused, no placeholder left.
    languages = list(template["landing"]["pages"])
    assert len(languages) == 10 and set(languages) == set(next(iter(template["legal"].values()))["languages"]), languages
    page.evaluate("Maity.api.patch('/admin/settings/landing', { enabled: true })")
    visitor = page.context.browser.new_context(viewport={"width": 390, "height": 844})
    seen = visitor.new_page()
    for tag in languages:
        for address in ("/", "/impressum", "/privacy", "/terms"):
            answer = seen.goto(f"{run.base}{address}?lang={tag}")
            assert answer.status == 200, f"{address} in {tag}: {answer.status}"
            assert seen.locator("html").get_attribute("lang") == tag, f"{address} in {tag}: another language"
            body = seen.locator("body").inner_text()
            assert "{{" not in body, f"{address} in {tag}: a placeholder is left"
            wide = seen.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert wide <= 0, f"{address} in {tag}: {wide} px wider than a phone"
            if address == "/" and tag in ("ja", "ko", "zh-Hans"):
                run.shot(seen, f"site-{tag}-phone")
            if address == "/":
                assert seen.locator(".site-footer .langs a").count() == 10, f"the language bar in {tag}"
            else:
                assert "Example " in body, f"{address} in {tag}: no value"
    visitor.close()
    page.evaluate("Maity.api.patch('/admin/settings/landing', { enabled: false })")
    filled = json.dumps(template["legal"])
    for name, value in values.items():
        filled = filled.replace("{{" + name + "}}", value)
    assert "{{" not in filled, "a placeholder is left in the template"
    for key, value in json.loads(filled).items():
        assert out["legal"][key]["languages"] == value["languages"], f"legal {key} differs after the round trip"
    assert "registration" not in template, "the template carries a registration part"
    # Registration as it was; only `terms` may leave the export: with the terms page saved and no
    # value of its own, the hub takes it from the legal pages, which the export never carries.
    reg_before, reg_after = before.get("registration", {}), out.get("registration", {})
    assert all(reg_before.get(k) == v for k, v in reg_after.items()), f"registration changed: {reg_before} -> {reg_after}"
    assert set(reg_before) - set(reg_after) <= {"terms"}, f"registration lost fields: {reg_before} -> {reg_after}"
    no_problems(run, "whole site JSON")


def landing_variants_step(run: Run, page: Page) -> None:
    """Landing variants and campaigns on the real hub (docs/api.md §16.7.2, tsk-ets3x0c4ethg): one of each
    saved in the editor, carried by the whole site's file, the counts' CSV downloaded, both removed again."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("landing variants: a variant and a campaign saved, in the site file, the counts as CSV, then removed")
    settings = f"{run.base}/api/v1/admin/settings/landing"
    language = page.request.get(settings).json()["default_language"]
    page.goto(f"{run.base}/admin")
    page.locator("nav.admin-nav").get_by_role("button", name="Pages", exact=True).click()
    nav = page.locator("nav.admin-subnav")
    nav.get_by_role("button", name="Landing pages", exact=True).click()
    section = page.locator("#admin-landing-page")
    form = page.locator("form.lp-form")

    def save() -> dict:
        form.get_by_role("button", name="Save the landing page", exact=True).click()
        expect(section.locator(".send-status").first).to_contain_text("Saved. Visitors see it within a minute.")
        return page.request.get(settings).json()

    page.locator("#lp-new-variant").fill("e2e-spring")
    section.get_by_role("button", name="Add the variant", exact=True).click()
    page.locator(f"#lp-variants-e2e-spring-pages-{language}-title").fill("E2E spring")
    section.get_by_role("button", name="Add a campaign", exact=True).click()
    page.locator("#lp-campaigns-0-code").fill("e2e-spring")
    page.locator("#lp-campaigns-0-label").fill("E2E spring")
    run.a11y(page, "landing page, a variant and a campaign")
    saved = save()
    assert saved["variants"]["e2e-spring"]["pages"][language]["title"] == "E2E spring", saved["variants"]
    assert saved["campaigns"] == [{"code": "e2e-spring", "label": "E2E spring"}], saved["campaigns"]

    # The whole site's file carries both, and the hub's preview takes them: its own export changes nothing.
    page.locator("details.admin-pages-file > summary").click()
    whole = page.locator("#admin-whole-site")
    io = whole.locator("details.json-io")
    io.locator("summary").click()
    page.locator("#site-json").fill("")
    io.get_by_role("button", name="Export", exact=True).click()
    expect(page.locator("#site-json")).not_to_have_value("")
    exported = json.loads(page.locator("#site-json").input_value())["landing"]
    assert exported["variants"] == saved["variants"], exported["variants"]
    assert exported["campaigns"] == saved["campaigns"], exported["campaigns"]
    io.get_by_role("button", name="Check the file", exact=True).click()
    expect(whole.locator("li.site-part[data-part='landing']")).to_have_class(re.compile(r"\bsite-same\b"))

    # The link h() refused once, which fixtures cannot show: they have no address for it.
    page.locator("nav.admin-nav").get_by_role("button", name="Statistics", exact=True).click()
    csv = page.locator("section.admin-section[aria-label='Statistics'] .campaign-stats").get_by_role(
        "link", name="Download as CSV", exact=True
    )
    with page.expect_download() as download:
        csv.click()
    assert download.value.suggested_filename == "campaigns.csv", download.value.suggested_filename

    # Off again: while either is set the hub rewrites links and keeps an origin (§16.7.2).
    page.locator("nav.admin-nav").get_by_role("button", name="Pages", exact=True).click()
    nav.get_by_role("button", name="Landing pages", exact=True).click()
    section.locator(".lp-variant-tabs").get_by_role("button", name="/for/e2e-spring", exact=True).click()
    section.get_by_role("button", name="Remove /for/e2e-spring", exact=True).click()
    section.locator(".lp-campaign-list").get_by_role("button", name="Remove", exact=True).click()
    saved = save()
    assert saved["variants"] == {} and saved["campaigns"] == [], (saved["variants"], saved["campaigns"])
    no_problems(run, "landing variants")


def start_page_step(run: Run, page: Page) -> None:
    """The way to `/` from the sign-in page leaves the dashboard (docs/api.md §16.7, tsk-fmdn6vb2zs19):
    the hub, not the dashboard, decides per request what `/` shows, so the frame's logo, a section link
    and the app's own logo are page loads. Only a served page shows it: fixture mode has no click
    handler. Wide and light, narrow and dark."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("start page: from the sign-in page the logo and a section link open the landing page")
    page.goto(f"{run.base}/admin/pages/landing")
    io = page.locator("details.lp-json")
    io.locator("summary").click()
    landing = json.loads((WEB / "tools" / "site-fixture.json").read_text(encoding="utf-8"))["landing"]
    body = {**landing, "enabled": True, "footer": {**landing["footer"], "operator": "Example operator"}}
    page.locator("#lp-json").fill(json.dumps(body))
    page.once("dialog", lambda d: d.accept())
    io.get_by_role("button", name="Load into the editor", exact=True).click()
    section = page.locator("#admin-landing-page")
    expect(section.locator(".send-status").first).to_contain_text("checked by the hub")
    form = page.locator("form.lp-form")
    form.get_by_role("button", name="Save the landing page", exact=True).click()
    expect(section.locator(".send-status").first).to_contain_text("Saved. Visitors see it within a minute.")
    assert page.request.get(f"{run.base}/api/v1/admin/settings/landing").json()["enabled"] is True

    def on_landing(seen: Page, where: str) -> None:
        # The hub's landing page: its own HTML, no dashboard and no sign-in form in it.
        expect(seen.locator("main#main")).to_have_count(0)
        expect(seen.locator("#login-email")).to_have_count(0)
        expect(seen.locator("main .hero, main section").first).to_be_visible()
        assert not seen.evaluate("!!(window.Maity && window.Maity.route)"), f"{where}: the dashboard is still loaded"

    try:
        for width, height, scheme in ((1280, 800, "light"), (390, 844, "dark")):
            visitor = page.context.browser.new_context(
                viewport={"width": width, "height": height}, locale="en-US", color_scheme=scheme
            )
            seen = visitor.new_page()
            seen.goto(f"{run.base}/login")
            frame = seen.locator("header.site-header")
            expect(frame).to_be_visible()
            frame.locator("a.brand").click()
            expect(seen).to_have_url(f"{run.base}/")
            on_landing(seen, f"the frame's logo at {width} px {scheme}")
            run.shot(seen, f"start-page-{width}-{scheme}")

            # A section link (`/?lang=en#sN`): the header's where it shows, else the footer's platform column.
            seen.goto(f"{run.base}/login")
            expect(seen.locator("header.site-header")).to_be_visible()
            links = seen.locator("header.site-header a[href*='#s'], footer.site-footer a[href*='#s']")
            shown = links.evaluate_all("(all) => all.findIndex((a) => a.offsetParent !== null)")
            assert shown >= 0, f"no section link shows at {width} px"
            nav = links.nth(shown)
            href = nav.get_attribute("href")
            assert href and href.startswith("/?lang=") and "#s" in href, href
            nav.click()
            expect(seen).to_have_url(f"{run.base}{href}")
            on_landing(seen, f"a section link at {width} px {scheme}")
            expect(seen.locator(f"#{href.split('#', 1)[1]}")).to_be_attached()

            # Without the frame (its read failed), the app's own logo leads to the same start page.
            seen.route("**/api/v1/site/chrome**", lambda r: r.abort())
            seen.goto(f"{run.base}/login")
            expect(seen.locator("#login-email")).to_be_visible()
            expect(seen.locator("header.site-header")).to_have_count(0)
            seen.locator("#header a.brand-home").click()
            expect(seen).to_have_url(f"{run.base}/")
            on_landing(seen, f"the app's logo at {width} px {scheme}")
            visitor.close()

        # Signing out leaves for the start page too: a page load, so the landing page, not the
        # dashboard's sign-in form under `/`. A second session of the owner's, this one stays.
        leaving = page.context.browser.new_context(viewport={"width": 1280, "height": 800}, locale="en-US")
        out = leaving.new_page()
        out.goto(f"{run.base}/login")
        out.locator("#login-email").fill(OWNER_EMAIL)
        out.locator("#login-password").fill(OWNER_PASSWORD)
        out.get_by_role("button", name="Sign in", exact=True).click()
        expect(out.locator("header .me")).to_contain_text("Owner")
        out.goto(f"{run.base}/all")
        out.locator("header").get_by_role("button", name=re.compile(r"^Your profile: ")).click()
        out.get_by_role("menuitem", name="Sign out", exact=True).click()
        expect(out).to_have_url(f"{run.base}/")
        on_landing(out, "after signing out")
        run.shot(out, "start-page-signed-out")
        leaving.close()
    finally:
        # Off again: a landing page that is on would greet the signed-out steps after this one.
        page.goto(f"{run.base}/admin/pages/landing")
        enabled = page.locator("#lp-enabled")
        if enabled.is_checked():
            enabled.uncheck()
        form.get_by_role("button", name="Save the landing page", exact=True).click()
        expect(section.locator(".send-status").first).to_contain_text("Saved.")
        assert page.request.get(f"{run.base}/api/v1/admin/settings/landing").json()["enabled"] is False
    no_problems(run, "start page")


def auth_pages_step(run: Run, page: Page) -> None:
    """Instance administration → Pages → Sign up (docs/api.md §16.7.4): the admin writes a pitch, the
    hub stores it, and a visitor's call gets exactly that language's keys."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("sign-up page: the admin writes its pitch, the public call serves it")
    page.goto(f"{run.base}/admin/pages/sign-up")
    section = page.locator("#admin-sign-up-page")
    section.locator(".lp-tabs").get_by_role("button", name="fr", exact=True).click()
    page.locator("#ap-sign_up-title").fill("Rejoindre")
    run.a11y(page, "sign-up page's pitch")
    section.get_by_role("button", name="Save the sign-in and sign-up pages", exact=True).click()
    expect(section.locator(".send-status").last).to_contain_text("Saved.")
    answer = page.request.get(f"{run.base}/api/v1/auth/pages/sign_up?lang=fr").json()
    assert answer["language"] == "fr" and answer["texts"]["title"] == "Rejoindre", answer
    # What a visitor sees, in a browser with no session; sign-in works whatever these words are.
    page.locator("nav.admin-subnav").get_by_role("button", name="Sign in", exact=True).click()
    page.locator("#ap-sign_in-title").fill("Welcome to the E2E hub")
    page.locator("#ap-sign_in-point_1").fill("A first point")
    run.a11y(page, "sign-in page's pitch")
    page.locator("#admin-sign-in-page").get_by_role("button", name="Save the sign-in and sign-up pages", exact=True).click()
    expect(page.locator("#admin-sign-in-page .send-status").last).to_contain_text("Saved.")
    visitor = page.context.browser.new_context(viewport={"width": 1280, "height": 800}, locale="en-US")
    seen = visitor.new_page()
    seen.goto(f"{run.base}/login")
    expect(seen.locator(".door-form h1")).to_have_text("Welcome to the E2E hub")
    expect(seen.locator(".door-panel li")).to_have_text(["A first point"])
    run.a11y(seen, "sign-in with the instance's pitch")
    run.shot(seen, "login-pitch")
    visitor.close()
    no_problems(run, "sign-up page")


def legal_json_step(run: Run, page: Page) -> None:
    """Instance administration → Legal pages (docs/api.md §16.7.1, tsk-knb9me77f32t): a page's
    languages imported as JSON, checked by its preview call, saved only by Save; a preview
    while the field holds text not loaded says so."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("legal pages: the admin imports the imprint as JSON, the hub checks it, then it is saved")
    page.goto(f"{run.base}/admin/pages/legal")
    imprint = page.locator("section.lg-page[aria-label='Imprint']")
    io = imprint.locator("details.json-io")
    io.locator("summary").click()
    page.locator("#lg-imprint-json").fill(
        json.dumps({"imprint": {"en": {"title": "E2E imprint", "markdown": "Operated by **e2e**."}}})
    )
    # Not loaded yet: a preview says so and opens no tab.
    if imprint.get_by_role("button", name="Preview the draft", exact=True).count():
        imprint.get_by_role("button", name="Preview the draft", exact=True).click()
        expect(imprint.locator(".send-status").first).to_contain_text("not loaded into the editor")
    asked = []
    page.once("dialog", lambda d: (asked.append(d.message), d.accept()))
    io.get_by_role("button", name="Load into the editor", exact=True).click()
    expect(imprint.locator(".send-status").first).to_contain_text("checked by the hub")
    assert asked and asked[0].startswith("Replace the Imprint"), asked
    expect(page.locator("#lp-imprint-en-title")).to_have_value("E2E imprint")
    before = page.request.get(f"{run.base}/api/v1/admin/settings/legal").json()
    assert ((before.get("pages") or {}).get("imprint") or {}).get("languages", {}).get("en", {}).get("title") != "E2E imprint", "the import saved before Save"
    run.a11y(page, "legal pages, a JSON import")
    imprint.locator("form.lg-form").get_by_role("button", name="Save the imprint", exact=True).click()
    expect(page.locator("section.lg-page[aria-label='Imprint']")).to_contain_text("Served at /impressum")
    saved = page.request.get(f"{run.base}/api/v1/admin/settings/legal").json()
    assert saved["pages"]["imprint"]["languages"]["en"]["title"] == "E2E imprint", saved
    no_problems(run, "legal JSON")


def reports_admin_step(run: Run, page: Page, alpha: Path) -> None:
    """Instance administration → Reports (docs/api.md §16.8): an agent reports a card; the admin
    opens it from the request in the all-projects inbox, reads the report and its snapshot as
    text, and resolves it with hide and a note, which withdraws the request."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("reports: an agent reports a card; the admin reads it as text and hides it with a note")
    card = run.api(alpha, "POST", "/projects/owner/e2e-alpha/tasks", {"title": "e2e: a card to report", "body": "<b>not markup</b>"})
    filed = run.api(
        alpha,
        "POST",
        "/reports",
        {"target": {"type": "card", "id": card["id"], "project": "owner/e2e-alpha"}, "reason": "spam", "text": "<i>e2e</i> report"},
    )
    assert filed.get("id"), filed
    # The admin is told by a personal request without a project (§16.8, §7), in the
    # all-projects inbox: no answer, no withdrawal, only Open report.
    mine = page.request.get(f"{run.base}/api/v1/requests").json()["items"]
    [asked] = [r for r in mine if (r.get("report") or {}).get("id") == filed["id"]]
    assert (asked["personal"], asked["project"], asked["replies"]) == (True, None, []), asked
    page.goto(f"{run.base}/all")
    expect(page.locator("header .project")).to_have_text("Everything waiting for you")
    entry = page.locator("li.entry", has_text="Report: spam — card")
    entry.locator("button.entry-head").click()
    expect(entry.locator("textarea")).to_have_count(0)
    expect(entry.get_by_role("button", name="Withdraw", exact=True)).to_have_count(0)
    entry.get_by_role("link", name="Open report", exact=True).click()
    # Where it leads: the section, that report opened.
    expect(page).to_have_url(re.compile(r"/admin/reports/" + re.escape(filed["id"]) + "$"))
    section = page.locator("section.admin-section[aria-label='Reports']")
    expect(section).to_be_visible()
    expect(section.locator(f"li.report-item[data-report='{filed['id']}']")).to_be_visible()
    opened = section.locator("section.report-open")
    expect(opened).to_contain_text("e2e: a card to report")
    # The reporter's text and the snapshot are text, never markup.
    expect(opened.locator("pre.report-body").first).to_have_text("<i>e2e</i> report")
    expect(opened.locator("i, b")).to_have_count(0)
    page.locator("#report-action").select_option("hide")
    page.locator("#report-note").fill("e2e: hidden on purpose")
    opened.get_by_role("button", name="Resolve", exact=True).click()
    expect(section).to_contain_text("Resolved: Hide.")
    expect(section.locator(f"li.report-item[data-report='{filed['id']}']")).to_have_count(0)
    # Resolving withdrew the request (§16.8).
    shown = page.request.get(f"{run.base}/api/v1/requests/{asked['id']}").json()
    assert shown["status"] == "withdrawn", shown
    run.shot(page, "reports-admin")
    run.a11y(page, "reports admin")
    no_problems(run, "reports admin")


def forge_access_step(run: Run, page: Page) -> None:
    """Forge access (docs/api.md §11.4) at /settings/forge, where the hub's setup redirect
    lands: this hub has no GitHub App and no secret key, and says so."""
    run.step("forge: /settings/forge shows the account's forge access; no App, a token needs the secret key")
    page.goto(f"{run.base}/settings/forge?error=link_state")
    box = page.locator("section.forge-access")
    expect(box).to_contain_text("The link expired or was started in another session")
    expect(page).to_have_url(re.compile(r"/settings/forge$"))
    expect(box).to_contain_text("This instance has no GitHub App configured")
    expect(box).to_contain_text("No token is stored.")
    page.locator("#forge-token").fill("github_pat_e2e_not_a_real_token")
    box.get_by_role("button", name="Store the token", exact=True).click()
    expect(box).to_contain_text("This hub has no secret key to store a token with")
    # That refusal is this hub's configuration, the expected answer here.
    refused = "PUT /api/v1/me/forge/github/token answered 409"
    run.problems = [p for p in run.problems if p != refused]
    run.shot(page, "forge-access")
    run.a11y(page, "forge access")
    no_problems(run, "forge access")
    # Leave the account page: a later step opens it from the menu and must not find this one.
    page.goto(f"{run.base}/all")
    expect(page.locator("header .project")).to_have_text("Everything waiting for you")


def join_expiry_step(run: Run, page: Page) -> None:
    """A join that expires while Agents is open leaves the seats for the record, without Revoke."""
    run.step("joins: a join expires while the view is open; it is listed as expired, without Revoke")
    # A second tab of the same human whose clock can be moved: the hub's is not.
    other = page.context.browser.new_context(storage_state=page.context.storage_state())
    second = other.new_page()
    watch_page(run, second)
    # The page judges expiry by the hub's clock: every answer's Maity-Server-Time
    # sets how far the browser is off it (js/api.js). Moving only the browser's
    # clock let the next answer pull the page back to the hub's real time, and
    # the join read as open again: the step failed or passed by which came first.
    # So this tab sees the hub's clock moved by the same amount as its own.
    moved = {"by": timedelta(0)}
    # Set before the tab's context goes: a poll held then fails with "Request
    # context disposed" or "closed", the same end of the step, not a problem.
    ending = {"now": False}

    def quiet(err: PlaywrightError) -> bool:
        return ending["now"] or "closed" in str(err)

    def hub_clock(route: object) -> None:
        # Only a tab ending while an answer was held is quiet; any other error
        # is said where it happens and the request ends, not as a later timeout.
        try:
            answer = route.fetch()
        except PlaywrightError as err:
            if not quiet(err):
                run.problems.append(f"join expiry: the hub's answer could not be held: {err}")
                try:
                    route.abort()
                except PlaywrightError:
                    pass
            return
        headers = dict(answer.headers)
        served = headers.get("maity-server-time")
        if served and moved["by"]:
            at = datetime.fromisoformat(served.replace("Z", "+00:00")) + moved["by"]
            headers["maity-server-time"] = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        try:
            route.fulfill(response=answer, headers=headers)
        except PlaywrightError as err:
            if not quiet(err):
                run.problems.append(f"join expiry: the moved answer could not be given: {err}")

    second.route(re.compile(r"/api/v1/"), hub_clock)
    second.clock.install()
    second.goto(f"{run.base}/owner/e2e-alpha/agents/join")
    # A direct navigation to Agents with the join panel open: the focus in its first field.
    expect(second).to_have_url(re.compile(r"/owner/e2e-alpha/agents/join$"))
    expect(second.locator("#join-agent")).to_be_focused()
    # A new profile: the existing one is a member here already.
    second.locator("#join-agent").select_option("")
    second.locator("#join-handle").fill("e2e-expiring")
    second.locator("#join-display").fill("E2E Expiring")
    second.get_by_role("button", name="Create join line", exact=True).click()
    expect(second.locator(".paste-line")).to_be_visible()
    row = second.locator("article.seat").first
    expect(row.get_by_role("button", name=re.compile(r"^Revoke"))).to_be_visible()
    join_id = row.get_attribute("data-join")
    # Past the default 15 minutes, the browser's clock and the hub's as this tab sees it.
    moved["by"] = timedelta(minutes=16)
    second.clock.fast_forward("16:00")
    gone = second.locator("ul.closed-joins li", has_text=join_id)
    expect(gone).to_contain_text("expired")
    expect(gone.get_by_role("button", name="Revoke")).to_have_count(0)
    expect(second.locator(f'article.seat[data-join="{join_id}"]')).to_have_count(0)
    run.shot(second, "join-expired")
    ending["now"] = True
    second.unroute_all(behavior="ignoreErrors")
    other.close()
    no_problems(run, "joins")


def memory_provider_step(run: Run, page: Page, alpha: Path) -> None:
    """The memory provider in Project settings (docs/api.md §6.1, §6.21, tsk-41hpr02cvej8): to None and back."""
    run.step("memory: the owner switches the provider to None and back; the commitment follows")
    project_settings(page)
    expect(page.locator("#memory-provider")).to_have_value("keep-the-why")
    page.locator("#memory-provider").select_option("none")
    page.locator("#memory-reason").fill("e2e: without a memory provider")
    page.locator("form.memory-panel").get_by_role("button", name="Change memory", exact=True).click()
    expect(page.locator("main p.ok")).to_have_text("Project memory saved.")
    expect(page.locator("#ktw-policy-select")).to_be_disabled()
    expect(page.locator("#ktw-policy-select")).to_have_value("optional")
    shown = run.api(alpha, "GET", "/projects/owner/e2e-alpha")
    assert shown["memory"]["provider"] == "none" and shown["policy"]["keep_the_why"] == "optional", shown
    page.locator("#memory-provider").select_option("keep-the-why")
    page.locator("#memory-reason").fill("e2e: back to Keep the Why")
    page.locator("form.memory-panel").get_by_role("button", name="Change memory", exact=True).click()
    expect(page.locator("#memory-provider")).to_have_value("keep-the-why")
    expect(page.locator("#ktw-policy-select")).to_be_enabled()
    expect(page.locator("#ktw-policy-select")).to_have_value("required")
    shown = run.api(alpha, "GET", "/projects/owner/e2e-alpha")
    # Nobody set the commitment in e2e-alpha: back under Keep the Why it reads required (§6.23).
    assert shown["memory"]["provider"] == "keep-the-why" and shown["policy"]["keep_the_why"] == "required", shown
    run.a11y(page, "project settings, memory")
    no_problems(run, "memory provider")


def availability_step(run: Run, page: Page, clone: Path) -> None:
    """Outage and cover (docs/api.md §6.12) on the real hub: the agent declares a limit,
    Members says until when and why, and the next resume clears it."""
    run.step("members: an agent's declared limit shows until when and why")
    until = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    run.maity(clone, "limit", "--until", until, "--reason", "e2e quota")
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    note = page.locator("table.members tr.member", has_text="E2E Agent").locator(".availability-note")
    expect(note).to_contain_text("Away until")
    expect(note).to_contain_text("(e2e quota)")
    run.a11y(page, "members, an agent away")
    run.maity(clone, "resume")


def agent_owners_step(run: Run, page: Page) -> None:
    """Agents of owners who are not members (docs/api.md §6.1) on the real hub: the hub takes
    the setting and the roles, and the form then reads them back, no longer offering unset."""
    run.step("settings: a human admin sets who may keep an agent here, and the roles for outside agents")
    page.goto(f"{run.base}/owner/e2e-alpha/settings")
    form = page.locator("form.agent-owners-form")
    form.locator("#agent-owners-select").select_option("anyone")
    form.locator("#outside-role-writer").check()
    form.locator("#agent-owners-reason").fill("e2e: outsiders may write")
    form.get_by_role("button", name="Save").click()
    form = page.locator("form.agent-owners-form")
    expect(form.locator("#outside-role-writer")).to_be_checked()
    expect(form.locator("#agent-owners-select")).to_have_value("anyone")
    expect(form.locator("#agent-owners-select option[value='']")).to_have_count(0)
    run.a11y(page, "settings, agents of owners who are not members")


def isolate_step(run: Run, page: Page) -> None:
    """Isolation (docs/api.md §6.2) on the real hub. Last of the agent's steps: isolating
    releases its claims, which the steps before rely on, and lifting does not bring them back."""
    run.step("members: the owner isolates the agent with a reason, sees the badge, and lifts the isolation")
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    agents = page.locator("main .members-agents")
    row = agents.locator("tr.member", has_text="E2E Agent")
    row.get_by_role("button", name="Manage E2E Agent").click()
    manage = page.locator("tr.member-manage")
    manage.locator("input[id^=member-isolate-]").fill("e2e: isolated on purpose")
    asked = []
    page.once("dialog", lambda d: (asked.append(d.message), d.accept()))
    manage.get_by_role("button", name="Isolate", exact=True).click()
    expect(page.locator("main section.view-team > .send-status")).to_contain_text("E2E Agent is isolated.")
    assert asked and asked[0].startswith("Isolate E2E Agent?"), asked
    expect(row.locator(".badge.member-isolated")).to_have_text("Isolated")
    expect(row.locator(".badge.member-isolated")).to_have_attribute("title", "Isolated: e2e: isolated on purpose")
    expect(manage.locator(".member-isolate")).to_contain_text("e2e: isolated on purpose")
    run.a11y(page, "members, an isolated agent")
    run.shot(page, "member-isolated")
    # Lifting with the box ticked (tsk-zwxtdfmdscf7): the isolation's events stay hidden from the agent.
    hide = manage.locator("input[id^=member-lift-hide-]")
    expect(hide).not_to_be_checked()
    hide.check()
    manage.get_by_role("button", name="Lift isolation", exact=True).click()
    expect(page.locator("main section.view-team > .send-status")).to_contain_text(
        "The isolation of E2E Agent is lifted; what happened meanwhile stays hidden from it."
    )
    expect(row.locator(".badge.member-isolated")).to_have_count(0)
    expect(row.locator(".member-hidden-windows")).to_contain_text("Hidden from it after an isolation: events ")
    expect(manage.locator("input[id^=member-isolate-]")).to_be_visible()
    row.get_by_role("button", name="Done managing E2E Agent").click()
    # The owner is told of both in their inbox (§6.2, a hub notice with one reply, Seen):
    # read and marked seen here, so the steps after find their own requests first.
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    told = re.compile(r"e2e-agent was isolated|The isolation of e2e-agent was lifted")
    seen = []
    for _ in range(2):
        entry = page.locator("li.entry.current")
        expect(entry).to_contain_text(told)
        seen.append(entry.locator(".title").first.inner_text())
        entry.get_by_role("button", name="Seen", exact=True).click()
        expect(page.locator("li.entry.current", has_text=seen[-1])).to_have_count(0)
    assert any("was isolated" in x for x in seen) and any("was lifted" in x for x in seen), seen
    no_problems(run, "isolation")


def agents_page_step(run: Run, page: Page) -> None:
    """Your agents (/agents, tsk-05meme59sq1x): Add and Join an agent at the head; the profiles as rows,
    Manage opening a row with the instances of each membership read on the real hub."""
    run.step("agents page: the profiles as rows; Manage shows the instances in each project")
    page.goto(f"{run.base}/agents")
    expect(page.get_by_role("button", name="+ Add an agent", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Join an agent", exact=True)).to_be_visible()
    expect(page.locator("section.agents-join")).to_be_hidden()
    row = page.locator("tr.agent-row", has_text="E2E Agent").first
    expect(row).to_be_visible()
    row.get_by_role("button", name=re.compile(r"^Manage ")).click()
    expect(row.get_by_role("button", name=re.compile(r"^Manage "))).to_have_attribute("aria-expanded", "true")
    inside = page.locator("tr.agent-manage").first
    # Allowed projects (§6.3) on the real hub: a list saved, then any project again.
    inside.locator("details.agent-settings summary").click()
    allowed = inside.locator("form.agent-allowed")
    allowed.get_by_label("Any project").uncheck()
    allowed.get_by_role("button", name="Save the allowed projects").click()
    expect(page.get_by_text("Allowed projects saved.")).to_be_visible()
    run.a11y(page, "agents page, allowed projects")
    row = page.locator("tr.agent-row", has_text="E2E Agent").first
    if row.get_by_role("button", name=re.compile(r"^Manage ")).get_attribute("aria-expanded") != "true":
        row.get_by_role("button", name=re.compile(r"^Manage ")).click()
    inside = page.locator("tr.agent-manage").first
    if not inside.locator("form.agent-allowed").is_visible():
        inside.locator("details.agent-settings summary").click()
    inside.locator("form.agent-allowed").get_by_label("Any project").check()
    inside.locator("form.agent-allowed").get_by_role("button", name="Save the allowed projects").click()
    expect(page.get_by_text("Allowed projects saved.")).to_be_visible()
    row = page.locator("tr.agent-row", has_text="E2E Agent").first
    if row.get_by_role("button", name=re.compile(r"^Manage ")).get_attribute("aria-expanded") != "true":
        row.get_by_role("button", name=re.compile(r"^Manage ")).click()
    inside = page.locator("tr.agent-manage").first
    expect(inside.locator(".agent-instances", has_text="Instances in E2E Alpha").first).to_be_visible()
    expect(inside.locator(".agent-instances .member-credentials").first).to_be_visible()
    run.a11y(page, "agents page, a row opened")
    no_problems(run, "agents page")


# The handle hints that stand in the page (tsk-srzrkf2parzt): each one's lines (its height over its
# line height) and whether it runs wider than itself; hidden ones are not counted.
HANDLE_HINTS = """() => Array.from(document.querySelectorAll("p.handle-explain")).filter((p) => p.offsetParent !== null).map((p) => {
  const s = getComputedStyle(p), lh = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.5;
  const owner = document.querySelector('[aria-describedby~="' + p.id + '"]');
  return { field: owner ? owner.id : null, lines: Math.round(p.getBoundingClientRect().height / lh), wide: p.scrollWidth > p.clientWidth + 1 };
})"""


# The owner's 31-character handle while handle_hints_step runs; an alias of the owner after it,
# which notifications_step mentions, since "@owner" is a group word, never a member (§8.6).
LONG_OWNER = "e2e-hints-owner-handle-31-chars"


def handle_hints_step(run: Run, page: Page) -> None:
    """Every field that asks for a handle explains the word (tsk-srzrkf2parzt): one sentence the field
    names in its aria-describedby, at most two lines at 390 and 360 px, light and dark. The seven fields:
    your own handle, an agent's when it is added, renamed or joined, an organisation's when it is
    created or renamed (here with a handle of the full 31 characters), and the person invited to one.
    The owner is renamed to 31 characters for the step and back after it, so /account's own hint is
    measured with a long handle too: a hint that filled in the handle (2026c18b) took three lines there
    (nte-j9ae0tjdqykf). Two of the three renames a day the hub allows; no other step renames the owner."""
    run.step("handle hints: every handle field explains the word, at most two lines on a phone")
    org = "e2e-hints-organisation-handle-x"
    assert len(org) == 31, org
    long_owner = LONG_OWNER
    assert len(long_owner) == 31, long_owner

    def rename_owner(old: str, new: str) -> None:
        page.goto(f"{run.base}/account")
        field = page.locator(".handle-editor input[type=text]").first
        expect(field).to_have_value(old)
        field.fill(new)
        page.locator(".handle-editor").first.get_by_role("button", name="Rename", exact=True).click()
        # The editor is drawn again with the new handle; the old one is listed as an alias.
        expect(page.locator(".handle-editor input[type=text]").first).to_have_value(new)
        expect(page.locator(".handle-editor").first).to_contain_text(f"@{old}")

    def restore_owner() -> None:
        """Back to "owner" whatever happened since the rename began: the page says the handle now,
        so a rename that went through before a failed check is undone too, and one that never
        happened costs no rename."""
        page.goto(f"{run.base}/account")
        field = page.locator(".handle-editor input[type=text]").first
        expect(field).to_be_visible()
        if field.input_value() != "owner":
            rename_owner(field.input_value(), "owner")

    def measured(where: str) -> list[dict]:
        hints = page.evaluate(HANDLE_HINTS)
        for x in hints:
            assert x["field"], f"{where}: a handle hint no field names: {hints}"
            assert x["lines"] <= 2 and not x["wide"], f"{where}: {x}"
        return hints

    # Everything from the rename on is inside the try, so a failure anywhere after it, its own
    # check included, still ends with the owner's handle restored (#1581 review).
    try:
        rename_owner("owner", long_owner)
        page.goto(f"{run.base}/account/orgs")
        page.locator("#org-new-handle").fill(org)
        page.locator("#org-new-name").fill("E2E Hints Organisation")
        page.get_by_role("button", name="Create the organisation", exact=True).click()
        expect(page.locator("#org-handle")).to_have_value(org)
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            for width in (390, 360):
                page.set_viewport_size({"width": width, "height": 900})
                at = f"{width} px {scheme}"
                seen: set[str] = set()
                page.goto(f"{run.base}/account")
                expect(page.locator(".handle-editor p.handle-explain")).to_be_visible()
                seen |= {x["field"] for x in measured(f"account, {at}")}
                page.goto(f"{run.base}/account/orgs")
                expect(page.locator("#org-new-handle")).to_be_visible()
                seen |= {x["field"] for x in measured(f"new organisation, {at}")}
                page.goto(f"{run.base}/account/orgs/{org}")
                expect(page.locator("#org-invite-handle")).to_be_visible()
                seen |= {x["field"] for x in measured(f"organisation, {at}")}
                page.goto(f"{run.base}/agents")
                page.get_by_role("button", name="+ Add an agent", exact=True).click()
                expect(page.locator("#agent-new-handle")).to_be_visible()
                seen |= {x["field"] for x in measured(f"new agent, {at}")}
                page.goto(f"{run.base}/agents")
                row = page.locator("tr.agent-row", has_text="E2E Agent").first
                row.get_by_role("button", name=re.compile(r"^Manage ")).click()
                page.locator("tr.agent-manage").first.locator("details.agent-settings summary").click()
                expect(page.locator("tr.agent-manage").first.locator("p.handle-explain").first).to_be_visible()
                seen |= {x["field"] for x in measured(f"agent settings, {at}")}
                page.goto(f"{run.base}/agents")
                page.get_by_role("button", name="Join an agent", exact=True).click()
                page.locator("#join-agent").select_option("")
                expect(page.locator("#join-handle")).to_be_visible()
                seen |= {x["field"] for x in measured(f"join an agent, {at}")}
                fields = {f for f in seen if f}
                kinds = {
                    "own": any(re.fullmatch(r"handle-[a-z0-9]{1,8}", f) for f in fields),
                    "agent-new": "agent-new-handle" in fields,
                    "agent-edit": any(f.startswith("agent-handle-") for f in fields),
                    "join": "join-handle" in fields,
                    "org-new": "org-new-handle" in fields,
                    "org-rename": "org-handle" in fields,
                    "org-invite": "org-invite-handle" in fields,
                }
                assert all(kinds.values()), f"handle hints at {at}: {kinds} from {sorted(fields)}"
                print(f"   handle hints: 7 kinds, each at most two lines at {at}, the owner's handle of 31 characters")
    finally:
        # The handle first: a media or viewport reset that fails must not leave the owner renamed.
        try:
            restore_owner()
        finally:
            page.emulate_media(color_scheme="light")
            page.set_viewport_size({"width": 1280, "height": 900})
    no_problems(run, "handle hints")


def invitations_step(run: Run, page: Page) -> None:
    """Invitations (docs/api.md §3.4) on the real hub: the owner goes from Members' Invite user to
    /invite with the project chosen and invites there; a browser
    without a session opens the link, signs in with it as next and comes back; joining is refused
    in the hub's words (the only human there is a member already: without mail the e2e hub makes
    no second account); revoked, the link is one uniform answer."""
    run.step("invitations: the owner invites a person from /invite, reached by Members' Invite user; the link is shown once")
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    expect(page.locator("section.invitations")).to_have_count(0)
    page.get_by_role("link", name="Invite user", exact=True).click()
    expect(page).to_have_url(re.compile(r"/invite\?project=owner%2Fe2e-alpha$"))
    expect(page.locator("#invitations-project")).to_have_value("owner/e2e-alpha")
    box = page.locator("section.invitations").first
    expect(box).to_be_visible()
    page.locator("#invite-role").select_option("reviewer")
    page.locator("#invite-note").fill("Welcome to the e2e project.")
    # This hub has no join host (no MAITY_JOIN_URL): no "Link via" choice, and the
    # link is on the hub's own address (§3.4 `via` defaults to public).
    session = page.request.get(f"{run.base}/api/v1/auth/session").json()
    if not session.get("join_url"):
        expect(page.locator("#invite-via-join")).to_have_count(0)
    box.get_by_role("button", name="Create the invitation", exact=True).click()
    shown = page.locator("#invite-url")
    expect(shown).to_have_value(re.compile(r"/invite/[A-Za-z0-9_-]{22}$"))
    token = shown.input_value().rsplit("/", 1)[1]
    expect(box.locator("li.invite-item.invite-open")).to_have_count(1)
    run.a11y(page, "invitations page, an invitation created")

    run.step("invitations: a browser without a session opens the link, signs in and comes back to it")
    other = page.context.browser.new_context()
    try:
        guest = other.new_page()
        watch_page(run, guest)
        guest.goto(f"{run.base}/invite/{token}")
        card = guest.locator("article.invite")
        expect(card).to_contain_text("Owner invites you to join E2E Alpha as member · reviewer.")
        expect(card.locator(".invite-note")).to_have_text("Welcome to the e2e project.")
        # A closed hub and no address: signing in is the one way in.
        expect(card.get_by_role("link", name="Create one", exact=True)).to_have_count(0)
        run.a11y(guest, "invitation page, signed out")
        card.get_by_role("link", name="Sign in to accept", exact=True).click()
        guest.locator("#login-email").fill(OWNER_EMAIL)
        guest.locator("#login-password").fill(OWNER_PASSWORD)
        guest.locator("form.login").get_by_role("button", name="Sign in", exact=True).click()
        expect(guest).to_have_url(re.compile(rf"/invite/{token}$"))
        join = guest.locator("article.invite").get_by_role("button", name=re.compile(r"^Join E2E Alpha as "))
        expect(join).to_be_visible()
        join.click()
        expect(guest.locator("article.invite .send-status")).to_contain_text("(already_member)")
        run.problems = [p for p in run.problems if p != f"POST /api/v1/invitations/{token}/accept answered 400"]

        run.step("invitations: revoked by the owner, the link answers as an unknown one")
        box.locator("li.invite-item.invite-open").get_by_role("button", name="Revoke", exact=True).click()
        expect(box).to_contain_text("Revoked; the link no longer works.")
        guest.reload()
        expect(guest.locator("article.invite")).to_contain_text("This invitation cannot be used")
        run.problems = [p for p in run.problems if p != f"GET /api/v1/invitations/{token} answered 404"]
    finally:
        other.close()
    no_problems(run, "invitations")


def project_tabs_step(run: Run, page: Page) -> None:
    """Project tabs (docs/api.md §5.1 "Start tabs", tsk-p6aye59z0k7g): moved by key and drag,
    closed from the menu, the inbox's filter to open tabs, the start set on a fresh browser."""
    run.step("tabs: move by key and drag, close one, filter the inbox, keep a start set, a fresh browser")
    page.goto(f"{run.base}/all")
    tabs = page.locator("nav.switcher a[data-project]")

    def names() -> list[str]:
        return [t.strip() for t in tabs.evaluate_all("(els) => els.map((e) => e.textContent)")]

    expect(tabs).to_have_count(2)
    assert [n.startswith(("E2E Alpha", "EA")) for n in names()] == [True, False], names()
    # The keyboard: Alt+Shift+ArrowLeft moves the focused tab, the focus stays on it, it is said.
    beta = page.locator("nav.switcher a[data-project]", has_text="E2E Beta")
    beta.focus()
    page.keyboard.press("Alt+Shift+ArrowLeft")
    expect(tabs.first).to_contain_text("E2E Beta")
    expect(page.locator("nav.switcher a[data-project]", has_text="E2E Beta")).to_be_focused()
    expect(page.locator(".tabs-said")).to_have_text("E2E Beta moved to place 1 of 2")
    # A drag, as the browser's drag events: Alpha dropped on Beta's first half goes before it.
    dt = page.evaluate_handle("() => new DataTransfer()")
    alpha = page.locator("nav.switcher a[data-project]", has_text="E2E Alpha")
    first = page.locator("nav.switcher a[data-project]", has_text="E2E Beta")
    box = first.bounding_box()
    assert box is not None
    alpha.dispatch_event("dragstart", {"dataTransfer": dt})
    # While dragging, a line shows the place by the drop's own half (tsk-hp9gq9rmrdq2): after on the second half,
    # before on the first; one tab marked at a time.
    first.dispatch_event("dragover", {"dataTransfer": dt, "clientX": box["x"] + box["width"] - 2})
    expect(first).to_have_class(re.compile(r"\bdrop-after\b"))
    first.dispatch_event("dragover", {"dataTransfer": dt, "clientX": box["x"] + 2})
    expect(first).to_have_class(re.compile(r"\bdrop-before\b"))
    expect(first).not_to_have_class(re.compile(r"\bdrop-after\b"))
    expect(page.locator("nav.switcher a.drop-before, nav.switcher a.drop-after")).to_have_count(1)
    # The line itself: an upright bar in the gap before the tab, drawn and inside the row's visible box.
    line = first.evaluate("(el) => { const s = getComputedStyle(el, '::before'); const r = el.getBoundingClientRect();"
                          " const n = el.parentNode.getBoundingClientRect();"
                          " return [s.content, s.width, parseFloat(s.left), r.left, n.left, s.backgroundColor]; }")
    assert line[0] == '""' and line[1] == "3px" and line[2] < 0 and line[3] + line[2] >= line[4], f"the drop line is not drawn in the gap: {line}"
    run.shot(page, "tabs-drop-line")
    first.dispatch_event("drop", {"dataTransfer": dt, "clientX": box["x"] + 2})
    page.locator("nav.switcher a[data-project]", has_text="E2E Alpha").dispatch_event("dragend", {"dataTransfer": dt})
    expect(tabs.first).to_contain_text("E2E Alpha")
    expect(page.locator("nav.switcher a.drop-before, nav.switcher a.drop-after")).to_have_count(0)
    # The tabs menu stands right after the last tab, not at the row's far end.
    gap = page.evaluate("(() => { const t = Array.from(document.querySelectorAll('nav.switcher a')).pop().getBoundingClientRect();"
                        " const m = document.querySelector('.tabs-menu-box').getBoundingClientRect(); return [m.left - t.right, Math.abs(m.top - t.top) < t.height]; })()")
    assert 0 <= gap[0] <= 24 and gap[1], f"the tabs menu is not right after the tabs: {gap}"
    # The tabs menu: one switch per project; switching one off closes its tab, the menu stays.
    menu = page.locator(".tabs-menu-box")
    menu.get_by_role("button", name="Project tabs", exact=True).click()
    run.a11y(page, "tabs menu")
    # A checked item's name starts with the stylesheet's "✓ " (.menu-item.checked::before), so not exact.
    beta_item = menu.get_by_role("menuitemcheckbox", name="E2E Beta")
    beta_item.click()
    expect(tabs).to_have_count(1)
    expect(beta_item).to_have_attribute("aria-checked", "false")
    expect(beta_item).to_be_focused()
    page.keyboard.press("Escape")
    # The cross-project inbox's filter to open tabs, kept by this browser across a reload.
    page.locator("#inbox-project").select_option("open-tabs")
    page.reload()
    expect(page.locator("#inbox-project")).to_have_value("open-tabs")
    expect(tabs).to_have_count(1)
    page.locator("#inbox-project").select_option("")
    # The row as the account's start set.
    menu.get_by_role("button", name="Project tabs", exact=True).click()
    menu.get_by_role("menuitem", name="Keep these tabs at start", exact=True).click()
    expect(page.locator(".tabs-said")).to_have_text("Saved: a browser with no tabs of its own yet opens these.")
    # A fresh browser profile: no tabs of its own, so it opens the account's start set.
    fresh, other = signed_in_page(run, page.context.browser)
    try:
        other_tabs = other.locator("nav.switcher a[data-project]")
        expect(other_tabs).to_have_count(1)
        expect(other_tabs.first).to_contain_text("E2E Alpha")
    finally:
        fresh.close()
    # Beta back in the start set from its own settings (Mine), and its tab back by its address.
    page.goto(f"{run.base}/owner/e2e-beta/settings/mine")
    expect(tabs).to_have_count(2)  # opened by its address, its tab is back
    start = page.locator("#my-start-tab")
    expect(start).not_to_be_checked()
    run.a11y(page, "settings, mine, start tab")
    start.check()
    expect(page.locator("fieldset.my-start-tab")).to_contain_text("Saved: this project opens as a tab at start.")
    page.reload()
    expect(page.locator("#my-start-tab")).to_be_checked()
    no_problems(run, "tabs")


def my_settings_step(run: Run, page: Page) -> None:
    """Agents that stop listening (§5.3, §6.2, §18.4): the account's default, a project's own value."""
    run.step("my settings: the account's default, then a value for the project, then back to the default")
    page.goto(f"{run.base}/account/notifications")
    form = page.locator("form.not-listening-settings")
    expect(page.locator("#not-listening-minutes")).to_have_value("60")
    page.locator("#not-listening-minutes").fill("45")
    form.get_by_role("button", name="Save", exact=True).click()
    expect(form).to_contain_text("Saved.")
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    view_tab(page, "Settings").click()
    page.locator("nav.settings-tabs").get_by_role("link", name="Mine", exact=True).click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/settings/mine$"))
    effective = page.locator(".my-nl-effective")
    expect(effective).to_have_text("Applies now: 45 minutes, your default.")
    page.locator("#my-nl-here").check()
    page.locator("#my-nl-minutes").fill("20")
    page.locator("form.my-settings").get_by_role("button", name="Save", exact=True).click()
    expect(effective).to_have_text("Applies now: 20 minutes, set here.")
    # Memory (§19), against the real hub: an entry added, deleted with a reason, its row stays.
    page.goto(f"{run.base}/owner/e2e-alpha/memory")
    memory = page.locator("section.memory-entries")
    # The agent and role pickers only for their store: a display rule must not undo `hidden`.
    expect(page.locator("#memory-team")).to_be_hidden()
    expect(page.locator("#memory-role")).to_be_hidden()
    page.locator("#memory-store").select_option("team")
    expect(page.locator("#memory-team")).to_be_visible()
    page.locator("#memory-store").select_option("")
    page.locator("#memory-add-text").fill("Rebase before the review.")
    page.locator("#memory-add-tags").fill("Git")
    memory.get_by_role("button", name="Add to the memory", exact=True).click()
    expect(memory.locator(".memory-list")).to_contain_text("Rebase before the review.")
    run.shot(page, "memory")
    run.a11y(page, "memory")
    memory.get_by_role("button", name="Delete the entry: Rebase before the review.", exact=True).click()
    page.locator("form.memory-delete input").fill("out of date")
    memory.get_by_role("button", name="Delete the entry", exact=True).click()
    expect(memory).not_to_contain_text("Rebase before the review.")
    page.locator("#memory-deleted").check()
    expect(memory.locator(".memory-list")).to_contain_text("because: out of date")
    page.goto(f"{run.base}/owner/e2e-alpha/settings/mine")
    run.a11y(page, "my settings")
    page.locator("#my-nl-default").check()
    page.locator("form.my-settings").get_by_role("button", name="Save", exact=True).click()
    expect(effective).to_have_text("Applies now: 45 minutes, your default.")
    no_problems(run, "my settings")


def members_step(run: Run, page: Page) -> None:
    """Members (docs/api.md §6.2): humans and agents; the owner changes an agent's role and back."""
    run.step("members: the owner and the agent in two tables; an agent's role changed and back")
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    view_tab(page, "Team").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/team$"))
    # Two tables, humans first; the levels by trust are the Organisation tree's (the maintainer, 2026-11-01).
    table = page.locator("table.members")
    expect(table).to_have_count(2)
    humans, agents = table.nth(0), table.nth(1)
    expect(humans.locator("tr.member")).to_have_count(1)
    expect(humans.locator("tr.member")).to_contain_text("owner")
    row = agents.locator("tr.member", has_text="E2E Agent")
    expect(page.locator("tr.member[data-level]")).to_have_count(0)
    expect(row.locator("td").nth(0)).to_contain_text("member")
    # A neutral list: no credentials column (they are in Manage and on Agents), a Chat per entry.
    header = agents.locator("thead th")
    expect(header.filter(has_text="Credentials")).to_have_count(0)
    expect(row.locator("a.member-chat")).to_have_count(1)
    run.a11y(page, "members")
    run.step("members: Only my agents shows the owner's agents alone, and is kept on the next visit")
    mine = page.get_by_role("checkbox", name="Only my agents", exact=True)
    expect(mine).not_to_be_checked()
    mine.check()
    expect(page.locator("table.members")).to_have_count(1)
    expect(page.locator("table.members tr.member")).to_have_count(1)
    expect(page.locator("table.members tr.member")).to_contain_text("E2E Agent")
    expect(mine).to_be_focused()
    run.a11y(page, "members, only my agents")
    page.reload()
    expect(page.get_by_role("checkbox", name="Only my agents", exact=True)).to_be_checked()
    expect(page.locator("table.members")).to_have_count(1)
    page.get_by_role("checkbox", name="Only my agents", exact=True).uncheck()
    expect(page.locator("table.members")).to_have_count(2)
    expect(page.locator("table.members tr.member")).to_have_count(2)
    # A member's page (#6484, read only): the agent's name leads there; header, Actions, tabs.
    row.locator("a.member-ref").first.click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/team/agt-[0-9a-z]+$"))
    head = page.locator(".member-head")
    expect(head).to_contain_text("E2E Agent")
    expect(head.locator(".member-pill", has_text="agent of")).to_have_count(1)
    expect(page.locator("nav.member-tabs a")).to_have_count(4)
    head.get_by_role("button", name="Actions for E2E Agent").click()
    expect(head.get_by_role("menuitem", name="Manage on Team")).to_be_visible()
    page.keyboard.press("Escape")
    run.a11y(page, "member page")
    page.locator("nav.member-tabs").get_by_role("link", name="Sessions & credentials").click()
    expect(page.locator(".member-section")).to_contain_text("Instances")
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    expect(table.locator("tr.member", has_text="E2E Agent")).to_be_visible()
    row.get_by_role("button", name="Manage E2E Agent").click()
    manage = page.locator("tr.member-manage")
    manage.locator("select[id^=member-role-]").select_option("reviewer")
    manage.get_by_role("button", name="Save changes", exact=True).click()
    expect(row.locator("td").nth(0)).to_contain_text("reviewer")
    run.shot(page, "members")
    manage.locator("select[id^=member-role-]").select_option("coder")
    manage.get_by_role("button", name="Save changes", exact=True).click()
    expect(row.locator("td").nth(0)).to_contain_text("member · coder")
    # Reports to: the agent under the owner, at once in the organisation.
    manage.locator("select[id^=member-reports-]").select_option(label="Owner (@owner)")
    manage.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.locator("main section.view-team > .send-status")).to_contain_text("Saved for E2E Agent: reports to.")
    page.locator("main nav.team-tabs").get_by_role("link", name="Organisation", exact=True).click()
    owner_node = page.locator(".org-tree > li", has=page.locator(".org-node strong", has_text="Owner"))
    expect(owner_node.locator("ul .org-node")).to_contain_text("E2E Agent")
    # Each of the agent's instances is a link to its Sessions on the member's page.
    instance_link = owner_node.locator("ul .org-node .org-instances a.member-instance").first
    expect(instance_link).to_have_text(re.compile(r"^#\S+$"))
    instance_link.click()
    expect(page).to_have_url(re.compile(r"/team/agt-[0-9a-z]+/sessions/[0-9a-z]+$"))
    expect(page.locator(".member-instances li.chosen")).to_have_count(1)
    page.go_back()
    expect(page.locator("main .org-tree")).to_be_visible()
    # Paths (tsk-j9ktmj7e4fxq): the same members drawn, and one chip's route from the hub's member views.
    page.locator("main .org-faces").get_by_role("button", name="Paths", exact=True).click()
    page.locator("main .paths-chips").get_by_role("button", name="Not listening", exact=True).click()
    expect(page.locator("main .paths-panel .paths-route-list")).to_contain_text("E2E Agent ⇢ Owner")
    expect(page.locator("main .paths-lines path.paths-route").first).to_be_attached()
    run.a11y(page, "team page, organisation paths")
    run.shot(page, "organisation-paths")
    page.locator("main .org-faces").get_by_role("button", name="Tree", exact=True).click()
    expect(page.locator("main .org-tree")).to_be_visible()
    view_tab(page, "Team").click()
    # The owner reporting to the agent would close a circle: refused before it is sent.
    table.get_by_role("button", name="Manage Owner").click()
    owner_manage = page.locator("tr.member-manage")
    owner_manage.locator("select[id^=member-reports-]").select_option(label="E2E Agent (@e2e-agent)")
    owner_manage.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.locator("main section.view-team > .send-status")).to_contain_text("That would close a circle")
    table.get_by_role("button", name="Done managing Owner").click()
    row.get_by_role("button", name="Manage E2E Agent").click()
    manage.locator("select[id^=member-reports-]").select_option("")
    manage.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.locator("main section.view-team > .send-status")).to_contain_text("Saved for E2E Agent: reports to.")
    # On a phone each row is a card: Manage and Remove are on screen, not in a sideways scroll.
    page.set_viewport_size({"width": 360, "height": 780})
    for button in (row.get_by_role("button", name=re.compile("^(Manage|Done managing) E2E Agent$")),
                   manage.get_by_role("button", name="Remove from the project", exact=True)):
        button.scroll_into_view_if_needed()
        box = button.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 360 + 1, f"members at 360 px: a button is off screen: {box}"
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1], f"members is {width[0]} px wide at {width[1]} px"
    run.shot(page, "phone-members")
    page.set_viewport_size({"width": 1280, "height": 900})
    no_problems(run, "members")


def picture_step(run: Run, page: Page) -> None:
    """docs/api.md §6.10: the owner's picture, on the account's Profile from the profile menu, and at
    the address before the tabs, /account/picture, which leads there; uploaded where the hub has it."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.locator("header").get_by_role("button", name=re.compile(r"^Your profile: ")).click()
    page.get_by_role("menuitem", name="Profile", exact=True).click()
    expect(page).to_have_url(re.compile(r"/account$"))
    expect(page.locator(".picture-heading")).to_be_visible()
    page.goto(run.base + "/account/picture")
    expect(page).to_have_url(re.compile(r"/account$"))
    expect(page.locator(".picture-heading")).to_be_focused()
    run.a11y(page, "account picture")
    page.locator("#avatar-file-" + page.evaluate("Maity.api.get('/me').then((m) => m.member.id)")).set_input_files(
        files=[{"name": "me.png", "mimeType": "image/png", "buffer": tiny_png(48, 48, (217, 102, 26))}]
    )
    expect(page.locator("main")).to_contain_text("Picture uploaded.")
    run.step("picture: the owner uploads a picture from the profile menu, it shows in the header, then removes it")
    face = page.locator("header .profile-menu img.avatar-img")
    expect(face).to_have_attribute("src", re.compile(r"^/api/v1/avatars/[A-Za-z0-9_-]+\?v="))
    page.wait_for_function("() => { const i = document.querySelector('header .profile-menu img.avatar-img'); return i && i.complete; }")
    assert page.evaluate("() => document.querySelector('header .profile-menu img.avatar-img').naturalWidth") > 0
    run.shot(page, "account-picture")
    page.get_by_role("button", name="Remove the upload", exact=True).click()
    expect(page.locator("main")).to_contain_text("Uploaded picture removed")
    expect(page.locator("header .profile-menu svg.avatar-svg")).to_be_visible()
    no_problems(run, "picture")


def dormant_step(run: Run, page: Page) -> None:
    """A dormant instance on the real hub (docs/api.md §6.17, tsk-3djwtefkr3yv): the owner puts the agent's
    instance to rest in the Manage row, it is said with its address and as the team's limit, and it wakes."""
    run.step("members: the owner puts an agent's instance to rest and wakes it")
    page.goto(f"{run.base}/owner/e2e-alpha/team")
    table = page.locator("table.members")
    row = table.locator("tr.member", has_text="E2E Agent")
    row.get_by_role("button", name="Manage E2E Agent").click()
    part = page.locator("tr.member-manage .member-dormant-part")
    rest = part.get_by_role("button", name=re.compile(r"^Put @e2e-agent#\S+ to rest$"))
    expect(rest).to_have_count(1)
    address = (rest.text_content() or "").removeprefix("Put ").removesuffix(" to rest")
    rest.click()
    status = page.locator("main section.view-team > .send-status")
    expect(status).to_contain_text(f"{address} is dormant.")
    expect(row).to_contain_text(f"dormant — ask {address} directly")
    # Its only instance: the whole team member rests (§6.12), with no end to name.
    expect(row).to_contain_text("Resting: every instance is dormant")
    run.a11y(page, "members, a dormant instance")
    run.shot(page, "members-dormant")
    part.get_by_role("button", name=f"Wake {address}", exact=True).click()
    expect(status).to_contain_text(f"{address} is awake.")
    expect(row).not_to_contain_text("dormant — ask")
    expect(row).not_to_contain_text("Resting:")
    no_problems(run, "dormant instance")


def change_password(run: Run, page: Page) -> None:
    """docs/api.md §2.1: the new password works, the old one does not, other sessions end."""
    run.step("account: change the password; another session ends; sign in with the new one")
    new_password = "e2e changed password, long enough"
    other = page.context.browser.new_context()
    second = other.new_page()
    second.goto(run.base + "/")
    second.locator("#login-email").fill(OWNER_EMAIL)
    second.locator("#login-password").fill(OWNER_PASSWORD)
    second.get_by_role("button", name="Sign in", exact=True).click()
    expect(second.locator("header .me")).to_contain_text("Owner")

    page.set_viewport_size({"width": 1280, "height": 900})
    page.locator("header").get_by_role("button", name=re.compile(r"^Your profile: ")).click()
    page.get_by_role("menuitem", name="Security", exact=True).click()
    expect(page).to_have_url(re.compile(r"/account/security$"))
    # The sessions (§2.6.5), Security's tab of their own: the list, this session in it.
    tabs = page.locator("main nav.security-tabs")
    tabs.get_by_role("link", name="Sessions", exact=True).click()
    expect(page).to_have_url(re.compile(r"/account/security/sessions$"))
    sessions = page.locator("section.sessions")
    expect(sessions.locator("li.session.current")).to_be_visible()
    tabs.get_by_role("link", name="Sign-in", exact=True).click()
    expect(page).to_have_url(re.compile(r"/account/security$"))
    page.locator("#password-current").fill("not the password")
    page.locator("#password-new").fill(new_password)
    page.locator("#password-repeat").fill(new_password)
    page.get_by_role("button", name="Change password", exact=True).click()
    expect(page.locator("#password-current-error")).to_have_text(
        "This is not your current password."
    )
    # The hub answered 400 invalid on purpose; that is not a failure of the page.
    run.problems = [p for p in run.problems if "/api/v1/auth/password answered 400" not in p]
    page.locator("#password-current").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Change password", exact=True).click()
    expect(page.locator("main form.project-form .send-status")).to_contain_text(
        "Password changed. Every other session of yours was signed out"
    )
    run.shot(page, "password-changed")
    run.a11y(page, "account")

    second.reload()
    expect(second.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
    other.close()

    page.locator("header").get_by_role("button", name=re.compile(r"^Your profile: ")).click()
    page.get_by_role("menuitem", name="Sign out", exact=True).click()
    page.locator("#login-email").fill(OWNER_EMAIL)
    page.locator("#login-password").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator("main")).to_contain_text("wrong")
    # The refused old password is the point of this step.
    run.problems = [p for p in run.problems if "/api/v1/auth/login answered 401" not in p]
    page.locator("#login-password").fill(new_password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator("header .me")).to_contain_text("Owner")
    no_problems(run, "change password")


def briefing_step(run: Run, page: Page, alpha: Path, agent_id: str) -> None:
    """The briefing (docs/api.md §3, §6.2)."""
    # The briefing is in the agent's row on Members (tsk-7v2snhk002ak).
    agents = page.locator("main .members-agents")
    page.reload()
    expect(agents).to_contain_text("@e2e-agent")
    agents.get_by_role("button", name="Manage E2E Agent", exact=True).click()
    expect(agents.locator("tr.member-manage")).to_be_visible()
    run.step("briefing: the owner writes it in the agent's row; the agent's resume carries it")
    agents.locator(".briefing").get_by_role("button", name=re.compile("briefing$")).click()
    page.locator(f"#briefing-{agent_id}").fill("You test the dashboard. First: the e2e card.")
    page.get_by_role("button", name="Save briefing", exact=True).click()
    expect(agents.locator(".briefing")).to_contain_text(
        "You test the dashboard. First: the e2e card."
    )
    run.a11y(page, "agents with a briefing")
    packet = json.loads(run.maity(alpha, "resume", "--json"))
    assert packet["membership"].get("briefing") == "You test the dashboard. First: the e2e card."
    no_problems(run, "briefing")


if __name__ == "__main__":
    sys.exit(main())
