"""The delivered Keep the Why skill on the agents' side (runner/skillop.py, skills.deliver,
tsk-7casfxb7cn49): the runner's checked copy put below the agents' home, never through a link,
and handed out only while its manifest is the one the runner recorded.

The runner's copy is built here the way the fetch builds it (the plugin manifest, then the
manifest of every file), without git; test_skills.py covers the fetch itself.
"""

from __future__ import annotations

import base64
import dataclasses
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


def _codex_home(tmp_path: Path) -> tuple[Path, Path]:
    """A placement's scratch below a workspaces root, as scratch.make leaves it; its codex-home."""
    under = tmp_path / "ws"
    place = under / "proj" / ".scratch" / "plc-0003"
    (place / "tmp").mkdir(parents=True)
    return under, place / "codex-home"


def test_codex_gets_the_skill_in_its_own_skills_directory_beside_its_system_skills(
    tmp_path: Path,
) -> None:
    # PR 2 of tsk-7casfxb7cn49, after ops' live check (nte-nqs227hnpqzz): Codex 0.171.0 loads
    # `<CODEX_HOME>/skills/keep-the-why/SKILL.md`; it writes its own `.system/` beside it.
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    under, home = _codex_home(tmp_path)
    (home / "skills" / ".system" / "imagegen").mkdir(parents=True)
    (home / "skills" / ".system" / "imagegen" / "SKILL.md").write_text("codex's own\n")
    document = json.loads(skillop.payload(root.parent, KEY))
    assert skillop.codex_put(str(under), str(home), document) == {"result": "put", "files": 2}
    skill = home / "skills" / "keep-the-why"
    assert (skill / "SKILL.md").read_text() == "---\nname: keep-the-why\n---\n"
    assert (skill / "references" / "help.md").read_text() == "# help\n"
    assert not (skill / ".claude-plugin").exists()  # the skill alone, not the plugin around it
    for path in [skill, *skill.rglob("*")]:
        mode = stat.S_IMODE(path.lstat().st_mode)
        assert mode == (0o755 if path.is_dir() else 0o644), path
    assert (home / "skills" / ".system" / "imagegen" / "SKILL.md").read_text() == "codex's own\n"
    (skill / "planted.md").write_text("planted\n")
    skillop.codex_put(str(under), str(home), document)  # every launch: written whole again
    assert not (skill / "planted.md").exists()
    assert sorted(p.name for p in (home / "skills").iterdir()) == [".system", "keep-the-why"]


