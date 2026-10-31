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

  pip install -e hub -e cli playwright==1.64.0
  python -m playwright install chromium
  python web/tools/e2e.py --artifacts /path/to/screenshots

Exit 0 = every step passed. The hub is the one process this script starts
and it is stopped by its own PID; nothing else is touched.
"""

from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright

WEB = Path(__file__).resolve().parent.parent
OWNER = "owner"
OWNER_PASSWORD = "e2e owner password"
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

# The caller's own MAITY_* settings (a state dir, a forge token) never reach
# the throwaway hub or the scratch clones.
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("MAITY_")}


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
        """axe-core on the page as it stands, in each pass; back to 1280 px, light, after."""
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
        page.set_viewport_size({"width": 1280, "height": 900})
        page.emulate_media(color_scheme="light")
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


def start_hub(work: Path, logs: Path, port: int) -> subprocess.Popen:
    """Migrate, create the owner and serve; every output goes to logs/hub.log."""
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
    )
    log_path = logs / "hub.log"
    with open(log_path, "w") as log:  # the hub keeps its own copy of the descriptor
        for args, stdin in (
            (["migrate"], None),
            (
                ["owner", "create", "--handle", OWNER, "--display-name", "Owner"],
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


def join_line(
    run: Run,
    page: Page,
    slug: str,
    handle: str | None,
    display: str = "E2E Agent",
    role: str = "coder",
) -> tuple[str, str]:
    """Create a join line in the join panel on Agents; a new profile when handle is given."""
    view_tab(page, "Agents").click()
    expect(page).to_have_url(re.compile(rf"/{OWNER}/{slug}/agents$"))
    # A project without an agent of one's own opens the panel itself;
    # otherwise the button at the head does. The panel is read beside the list, after it: wait
    # for one of the two, since the count line is drawn before either, and an
    # instant look could see neither and click a button that stays hidden.
    panel = page.locator(".join-panel")
    add = page.get_by_role("button", name="+ Add an agent", exact=True)
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
    page.locator("#join-role").select_option(role)
    page.locator("#join-areas").fill("web/")
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
    assert words[:2] == ["maity", "join"] and words[3] == "--code", words
    return words[2], words[4]


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
                except Exception:
                    report_failure(list(run.recent), base, artifacts)
                    # What the page itself said before the step failed: its errors explain more than a missing element.
                    for problem in run.problems:
                        print("  page: " + problem)
                    raise
                fixture_views(run, browser)
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
    run.shot(page, "sign-in")
    run.a11y(page, "sign-in")
    page.locator("#login-handle").fill(OWNER)
    page.locator("#login-password").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="No projects yet", exact=True)).to_be_visible()
    expect(page.locator("header .me")).to_contain_text("Owner")
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
    view_tab(page, "Members").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/members$"))
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
    )
    request_id = re.search(r"req-[0-9a-z]+", out).group(0)
    print(f"   asked {request_id}")
    run.maity(alpha, "resume")  # the wait starts after the agent's own events
    wait = subprocess.Popen(
        ["maity", "wait", "--one", "--timeout", str(WAIT_S)],
        cwd=alpha,
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
        free.fill("")
        page.locator("li.entry.current").get_by_role("button", name="Ship it", exact=True).click()
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
    assert (event.get("payload") or {}).get("answer", {}).get("reply_id") == "o1", event
    view_tab(page, "Board").click()
    card = board_card(page, "E2E card")
    expect(card).to_contain_text("Claimed by")
    expect(card).not_to_contain_text(request_id)
    run.shot(page, "card-unblocked")
    no_problems(run, "answer")

    run.step("a second project, the same agent joins it and asks")
    page.locator("nav.switcher").get_by_role("link", name="+ New project", exact=True).click()
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
    chat_pause_state(run, page, alpha, agent_id)
    group_chat_form_step(run, page)
    direct_removal_step(run, page, agent_id)
    attachments_step(run, page, agent_id)
    members_step(run, page)
    my_settings_step(run, page)
    invitations_step(run, page)
    message_step(run, page, alpha, agent_id)
    release_contract(run, page, alpha, agent_id, task["id"])
    signing_step(run, page, alpha, agent_id)
    images_step(run, page, alpha)
    board_cards_step(run, page)

    why_step(run, page, alpha)
    runners_step(run, page)
    isolate_step(run, page)

    run.step("phone width: no view scrolls sideways")
    run.maity(alpha, "ask", "Phone check?", "--to", "human", "--class", "consent")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    # The text beside the logo is hidden from sight only: still in the page for a screen reader.
    expect(page.locator("header .bar > .project")).to_have_count(1)
    box = page.locator("header .bar > .project").bounding_box()
    assert box and box["width"] <= 1 and box["height"] <= 1, f"the header's text beside the logo shows at 390 px: {box}"
    # Each view through its tab: the tab row scrolls sideways on its own, so
    # every tab has to stay reachable there.
    tabs = (
        ("inbox", "Inbox"),
        ("board", "Board"),
        ("overview", "Overview"),
        ("members", "Members"),
        ("agents", "Agents"),
    )
    # Why, where the hub offers it (its 409 ktw_not_configured is expected here).
    if view_tab(page, "Why").count():
        tabs += (("why", "Why"),)
    tabs += (("runners", "Runners"),)
    for view, tab in tabs:
        view_tab(page, tab).click()
        expect(page.locator(f"main section.view-{view}")).to_be_visible()
        if view == "inbox":
            expect(page.locator("li.entry.current")).to_contain_text("Phone check?")
        expect(page.locator("main .send-status.failed, main .error, main .page-failed")).to_have_count(0)
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert width[0] <= width[1], f"/owner/e2e-alpha/{view} is {width[0]} px wide at {width[1]} px"
        # The views row is wider than 390 px; it shows a fade where more tabs are.
        cue = page.locator("nav.views").get_attribute("class") or ""
        assert "more-after" in cue or "more-before" in cue, f"{view}: no scroll cue ({cue!r})"
        # The current tab and project chip are scrolled into their rows.
        hidden = [cls for cls, shown in page.evaluate(CURRENT_SHOWN_JS) if not shown]
        assert not hidden, f"{view}: the current entry of nav.{hidden} is scrolled out of view"
        # Revoke keeps its label on one line: one line box for its text.
        lines = page.evaluate(ONE_LINE_JS, ".credentials button, .seat-actions button")
        assert all(n == 1 for n in lines), f"{view}: a Revoke label wraps ({lines} lines)"
        run.shot(page, f"phone-{view}")
        run.problems = [p for p in run.problems if "/keep-the-why answered 409" not in p]
    # The create form: its preset select has long option labels.
    page.locator("nav.switcher").get_by_role("link", name="+ New project", exact=True).click()
    expect(page.locator("main section.view-new")).to_be_visible()
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1], f"/new is {width[0]} px wide at {width[1]} px"
    run.shot(page, "phone-new")
    run.a11y(page, "create a project")
    # The Runners view: the pairing form and its long install line; reached from the gear menu.
    page.locator("header").get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("menuitem", name="Runners", exact=True).click()
    expect(page.locator("main section.view-runners")).to_be_visible()
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width[0] <= width[1], f"/runners is {width[0]} px wide at {width[1]} px"
    run.shot(page, "phone-runners")
    no_problems(run, "phone width")

    users_step(run, page)
    registration_admin_step(run, page)
    reports_admin_step(run, page, alpha)
    forge_access_step(run, page)
    landing_json_step(run, page)
    join_expiry_step(run, page)
    change_password(run, page)
    picture_step(run, page)


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
    page.set_viewport_size({"width": 390, "height": 844})
    box = panel.bounding_box()
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert box and box["width"] >= 300 and width[0] <= width[1], f"the card's panel at 390 px: {box}, page {width}"
    run.shot(page, "card-panel-phone")
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
    page.set_viewport_size({"width": 1280, "height": 900})
    no_problems(run, "global chat")
    # Back where the chat step left the page: the project's chat with the agent.
    page.goto(f"{run.base}/owner/e2e-alpha/chat/{agent_id}")
    expect(page.get_by_role("heading", name="Chat with E2E Agent", exact=True)).to_be_visible()

    run.step("pause: the owner pauses the agent; the agent cannot lift it itself")
    # The pause is in the agent's row on Members (tsk-7v2snhk002ak), once.
    view_tab(page, "Members").click()
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
    view_tab(page, "Members").click()
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
    page.goto(f"{run.base}/owner/e2e-alpha/members")
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
    page.get_by_role("button", name="Remove the uploaded logo", exact=True).click()
    expect(page.locator("header .bar .project-mark.monogram")).to_have_text("EA")
    expect(page.locator("#project-panel")).to_contain_text("Uploaded logo removed")
    project_settings(page)
    assert run.api(alpha, "GET", "/projects/owner/e2e-alpha")["logo"]["available"] is False
    no_problems(run, "images")


def fixture_views(run: Run, browser) -> None:
    """Views whose richer states the hub here cannot reach, in fixture mode (file://):
    the Why view with the published maity.dev family, one part failing, the root unreadable."""
    run.step("fixtures: the Why view as the published family shows it, and its failure states")
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    index = (WEB / "index.html").as_uri()
    try:
        for query, name, says in (
            ("", "why", "1 entry needs attention · 71 entries in 4 parts of the project"),
            (
                "?ktw=member_failed",
                "why-part-failed",
                "Could not be read: its state.json did not answer in time",
            ),
            ("?ktw=unavailable", "why-root-unreadable", "Shown is its last good read"),
        ):
            page.goto(f"{index}{query}#/maintainer/maity/why")
            expect(page.locator("main section.view-why")).to_contain_text(says)
            assert not errors, errors  # the page's own errors, before axe runs
            run.shot(page, f"fixtures-{name}")
            run.a11y(page, f"fixtures: {name}")
            # axe reads stylesheets by XHR, which file:// refuses; that is axe's, not the page's.
            errors.clear()
        # The family at phone width: the summary, the entries, the table that scrolls.
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{index}#/maintainer/maity/why")
        expect(page.locator("main section.view-why")).to_contain_text("1 entry needs attention")
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert width[0] <= width[1], f"the Why view is {width[0]} px wide at {width[1]} px"
        assert not errors, errors
        run.shot(page, "fixtures-why-phone")
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
    page.goto(f"{run.base}/owner/e2e-alpha/members")
    # A hash-only goto returns before the page renders anew, and that render
    # replaces the header: a menu opened on the old one is gone mid-click.
    expect(page.locator("main section.view-members")).to_be_visible()
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


def board_cards_step(run: Run, page: Page) -> None:
    """Cards from the board (docs/api.md §6.4): create, move by menu and by dragging."""
    run.step("board: the owner writes a card, moves it with the menu, drags it to a refused and an allowed column")
    page.goto(f"{run.base}/owner/e2e-alpha/board")
    page.get_by_role("button", name="New card", exact=True).click()
    page.locator("#new-card-title").fill("E2E: a card from the board")
    page.locator("#new-card-area").fill("web/")
    page.locator("#new-card-status").select_option("proposed")
    run.a11y(page, "board, new card")
    page.locator("form.new-card").get_by_role("button", name="Create card", exact=True).click()
    view = page.locator("main section.view-board")
    expect(view.locator(".send-status").first).to_contain_text("created in proposed")
    card = page.locator("article.card", has_text="E2E: a card from the board")
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
    board_order_step(run, page)
    overview_step(run, page)
    ticker_step(run, page)
    notifications_step(run, page)


def board_order_step(run: Run, page: Page) -> None:
    """Card order within a column (docs/api.md §6.4): Place and dragging, by tasks:admin."""
    page.goto(f"{run.base}/owner/e2e-alpha/board")
    view = page.locator("main section.view-board")
    for title in ("E2E order: first", "E2E order: second"):
        page.get_by_role("button", name="New card", exact=True).click()
        page.locator("#new-card-title").fill(title)
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
    page.goto(f"{run.base}/owner/e2e-alpha/members")
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
    page.goto(f"{run.base}/owner/e2e-alpha/members")
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
    # In a private chat an @name tells nobody: the hub resolves nothing there.
    wait = run.wait_start(alpha)
    page.goto(f"{run.base}/owner/e2e-alpha/chat/{agent_id}")
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
    page.goto(f"{run.base}/owner/e2e-alpha/members")
    view_tab(page, "Runners").click()
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
    detach()
    expect(view).to_contain_text("No runner is allowed in this project yet.")
    no_problems(run, "project runners")


def notifications_step(run: Run, page: Page) -> None:
    """Notifications, stage 1 (docs/api.md §18.2): the bell, its list, its keyboard."""
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    expect(page.locator("main section.view-inbox")).to_be_visible()
    bell = page.locator("header button.bell")
    # The header's right block: Chat, the Lead button where there is a lead to reach, Notifications,
    # the gear, the profile, in one row also on a phone.
    order = page.evaluate("Array.from(document.querySelectorAll('header .me > *')).map((e) => e.className)")
    lead = 1 if len(order) > 1 and "lead-button" in order[1] else 0
    assert len(order) == 4 + lead and "chat-button" in order[0] and "bell-box" in order[1 + lead], f"header order: {order}"
    page.set_viewport_size({"width": 390, "height": 844})
    # One row: every button's vertical middle within the others' height (a pixel of alignment is no wrap).
    boxes = page.evaluate("Array.from(document.querySelectorAll('header .me > *')).map((e) => { const r = e.getBoundingClientRect(); return [r.top, r.bottom]; })")
    middles = [(top + bottom) / 2 for top, bottom in boxes]
    assert all(top <= m <= bottom for top, bottom in boxes for m in middles), f"the header's four buttons wrap at 390 px: {boxes}"
    page.set_viewport_size({"width": 1280, "height": 900})
    run.step("chats: the Chat button opens every chat across the projects")
    page.locator("header a.chat-button").click()
    expect(page).to_have_url(re.compile(r"/chats$"))
    expect(page.locator("main section.view-chats h2")).to_have_text("Chats")
    run.a11y(page, "chats across projects")
    run.step("all projects: Inbox and Chats are its two pages; Inbox leads back to the requests")
    pages = page.locator("header nav.views a")
    expect(pages).to_have_count(2)
    expect(pages.nth(1)).to_have_attribute("aria-current", "page")
    expect(page.locator("header nav.switcher a[href='/all']")).to_have_attribute("aria-current", "page")
    pages.nth(0).click()
    expect(page).to_have_url(re.compile(r"/all$"))
    expect(page.locator("header nav.views a").nth(0)).to_have_attribute("aria-current", "page")
    expect(page.locator("main section.view-all")).to_be_visible()
    run.shot(page, "all-projects-pages")
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
    no_problems(run, "notifications")


def why_step(run: Run, page: Page, alpha: Path) -> None:
    """The Keep the Why export (docs/api.md §11.3)."""
    project = run.api(alpha, "GET", "/projects/owner/e2e-alpha")
    page.goto(f"{run.base}/owner/e2e-alpha/members")
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
    run.problems = [p for p in run.problems if "/keep-the-why answered 409" not in p]
    run.shot(page, "why-not-configured")
    run.a11y(page, "why, not configured")
    no_problems(run, "why")


def release_contract(run: Run, page: Page, alpha: Path, agent_id: str, card_id: str) -> None:
    run.step("release: a reviewer joins and opens a release; the hub has no forge probe here")
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    url, code = join_line(run, page, "e2e-alpha", "e2e-reviewer", "E2E Reviewer", "reviewer")
    rev = run.clone("clone-reviewer")
    run.maity(
        rev, "join", url, "--code", code, "--harness", "e2e", "--model", "none", "--no-pointer"
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
    page.goto(f"{run.base}/owner/e2e-alpha/members")
    page.locator("main .members-agents").get_by_role("button", name="Manage E2E Agent", exact=True).click()
    expect(page.locator("main tr.member-manage")).to_contain_text("(bearer token)")
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


def landing_json_step(run: Run, page: Page) -> None:
    """Instance administration → Landing page (docs/api.md §16.7, tsk-36d575f5yybz): a draft
    imported as JSON, checked by the hub's preview call, saved only by Save."""
    me = page.request.get(f"{run.base}/api/v1/me").json()["member"]
    if not me.get("instance_admin"):
        return
    run.step("landing page: the admin imports a page as JSON, the hub checks it, then it is saved")
    page.goto(f"{run.base}/admin")
    page.locator("nav.admin-nav").get_by_role("button", name="Landing page", exact=True).click()
    io = page.locator("details.lp-json")
    io.locator("summary").click()
    # No footer, as the prepared landing V3 file: the editor's footer stays (§16.7, #808's review).
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
    section = page.locator("section.admin-section[aria-label='Landing page']")
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
    # The prepared landing V3 itself (tsk-k7pwrzs8vb8k): the real hub's check refuses nothing.
    v3 = (WEB / "tools" / "landing-v3-complete.json").read_text(encoding="utf-8")
    page.locator("#lp-json").fill(v3)
    page.once("dialog", lambda d: d.accept())
    io.get_by_role("button", name="Load into the editor", exact=True).click()
    expect(section.locator(".send-status").first).to_contain_text("checked by the hub")
    expect(page.locator("li.lp-section")).to_have_count(len(json.loads(v3)["pages"][json.loads(v3)["default_language"]]["sections"]))
    run.shot(page, "landing-json")
    no_problems(run, "landing JSON")


def reports_admin_step(run: Run, page: Page, alpha: Path) -> None:
    """Instance administration → Reports (docs/api.md §16.8): an agent reports a card; the admin
    reads the report and its snapshot as text, and resolves it with hide and a note."""
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
    # The admin is told (§16.8), and the item names the report the bell links to (§18.2).
    told = page.request.get(f"{run.base}/api/v1/me/notifications?limit=20").json()["items"]
    assert any((i.get("target") or {}) == {"type": "report", "id": filed["id"]} for i in told), told
    # Where the report_open notification leads (§18.2): the section, that report opened.
    page.goto(f"{run.base}/admin/reports/{filed['id']}")
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


def isolate_step(run: Run, page: Page) -> None:
    """Isolation (docs/api.md §6.2) on the real hub. Last of the agent's steps: isolating
    releases its claims, which the steps before rely on, and lifting does not bring them back."""
    run.step("members: the owner isolates the agent with a reason, sees the badge, and lifts the isolation")
    page.goto(f"{run.base}/owner/e2e-alpha/members")
    agents = page.locator("table.members").nth(1)
    row = agents.locator("tr.member", has_text="E2E Agent")
    row.get_by_role("button", name="Manage E2E Agent").click()
    manage = page.locator("tr.member-manage")
    manage.locator("input[id^=member-isolate-]").fill("e2e: isolated on purpose")
    asked = []
    page.once("dialog", lambda d: (asked.append(d.message), d.accept()))
    manage.get_by_role("button", name="Isolate", exact=True).click()
    expect(page.locator("main section.view-members > .send-status")).to_contain_text("E2E Agent is isolated.")
    assert asked and asked[0].startswith("Isolate E2E Agent?"), asked
    expect(row.locator(".badge.member-isolated")).to_have_text("Isolated")
    expect(row.locator(".badge.member-isolated")).to_have_attribute("title", "Isolated: e2e: isolated on purpose")
    expect(manage.locator(".member-isolate")).to_contain_text("e2e: isolated on purpose")
    run.a11y(page, "members, an isolated agent")
    run.shot(page, "member-isolated")
    manage.get_by_role("button", name="Lift isolation", exact=True).click()
    expect(page.locator("main section.view-members > .send-status")).to_contain_text("The isolation of E2E Agent is lifted.")
    expect(row.locator(".badge.member-isolated")).to_have_count(0)
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


def invitations_step(run: Run, page: Page) -> None:
    """Invitations (docs/api.md §3.4) on the real hub: the owner invites from Members; a browser
    without a session opens the link, signs in with it as next and comes back; joining is refused
    in the hub's words (the only human there is a member already: without mail the e2e hub makes
    no second account); revoked, the link is one uniform answer."""
    run.step("invitations: the owner invites a person from Members; the link is shown once")
    page.goto(f"{run.base}/owner/e2e-alpha/members")
    box = page.locator("section.invitations")
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
    run.a11y(page, "members, an invitation created")

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
        guest.locator("#login-handle").fill(OWNER)
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
    run.a11y(page, "my settings")
    page.locator("#my-nl-default").check()
    page.locator("form.my-settings").get_by_role("button", name="Save", exact=True).click()
    expect(effective).to_have_text("Applies now: 45 minutes, your default.")
    no_problems(run, "my settings")


def members_step(run: Run, page: Page) -> None:
    """Members (docs/api.md §6.2): humans and agents; the owner changes an agent's role and back."""
    run.step("members: the owner and the agent in one list; an agent's role changed and back")
    page.goto(f"{run.base}/owner/e2e-alpha/inbox")
    view_tab(page, "Members").click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/members$"))
    humans, agents = page.locator("table.members").nth(0), page.locator("table.members").nth(1)
    expect(humans.locator("tr.member")).to_have_count(1)
    expect(humans.locator("tr.member")).to_contain_text("owner")
    row = agents.locator("tr.member", has_text="E2E Agent")
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
    # A member's page (#6484, read only): the agent's name leads there; header, Actions, tabs.
    row.locator("a.member-ref").first.click()
    expect(page).to_have_url(re.compile(r"/owner/e2e-alpha/members/agt-[0-9a-z]+$"))
    head = page.locator(".member-head")
    expect(head).to_contain_text("E2E Agent")
    expect(head.locator(".member-pill", has_text="agent of")).to_have_count(1)
    expect(page.locator("nav.member-tabs a")).to_have_count(4)
    head.get_by_role("button", name="Actions for E2E Agent").click()
    expect(head.get_by_role("menuitem", name="Manage on Members")).to_be_visible()
    page.keyboard.press("Escape")
    run.a11y(page, "member page")
    page.locator("nav.member-tabs").get_by_role("link", name="Sessions & credentials").click()
    expect(page.locator(".member-section")).to_contain_text("Instances")
    page.goto(f"{run.base}/owner/e2e-alpha/members")
    expect(agents.locator("tr.member", has_text="E2E Agent")).to_be_visible()
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
    expect(page.locator("main section.view-members > .send-status")).to_contain_text("Saved for E2E Agent: reports to.")
    page.locator("main nav.team-tabs").get_by_role("link", name="Organisation", exact=True).click()
    owner_node = page.locator(".org-tree > li", has=page.locator(".org-node strong", has_text="Owner"))
    expect(owner_node.locator("ul .org-node")).to_contain_text("E2E Agent")
    view_tab(page, "Members").click()
    # The owner reporting to the agent would close a circle: refused before it is sent.
    humans.get_by_role("button", name="Manage Owner").click()
    owner_manage = page.locator("tr.member-manage")
    owner_manage.locator("select[id^=member-reports-]").select_option(label="E2E Agent (@e2e-agent)")
    owner_manage.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.locator("main section.view-members > .send-status")).to_contain_text("That would close a circle")
    humans.get_by_role("button", name="Done managing Owner").click()
    row.get_by_role("button", name="Manage E2E Agent").click()
    manage.locator("select[id^=member-reports-]").select_option("")
    manage.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.locator("main section.view-members > .send-status")).to_contain_text("Saved for E2E Agent: reports to.")
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
    """docs/api.md §6.10: the owner's picture, from the profile menu; uploaded where the hub has it."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.locator("header").get_by_role("button", name=re.compile(r"^Your profile: ")).click()
    page.get_by_role("menuitem", name="Picture", exact=True).click()
    expect(page).to_have_url(re.compile(r"/account/picture$"))
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


def change_password(run: Run, page: Page) -> None:
    """docs/api.md §2.1: the new password works, the old one does not, other sessions end."""
    run.step("account: change the password; another session ends; sign in with the new one")
    new_password = "e2e changed password, long enough"
    other = page.context.browser.new_context()
    second = other.new_page()
    second.goto(run.base + "/")
    second.locator("#login-handle").fill(OWNER)
    second.locator("#login-password").fill(OWNER_PASSWORD)
    second.get_by_role("button", name="Sign in", exact=True).click()
    expect(second.locator("header .me")).to_contain_text("Owner")

    page.set_viewport_size({"width": 1280, "height": 900})
    page.locator("header").get_by_role("button", name=re.compile(r"^Your profile: ")).click()
    page.get_by_role("menuitem", name="Change password", exact=True).click()
    expect(page).to_have_url(re.compile(r"/account$"))
    # The sessions (§2.6.5): the list, this session in it.
    sessions = page.locator("section.sessions")
    expect(sessions.locator("li.session.current")).to_be_visible()
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
    page.locator("#login-handle").fill(OWNER)
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
