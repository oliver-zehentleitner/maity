#!/usr/bin/env python3
"""The Runners view's starter configurations against the runner's own check.

For each case of tools/starter-configs.js, in a throwaway HOME and under
umask 002: the page's "copy as a command" writes
~/.config/maity-runner/runner.toml (owner-only, exactly the configuration),
a second run refuses to overwrite it, and `maity runner check --offline`
loads it without a word about the file. What check says about the machine
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
    """The service way's file: its command writes the fixed path with sudo, which this test
    does not run; the file is checked by the runner from a copy, and against install's paths."""
    home = root / name
    home.mkdir()
    failures = []
    expected = (
        f"sudo cp -p {SERVICE_CONFIG} {SERVICE_CONFIG}.install && sudo tee {SERVICE_CONFIG} "
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
    path.write_text(case["config"], encoding="utf-8")
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