@pytest.mark.parametrize("level", ["codex-home", "skills"])
def test_a_link_on_the_way_to_codexs_skills_is_never_written_through(
    tmp_path: Path, level: str
) -> None:
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    under, home = _codex_home(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    if level == "skills":
        home.mkdir()
    (home if level == "codex-home" else home / "skills").symlink_to(elsewhere)
    with pytest.raises(scratchop.OnTheWay):
        skillop.codex_put(str(under), str(home), json.loads(skillop.payload(root.parent, KEY)))
    assert list(elsewhere.iterdir()) == []


def test_a_codex_launch_writes_the_skill_and_a_launch_without_one_writes_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_adapters import _codex_scratch_context

    from maity.runner import adapters, scratch

    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    ctx = _codex_scratch_context(tmp_path / "with")
    (tmp_path / "with" / "ws").mkdir()
    assert ctx.scratch is not None
    scratch.make(ctx.scratch)
    place = ctx.scratch
    ctx = dataclasses.replace(ctx, skill=root, skill_source=root.parent)
    adapters.launch(ctx)
    assert (place / "codex-home" / "skills" / "keep-the-why" / "SKILL.md").is_file()
    plain = _codex_scratch_context(tmp_path / "without")
    (tmp_path / "without" / "ws").mkdir()
    assert plain.scratch is not None
    scratch.make(plain.scratch)
    adapters.launch(plain)
    assert not (plain.scratch / "codex-home" / "skills").exists()


def test_a_codex_skill_that_cannot_be_written_leaves_the_launch_as_it_was(tmp_path: Path) -> None:
    # Codex then keeps MAITY_KTW_SKILL_DIR alone, as before this change.
    from test_adapters import _codex_scratch_context

    from maity.runner import adapters

    ctx = _codex_scratch_context(tmp_path)
    missing = tmp_path / "runner" / "keep-the-why" / KEY  # no copy there
    ctx = dataclasses.replace(ctx, skill=missing / "plugin", skill_source=missing)
    assert adapters.codex_skill(ctx, tmp_path / "home") is False


def test_a_reused_codex_home_loses_the_earlier_skill_when_a_launch_hands_out_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The review of #2093 (ukxh): the same scratch launched again without a skill, and then
    # with one that cannot be written, leaves Codex no copy from the launch before.
    from test_adapters import _codex_scratch_context

    from maity.runner import adapters, scratch

    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    plain = _codex_scratch_context(tmp_path)
    (tmp_path / "ws").mkdir()
    assert plain.scratch is not None
    scratch.make(plain.scratch)
    skill = plain.scratch / "codex-home" / "skills" / "keep-the-why"
    with_skill = dataclasses.replace(plain, skill=root, skill_source=root.parent)
    adapters.launch(with_skill)
    assert (skill / "SKILL.md").is_file()
    adapters.launch(plain)  # no skill named this time
    assert not skill.exists()
    assert (plain.scratch / "codex-home" / "skills").is_dir()  # only the runner's directory
    adapters.launch(with_skill)
    assert (skill / "SKILL.md").is_file()
    missing = tmp_path / "runner" / "keep-the-why" / ("e" * 40 + "-" + "1" * 16)
    broken = dataclasses.replace(plain, skill=missing / "plugin", skill_source=missing)
    adapters.launch(broken)  # named, but no copy to write it from
    assert not skill.exists()


@pytest.mark.parametrize("leaf", ["..", "other", "."])
def test_codexs_skill_goes_only_into_the_scratchs_codex_home(tmp_path: Path, leaf: str) -> None:
    # The review of #2093 (kduz): `<scratch>/..` passed the scratch check on its parent and
    # stepped out of it; only `<scratch>/codex-home` is accepted, by both Codex ops.
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    under, home = _codex_home(tmp_path)
    bad = str(home.parent) + "/" + leaf
    with pytest.raises(OSError, match="codex-home"):
        skillop.codex_put(str(under), bad, json.loads(skillop.payload(root.parent, KEY)))
    with pytest.raises(OSError, match="codex-home"):
        skillop.codex_clear(str(under), bad)
    assert not list(under.rglob("skills"))  # nothing written anywhere below the root


def test_clearing_codexs_skill_follows_no_link_and_answers_for_a_missing_one(
    tmp_path: Path,
) -> None:
    under, home = _codex_home(tmp_path)
    assert skillop.codex_clear(str(under), str(home)) == {"result": "missing"}
    home.mkdir()
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "keep-the-why").mkdir(parents=True)
    (home / "skills").symlink_to(elsewhere)
    with pytest.raises(scratchop.OnTheWay):
        skillop.codex_clear(str(under), str(home))
    assert (elsewhere / "keep-the-why").is_dir()
    (home / "skills").unlink()
    (home / "skills").mkdir()
    (home / "skills" / "keep-the-why").symlink_to(elsewhere / "keep-the-why")
    assert skillop.codex_clear(str(under), str(home)) == {"result": "removed"}
    assert (elsewhere / "keep-the-why").is_dir()  # the link went, never what it named


@pytest.mark.parametrize("change", ["extra", "changed", "missing", "link"])
def test_a_staged_skill_that_does_not_hold_exactly_its_files_is_never_published(
    tmp_path: Path, change: str
) -> None:
    # The review of #2093: the staging is verified before the rename, as `put` verifies.
    wanted = {("SKILL.md",): b"skill\n", ("references", "help.md"): b"# help\n"}
    staged = tmp_path / "staged"
    (staged / "references").mkdir(parents=True)
    (staged / "SKILL.md").write_bytes(b"skill\n")
    (staged / "references" / "help.md").write_bytes(b"# help\n")
    fd = os.open(staged, os.O_RDONLY)
    try:
        skillop._verify_staged(fd, wanted)  # exactly its files: holds
        if change == "extra":
            (staged / "references" / "planted.md").write_text("planted\n")
        elif change == "changed":
            (staged / "SKILL.md").write_bytes(b"other\n")
        elif change == "missing":
            (staged / "references" / "help.md").unlink()
        else:
            (staged / "SKILL.md").unlink()
            (staged / "SKILL.md").symlink_to(tmp_path / "elsewhere.md")
        with pytest.raises(OSError, match="staged skill"):
            skillop._verify_staged(fd, wanted)
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "where, error",
    [
        ("skill_check", UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")),
        ("skill_check", scratchop.Unsupported("host maity has no skill ops")),
        ("skill_check", skillop.OnTheWay(".local below /home/agents is a link")),
        ("payload", skillop.Mismatch("SKILL.md in the skill's copy cannot be read")),
    ],
)  # fmt: skip
def test_every_delivery_error_is_unavailable_so_a_start_goes_on_without_the_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str, error: Exception
) -> None:
    # The review of #2089 (A1893): a decoding error on the ssh answer, or a cached file that
    # turned unreadable between the check and the packaging, must not escape as a failed start.
    runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()

    def fail(*_: object, **__: object) -> Any:
        raise error

    if where == "payload":
        monkeypatch.setattr(skillop, "payload", fail)
    else:
        monkeypatch.setattr(AsUser, where, fail)
    with pytest.raises(skills.Unavailable, match="could not be put below"):
        skills.deliver(AsUser(), home, tmp_path / "runner", tmp_path / "state", SOURCE, COMMIT)


