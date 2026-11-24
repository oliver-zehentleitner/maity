#!/usr/bin/env python3
"""Check the hub's built sdist and wheel before they are uploaded (`make release-check`).

1. The wheel carries the join page and the dashboard (hatch_build.py's BUNDLED) byte for
   byte as they are in the checkout.
2. A wheel built again from the sdist, as pip does when it installs from source, has the
   same files with the same bytes.
3. The wheel installs into a fresh environment, outside the checkout, from the hashed
   runtime lock (requirements/runtime.txt) and the wheel without dependencies; there
   `maity-hub migrate` and `maity-hub serve` run on SQLite, and the dashboard answers:
   its page at `/`, and every stylesheet, script and icon the page names under `/assets/`,
   with the bytes the wheel carries.

The rebuild runs with this Python (build and hatchling, the release lock); the new
environment is made with it too.
Usage: python scripts/check_dist.py <dist directory>    exit 0 = all three hold
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
REPOSITORY = HUB.parent
# The files the shell names relative to itself (`href="css/app.css"`, `src="js/…"`).
NAMED = re.compile(rb'(?:href|src)="((?:brand|css|js|vendor)/[^"?#]+)(?:\?v=([0-9a-f]{16}))?"')
# A stylesheet is served with its `url()`s under their versions (docs/api.md §16.11): taken out
# again, it is the wheel's file.
URL_VERSION = re.compile(rb"\?v=[0-9a-f]{16}(?=[\"')])")


def bundled() -> dict[str, str]:
    """hatch_build.py's BUNDLED, read without importing hatchling."""
    tree = ast.parse((HUB / "hatch_build.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "BUNDLED":
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return {str(k): str(v) for k, v in value.items()}
    raise SystemExit("check_dist: no BUNDLED in hatch_build.py")


def wheel_files(wheel: Path) -> dict[str, bytes]:
    """The wheel's files and bytes, without RECORD (it names the wheel's own hashes)."""
    with zipfile.ZipFile(wheel) as archive:
        return {
            name: archive.read(name)
            for name in archive.namelist()
            if not name.endswith(".dist-info/RECORD")
        }


def expected_bundle() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for source, target in bundled().items():
        path = REPOSITORY / source
        if path.is_file():
            files[target] = path.read_bytes()
            continue
        for item in sorted(path.rglob("*")):
            if item.is_file():
                files[f"{target}/{item.relative_to(path).as_posix()}"] = item.read_bytes()
    return files


def check_bundle(files: dict[str, bytes]) -> None:
    for name, content in expected_bundle().items():
        if files.get(name) != content:
            raise SystemExit(f"check_dist: the wheel lacks {name} or carries other bytes")
    print(f"check_dist: the wheel carries the {len(expected_bundle())} bundled files")


def check_rebuild(sdist: Path, files: dict[str, bytes], work: Path) -> None:
    with tarfile.open(sdist) as archive:
        archive.extractall(work / "sdist", filter="data")
    (unpacked,) = (work / "sdist").iterdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(work / "rebuilt"),
            str(unpacked),
        ],
        check=True,
        cwd=work,
    )
    (rebuilt,) = (work / "rebuilt").glob("*.whl")
    again = wheel_files(rebuilt)
    if again != files:
        differ = sorted(set(again) ^ set(files)) or sorted(
            name for name in files if files[name] != again[name]
        )
        raise SystemExit(f"check_dist: the wheel from the sdist differs: {differ[:10]}")
    print(f"check_dist: the wheel from the sdist has the same {len(files)} files")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as response:
        body: bytes = response.read()
        return body


def check_install(wheel: Path, files: dict[str, bytes], work: Path) -> None:
    env_dir = work / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(env_dir)], check=True)
    bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / "python"
    pip = [str(python), "-m", "pip", "install", "--quiet"]
    subprocess.run(
        [*pip, "--require-hashes", "-r", str(HUB / "requirements" / "runtime.txt")], check=True
    )
    subprocess.run([*pip, "--no-deps", str(wheel)], check=True)

    data = work / "data"  # outside the checkout: nothing can come from web/ beside hub/
    data.mkdir()
    port = free_port()
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("MAITY_") and key != "PYTHONPATH"
    }
    env["MAITY_BIND"] = f"127.0.0.1:{port}"
    hub = str(bin_dir / "maity-hub")
    subprocess.run([hub, "migrate"], check=True, cwd=data, env=env)
    server = subprocess.Popen([hub, "serve"], cwd=data, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        page = b""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise SystemExit(f"check_dist: maity-hub serve exited with {server.returncode}")
            try:
                page = fetch(f"{base}/")
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.5)
        else:
            raise SystemExit("check_dist: the installed hub did not answer within 60 s")
        if b'<base href="/assets/">' not in page:
            raise SystemExit("check_dist: / is not the dashboard's page")
        found = sorted({(name.decode(), version.decode()) for name, version in NAMED.findall(page)})
        named = [name for name, _ in found]
        if not any(name.startswith("css/") for name in named) or not any(
            name.startswith("js/") for name in named
        ):
            raise SystemExit(f"check_dist: the page names no stylesheet or no script: {named}")
        for name, version in found:
            # The shell names each file under the version of the body the hub sends (§16.11).
            if not version:
                raise SystemExit(f"check_dist: the page names {name} without its version")
            body = fetch(f"{base}/assets/{name}?v={version}")
            if hashlib.sha256(body).hexdigest()[:16] != version:
                raise SystemExit(f"check_dist: /assets/{name} is not the body its version names")
            if name.endswith(".css"):
                body = URL_VERSION.sub(b"", body)
            if body != files[f"maity_hub/web/{name}"]:
                raise SystemExit(f"check_dist: /assets/{name} is not the wheel's file")
        print(f"check_dist: the installed hub serves its page and the {len(named)} files it names")
    finally:
        server.terminate()
        server.wait(timeout=30)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    dist = Path(argv[0]).resolve()
    (wheel,) = dist.glob("maity_hub-*.whl")
    (sdist,) = dist.glob("maity_hub-*.tar.gz")
    files = wheel_files(wheel)
    check_bundle(files)
    work = Path(tempfile.mkdtemp(prefix="maity-hub-dist-"))
    try:
        check_rebuild(sdist, files, work)
        check_install(wheel, files, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
