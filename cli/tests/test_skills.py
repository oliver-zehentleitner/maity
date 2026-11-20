"""The Keep the Why skill a runner delivers (runner/skills.py, tsk-172s8y208whg): fetched at the
commit the hub names, only plain files, checked against its manifest every time it is handed out.

The fetch runs real git against a local repository; the https-only source is swapped for a
`file://` one, the only thing these tests change in the module.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from conftest import posix

from maity.runner import skills

# The runner and its skills directory are POSIX (links, modes, FIFOs), as test_scratchop.py is.
pytestmark = posix

SOURCE = "https://github.com/oliver-zehentleitner/keep-the-why/tree/v0.20.3/skills/keep-the-why"


def _git(repo: Path, *args: str) -> str:
    # Nothing of a placed session's git (GIT_COMMON_DIR and the rest) reaches the fixture's.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env |= {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@invalid", *args],
        env=env, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.strip()


@pytest.fixture
def upstream(tmp_path: Path) -> Path:
    repo = tmp_path / "upstream"
    (repo / "skills" / "keep-the-why" / "references").mkdir(parents=True)
    (repo / "skills" / "keep-the-why" / "SKILL.md").write_text("---\nname: keep-the-why\n---\n")
    (repo / "skills" / "keep-the-why" / "references" / "help.md").write_text("# help\n")
    (repo / "README.md").write_text("not part of the skill\n")
    _git(repo, "init", "--quiet", "-b", "main")
    _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "skill")
    return repo


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch, upstream: Path) -> Path:
    monkeypatch.setattr(skills, "_TRANSPORTS", "file")
    real = skills.split_source

    def split(source: str) -> tuple[str, str]:
        _, path = real(source)
        return f"file://{upstream}", path

    monkeypatch.setattr(skills, "split_source", split)
    return upstream


def test_the_named_commit_is_fetched_as_a_plugin_of_plain_read_only_files(
    tmp_path: Path, local: Path
) -> None:
    commit = _git(local, "rev-parse", "HEAD")
    root = skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    assert root == skills.plugin_root(tmp_path / "skills", SOURCE, commit)
    assert root.parent.name == skills.key(SOURCE, commit) and root.parent.name.startswith(commit)
    skill = skills.skill_dir(tmp_path / "skills", SOURCE, commit)
    assert (skill / "SKILL.md").read_text() == "---\nname: keep-the-why\n---\n"
    assert (skill / "references" / "help.md").read_text() == "# help\n"
    assert not (root / "README.md").exists() and not (skill / "README.md").exists()
    plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    assert (plugin["name"], plugin["version"]) == ("keep-the-why", commit[:12])
    for path in [root, *root.rglob("*")]:
        mode = stat.S_IMODE(path.lstat().st_mode)
        assert mode == (0o755 if path.is_dir() else 0o644), path
    manifest = json.loads((root.parent / skills.MANIFEST).read_text())
    assert manifest["commit"] == commit
    assert "plugin/skills/keep-the-why/SKILL.md" in manifest["files"]
    left = [p.name for p in (tmp_path / "skills" / "keep-the-why").iterdir()]
    assert left == [skills.key(SOURCE, commit)]  # no fetch directory left behind


def test_a_copy_rewritten_with_its_manifest_is_refused_by_the_recorded_hash(
    tmp_path: Path, local: Path
) -> None:
    # The review of #2056 (security leg): the manifest's hash lives in the runner's state
    # directory, so a file and a manifest rewritten together beside it do not pass.
    commit = _git(local, "rev-parse", "HEAD")
    root = skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    recorded = json.loads((tmp_path / "state" / skills.ANCHORS).read_text())
    name = skills.key(SOURCE, commit)
    assert recorded == {name: skills._sha256(root.parent / skills.MANIFEST)}
    assert stat.S_IMODE((tmp_path / "state" / skills.ANCHORS).stat().st_mode) == 0o600
    skill_md = root / "skills" / "keep-the-why" / "SKILL.md"
    os.chmod(skill_md, 0o644)
    skill_md.write_text("rewritten\n")
    manifest = root.parent / skills.MANIFEST
    data = json.loads(manifest.read_text())
    data["files"]["plugin/skills/keep-the-why/SKILL.md"] = skills._sha256(skill_md)
    os.chmod(manifest, 0o644)
    manifest.write_text(json.dumps(data))
    skills.verify(root.parent, SOURCE, commit)  # consistent on its own
    with pytest.raises(skills.Unavailable, match="not the one the runner fetched"):
        skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)


def test_without_a_record_the_commit_is_fetched_again_and_compared(
    tmp_path: Path, local: Path
) -> None:
    # A state directory made anew: the copy is kept when the fresh fetch gives the same
    # manifest, and refused when it does not.
    commit = _git(local, "rev-parse", "HEAD")
    root = skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    assert skills.ensure(tmp_path / "skills", tmp_path / "fresh", SOURCE, commit) == root
    assert skills.key(SOURCE, commit) in json.loads(
        (tmp_path / "fresh" / skills.ANCHORS).read_text()
    )
    skill_md = root / "skills" / "keep-the-why" / "SKILL.md"
    os.chmod(skill_md, 0o644)
    skill_md.write_text("rewritten\n")
    manifest = root.parent / skills.MANIFEST
    data = json.loads(manifest.read_text())
    data["files"]["plugin/skills/keep-the-why/SKILL.md"] = skills._sha256(skill_md)
    os.chmod(manifest, 0o644)
    manifest.write_text(json.dumps(data))
    with pytest.raises(skills.Unavailable, match="not what commit"):
        skills.ensure(tmp_path / "skills", tmp_path / "other", SOURCE, commit)
    assert not (tmp_path / "other" / skills.ANCHORS).exists()


def test_a_manifest_of_another_source_or_commit_is_refused(tmp_path: Path, local: Path) -> None:
    # The review of #2056: the copy is keyed and checked by source and commit both, so the same
    # commit at another path of the tree is another copy, and a rewritten manifest is refused.
    commit = _git(local, "rev-parse", "HEAD")
    root = skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    other = SOURCE.replace("/skills/keep-the-why", "/skills/keep-the-why/")
    assert skills.key(other, commit) != skills.key(SOURCE, commit)
    with pytest.raises(skills.Unavailable, match="is not of"):
        skills.verify(root.parent, other, commit)
    manifest = root.parent / skills.MANIFEST
    data = json.loads(manifest.read_text())
    os.chmod(manifest, 0o644)
    manifest.write_text(json.dumps({**data, "commit": "f" * 40}))
    with pytest.raises(skills.Unavailable, match="is not of"):
        skills.verify(root.parent, SOURCE, commit)


def test_a_checked_copy_is_handed_out_again_without_a_fetch(
    tmp_path: Path, local: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = _git(local, "rev-parse", "HEAD")
    first = skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)

    def no_fetch(*_: object) -> None:
        raise AssertionError("fetched again")

    monkeypatch.setattr(skills, "_fetch", no_fetch)
    assert skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit) == first


def test_a_changed_copy_is_refused_not_handed_out(tmp_path: Path, local: Path) -> None:
    commit = _git(local, "rev-parse", "HEAD")
    root = skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    skill = root / "skills" / "keep-the-why"
    os.chmod(skill / "SKILL.md", 0o644)
    (skill / "SKILL.md").write_text("changed\n")
    with pytest.raises(skills.Unavailable, match="does not match its manifest"):
        skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    (skill / "SKILL.md").write_text("---\nname: keep-the-why\n---\n")
    (skill / "extra.md").write_text("added\n")
    with pytest.raises(skills.Unavailable, match="does not match its manifest"):
        skills.verify(root.parent, SOURCE, commit)
    (skill / "extra.md").unlink()
    (skill / "link.md").symlink_to(skill / "SKILL.md")
    with pytest.raises(skills.Unavailable, match="cannot be opened as a plain file"):
        skills.verify(root.parent, SOURCE, commit)


def test_a_cache_whose_roots_or_manifest_are_not_plain_is_refused(
    tmp_path: Path, local: Path
) -> None:
    # The review of #2056: the copy, its plugin root and the manifest are checked too, never
    # followed through a link.
    commit = _git(local, "rev-parse", "HEAD")
    skills_dir = tmp_path / "skills"
    root = skills.ensure(skills_dir, tmp_path / "state", SOURCE, commit)
    copy = root.parent
    manifest = copy / skills.MANIFEST
    kept = tmp_path / "manifest.json"
    manifest.rename(kept)
    manifest.symlink_to(kept)
    with pytest.raises(skills.Unavailable, match="cannot be opened as a plain file"):
        skills.verify(copy, SOURCE, commit)
    manifest.unlink()
    kept.rename(manifest)
    moved = tmp_path / "plugin"
    root.rename(moved)
    root.symlink_to(moved)
    with pytest.raises(skills.Unavailable, match="not a plain directory"):
        skills.verify(copy, SOURCE, commit)
    root.unlink()
    moved.rename(root)
    skills.verify(copy, SOURCE, commit)  # put back: whole again


def test_a_fifo_in_the_cache_is_refused_without_waiting_on_it(tmp_path: Path, local: Path) -> None:
    commit = _git(local, "rev-parse", "HEAD")
    root = skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    os.mkfifo(root / "skills" / "keep-the-why" / "pipe.md")
    with pytest.raises(skills.Unavailable, match="not a plain file"):
        skills.verify(root.parent, SOURCE, commit)  # returns at once; a read would block


def test_the_bounds_hold_for_a_cached_copy_too(
    tmp_path: Path, local: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = _git(local, "rev-parse", "HEAD")
    root = skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    monkeypatch.setattr(skills, "MAX_FILES", 1)  # SKILL.md, help.md and plugin.json are 3
    with pytest.raises(skills.Unavailable, match="too many files"):
        skills.verify(root.parent, SOURCE, commit)
    monkeypatch.setattr(skills, "MAX_FILES", 200)
    monkeypatch.setattr(skills, "MANIFEST_MAX", 0)
    monkeypatch.setattr(skills, "MAX_BYTES", 10)
    with pytest.raises(skills.Unavailable):
        skills.verify(root.parent, SOURCE, commit)


def test_the_fetch_keeps_the_runners_proxy_and_trust_roots_and_nothing_else_of_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The review of #2056: an operator's proxy and CA reach the fetch; git configuration and
    # the other GIT_* variables do not.
    seen: dict[str, str] = {}

    def run(
        command: list[str], *, env: dict[str, str], **_: object
    ) -> subprocess.CompletedProcess[bytes]:
        seen.update(env)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    for name, value in {
        "HTTPS_PROXY": "http://proxy.example:3128", "NO_PROXY": "localhost",
        "SSL_CERT_FILE": "/etc/ssl/ca.pem", "GIT_SSL_CAINFO": "/etc/ssl/ca.pem",
        "GIT_CONFIG_PARAMETERS": "'core.sshCommand=evil'", "GIT_DIR": "/elsewhere",
        "GIT_ALLOW_PROTOCOL": "ext:file:https",
    }.items():  # fmt: skip
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(subprocess, "run", run)
    skills._git(tmp_path / "git", "fetch")
    assert seen["HTTPS_PROXY"] == "http://proxy.example:3128" and seen["NO_PROXY"] == "localhost"
    assert seen["SSL_CERT_FILE"] == seen["GIT_SSL_CAINFO"] == "/etc/ssl/ca.pem"
    assert "GIT_CONFIG_PARAMETERS" not in seen
    assert seen["GIT_DIR"] == str(tmp_path / "git") and seen["GIT_ALLOW_PROTOCOL"] == "https"
    assert seen["GIT_CONFIG_GLOBAL"] == os.devnull and seen["GIT_CONFIG_NOSYSTEM"] == "1"


def test_a_commit_the_source_does_not_have_is_unavailable(tmp_path: Path, local: Path) -> None:
    with pytest.raises(skills.Unavailable, match="git fetch exited"):
        skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, "0" * 40)
    assert not (tmp_path / "skills" / "keep-the-why" / skills.key(SOURCE, "0" * 40)).exists()


def test_a_link_or_a_submodule_in_the_skill_is_refused(tmp_path: Path, local: Path) -> None:
    (local / "skills" / "keep-the-why" / "evil.md").symlink_to("/etc/passwd")
    _git(local, "add", ".")
    _git(local, "commit", "--quiet", "-m", "link")
    commit = _git(local, "rev-parse", "HEAD")
    with pytest.raises(skills.Unavailable, match="not a plain file"):
        skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)
    assert not (tmp_path / "skills" / "keep-the-why" / skills.key(SOURCE, commit)).exists()


def test_a_tree_without_the_skill_is_unavailable(tmp_path: Path, local: Path) -> None:
    other = SOURCE.replace("skills/keep-the-why", "skills/other")
    commit = _git(local, "rev-parse", "HEAD")
    with pytest.raises(skills.Unavailable, match="has no skills/other/"):
        skills.ensure(tmp_path / "skills", tmp_path / "state", other, commit)


def test_too_large_a_skill_is_refused(
    tmp_path: Path, local: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(skills, "MAX_BYTES", 10)
    commit = _git(local, "rev-parse", "HEAD")
    with pytest.raises(skills.Unavailable, match="larger than 10 bytes"):
        skills.ensure(tmp_path / "skills", tmp_path / "state", SOURCE, commit)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (SOURCE, ("https://github.com/oliver-zehentleitner/keep-the-why", "skills/keep-the-why")),
        (
            "https://gitlab.example.org/g/ktw/-/tree/v1/skills/keep-the-why",
            ("https://gitlab.example.org/g/ktw", "skills/keep-the-why"),
        ),
    ],
)
def test_the_source_splits_into_repository_and_path(source: str, expected: tuple[str, str]) -> None:
    assert skills.split_source(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "http://github.com/o/ktw/tree/v1/skills/keep-the-why",
        "file:///etc/tree/v1/skills",
        "https://github.com/o/ktw",
        "https://github.com/o/ktw/tree/v1",
        "https://github.com/o/ktw/tree/v1/../../etc",
        "https://github.com/o/ktw/tree/v1/skills?x=1",
        "https://user:secret@github.com/o/ktw/tree/v1/skills/keep-the-why",
        "https://token@github.com/o/ktw/tree/v1/skills/keep-the-why",
        "https://@github.com/o/ktw/tree/v1/skills/keep-the-why",
    ],
)
def test_a_source_the_runner_does_not_fetch_is_unavailable(source: str) -> None:
    with pytest.raises(skills.Unavailable):
        skills.split_source(source)


def test_what_a_placement_names() -> None:
    commit = "a" * 40
    assert skills.named({}) is None
    assert skills.named({"keep_the_why": None}) is None
    assert skills.named({"keep_the_why": {"source": SOURCE, "commit": commit}}) == (SOURCE, commit)
    for bad in ("x", {"source": SOURCE}, {"source": SOURCE, "commit": "A" * 40},
                {"source": 1, "commit": commit}):  # fmt: skip
        with pytest.raises(skills.Unavailable):
            skills.named({"keep_the_why": bad})


def test_gc_removes_only_copies_no_placement_names(tmp_path: Path) -> None:
    parent = tmp_path / "keep-the-why"
    kept, old = skills.key(SOURCE, "a" * 40), skills.key(SOURCE, "b" * 40)
    for name in (kept, old, ".fetch-x", "notes", "c" * 40):
        (parent / name).mkdir(parents=True)
    assert sorted(skills.remove_unused(tmp_path, {kept})) == sorted([".fetch-x", old])
    assert sorted(p.name for p in parent.iterdir()) == sorted([kept, "notes", "c" * 40])