def _cfg(tmp_path: Path, agent_user: str | None = None) -> Any:
    """What `check` and `gc --skills` read of a configuration."""
    from types import SimpleNamespace

    layout = "agent_user" if agent_user else "single"
    local = SimpleNamespace(layout=layout, agent_user=agent_user)
    runner, state_dir = tmp_path / "runner", tmp_path / "state"
    return SimpleNamespace(skills_dir=runner, state_dir=state_dir, local=local)


def test_check_names_each_copy_and_warns_for_one_that_is_not_handed_out(tmp_path: Path) -> None:
    from maity.runner import commands

    report = commands.Report()
    commands._check_skills(report, _cfg(tmp_path))
    none = f"Keep the Why skill: no copy in {tmp_path / 'runner'} yet; a start fetches one"
    assert report.lines == [("ok", none)]
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    report = commands.Report()
    commands._check_skills(report, _cfg(tmp_path))
    assert [level for level, _ in report.lines] == ["ok"]
    assert COMMIT[:12] in report.lines[0][1] and "checked" in report.lines[0][1]
    (tmp_path / "state" / skills.ANCHORS).unlink()  # a state directory made anew
    assert skills.copies(tmp_path / "runner", tmp_path / "state")[0][3] == "unrecorded"
    skill_md = root / "skills" / "keep-the-why" / "SKILL.md"
    os.chmod(skill_md, 0o644)
    skill_md.write_text("changed\n")
    report = commands.Report()
    commands._check_skills(report, _cfg(tmp_path))
    ((level, text),) = report.lines
    assert level == "warn" and "does not match its manifest" in text and "not handed out" in text
    assert not report.failed  # a warning, never an error: a start fetches again or goes without


def test_gc_skills_lists_then_removes_only_what_nothing_names_or_runs_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from maity.runner import operate

    runner_copy(tmp_path / "runner", tmp_path / "state")
    other = "f" * 40 + "-" + "0" * 16  # an older pin's copy, a session still running with it
    gone = "e" * 40 + "-" + "1" * 16  # no placement names it, no session runs with it
    for name in (other, gone):
        (tmp_path / "runner" / "keep-the-why" / name / "plugin").mkdir(parents=True)
        skills._record(tmp_path / "state", name, "0" * 64)
    monkeypatch.setattr(operate, "_skills_running", lambda cfg: {other})
    listing = [(n, "", "", "ok") for n in sorted((KEY, other, gone))]
    monkeypatch.setattr(skills, "copies", lambda d, s: listing)
    operate._collect_skills(_cfg(tmp_path), {KEY}, remove=False)
    listed = capsys.readouterr().out
    assert gone in listed and KEY not in listed and other not in listed
    assert (tmp_path / "runner" / "keep-the-why" / gone).is_dir()  # only listed
    operate._collect_skills(_cfg(tmp_path), {KEY}, remove=True)
    left = sorted(p.name for p in (tmp_path / "runner" / "keep-the-why").iterdir())
    assert left == sorted([KEY, other])
    assert set(skills._anchors(tmp_path / "state")) == {KEY, other}  # its record went with it


@pytest.mark.parametrize(
    "records, expected",
    [
        ({"plc-1": {"skill_key": KEY}, "plc-2": {"skill_key": None}}, {KEY}),
        ({"plc-1": {"skill_key": KEY}}, None),  # plc-2 runs with no record: not saved yet
        ({"plc-1": {"skill_key": KEY}, "plc-2": {"id": "plc-2"}}, None),  # an older record
        ({"plc-1": {"skill_key": KEY}, "plc-2": {"skill_key": 7}}, None),
    ],
)
def test_gc_keeps_everything_while_a_running_sessions_copy_is_not_known(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    records: dict[str, Any],
    expected: set[str] | None,
) -> None:
    # The review of #2093 (ukxh): a session from before `skill_key`, or one whose record the
    # service had not saved yet, may run with any copy; none of them goes by that.
    from maity import state
    from maity.runner import operate, supervisor

    monkeypatch.setattr(operate, "_running", lambda cfg, what="scratch": {"plc-1", "plc-2"})
    state.save_state(tmp_path / "state", records, name=supervisor.ACTUAL_FILE)
    assert operate._skills_running(_cfg(tmp_path)) == expected


