"""The vendor installers (§15.16, lotse 131248): an exact version, checked against the
vendor's checksum (and, for Claude Code, its signed manifest) before anything runs; refused
rather than fallen back. No network: vendor answers are recorded or built here."""

from __future__ import annotations

import hashlib
import io
import json
import platform
import shutil
import tarfile
from pathlib import Path
from typing import Any

import pytest

from maity.runner import installers, tools

DATA = Path(__file__).parent / "data" / "claude-code-2.1.325"
needs_gpgv = pytest.mark.skipif(shutil.which("gpgv") is None, reason="gpgv not installed")


def serve(pages: dict[str, bytes]) -> Any:
    def get(url: str) -> bytes:
        if url not in pages:
            raise tools.InstallError("installer_failed", f"HTTP 404 {url}")
        return pages[url]

    return get


def claude_pages(manifest: bytes | None = None) -> dict[str, bytes]:
    base = installers.CLAUDE_BASE + "/2.1.325"
    return {
        installers.CLAUDE_BASE + "/latest": b"2.1.325\n",
        base + "/manifest.json": manifest or (DATA / "manifest.json").read_bytes(),
        base + "/manifest.json.sig": (DATA / "manifest.json.sig").read_bytes(),
    }


@pytest.fixture
def linux_x64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(platform, "libc_ver", lambda: ("glibc", "2.39"))


def test_the_shipped_release_key_is_the_pinned_one() -> None:
    key = installers.dearmor(installers.CLAUDE_KEY.read_text(encoding="ascii"))
    assert key[:1] == b"\x99"  # an OpenPGP public-key packet
    assert installers.CLAUDE_KEY_FINGERPRINT == "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"


def test_claude_code_latest_is_the_vendors_answer() -> None:
    assert installers.ClaudeCode(serve(claude_pages())).latest() == "2.1.325"
    html = serve({installers.CLAUDE_BASE + "/latest": b"<html>blocked</html>"})
    with pytest.raises(tools.InstallError) as refused:
        installers.ClaudeCode(html).latest()
    assert refused.value.reason == "network"


@needs_gpgv
def test_claude_code_takes_the_binary_the_signed_manifest_names(
    tmp_path: Path, linux_x64: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[str, str, int | None]] = []

    def download(url: str, into: Path, sha256: str, size: int | None = None) -> None:
        asked.append((url, sha256, size))
        into.write_text("#!/bin/sh\necho '2.1.325 (Claude Code)'\n", encoding="utf-8")

    monkeypatch.setattr(installers, "download", download)
    installer = installers.ClaudeCode(serve(claude_pages()))
    found = installer.install("2.1.325", tmp_path)
    entry = json.loads((DATA / "manifest.json").read_text())["platforms"]["linux-x64"]
    assert asked == [
        (installers.CLAUDE_BASE + "/2.1.325/linux-x64/claude", entry["checksum"], entry["size"])
    ]
    assert found == tmp_path / "bin" / "claude"
    assert installer.version_of(found) == "2.1.325"


