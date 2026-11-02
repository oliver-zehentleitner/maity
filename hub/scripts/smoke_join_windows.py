#!/usr/bin/env python3
"""Run the PowerShell join lines (docs/api.md §3.2) in Windows PowerShell 5.1 and PowerShell 7.

Against a fresh hub on loopback, in each shell:
  1. `maity` missing, the install fails: no join, and the code in no output;
  2. `maity` missing, the install works: it installs and joins, from pipx's default bin
     directory and from PIPX_BIN_DIR;
  3. `maity` there, the install line would fail: it is not run, and the line joins;
  4. `maity join <url> --code <code>` alone, with `maity` on the PATH.

The install line installs this checkout's CLI, not the published one. Needs Windows, `pipx`, `git`,
both shells, and the hub in the running Python; `maity` must not be on the PATH yet.
Usage: python hub/scripts/smoke_join_windows.py    exit 0 = every line did what it should
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from maity_hub import join_line

PORT = 18766
HUB = f"http://127.0.0.1:{PORT}"
PROJECT = f"{HUB}/api/v1/projects/owner/smoke"
PASSWORD = "smoke owner password"
SHELLS = ("powershell", "pwsh")
CLI = Path(__file__).resolve().parents[2] / "cli"
GOOD_INSTALL = f"pipx install {CLI}"
BAD_INSTALL = f"pipx install {CLI / 'no-such-directory'}"
JOINED = "joined owner/smoke as agt-"
# The hub is not made for Windows: `avatar_decode` imports `resource` at the top. This smoke test
# uploads no avatar, so an empty module lets the rest of the hub start.
RUN_HUB = (
    "import sys, types; sys.modules['resource'] = types.ModuleType('resource'); "
    "from maity_hub.cli import main; sys.exit(main(sys.argv[1:]))"
)


class Smoke:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.count = 0
        jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.csrf = ""
        self.env = dict(os.environ, PIPX_HOME=str(work / "pipx"))
        self.env.pop("PIPX_BIN_DIR", None)
        self.current_env = self.env

    def human(self, url: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            url,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-CSRF-Token": self.csrf},
        )
        with self.http.open(request, timeout=30) as answer:
            text = answer.read()
        return json.loads(text) if text else None

    def login(self) -> None:
        self.human(f"{HUB}/api/v1/auth/login", {"handle": "owner", "password": PASSWORD})
        self.csrf = self.human(f"{HUB}/api/v1/auth/session")["csrf_token"]
        self.human(f"{HUB}/api/v1/projects", {"slug": "smoke", "name": "Smoke test"})

    def new_join(self) -> tuple[str, str, str]:
        self.count += 1
        handle = f"agent-{self.count}"
        answer = self.human(
            f"{PROJECT}/joins",
            {
                "agent": {"handle": handle, "display_name": handle},
                "trust": "member",
                "role": "coder",
                "areas": [f"{handle}/"],
            },
        )
        return handle, answer["join_url"], answer["code"]

    def is_member(self, handle: str) -> bool:
        return any(m["handle"] == handle for m in self.human(f"{PROJECT}/members")["items"])

    def paste(
        self, name: str, shell: str, line: str, code: str, env: dict[str, str]
    ) -> tuple[str, int]:
        """Run the line as one command of a fresh shell, in a new clone; never print the code."""
        clone = self.work / f"clone-{self.count}"
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        encoded = base64.b64encode(line.encode("utf-16-le")).decode()
        done = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=clone,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        print(f"== {shell}: {name}: exit {done.returncode}")
        print(done.stdout.replace(code, "<code>"))
        return done.stdout, done.returncode

    def pipx_clean(self, env: dict[str, str]) -> None:
        subprocess.run(["pipx", "uninstall", "maity"], env=env, capture_output=True)
        if shutil.which("maity", path=env.get("PATH")):
            raise SystemExit("smoke: maity is on the PATH before a line that expects it missing")

    def expect_join(self, name: str, shell: str, line: str, handle: str, code: str) -> None:
        output, _ = self.paste(name, shell, line, code, self.current_env)
        if JOINED not in output or not self.is_member(handle):
            raise SystemExit(f"smoke: {shell}: {name}: the line did not join")

    def run_shell(self, shell: str) -> None:
        default_bin = Path.home() / ".local" / "bin"
        own_bin = self.work / f"bin-{shell}"
        self.current_env = self.env
        self.pipx_clean(self.env)

        handle, url, code = self.new_join()
        line = join_line.windows(BAD_INSTALL, url, code)
        assert line is not None
        name = "maity missing, the install fails"
        output, _ = self.paste(name, shell, line, code, self.env)
        if code in output:
            raise SystemExit(f"smoke: {shell}: {name}: the code is in the output")
        if JOINED in output or self.is_member(handle):
            raise SystemExit(f"smoke: {shell}: {name}: the line joined all the same")

        handle, url, code = self.new_join()
        line = join_line.windows(GOOD_INSTALL, url, code)
        assert line is not None
        self.expect_join("maity missing, default bin directory", shell, line, handle, code)

        handle, url, code = self.new_join()
        line = join_line.windows(BAD_INSTALL, url, code)
        assert line is not None
        self.expect_join("maity there, install not run", shell, line, handle, code)

        handle, url, code = self.new_join()
        self.current_env = dict(self.env, PATH=f"{default_bin}{os.pathsep}{self.env['PATH']}")
        self.expect_join("only join", shell, f"maity join {url} --code {code}", handle, code)
        self.current_env = self.env
        self.pipx_clean(self.env)

        self.current_env = dict(self.env, PIPX_BIN_DIR=str(own_bin))
        handle, url, code = self.new_join()
        line = join_line.windows(GOOD_INSTALL, url, code)
        assert line is not None
        self.expect_join("maity missing, PIPX_BIN_DIR", shell, line, handle, code)
        self.pipx_clean(self.current_env)


def wait_for_hub() -> None:
    for _ in range(150):
        try:
            with urllib.request.urlopen(f"{HUB}/api/v1/health", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    raise SystemExit("smoke: the hub did not come up")


def main() -> int:
    for tool in (*SHELLS, "pipx", "git"):
        if not shutil.which(tool):
            raise SystemExit(f"smoke: {tool} is not on this machine")
    work = Path(tempfile.mkdtemp())
    hub_env = dict(
        os.environ,
        MAITY_DATABASE_URL=f"sqlite:///{(work / 'hub.db').as_posix()}",
        MAITY_BIND=f"127.0.0.1:{PORT}",
        MAITY_PUBLIC_URL=HUB,
    )
    hub = [sys.executable, "-c", RUN_HUB]
    subprocess.run([*hub, "migrate"], env=hub_env, check=True, capture_output=True)
    subprocess.run(
        [*hub, "owner", "create", "--handle", "owner", "--display-name", "Owner"],
        env=hub_env,
        check=True,
        input=f"{PASSWORD}\n",
        text=True,
    )
    log = (work / "serve.log").open("w", encoding="utf-8")
    server = subprocess.Popen([*hub, "serve"], env=hub_env, stdout=log, stderr=subprocess.STDOUT)
    try:
        wait_for_hub()
        smoke = Smoke(work)
        smoke.login()
        for shell in SHELLS:
            smoke.run_shell(shell)
    except BaseException:
        log.flush()
        print((work / "serve.log").read_text(encoding="utf-8", errors="replace")[-4000:])
        raise
    finally:
        server.terminate()
        server.wait(timeout=30)
        log.close()
        shutil.rmtree(work, ignore_errors=True)
    print("smoke: every PowerShell line did what it should, in both shells")
    return 0


if __name__ == "__main__":
    sys.exit(main())