def test_gc_keeps_everything_when_an_active_placements_pin_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maity import state
    from maity.runner import operate, serve, supervisor

    placements: list[dict[str, Any]] = [
        {"id": f"plc-{n}", "project_id": "prj-1", "workspace": {"clone": "c"}, "agent": {}}
        for n in (1, 2)
    ]
    service = type("S", (), {"client": type("C", (), {"call": staticmethod(
        lambda method, path: {"items": placements})})()})()  # fmt: skip
    monkeypatch.setattr(serve, "open_service", lambda cfg, st: service)
    monkeypatch.setattr(state, "load_state", lambda d, name: {})
    monkeypatch.setattr(supervisor, "valid", lambda p: True)

    def named(p: dict[str, Any]) -> tuple[str, str] | None:
        if p["id"] == "plc-2":
            raise skills.Unavailable("a pin that is not a commit")
        return (SOURCE, COMMIT)

    monkeypatch.setattr(skills, "named", named)
    monkeypatch.setattr(skills, "key", lambda source, commit: KEY)
    _pairs, _agents, _ids, keys = operate._active_with_skills(_cfg(Path("unused")))
    assert keys is None


def test_gc_skills_keeps_everything_when_the_hubs_list_is_partial(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from maity.runner import operate

    runner_copy(tmp_path / "runner", tmp_path / "state")
    operate._collect_skills(_cfg(tmp_path), None, remove=True)
    assert "every copy is kept" in capsys.readouterr().out
    assert (tmp_path / "runner" / "keep-the-why" / KEY).is_dir()


def test_gc_skills_removes_the_agents_copies_in_the_agent_user_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity.runner import operate

    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    skillop.put(str(home), json.loads(skillop.payload(root.parent, KEY)))
    holder = skillop.agent_copy(home, KEY).parent
    (holder / ("e" * 40 + "-" + "1" * 16)).mkdir()  # an older copy, nothing names it
    (holder / ".put-left0ver").mkdir()  # a staging directory a crash left
    (holder / "notes").mkdir()  # not the runner's: left alone

    class Agents(AsUser):
        def home(self) -> Path:
            return home

    agents = Agents("agents")
    monkeypatch.setattr(operate, "_as_user", lambda cfg: agents)
    monkeypatch.setattr(operate, "_skills_running", lambda cfg: set())

    # In-process here: the op the sudo path starts (skillop.remove), as the agents' user would.
    def remove(self: AsUser, h: Path, keep: set[str]) -> list[str]:
        return [str(n) for n in skillop.remove(str(h), sorted(keep))["names"]]  # type: ignore

    monkeypatch.setattr(Agents, "skill_remove", remove)
    operate._collect_skills(_cfg(tmp_path, "agents"), {KEY}, remove=True)
    assert sorted(p.name for p in holder.iterdir()) == [KEY, "notes"]


# Evaluated at import, which Windows collection does too: no geteuid there (the review of #2089).
needs_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root reads every directory whatever its mode",
)


@needs_permissions
def test_a_directory_the_check_cannot_read_is_a_mismatch_on_both_sides(tmp_path: Path) -> None:
    # The review of #2089: a directory below the plugin root that cannot be opened is never
    # skipped, on the agents' copy (skillop.check) and the runner's own (skills.verify).
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    skillop.put(str(home), json.loads(skillop.payload(root.parent, KEY)))
    for plugin in (root, skillop.agent_copy(home, KEY) / "plugin"):
        closed = plugin / "skills" / "keep-the-why" / "extra"
        closed.mkdir()
        (closed / "more.md").write_text("not in the manifest\n")
        os.chmod(closed, 0o111)  # noqa: S103 - searchable, not readable: the case under test
    try:
        found = skillop.check(str(home), KEY, SOURCE, COMMIT)
        assert found["result"] == "mismatch"
        with pytest.raises(skills.Unavailable):
            skills.verify(root.parent, SOURCE, COMMIT)
    finally:
        for plugin in (root, skillop.agent_copy(home, KEY) / "plugin"):
            os.chmod(plugin / "skills" / "keep-the-why" / "extra", 0o755)  # noqa: S103