@needs_gpgv
def test_claude_code_refuses_a_manifest_the_key_did_not_sign(
    tmp_path: Path, linux_x64: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(installers, "download", lambda *a, **k: pytest.fail("downloaded"))
    original = (DATA / "manifest.json").read_bytes()
    forged = original.replace(b'"checksum": "0', b'"checksum": "1', 1)
    assert forged != original
    with pytest.raises(tools.InstallError, match="signature") as refused:
        installers.ClaudeCode(serve(claude_pages(forged))).install("2.1.325", tmp_path)
    assert refused.value.reason == "installer_failed"


@needs_gpgv
def test_claude_code_refuses_a_signed_manifest_of_another_version(
    tmp_path: Path, linux_x64: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replayed older manifest is signed too; it must name the version asked for."""
    monkeypatch.setattr(installers, "download", lambda *a, **k: pytest.fail("downloaded"))
    pages = claude_pages()
    base = installers.CLAUDE_BASE
    pages[base + "/2.1.326/manifest.json"] = pages[base + "/2.1.325/manifest.json"]
    pages[base + "/2.1.326/manifest.json.sig"] = pages[base + "/2.1.325/manifest.json.sig"]
    with pytest.raises(tools.InstallError, match="another version"):
        installers.ClaudeCode(serve(pages)).install("2.1.326", tmp_path)


def test_claude_code_without_gpgv_is_refused(
    tmp_path: Path, linux_x64: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(installers, "download", lambda *a, **k: pytest.fail("downloaded"))
    with pytest.raises(tools.InstallError, match="gpgv is not installed"):
        installers.ClaudeCode(serve(claude_pages())).install("2.1.325", tmp_path)


# --- downloads ---------------------------------------------------------------------------


def test_a_download_that_does_not_match_its_checksum_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"payload"
    monkeypatch.setattr(installers, "_open", lambda url: io.BytesIO(body))
    good = hashlib.sha256(body).hexdigest()
    installers.download("https://vendor.example/x", tmp_path / "ok", good, len(body))
    assert (tmp_path / "ok").read_bytes() == body
    for sha, size in ((hashlib.sha256(b"other").hexdigest(), None), (good, len(body) - 1)):
        with pytest.raises(tools.InstallError) as refused:
            installers.download("https://vendor.example/x", tmp_path / "bad", sha, size)
        assert refused.value.reason == "installer_failed"
        assert not (tmp_path / "bad").exists()


def test_only_https_is_fetched() -> None:
    with pytest.raises(tools.InstallError, match="not https"):
        installers.fetch("http://downloads.claude.ai/claude-code-releases/latest")


# --- Codex --------------------------------------------------------------------------------


def codex_tarball(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            bundle.addfile(info, io.BytesIO(data))
    return out.getvalue()


GOOD = {"bin/codex": b"#!/bin/sh\necho 'codex-cli 0.169.0'\n", "codex-path/rg": b"rg"}
NAME = "codex-package-x86_64-unknown-linux-musl.tar.gz"
URL = f"https://github.com/openai/codex/releases/download/rust-v0.169.0/{NAME}"


def codex_release(archive: bytes, **change: Any) -> dict[str, Any]:
    asset = {
        "name": NAME,
        "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
        "size": len(archive),
        "browser_download_url": URL,
    }
    asset.update(change)
    return {"tag_name": "rust-v0.169.0", "draft": False, "prerelease": False, "assets": [asset]}


def codex_with(
    monkeypatch: pytest.MonkeyPatch, archive: bytes, release: dict[str, Any]
) -> installers.Codex:
    monkeypatch.setattr(installers, "_open", lambda url: io.BytesIO(archive))
    body = json.dumps(release).encode()
    return installers.Codex(
        serve(
            {
                installers.CODEX_API + "/latest": body,
                installers.CODEX_API + "/tags/rust-v0.169.0": body,
            }
        )
    )


def test_codex_unpacks_the_package_whose_digest_github_states(
    tmp_path: Path, linux_x64: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = codex_tarball(GOOD)
    codex = codex_with(monkeypatch, archive, codex_release(archive))
    assert codex.latest() == "0.169.0"
    found = codex.install("0.169.0", tmp_path)
    assert found == tmp_path / "codex" / "bin" / "codex"
    assert codex.version_of(found) == "0.169.0"
    assert not (tmp_path / NAME).exists()  # the archive does not stay


@pytest.mark.parametrize(
    "change, why",
    [
        ({"digest": None}, "no SHA-256 digest"),
        ({"digest": "sha256:" + "0" * 64}, "checksum does not match"),
        ({"browser_download_url": "https://elsewhere.example/" + NAME}, "unexpected download URL"),
    ],
)
def test_codex_refuses_what_it_cannot_check(
    tmp_path: Path,
    linux_x64: None,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
    why: str,
) -> None:
    archive = codex_tarball(GOOD)
    codex = codex_with(monkeypatch, archive, codex_release(archive, **change))
    with pytest.raises(tools.InstallError, match=why) as refused:
        codex.install("0.169.0", tmp_path)
    assert refused.value.reason == "installer_failed"
    assert not (tmp_path / "codex").exists()


def test_codex_refuses_a_draft_or_prerelease(
    tmp_path: Path, linux_x64: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = codex_tarball(GOOD)
    release = codex_release(archive) | {"prerelease": True}
    with pytest.raises(tools.InstallError, match="not a published release"):
        codex_with(monkeypatch, archive, release).latest()


def test_codex_refuses_an_archive_that_reaches_outside(
    tmp_path: Path, linux_x64: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = codex_tarball({**GOOD, "../escaped": b"x"})
    codex = codex_with(monkeypatch, archive, codex_release(archive))
    (tmp_path / "into").mkdir()
    with pytest.raises(tools.InstallError) as refused:
        codex.install("0.169.0", tmp_path / "into")
    assert refused.value.reason == "installer_failed"
    assert not (tmp_path / "escaped").exists()


def test_both_installers_are_registered() -> None:
    assert {"claude-code", "codex"} <= set(tools.INSTALLERS)
