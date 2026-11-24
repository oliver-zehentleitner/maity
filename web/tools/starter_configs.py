#!/usr/bin/env python3
"""The Runners view's starter configurations against the runner's own check.

For each case of tools/starter-configs.js, in a throwaway HOME and under
umask 002: the page's "copy as a command" writes
~/.config/maity-runner/runner.toml (owner-only, exactly the configuration),
a second run refuses to overwrite it, and `maity runner check --offline`
loads it without a word about the file. The service way's command runs
without sudo on a stand-in for install's 0644 file, twice, and must leave it
0644, with install's own kept beside it from the first run. What check says about the machine
(no state_dir before pairing, no tmux) is not this test's business.

Needs node, bash and `maity` (Python 3.11+, from cli/) on PATH.
Exit 0 = every case passed.
"""

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
CONFIG = Path(".config/maity-runner/runner.toml")
# `maity runner install`'s fixed paths (cli/src/maity/runner/install.py: CONFIG, STATE_DIR,
# WORKSPACES): the service way's file must keep them, or serve looks for the credential
# somewhere install did not pair.
SERVICE_CONFIG = "/etc/maity-runner/runner.toml"
INSTALL_STATE = "/var/lib/maity-runner/state"
INSTALL_WORKSPACES = "/var/lib/maity-runner/workspaces"
LOADED = re.compile(r"^ok\s+configuration ", re.MULTILINE)
# The caller's own MAITY_* settings never reach the runner under test.
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("MAITY_")}


def run(args: list[str], home: Path) -> subprocess.CompletedProcess:
    env = dict(CLEAN_ENV, HOME=str(home))
    return subprocess.run(args, env=env, capture_output=True, text=True, check=False)


def checked_by_runner(name: str, path: Path, home: Path, extra: list[str]) -> list[str]:
    checked = run(["maity", "runner", "check", "--offline", *extra], home)
    said = checked.stdout + checked.stderr
    if not LOADED.search(said):
        return [f"{name}: maity runner check did not load it:\n{said}"]
    about_file = [ln for ln in said.splitlines() if str(path) in ln and not LOADED.match(ln)]
    if about_file:
        return [f"{name}: maity runner check objects to the file:\n" + "\n".join(about_file)]
    return []


def check_service_case(name: str, case: dict, root: Path) -> list[str]:
    """The service way's file: its command writes the fixed path with sudo. The test runs
    it without sudo against a stand-in for install's file (0644, as install writes it), so
    under umask 002 the file it leaves is what the runner checks, with install's paths."""
    home = root / name
    home.mkdir()
    failures = []
    expected = (
        f"{{ sudo test -e {SERVICE_CONFIG}.install || sudo cp -p {SERVICE_CONFIG} "
        f"{SERVICE_CONFIG}.install; }} && sudo tee {SERVICE_CONFIG} "
        f"> /dev/null <<'EOF'\n{case['config']}EOF"
    )
    if case["command"] != expected:
        failures.append(f"{name}: the command does not write {SERVICE_CONFIG}:\n{case['command']}")
    parsed = tomllib.loads(case["config"])
    if parsed["hub"].get("state_dir") != INSTALL_STATE or (
        parsed["backend"]["local"].get("workspaces") != INSTALL_WORKSPACES
    ):
        failures.append(f"{name}: state_dir or workspaces is not install's")
    path = home / "runner.toml"
    installed = "# install's own file\n"
    # install.py _write: a new file, 0644 whatever the umask.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o644)
        handle.write(installed)
    # Only the command line itself; the heredoc's text names the real path too.
    line, heredoc = case["command"].split("\n", 1)
    command = line.replace("sudo ", "").replace(SERVICE_CONFIG, str(path)) + "\n" + heredoc
    kept = home / "runner.toml.install"
    # Pasted twice: the second run writes the file again and keeps install's copy as it was.
    for _ in range(2):
        wrote = run(["bash", "-c", command], home)
        if wrote.returncode != 0 or path.read_text(encoding="utf-8") != case["config"]:
            failures.append(f"{name}: the command did not write the file: {wrote.stderr.strip()}")
        if not kept.exists() or kept.read_text(encoding="utf-8") != installed:
            failures.append(f"{name}: the command did not keep install's file beside it")
    for each in (path, kept):
        mode = stat.S_IMODE(each.stat().st_mode) if each.exists() else 0
        if mode != 0o644:
            failures.append(f"{name}: {each.name} is {oct(mode)}, not install's 0644")
    failures += checked_by_runner(name, path, home, ["--config", str(path)])
    print(f"{'FAIL' if failures else 'ok  '} {name}", flush=True)
    return failures


def check_case(name: str, case: dict, root: Path) -> list[str]:
    if case.get("way") == "service":
        return check_service_case(name, case, root)
    home = root / name
    home.mkdir()
    failures = []
    wrote = run(["bash", "-c", case["command"]], home)
    path = home / CONFIG
    if wrote.returncode != 0 or not path.exists():
        return [f"{name}: the command did not write the file: {wrote.stderr.strip()}"]
    if path.read_text(encoding="utf-8") != case["config"]:
        failures.append(f"{name}: the file is not the configuration the page shows")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        failures.append(f"{name}: the file is {oct(mode)}, readable or writable by others")
    again = run(["bash", "-c", case["command"]], home)
    if again.returncode == 0 or path.read_text(encoding="utf-8") != case["config"]:
        failures.append(f"{name}: a second run did not refuse to overwrite the file")
    failures += checked_by_runner(name, CONFIG, home, [])
    print(f"{'FAIL' if failures else 'ok  '} {name}", flush=True)
    return failures


def main() -> int:
    generated = subprocess.run(
        ["node", str(WEB / "tools/starter-configs.js")], capture_output=True, text=True, check=True
    )
    cases = json.loads(generated.stdout)
    os.umask(0o002)  # a common default; the page's command has to tighten it itself
    failures = []
    with tempfile.TemporaryDirectory(prefix="maity-starter-") as tmp:
        for name, case in cases.items():
            failures += check_case(name, case, Path(tmp))
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
