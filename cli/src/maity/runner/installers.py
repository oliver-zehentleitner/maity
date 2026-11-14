"""The vendor package of each harness tool the runner can install and update (§15.16).

Rules (lotse 131248): the runner never runs a script it has just downloaded; it fetches one
exact version's package straight from the vendor, checks it against the vendor's checksum
before it is unpacked or run, and refuses (InstallError) rather than fall back to anything it
cannot check. What each installer verifies, and what it does not, is written beside it and in
docs/runners.md.

A tool not listed in INSTALLERS cannot be configured with `install` or `update`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from maity.runner import tools

_TIMEOUT = 60
_CHUNK = 1 << 20
_META_LIMIT = 4 << 20  # manifests, signatures, release metadata
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _open(url: str) -> Any:
    if not url.startswith("https://"):
        raise tools.InstallError("installer_failed", f"not https: {url}")
    request = urllib.request.Request(  # noqa: S310 (https only, checked above)
        url, headers={"User-Agent": "maity-runner"}
    )
    try:
        return urllib.request.urlopen(request, timeout=_TIMEOUT)  # noqa: S310 (https only)
    except urllib.error.HTTPError as error:
        raise tools.InstallError("installer_failed", f"{url}: HTTP {error.code}") from error
    except (urllib.error.URLError, OSError) as error:
        raise tools.InstallError("network", f"{url}: {error}") from error


def fetch(url: str, limit: int = _META_LIMIT) -> bytes:
    """A small document, refused when larger than `limit`."""
    with _open(url) as response:
        try:
            data = response.read(limit + 1)
        except OSError as error:
            raise tools.InstallError("network", f"{url}: {error}") from error
    if len(data) > limit:
        raise tools.InstallError("installer_failed", f"{url}: larger than {limit} bytes")
    return bytes(data)


def download(url: str, into: Path, sha256: str, size: int | None = None) -> None:
    """Stream `url` to `into` and refuse it unless its SHA-256 is `sha256` (and its size
    `size`, when the vendor states one). A refused file is removed."""
    digest = hashlib.sha256()
    written = 0
    cap = size if size is not None else 2 << 30
    try:
        with _open(url) as response, open(into, "wb") as out:
            while chunk := response.read(_CHUNK):
                written += len(chunk)
                if written > cap:
                    raise tools.InstallError("installer_failed", f"{url}: larger than stated")
                digest.update(chunk)
                out.write(chunk)
    except tools.InstallError:
        into.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
        into.unlink(missing_ok=True)
        raise tools.InstallError("network", f"{url}: {error}") from error
    if (size is not None and written != size) or digest.hexdigest() != sha256:
        into.unlink(missing_ok=True)
        raise tools.InstallError("installer_failed", f"{url}: checksum does not match")


def _answer(binary: Path, *args: str) -> str | None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MAITY_")}
    try:
        done = subprocess.run(  # noqa: S603 (our own installed binary)
            [str(binary), *args], capture_output=True, text=True, timeout=30, env=env
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _musl() -> bool:
    libc, _ = platform.libc_ver()
    return platform.system() == "Linux" and libc != "glibc"


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    raise tools.InstallError("installer_failed", f"unsupported architecture {machine}")


# --- Claude Code ------------------------------------------------------------------------
#
# Verified: the release's manifest.json carries a detached OpenPGP signature
# (manifest.json.sig); gpgv checks it against Anthropic's release key shipped with maity
# (claude-code-release.asc, fingerprint below), never one fetched at install time. The
# manifest must name the requested version, and the binary must match the manifest's
# SHA-256 and size for this platform. No gpgv on the host: refused.
# Not verified: nothing beyond the signed manifest (no reproducible build).

CLAUDE_BASE = "https://downloads.claude.ai/claude-code-releases"
CLAUDE_KEY_FINGERPRINT = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
CLAUDE_KEY = Path(__file__).with_name("claude-code-release.asc")


def dearmor(armored: str) -> bytes:
    """The binary key out of an ASCII-armored OpenPGP block."""
    lines = armored.strip().splitlines()
    try:
        start = lines.index("") + 1
    except ValueError as error:
        raise tools.InstallError("installer_failed", "release key is not armored") from error
    body = [line for line in lines[start:] if line and not line.startswith(("=", "-----"))]
    return base64.b64decode("".join(body))


def verify_signature(data: bytes, signature: bytes, key: bytes, fingerprint: str) -> None:
    """Refuse `data` unless `signature` is a valid signature over it by `fingerprint`."""
    with tempfile.TemporaryDirectory(prefix="maity-gpgv-") as folder:
        keyring, signed, sig = (Path(folder) / n for n in ("key.gpg", "data", "data.sig"))
        keyring.write_bytes(key)
        signed.write_bytes(data)
        sig.write_bytes(signature)
        try:
            done = subprocess.run(  # noqa: S603, S607
                ["gpgv", "--keyring", str(keyring), "--status-fd", "1", str(sig), str(signed)],
                capture_output=True,
                text=True,
                timeout=60,
                env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"},
            )
        except FileNotFoundError as error:
            raise tools.InstallError("installer_failed", "gpgv is not installed") from error
        except (OSError, subprocess.SubprocessError) as error:
            raise tools.InstallError("installer_failed", f"gpgv: {error}") from error
    valid = [
        line.split()[2]
        for line in done.stdout.splitlines()
        if line.startswith("[GNUPG:] VALIDSIG ") and len(line.split()) > 2
    ]
    if done.returncode != 0 or fingerprint not in valid:
        raise tools.InstallError("installer_failed", "manifest signature does not verify")


class ClaudeCode:
    def __init__(self, get: Callable[[str], bytes] = fetch) -> None:
        self.get = get

    def platform(self) -> str:
        system = platform.system()
        if system == "Linux":
            return f"linux-{_arch()}" + ("-musl" if _musl() else "")
        if system == "Darwin":
            return f"darwin-{_arch()}"
        raise tools.InstallError("installer_failed", f"unsupported system {system}")

    def latest(self) -> str:
        version = self.get(f"{CLAUDE_BASE}/latest").decode("utf-8", "replace").strip()
        if not _VERSION.match(version):
            raise tools.InstallError("network", "the vendor did not answer with a version")
        return version

    def install(self, version: str, into: Path) -> Path:
        if not _VERSION.match(version):
            raise tools.InstallError("installer_failed", f"not a version: {version!r}")
        manifest = self.get(f"{CLAUDE_BASE}/{version}/manifest.json")
        signature = self.get(f"{CLAUDE_BASE}/{version}/manifest.json.sig")
        key = dearmor(CLAUDE_KEY.read_text(encoding="ascii"))
        verify_signature(manifest, signature, key, CLAUDE_KEY_FINGERPRINT)
        try:
            data = json.loads(manifest)
            entry = data["platforms"][self.platform()]
            checksum, size = str(entry["checksum"]), int(entry["size"])
        except (ValueError, KeyError, TypeError) as error:
            raise tools.InstallError("installer_failed", "manifest lacks this platform") from error
        if data.get("version") != version or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise tools.InstallError("installer_failed", "manifest names another version")
        found = into / "bin" / "claude"
        found.parent.mkdir()
        download(f"{CLAUDE_BASE}/{version}/{self.platform()}/claude", found, checksum, size)
        found.chmod(0o755)
        return found

    def version_of(self, binary: Path) -> str | None:
        out = _answer(binary, "--version")  # "2.1.325 (Claude Code)"
        return out.split()[0] if out and out.split() else None


# --- Codex ------------------------------------------------------------------------------
#
# Verified: the package tarball's SHA-256 against the `digest` GitHub's release API states
# for that asset (the release tagged rust-v<version>, not a draft or prerelease); unpacked
# only with the tarfile "data" filter (no links or paths out of its directory).
# Not verified: the asset's sigstore bundle (the runner carries no sigstore verifier), so the
# trust is GitHub's and the vendor's release account, over HTTPS.

CODEX_API = "https://api.github.com/repos/openai/codex/releases"


class Codex:
    def __init__(self, get: Callable[[str], bytes] = fetch) -> None:
        self.get = get

    def target(self) -> str:
        system, arch = platform.system(), _arch()
        cpu = "x86_64" if arch == "x64" else "aarch64"
        if system == "Linux":
            return f"{cpu}-unknown-linux-musl"
        if system == "Darwin":
            return f"{cpu}-apple-darwin"
        raise tools.InstallError("installer_failed", f"unsupported system {system}")

    def _release(self, url: str) -> dict[str, Any]:
        try:
            release = json.loads(self.get(url))
        except ValueError as error:
            raise tools.InstallError("network", "release metadata is not JSON") from error
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            raise tools.InstallError("installer_failed", "not a published release")
        return release

    def latest(self) -> str:
        tag = str(self._release(f"{CODEX_API}/latest").get("tag_name", ""))
        version = tag.removeprefix("rust-v")
        if not tag.startswith("rust-v") or not _VERSION.match(version):
            raise tools.InstallError("network", f"unexpected release tag {tag!r}")
        return version

    def install(self, version: str, into: Path) -> Path:
        if not _VERSION.match(version):
            raise tools.InstallError("installer_failed", f"not a version: {version!r}")
        release = self._release(f"{CODEX_API}/tags/rust-v{version}")
        name = f"codex-package-{self.target()}.tar.gz"
        asset = next((a for a in release.get("assets", []) if a.get("name") == name), None)
        digest = str((asset or {}).get("digest") or "")
        url = str((asset or {}).get("browser_download_url") or "")
        if not digest.startswith("sha256:") or not re.fullmatch(r"[0-9a-f]{64}", digest[7:]):
            raise tools.InstallError("installer_failed", f"{name}: no SHA-256 digest")
        prefix = f"https://github.com/openai/codex/releases/download/rust-v{version}/"
        if url != prefix + name:
            raise tools.InstallError("installer_failed", f"{name}: unexpected download URL")
        archive = into / name
        size = (asset or {}).get("size")
        download(url, archive, digest[7:], size if isinstance(size, int) else None)
        if not hasattr(tarfile, "data_filter"):
            raise tools.InstallError("installer_failed", "this Python cannot unpack safely")
        try:
            with tarfile.open(archive) as bundle:
                bundle.extractall(into / "codex", filter="data")
        except (tarfile.TarError, OSError) as error:
            raise tools.InstallError("installer_failed", f"{name}: {error}") from error
        finally:
            archive.unlink(missing_ok=True)
        found = into / "codex" / "bin" / "codex"
        if not found.is_file():
            raise tools.InstallError("installer_failed", f"{name}: no bin/codex inside")
        return found

    def version_of(self, binary: Path) -> str | None:
        out = _answer(binary, "--version")  # "codex-cli 0.169.0"
        return out.split()[-1] if out and out.split() else None


tools.INSTALLERS.update({"claude-code": ClaudeCode, "codex": Codex})