def test_a_directory_the_manifest_does_not_need_is_a_mismatch(tmp_path: Path) -> None:
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    (root / "skills" / "keep-the-why" / "empty").mkdir()
    with pytest.raises(skills.Unavailable, match="not a directory of the skill"):
        skills.verify(root.parent, SOURCE, COMMIT)


@needs_permissions
@pytest.mark.parametrize("which", ["subdirectory", "copy"])
def test_a_restrictive_old_copy_is_replaced_and_nothing_is_left_beside(
    tmp_path: Path, which: str
) -> None:
    # The review of #2089: an old copy holding a 0555 directory, or itself 0000, is replaced,
    # the put does not fail after the swap, and no set-aside directory stays.
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    home = tmp_path / "agents"
    home.mkdir()
    document = json.loads(skillop.payload(root.parent, KEY))
    skillop.put(str(home), document)
    copy = skillop.agent_copy(home, KEY)
    if which == "subdirectory":
        references = copy / "plugin" / "skills" / "keep-the-why" / "references"
        os.chmod(references, 0o555)  # noqa: S103 - a read-only directory left behind
    else:
        os.chmod(copy, 0o000)
    assert skillop.put(str(home), document)["result"] == "put"
    assert skillop.check(str(home), KEY, SOURCE, COMMIT)["result"] == "ok"
    assert sorted(p.name for p in copy.parent.iterdir()) == [KEY]


@pytest.mark.parametrize("change", ["nul", "empty"])
def test_a_nul_name_or_an_empty_payload_is_refused_and_main_answers_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    change: str,
) -> None:  # fmt: skip
    document = _document(tmp_path)
    manifest = json.loads(base64.b64decode(document["manifest"]))
    if change == "nul":
        name = "plugin/skills/keep-the-why/a\0b.md"
        manifest["files"][name] = hashlib.sha256(b"x").hexdigest()
        document["files"][name] = _encode(b"x")
    else:
        manifest["files"], document["files"] = {}, {}
    document["manifest"] = _encode(json.dumps(manifest).encode())
    home = tmp_path / "agents"
    home.mkdir()
    with pytest.raises(OSError):
        skillop.put(str(home), document)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(document)))
    assert skillop.main(["put", "--home", str(home)]) == 1
    assert "skillop:" in capsys.readouterr().err
    assert list(home.iterdir()) == []


def test_a_document_over_its_bound_is_not_read_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "agents"
    home.mkdir()
    monkeypatch.setattr(skillop, "DOCUMENT_MAX", 16)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"key": "' + "a" * 64 + '"}'))
    assert skillop.main(["put", "--home", str(home)]) == 1
    assert list(home.iterdir()) == []


def test_a_document_that_cannot_be_read_or_decoded_is_an_answer_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The review of #2089 (A1904): stdin decoded strictly, holding invalid UTF-8.
    home = tmp_path / "agents"
    home.mkdir()
    stdin = io.TextIOWrapper(io.BytesIO(b"\xff"), encoding="utf-8", errors="strict")
    monkeypatch.setattr("sys.stdin", stdin)
    assert skillop.main(["put", "--home", str(home)]) == 1
    assert "skillop:" in capsys.readouterr().err
    assert list(home.iterdir()) == []


@pytest.mark.parametrize("text", ["not json", '{"files": 3}', '{"source": "x"}'])
def test_a_runner_manifest_tampered_since_the_check_is_a_mismatch_when_packaged(
    tmp_path: Path, text: str
) -> None:
    # The review of #2089: packaging maps a broken manifest to Mismatch, which deliver turns
    # into Unavailable, never a KeyError or TypeError out of the start.
    root = runner_copy(tmp_path / "runner", tmp_path / "state")
    manifest = root.parent / skillop.MANIFEST
    os.chmod(manifest, 0o644)
    manifest.write_text(text)
    with pytest.raises(skillop.Mismatch, match="not a manifest the runner wrote"):
        skillop.payload(root.parent, KEY)


def test_an_old_host_maity_without_the_ops_is_unsupported() -> None:
    import subprocess

    done = subprocess.CompletedProcess(["maity"], 2, "", "maity runner: invalid choice 'skillop'")
    with pytest.raises(scratchop.Unsupported, match="no skill ops"):
        AsUser._skill_answer(done, "check", KEY)
    with pytest.raises(skillop.OnTheWay):
        AsUser._skill_answer(subprocess.CompletedProcess(["maity"], 4, "", ""), "put", "")
