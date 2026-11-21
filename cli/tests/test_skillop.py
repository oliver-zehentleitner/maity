"""The delivered Keep the Why skill on the agents' side (runner/skillop.py, skills.deliver,
tsk-7casfxb7cn49): the runner's checked copy put below the agents' home, never through a link,
and handed out only while its manifest is the one the runner recorded.

The runner's copy is built here the way the fetch builds it (the plugin manifest, then the
manifest of every file), without git; test_skills.py covers the fetch itself.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from conftest import posix

from maity.runner import scratchop, skillop, skills
from maity.runner.asuser import AsUser

pytestmark = posix

SOURCE = "https://github.com/oliver-zehentleitner/keep-the-why/tree/v0.20.3/skills/keep-the-why"
COMMIT = "2771046616a3c6bcd62916ed072f71feb5afd222"
KEY = skills.key(SOURCE, COMMIT)


def runner_copy(skills_dir: Path, state_dir: Path) -> Path:
    """The runner's checked copy of SOURCE at COMMIT, recorded in `state_dir` as ensure records
    it; its plugin root."""
    staged = skills_dir / skills.NAME / KEY
    skill = staged / skills.PLUGIN / "skills" / skills.NAME
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: keep-the-why\n---\n")
    (skill / "references" / "help.md").write_text("# help\n")
    skills._write_plugin(staged, SOURCE, COMMIT)
    skills._write_manifest(staged, SOURCE, COMMIT)
    skills._record(state_dir, KEY, skills._sha256(staged / skills.MANIFEST))
    return staged / skills.PLUGIN


def test_a_put_copy_lies_below_the_agents_home_in_plain_read_only_files(tmp_path: Path) -> None:
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    answer = skillop.put(str(home), json.loads(skillop.payload(root.parent, KEY)))
    copy = home / ".local" / "share" / "maity-runner" / "skills" / "keep-the-why" / KEY
    assert copy == skillop.agent_copy(home, KEY)
    recorded = skills._anchors(tmp_path / "state")[KEY]
    assert answer == {"result": "put", "digest": recorded}
    assert (copy / "plugin" / "skills" / "keep-the-why" / "SKILL.md").read_text().startswith("---")
    for path in [copy, *copy.rglob("*")]:
        mode = stat.S_IMODE(path.lstat().st_mode)
        assert mode == (0o755 if path.is_dir() else 0o644), path
    assert skillop.check(str(home), KEY, SOURCE, COMMIT) == {"result": "ok", "digest": recorded}
    assert sorted(p.name for p in copy.parent.iterdir()) == [KEY]  # no staging left


def test_a_copy_already_there_is_replaced_whole(tmp_path: Path) -> None:
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    document = json.loads(skillop.payload(root.parent, KEY))
    skillop.put(str(home), document)
    copy = skillop.agent_copy(home, KEY)
    skill_md = copy / "plugin" / "skills" / "keep-the-why" / "SKILL.md"
    os.chmod(skill_md, 0o644)
    skill_md.write_text("changed on the agents' side\n")
    (copy / "plugin" / "planted.md").write_text("planted\n")
    assert skillop.check(str(home), KEY, SOURCE, COMMIT)["result"] == "mismatch"
    skillop.put(str(home), document)
    assert skillop.check(str(home), KEY, SOURCE, COMMIT)["result"] == "ok"
    assert not (copy / "plugin" / "planted.md").exists()
    assert sorted(p.name for p in copy.parent.iterdir()) == [KEY]


def test_check_says_missing_mismatch_or_ok(tmp_path: Path) -> None:
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    assert skillop.check(str(home), KEY, SOURCE, COMMIT) == {"result": "missing"}
    skillop.put(str(home), json.loads(skillop.payload(root.parent, KEY)))
    other = SOURCE.replace("v0.20.3", "v0.20.4")
    found = skillop.check(str(home), KEY, other, COMMIT)
    assert found["result"] == "mismatch" and "is not of" in str(found["why"])
    plugin = skillop.agent_copy(home, KEY) / "plugin"
    os.mkfifo(plugin / "skills" / "keep-the-why" / "pipe.md")  # returns at once, never waits
    assert skillop.check(str(home), KEY, SOURCE, COMMIT)["result"] == "mismatch"


@pytest.mark.parametrize("level", [".local", "share", "maity-runner", "skills", "keep-the-why"])
def test_a_link_below_the_agents_home_is_never_written_through(tmp_path: Path, level: str) -> None:
    # Every directory from the agents' home down is opened without following a link: a link
    # planted at any level leads nothing out, and nothing is written where it points.
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    names = [".local", "share", "maity-runner", "skills", "keep-the-why"]
    parent = home.joinpath(*names[: names.index(level)])
    parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (parent / level).symlink_to(elsewhere)
    document = json.loads(skillop.payload(root.parent, KEY))
    with pytest.raises(skillop.OnTheWay):
        skillop.put(str(home), document)
    with pytest.raises(skillop.OnTheWay):
        skillop.check(str(home), KEY, SOURCE, COMMIT)
    assert list(elsewhere.iterdir()) == []


def test_a_copy_that_is_a_link_is_a_mismatch_not_followed(tmp_path: Path) -> None:
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    holder = skillop.agent_copy(home, KEY).parent
    holder.mkdir(parents=True)
    (holder / KEY).symlink_to(root.parent)  # the runner's own, perfectly valid copy
    assert skillop.check(str(home), KEY, SOURCE, COMMIT)["result"] == "mismatch"


def _document(tmp_path: Path) -> dict[str, Any]:
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    loaded: dict[str, Any] = json.loads(skillop.payload(root.parent, KEY))
    return loaded


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.mark.parametrize(
    "change, why",
    [
        (lambda d: d["files"].update({"plugin/extra.md": _encode(b"x")}), "exactly the files"),
        (lambda d: d["files"].update({"plugin/skills/keep-the-why/SKILL.md": _encode(b"x")}),
         "does not match its manifest"),
        (lambda d: d.update({"key": "f" * 40 + "-" + "0" * 16}), "not the one of its source"),
        (lambda d: d.update({"key": "../escape"}), "not one the runner makes"),
        (lambda d: d.update({"manifest": "not base64!"}), "not one the runner sends"),
    ],
)  # fmt: skip
def test_a_payload_that_is_not_the_runners_copy_is_refused_before_anything_is_written(
    tmp_path: Path, change: Any, why: str
) -> None:
    document = _document(tmp_path)
    change(document)
    home = tmp_path / "agents"
    home.mkdir()
    with pytest.raises(OSError, match=why):
        skillop.put(str(home), document)
    assert list(home.iterdir()) == []


@pytest.mark.parametrize("path", ["plugin/../escape.md", "other/SKILL.md", "plugin/.git/config"])
def test_a_path_the_runner_does_not_write_is_refused(tmp_path: Path, path: str) -> None:
    # A manifest that names it, with the right hash: still never written.
    document = _document(tmp_path)
    manifest = json.loads(base64.b64decode(document["manifest"]))
    manifest["files"][path] = hashlib.sha256(b"x").hexdigest()
    document["manifest"] = _encode(json.dumps(manifest).encode())
    document["files"][path] = _encode(b"x")
    home = tmp_path / "agents"
    home.mkdir()
    with pytest.raises(OSError, match="a path the runner does not write"):
        skillop.put(str(home), document)
    assert list(home.iterdir()) == []


def test_the_entry_point_runs_the_skill_ops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `python -I -m maity.runner.skillop` and an ssh host's `maity runner skillop` both run main.
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    monkeypatch.setattr("sys.stdin", io.StringIO(skillop.payload(root.parent, KEY)))
    assert skillop.main(["put", "--home", str(home)]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "put"
    check = ["check", "--home", str(home), KEY, SOURCE, COMMIT]
    assert skillop.main(check) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "ok"
    # A usage error is what an old host's maity answers too (AsUser._skill_answer).
    assert skillop.main(["check", "--home", str(home)]) == 2
    (home / ".local").rename(tmp_path / "moved")
    (home / ".local").symlink_to(tmp_path / "moved")
    assert skillop.main(check) == skillop.LINK


def test_the_cli_hands_its_arguments_to_skillop_as_they_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from maity import cli

    home = tmp_path / "agents"
    home.mkdir()
    code = cli.main(["runner", "skillop", "check", "--home", str(home), KEY, SOURCE, COMMIT])
    assert code == 0 and json.loads(capsys.readouterr().out) == {"result": "missing"}


def test_deliver_puts_the_copy_once_and_then_only_checks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    agents = AsUser()  # in-process: the ops are the same that sudo or ssh start
    args = (agents, home, tmp_path / "runner", tmp_path / "state", SOURCE, COMMIT)
    root = skills.deliver(*args)
    assert root == skillop.agent_copy(home, KEY) / "plugin"
    assert (root / "skills" / "keep-the-why" / "SKILL.md").is_file()

    def no_put(*_: object) -> dict[str, Any]:
        raise AssertionError("put again")

    monkeypatch.setattr(AsUser, "skill_put", no_put)
    assert skills.deliver(*args) == root


def test_deliver_puts_a_changed_agents_copy_again(tmp_path: Path) -> None:
    runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    args = (AsUser(), home, tmp_path / "runner", tmp_path / "state", SOURCE, COMMIT)
    root = skills.deliver(*args)
    skill_md = root / "skills" / "keep-the-why" / "SKILL.md"
    os.chmod(skill_md, 0o644)
    skill_md.write_text("rewritten by the agents' user\n")
    assert skills.deliver(*args) == root
    assert skill_md.read_text() == "---\nname: keep-the-why\n---\n"


def test_deliver_hands_out_nothing_the_runner_did_not_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    args = (AsUser(), home, tmp_path / "runner", tmp_path / "state", SOURCE, COMMIT)

    def put_other(self: AsUser, home: Path, payload: str) -> dict[str, Any]:
        return {"result": "put", "digest": "0" * 64}

    monkeypatch.setattr(AsUser, "skill_put", put_other)
    with pytest.raises(skills.Unavailable, match="not the one the runner fetched"):
        skills.deliver(*args)


def test_an_old_host_maity_without_the_ops_is_unsupported() -> None:
    import subprocess

    done = subprocess.CompletedProcess(["maity"], 2, "", "maity runner: invalid choice 'skillop'")
    with pytest.raises(scratchop.Unsupported, match="no skill ops"):
        AsUser._skill_answer(done, "check", KEY)
    with pytest.raises(skillop.OnTheWay):
        AsUser._skill_answer(subprocess.CompletedProcess(["maity"], 4, "", ""), "put", "")
