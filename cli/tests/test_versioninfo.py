"""Build provenance survives packaging and ignores a caller's unrelated Git state."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from conftest import git

from maity import __version__, cli, versioninfo


@pytest.fixture
def source_project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    package = root / "cli" / "src" / "maity"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# source\n")
    versioninfo.write_stamp(package / versioninfo.STAMP_FILE, None)
    git(root, "init", "--quiet")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "source")
    return root / "cli"


def test_source_stamp_is_scoped_to_the_cli_project(source_project: Path) -> None:
    head = git(source_project, "rev-parse", "HEAD")
    assert versioninfo.stamp_for(source_project) == versioninfo.Stamp(head, False)
    (source_project.parent / "unrelated.md").write_text("not CLI code\n")
    assert versioninfo.stamp_for(source_project) == versioninfo.Stamp(head, False)


@pytest.mark.parametrize("name", ["__init__.py", "new_module.py"])
def test_tracked_and_untracked_source_changes_are_dirty(source_project: Path, name: str) -> None:
    (source_project / "src" / "maity" / name).write_text("# changed\n")
    stamp = versioninfo.stamp_for(source_project)
    assert stamp is not None and stamp.dirty


def test_inherited_git_locations_cannot_select_another_repository(
    source_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = git(source_project, "rev-parse", "HEAD")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    git(foreign, "init", "--quiet")
    for key, value in {
        "GIT_DIR": foreign / ".git",
        "GIT_COMMON_DIR": foreign / ".git",
        "GIT_WORK_TREE": foreign,
        "GIT_INDEX_FILE": foreign / ".git" / "index",
    }.items():
        monkeypatch.setenv(key, str(value))
    assert versioninfo.stamp_for(source_project) == versioninfo.Stamp(head, False)


def test_a_source_archive_keeps_its_stamp_without_searching_distant_git_parents(
    source_project: Path,
) -> None:
    archive = source_project / "unrelated" / "extracted" / "cli"
    stamp = versioninfo.Stamp("b" * 40, True)
    versioninfo.write_stamp(archive / "src" / "maity" / versioninfo.STAMP_FILE, stamp)
    assert versioninfo.stamp_for(archive) == stamp


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"revision": "bad", "dirty": false}',
        '{"revision": "' + "a" * 40 + '", "dirty": "false"}',
    ],
)
def test_bad_stamp_data_is_unknown(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "stamp.json"
    path.write_text(raw)
    assert versioninfo.read_stamp(path) is None


def test_writing_a_release_tree_stamp_does_not_change_a_hard_linked_source(tmp_path: Path) -> None:
    source, target = tmp_path / "source.json", tmp_path / "release.json"
    original = versioninfo.Stamp("a" * 40, False)
    versioninfo.write_stamp(source, original)
    os.link(source, target)
    changed = versioninfo.Stamp("b" * 40, True)
    versioninfo.write_stamp(target, changed)
    assert versioninfo.read_stamp(source) == original
    assert versioninfo.read_stamp(target) == changed


def test_installed_version_uses_its_stamp_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "site-packages" / "maity"
    versioninfo.write_stamp(package / versioninfo.STAMP_FILE, versioninfo.Stamp("a" * 40, True))
    monkeypatch.setattr(versioninfo, "__file__", str(package / "versioninfo.py"))

    def no_git(*args: object) -> str:
        raise AssertionError("an installed wheel must not call git")

    monkeypatch.setattr(versioninfo, "_git", no_git)
    assert versioninfo.version_text("1.0") == "maity 1.0 (build aaaaaaaaaaaa-dirty)"


def test_an_unstamped_install_says_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "site-packages" / "maity"
    monkeypatch.setattr(versioninfo, "__file__", str(package / "versioninfo.py"))
    assert versioninfo.version_text("1.0") == "maity 1.0 (build unknown)"


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("git", 2)])
def test_unavailable_source_git_does_not_claim_a_stale_build(
    source_project: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    package = source_project / "src" / "maity"
    versioninfo.write_stamp(package / versioninfo.STAMP_FILE, versioninfo.Stamp("b" * 40, False))
    monkeypatch.setattr(versioninfo, "__file__", str(package / "versioninfo.py"))

    def unavailable(*args: object) -> str:
        raise error

    monkeypatch.setattr(versioninfo, "_git", unavailable)
    assert versioninfo.version_text("1.0") == "maity 1.0 (build unknown)"


def test_an_editable_checkout_uses_live_git_instead_of_a_stale_stamp(
    source_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = source_project / "src" / "maity"
    head = git(source_project, "rev-parse", "HEAD")
    versioninfo.write_stamp(package / versioninfo.STAMP_FILE, versioninfo.Stamp("b" * 40, False))
    monkeypatch.setattr(versioninfo, "__file__", str(package / "versioninfo.py"))
    assert versioninfo.version_text("1.0") == f"maity 1.0 (build {head[:12]}-dirty)"


def test_version_discovery_runs_only_when_version_is_requested(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def render(version: str) -> str:
        calls.append(version)
        return "maity test (build test)"

    monkeypatch.setattr(versioninfo, "version_text", render)
    cli.build_parser()
    assert calls == []
    with pytest.raises(SystemExit) as exited:
        cli.main(["--version"])
    assert exited.value.code == 0 and calls == [__version__]
    assert capsys.readouterr().out == "maity test (build test)\n"


def test_sdist_to_wheel_preserves_the_build_and_runs_without_git(tmp_path: Path) -> None:
    original = Path(versioninfo.__file__).resolve().parents[2]
    project = tmp_path / "repo" / "cli"
    project.mkdir(parents=True)
    for name in ("setup.py", "pyproject.toml", "README.md", ".gitignore"):
        shutil.copy2(original / name, project / name)
    shutil.copytree(
        original / "src",
        project / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    git(project.parent, "init", "--quiet")
    git(project.parent, "add", ".")
    git(project.parent, "commit", "--quiet", "-m", "source build")
    head = git(project, "rev-parse", "HEAD")
    placeholder = (project / "src" / "maity" / versioninfo.STAMP_FILE).read_bytes()
    output = tmp_path / "dist"
    built = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(output)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    expected = {"revision": head, "dirty": False}
    with tarfile.open(next(output.glob("*.tar.gz"))) as archive:
        member = next(
            m
            for m in archive.getmembers()
            if m.name.endswith("/src/maity/" + versioninfo.STAMP_FILE)
        )
        stream = archive.extractfile(member)
        assert stream is not None and json.load(stream) == expected
    installed = tmp_path / "installed"
    wheel_path = next(output.glob("*.whl"))
    with zipfile.ZipFile(wheel_path) as wheel:
        assert json.loads(wheel.read("maity/" + versioninfo.STAMP_FILE)) == expected
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--target",
            str(installed),
            str(wheel_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    assert (project / "src" / "maity" / versioninfo.STAMP_FILE).read_bytes() == placeholder
    env = {**os.environ, "PATH": "", "PYTHONPATH": str(installed)}
    ran = subprocess.run(
        [str(installed / "bin" / "maity"), "--version"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == f"maity {__version__} (build {head[:12]})"
