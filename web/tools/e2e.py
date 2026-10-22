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
  "needs you" view (#/all) -> answered there.

Every browser console error, page error and failed API call (status >= 400,
apart from the signed-out session check) fails the run.

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
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

WEB = Path(__file__).resolve().parent.parent
OWNER = "owner"
OWNER_PASSWORD = "e2e owner password"
TIMEOUT_MS = 15_000  # one step in the browser; the feed reads every 5 s
COUNTS_MS = 25_000  # counts of other projects: /me is re-read every 15 s
WAIT_S = 60  # the agent's `maity wait`

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

    def step(self, text: str) -> None:
        print(f"\n== {text}", flush=True)

    def shot(self, page: Page, name: str) -> None:
        self.shots += 1
        path = self.artifacts / f"{self.shots:02d}-{name}.png"
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

    def api(self, clone: Path, method: str, path: str, body: object | None = None) -> dict:
        args = ["api", method, path]
        if body is not None:
            args[1:1] = ["--json", "-"]
        out = self.maity(clone, *args, stdin=None if body is None else json.dumps(body))
        return json.loads(out) if out.strip() else {}

    def clone(self, name: str) -> Path:
        path = self.work / name
        subprocess.run(["git", "init", "-q", str(path)], check=True, env=CLEAN_ENV)
        return path


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
    env = dict(
        CLEAN_ENV,
        MAITY_DATABASE_URL=f"sqlite:///{work / 'hub.db'}",
        MAITY_BIND=f"127.0.0.1:{port}",
        MAITY_PUBLIC_URL=base,
        MAITY_WEB_DIR=str(WEB),
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
        # Signed out, the page asks /auth/session first and expects 401.
        if resp.status >= 400 and not (
            resp.status == 401 and path.startswith("/api/v1/auth/session")
        ):
            run.problems.append(f"{resp.request.method} {path} answered {resp.status}")

    page.on("console", console)
    page.on("pageerror", lambda err: run.problems.append(f"page error: {err}"))
    page.on("response", response)
    page.on("requestfailed", request_failed)


def no_problems(run: Run, where: str) -> None:
    if run.problems:
        raise AssertionError(f"{where}:\n  " + "\n  ".join(run.problems))


def create_project(run: Run, page: Page, name: str, slug: str) -> None:
    expect(page.get_by_role("heading", name="Create a project", exact=True)).to_be_visible()
    page.get_by_label("Name").fill(name)
    expect(page.get_by_label("Slug")).to_have_value(slug)  # proposed from the name
    page.get_by_role("button", name="Create project", exact=True).click()
    expect(page).to_have_url(re.compile(rf"#/p/{slug}/agents$"))
    expect(page.locator("header .project")).to_have_text(name)


def join_line(run: Run, page: Page, slug: str, handle: str | None) -> tuple[str, str]:
    """Create a join line in the Join view; a new profile when handle is given."""
    page.locator("nav.views").get_by_role("link", name="Join an agent", exact=True).click()
    expect(page).to_have_url(re.compile(rf"#/p/{slug}/join$"))
    if handle:
        expect(page.locator("#join-handle")).to_be_visible()
        page.locator("#join-handle").fill(handle)
        page.locator("#join-display").fill("E2E Agent")
    else:
        # The existing profile is preselected.
        expect(page.locator("#join-agent")).not_to_have_value("")
    page.locator("#join-areas").fill("web/")
    page.get_by_role("button", name="Create join line", exact=True).click()
    line = page.locator(".paste-line")
    expect(line).to_be_visible()
    expect(page.locator("ul.joins li").first).to_contain_text("E2E Agent as member")
    if handle:
        # The new profile is offered and selected at once, without a reload.
        expect(page.locator("#join-agent option:checked")).to_contain_text(f"(@{handle})")
    words = shlex.split(line.inner_text())
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
                scenario(run, page)
            finally:
                browser.close()
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
    page.locator("#login-handle").fill(OWNER)
    page.locator("#login-password").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="No projects yet", exact=True)).to_be_visible()
    expect(page.locator("header .me")).to_contain_text("Owner")
    run.shot(page, "empty-state")
    no_problems(run, "sign-in")

    run.step("create a project")
    page.get_by_role("link", name="Create a project", exact=True).click()
    create_project(run, page, "E2E Alpha", "e2e-alpha")
    run.shot(page, "project-created")
    no_problems(run, "create a project")

    run.step("join line in the dashboard, the agent joins with the CLI")
    url, code = join_line(run, page, "e2e-alpha", "e2e-agent")
    run.shot(page, "join-line")
    alpha = run.clone("clone-alpha")
    out = run.maity(
        alpha, "join", url, "--code", code, "--harness", "e2e", "--model", "none", "--no-pointer"
    )
    agent_id = re.search(r"agt-[0-9a-z]+", out).group(0)
    print(f"   joined as {agent_id}")
    page.locator("nav.views").get_by_role("link", name="Agents", exact=True).click()
    expect(page).to_have_url(re.compile(r"#/p/e2e-alpha/agents$"))
    agents = page.locator("main section.view-agents")
    expect(agents).to_contain_text("@e2e-agent")
    expect(agents).to_contain_text("member")
    expect(agents).to_contain_text("Online")
    run.shot(page, "agent-joined")
    no_problems(run, "join")

    run.step("the agent claims a card; the open board offers a reload")
    page.locator("nav.views").get_by_role("link", name="Board", exact=True).click()
    expect(page).to_have_url(re.compile(r"#/p/e2e-alpha/board$"))
    # The view has read the event head once its columns are drawn; what the
    # agent does from here on is offered as a reload.
    expect(page.get_by_role("region", name="Proposed")).to_be_visible()
    task = run.api(
        alpha, "POST", "/projects/e2e-alpha/tasks", {"title": "E2E card", "area": "web/"}
    )
    run.api(alpha, "POST", f"/projects/e2e-alpha/tasks/{task['id']}/claim", {})
    reload = page.locator(".notice").get_by_role("button", name="Reload", exact=True)
    expect(page.get_by_text("The board changed.")).to_be_visible()
    run.shot(page, "board-changed")
    reload.click()
    card = board_card(page, "E2E card")
    expect(card).to_contain_text("Claimed by")
    expect(card).to_contain_text("E2E Agent")
    run.shot(page, "card-claimed")
    no_problems(run, "board")

    run.step("the agent asks, blocking its card; its maity wait runs")
    page.locator("nav.views").get_by_role("link", name="Inbox", exact=True).click()
    expect(page.get_by_text("Nothing waits for you.")).to_be_visible()
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
        ["maity", "wait", "--timeout", str(WAIT_S)],
        cwd=alpha,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        expect(
            page.get_by_text(re.compile(r"What waits for you changed \(1 open\)"))
        ).to_be_visible()
        expect(page.locator("nav.switcher a", has_text="E2E Alpha").locator(".count")).to_have_text(
            "1"
        )
        run.shot(page, "inbox-notice")
        page.get_by_role("button", name="Reload the list", exact=True).click()
        entry = page.locator("li.entry.current")
        expect(entry).to_contain_text("Ship the e2e card?")
        expect(entry).to_contain_text("The test asks this.")
        run.shot(page, "inbox-request")
        page.locator("nav.views").get_by_role("link", name="Board", exact=True).click()
        expect(board_card(page, "E2E card")).to_contain_text(request_id)
        run.shot(page, "card-blocked")

        run.step("the owner answers in the inbox; the agent's wait wakes")
        page.locator("nav.views").get_by_role("link", name="Inbox", exact=True).click()
        page.locator("li.entry.current").get_by_role("button", name="Ship it", exact=True).click()
        expect(page.get_by_text("Nothing waits for you.")).to_be_visible()
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
    page.locator("nav.views").get_by_role("link", name="Board", exact=True).click()
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
    expect(page).to_have_url(re.compile(r"#/p/e2e-alpha/"))
    expect(page.locator("header .project")).to_have_text("E2E Alpha")
    expect(page.locator("li.entry.current")).to_contain_text("Which colour for alpha?")
    run.shot(page, "switched-to-alpha")
    no_problems(run, "switcher")

    run.step("everything waiting, across projects (#/all)")
    switcher.get_by_role("link", name=re.compile("^All projects")).click()
    expect(page).to_have_url(re.compile(r"#/all$"))
    entries = page.locator("li.entry")
    expect(entries).to_have_count(2)
    expect(entries.nth(0)).to_contain_text("E2E Alpha")  # high before normal
    expect(entries.nth(0)).to_contain_text("Which colour for alpha?")
    expect(entries.nth(1)).to_contain_text("E2E Beta")
    run.shot(page, "all-projects")
    current = page.locator("li.entry.current")
    current.locator("textarea").fill("Blue.")
    current.get_by_role("button", name="Send", exact=True).click()
    expect(page.locator("li.entry.current")).to_contain_text("May the beta agent tag 0.1.0?")
    page.locator("li.entry.current").get_by_role("button", name="go", exact=True).click()
    expect(page.get_by_text("Nothing waits for you.")).to_be_visible()
    expect(switcher.locator(".count")).to_have_count(0)
    run.shot(page, "all-answered")
    replies = run.maity(beta, "resume")
    got = json.loads(replies)["requests"]["answered_since_cursor"]
    assert [r.get("answer", {}).get("reply_id") for r in got] == ["go"], got
    no_problems(run, "all projects")

    run.step("phone width: no view scrolls sideways")
    run.maity(alpha, "ask", "Phone check?", "--to", "human", "--class", "consent")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{run.base}/#/p/e2e-alpha/inbox")
    # Each view through its tab: the tab row scrolls sideways on its own, so
    # every tab has to stay reachable there.
    tabs = (
        ("inbox", "Inbox"),
        ("board", "Board"),
        ("agents", "Agents"),
        ("org", "Organisation"),
        ("join", "Join an agent"),
    )
    for view, tab in tabs:
        page.locator("nav.views").get_by_role("link", name=tab, exact=True).click()
        expect(page.locator(f"main section.view-{view}")).to_be_visible()
        if view == "inbox":
            expect(page.locator("li.entry.current")).to_contain_text("Phone check?")
        expect(page.locator("main .send-status.failed, main .error")).to_have_count(0)
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert width[0] <= width[1], f"#/p/e2e-alpha/{view} is {width[0]} px wide at {width[1]} px"
        # The current tab and project chip are scrolled into their rows.
        hidden = [cls for cls, shown in page.evaluate(CURRENT_SHOWN_JS) if not shown]
        assert not hidden, f"{view}: the current entry of nav.{hidden} is scrolled out of view"
        # Revoke keeps its label on one line: one line box for its text.
        lines = page.evaluate(ONE_LINE_JS, ".credentials button, .joins button")
        assert all(n == 1 for n in lines), f"{view}: a Revoke label wraps ({lines} lines)"
        if view == "agents":
            assert lines, "agents: no Revoke button to measure"
        run.shot(page, f"phone-{view}")
    no_problems(run, "phone width")


if __name__ == "__main__":
    sys.exit(main())
