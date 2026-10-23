"""`maity chats`, `maity chat`, `maity say --chat/--attach` and `maity files` (§8.7, §9, §13)
against the fake hub."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli

P = "/api/v1/projects/maity"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GROUP: dict[str, Any] = {
    "id": "cnv-0007", "kind": "group", "title": "Release 0.2 go/no-go",
    "participants": [{"member_id": "hum-m", "kind": "human", "handle": "maintainer"},
                     {"member_id": "agt-b", "kind": "agent", "handle": "agent-b"}],
    "observers": [], "access": "participant", "closed_at": None,
    "last_message_at": "2026-10-21T13:30:00Z", "unread": 2, "mentions_unread": 1,
    "last_message": {"seq": 5020, "from": "hum-m", "body": "tag?", "sent_at": "x",
                     "redacted": False},
}  # fmt: skip


def message(seq: int, body: str | None = "hi", **extra: Any) -> dict[str, Any]:
    return {"id": f"evt-{seq}", "seq": seq, "conversation_id": "cnv-0007", "from": "hum-m",
            "to": "cnv-0007", "body": body, "sent_at": "2026-10-21T13:30:00Z", "mentions": [],
            "attachments": [], **extra}  # fmt: skip


def attachment(aid: str = "att-0042", **extra: Any) -> dict[str, Any]:
    return {"id": aid, "name": "build-log.txt", "size": 5, "type": "text/plain", "kind": "file",
            "sha256": hashlib.sha256(b"hello").hexdigest(), "width": None, "height": None,
            "uploaded_by": "agt-b", "message_seq": None, "deleted_at": None, **extra}  # fmt: skip


def listing(*items: dict[str, Any]) -> Any:
    return lambda s: (200, {"items": list(items), "next_cursor": None})


def query(seen: fakehub.Seen) -> dict[str, str]:
    return dict(p.partition("=")[::2] for p in seen.query.split("&") if p)


# --- chats ---------------------------------------------------------------------------------------


def test_chats_prints_one_line_per_conversation_cleaned(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = {**GROUP, "title": "go\x1b]52;c;aGk=\x07"}
    direct = {**GROUP, "id": "agt-b", "kind": "direct", "title": None, "unread": 0,
              "mentions_unread": 0}  # fmt: skip
    fake.routes[("GET", f"{P}/conversations")] = listing(hostile, direct)
    assert cli.main(["chats"]) == cli.EXIT_OK
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("cnv-0007  group  go\\x1b]52;c;aGk=\\x07  maintainer, agent-b")
    assert out[0].endswith("unread 2, mentions 1")
    assert out[1] == "agt-b  direct  -  maintainer, agent-b  unread 0, mentions 0"


def test_chats_follows_every_page_and_stops_on_a_repeated_cursor(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    def page(seen: fakehub.Seen) -> tuple[Any, ...]:
        if "cursor=c2" in seen.query:
            return 200, {"items": [{**GROUP, "id": "cnv-0008"}], "next_cursor": None}
        return 200, {"items": [GROUP], "next_cursor": "c2"}

    fake.routes[("GET", f"{P}/conversations")] = page
    assert cli.main(["chats", "--json"]) == cli.EXIT_OK
    assert [c["id"] for c in json.loads(capsys.readouterr().out)] == ["cnv-0007", "cnv-0008"]
    fake.routes[("GET", f"{P}/conversations")] = lambda s: (
        200, {"items": [], "next_cursor": "same"})  # fmt: skip
    assert cli.main(["chats"]) == cli.EXIT_ERROR


# --- chat ----------------------------------------------------------------------------------------


def test_chat_reads_the_unread_from_the_first_one_and_shows_what_arrived(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{P}/conversations")] = listing(GROUP)

    def messages(seen: fakehub.Seen) -> tuple[Any, ...]:
        q = query(seen)
        if "before" in q:  # the last `unread`: only to find where they start
            assert q == {"before": "5021", "limit": "2"}
            return 200, {"items": [message(5010), message(5020)], "earlier": 5001}
        assert q == {"after": "5009", "limit": "200"}  # the read that marks them read
        late = message(5030, None, attachments=[attachment(message_seq=5030)])
        return 200, {"items": [message(5010), message(5020), late]}

    fake.routes[("GET", f"{P}/conversations/cnv-0007/messages")] = messages
    assert cli.main(["chat", "cnv-0007"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "5010  maintainer  2026-10-21T13:30:00Z\n> hi\n" in out
    assert "5030  maintainer" in out and "> (redacted)" in out
    assert "  attachment att-0042  build-log.txt  5 bytes  text/plain" in out
    assert out.rstrip().endswith("before these: maity chat cnv-0007 --before 5010")


def test_chat_caps_the_unread_at_fifty_and_says_what_it_left_out(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{P}/conversations")] = listing({**GROUP, "unread": 120})
    fake.routes[("GET", f"{P}/conversations/cnv-0007/messages")] = lambda s: (
        200, {"items": [message(4000 + i) for i in range(50)], "earlier": 3990}
        if "before" in s.query else {"items": []})  # fmt: skip
    assert cli.main(["chat", "cnv-0007"]) == cli.EXIT_OK
    reads = [query(s) for s in fake.signed() if s.path.endswith("/messages")]
    assert reads == [{"before": "5021", "limit": "50"}, {"after": "3999", "limit": "200"}]
    out = capsys.readouterr().out
    assert (
        "70 earlier unread messages, marked read unshown: maity chat cnv-0007 --before 4000" in out
    )


def test_chat_pages_on_until_a_short_page(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{P}/conversations")] = listing({**GROUP, "unread": 1})

    def messages(seen: fakehub.Seen) -> tuple[Any, ...]:
        q = query(seen)
        if "before" in q:
            return 200, {"items": [message(5020)], "earlier": 5001}
        start = int(q["after"]) + 1
        count = 200 if start < 6000 else 3
        return 200, {"items": [message(start + i) for i in range(count)]}

    fake.routes[("GET", f"{P}/conversations/cnv-0007/messages")] = messages
    assert cli.main(["chat", "cnv-0007", "--json"]) == cli.EXIT_OK
    afters = [query(s)["after"] for s in fake.signed() if "after=" in s.query]
    assert afters == ["5019", "5219", "5419", "5619", "5819", "6019"]


def test_chat_with_nothing_unread_fetches_nothing(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{P}/conversations")] = listing({**GROUP, "unread": 0})
    assert cli.main(["chat", "cnv-0007"]) == cli.EXIT_OK
    assert not [s for s in fake.signed() if s.path.endswith("/messages")]
    out = capsys.readouterr().out
    assert "no unread messages; earlier: maity chat cnv-0007 --before 5021" in out


DIRECT_TODAY = {"agent_id": "agt-b", "last_message_at": "x", "unread": 2,
                "last_message": {"seq": 4300, "from": "hum-1", "body": "?", "sent_at": "x",
                                 "redacted": False}}  # fmt: skip


def test_chat_refuses_a_before_the_hub_ignored(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    # Today's hub answers a direct conversation from its start, without `earlier`.
    fake.routes[("GET", f"{P}/conversations")] = listing(DIRECT_TODAY)
    fake.routes[("GET", f"{P}/conversations/agt-b/messages")] = lambda s: (
        200, {"items": [message(3), message(9000)], "cursor": 9000})  # fmt: skip
    assert cli.main(["chat", "agt-b", "--before", "4000"]) == cli.EXIT_ERROR
    assert "does not page back" in capsys.readouterr().err


def test_chats_lists_a_direct_item_of_the_hub_as_it_is_today(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{P}/conversations")] = listing(DIRECT_TODAY)
    assert cli.main(["chats"]) == cli.EXIT_OK
    assert capsys.readouterr().out == "agt-b  direct  -  -  unread 2, mentions 0\n"


def test_chat_direct_reads_after_the_event_cursor_and_marks_nothing(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    from maity import state

    directory = state.resolve_state_dir()
    state.save_state(directory, {**state.load_state(directory), "cursor": 4231})
    fake.routes[("GET", f"{P}/conversations")] = listing(DIRECT_TODAY)
    fake.routes[("GET", f"{P}/conversations/agt-b/messages")] = lambda s: (
        200, {"items": [message(4290 + i) for i in range(11)], "cursor": 4300})  # fmt: skip
    assert cli.main(["chat", "agt-b", "--limit", "4"]) == cli.EXIT_OK
    reads = [query(s) for s in fake.signed() if s.path.endswith("/messages")]
    assert reads == [{"after": "4231", "limit": "200"}]  # never `before` on a direct chat
    out = capsys.readouterr().out
    assert "4296  hum-m" not in out and "4297  hum-m" in out and "4300  hum-m" in out
    assert (
        "7 earlier messages after your event cursor not shown: maity chat agt-b --after 4231" in out
    )
    assert "count as read when `maity wait` or `maity resume`" in out


def test_chat_json_escapes_what_a_terminal_would_act_on(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{P}/conversations")] = listing(GROUP)
    fake.routes[("GET", f"{P}/conversations/cnv-0007/messages")] = lambda s: (
        200, {"items": [message(5, "\u009b31m\u202eboo")]})  # fmt: skip
    assert cli.main(["chat", "cnv-0007", "--after", "1", "--json"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "\u009b" not in out and "\u202e" not in out and "\\u009b31m" in out


def test_chat_before_pages_back_and_names_the_next_page(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{P}/conversations")] = listing(GROUP)
    fake.routes[("GET", f"{P}/conversations/cnv-0007/messages")] = lambda s: (
        200, {"items": [message(4100)], "earlier": 4090})  # fmt: skip
    assert cli.main(["chat", "cnv-0007", "--before", "4200", "--limit", "10"]) == cli.EXIT_OK
    assert query(fake.signed()[-1]) == {"before": "4200", "limit": "10"}
    assert "earlier: maity chat cnv-0007 --before 4090" in capsys.readouterr().out


def test_chat_not_in_the_list(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{P}/conversations")] = listing()
    assert cli.main(["chat", "cnv-0099"]) == cli.EXIT_ERROR


@pytest.mark.parametrize(
    "argv",
    [["chat", "c", "--after", "1", "--before", "2"], ["chat", "c", "--limit", "201"],
     ["chat", "c", "--limit", "0"]],
)  # fmt: skip
def test_chat_flags_are_checked(joined: Path, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(argv)
    assert exited.value.code == cli.EXIT_USAGE


# --- say --chat / --attach -----------------------------------------------------------------------


def test_say_chat_posts_into_the_conversation(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/conversations/cnv-0007/messages")] = lambda s: (
        201, message(5040))  # fmt: skip
    assert cli.main(["say", "--chat", "cnv-0007", "yes, tagging now"]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"body": "yes, tagging now"}


@pytest.mark.parametrize(
    "argv",
    [["say", "--chat", "cnv-0007", "agt-a", "hi"], ["say", "--chat", "cnv-0007", "hi",
     "--type", "notice"], ["say", "--chat", "cnv-0007"], ["say", "all", "--type", "notice"]],
)  # fmt: skip
def test_say_chat_refuses_what_does_not_apply(joined: Path, argv: list[str]) -> None:
    assert cli.main(argv) == cli.EXIT_USAGE


def test_say_attach_uploads_then_names_the_files(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    shot, log = tmp_path / "shot.png", tmp_path / "build log.txt"
    shot.write_bytes(PNG)
    log.write_bytes(b"hello")
    ids = iter(["att-0001", "att-0002"])
    fake.routes[("POST", f"{P}/attachments")] = lambda s: (201, attachment(next(ids)))
    fake.routes[("POST", f"{P}/events")] = lambda s: (201, {"seq": 7})
    argv = ["say", "all", "", "--type", "notice", "--attach", str(shot), "--attach", str(log)]
    assert cli.main(argv) == cli.EXIT_OK
    up1, up2, post = fake.signed()
    assert up1.query == "name=shot.png" and up1.headers["content-type"] == "image/png"
    assert up1.body == PNG and len(up1.headers["idempotency-key"]) >= 16
    assert up2.query == "name=build%20log.txt"
    assert up2.headers["content-type"] == "application/octet-stream"
    assert post.json()["attachments"] == ["att-0001", "att-0002"] and post.json()["body"] == ""


def test_say_attach_to_the_chat(joined: Path, fake: fakehub.FakeHub, tmp_path: Path) -> None:
    (tmp_path / "a.gif").write_bytes(b"GIF89a" + b"\x00" * 10)
    fake.routes[("POST", f"{P}/attachments")] = lambda s: (201, attachment())
    fake.routes[("POST", f"{P}/conversations/cnv-0007/messages")] = lambda s: (201, message(9))
    argv = ["say", "--chat", "cnv-0007", "see", "--attach", str(tmp_path / "a.gif")]
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[0].headers["content-type"] == "image/gif"
    assert fake.signed()[-1].json() == {"body": "see", "attachments": ["att-0042"]}


def test_a_failed_upload_sends_nothing_and_deletes_what_went_up(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_bytes(b"x")
    calls = iter(
        [
            (201, attachment("att-0001")),
            (409, {"error": {"code": "attachment_quota", "message": "q", "details": {}}}),
        ]
    )
    fake.routes[("POST", f"{P}/attachments")] = lambda s: next(calls)  # fmt: skip
    fake.routes[("DELETE", f"{P}/attachments/att-0001")] = lambda s: (200, attachment("att-0001"))
    argv = ["say", "human", "hi", "--attach", str(tmp_path / "a.txt"),
            "--attach", str(tmp_path / "b.txt")]  # fmt: skip
    assert cli.main(argv) == cli.EXIT_ERROR
    assert [(s.method, s.path.rsplit("/", 1)[-1]) for s in fake.signed()] == [
        ("POST", "attachments"), ("POST", "attachments"), ("DELETE", "att-0001")]  # fmt: skip


def test_a_refused_post_deletes_the_uploads(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    (tmp_path / "a.txt").write_bytes(b"x")
    fake.routes[("POST", f"{P}/attachments")] = lambda s: (201, attachment())
    fake.routes[("POST", f"{P}/events")] = lambda s: (
        409, {"error": {"code": "project_closed", "message": "c", "details": {}}})  # fmt: skip
    fake.routes[("DELETE", f"{P}/attachments/att-0042")] = lambda s: (200, attachment())
    argv = ["say", "all", "x", "--type", "notice", "--attach", str(tmp_path / "a.txt")]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert fake.signed()[-1].method == "DELETE"


def test_too_large_or_too_many_files_send_nothing(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    big = tmp_path / "big.bin"
    with big.open("wb") as fh:
        fh.truncate(cli.ATTACHMENT_MAX + 1)
    small = tmp_path / "small.txt"
    small.write_bytes(b"x")
    argv = ["say", "human", "x", "--attach", str(small), "--attach", str(big)]
    assert cli.main(argv) == cli.EXIT_ERROR  # checked before the first upload
    assert cli.main(["say", "human", "x", *["--attach", str(big)] * 11]) == cli.EXIT_USAGE
    assert cli.main(["files", "put", str(big)]) == cli.EXIT_REFUSED
    assert not fake.signed()


# --- files put / get -----------------------------------------------------------------------------


def test_files_put_prints_the_pending_id(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "r.txt").write_bytes(b"hello")
    fake.routes[("POST", f"{P}/attachments")] = lambda s: (201, attachment())
    assert cli.main(["files", "put", str(tmp_path / "r.txt"), "--name", "report.txt"]) == 0
    assert fake.signed()[-1].query == "name=report.txt"
    assert capsys.readouterr().out.startswith("pending att-0042  build-log.txt  5 bytes")


@pytest.fixture
def served(fake: fakehub.FakeHub) -> fakehub.FakeHub:
    fake.routes[("GET", f"{P}/attachments/att-0042")] = lambda s: (200, attachment())
    fake.routes[("GET", f"{P}/attachments/att-0042/content")] = lambda s: (200, b"hello")
    return fake


def test_files_get_saves_into_maity_files_under_the_name_mode_0644(
    joined: Path, served: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    old = os.umask(0o022)
    try:
        assert cli.main(["files", "get", "att-0042"]) == cli.EXIT_OK
    finally:
        os.umask(old)
    folder = Path.cwd() / "maity-files"
    saved = folder / "build-log.txt"
    assert saved.read_bytes() == b"hello"
    assert stat.S_IMODE(saved.stat().st_mode) == 0o644
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert not (Path.cwd() / "build-log.txt").exists()  # never into the working directory
    assert "saved " in capsys.readouterr().out
    assert [p.name for p in folder.iterdir() if p.name.endswith(".part")] == []


def test_files_get_keeps_an_existing_folder_and_refuses_a_link_in_its_place(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path
) -> None:
    folder = Path.cwd() / "maity-files"
    folder.mkdir(mode=0o750)
    assert cli.main(["files", "get", "att-0042"]) == cli.EXIT_OK
    assert stat.S_IMODE(folder.stat().st_mode) == 0o750  # only a new one is made 0700
    (folder / "build-log.txt").unlink()
    folder.rmdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    folder.symlink_to(elsewhere)
    assert cli.main(["files", "get", "att-0042"]) == cli.EXIT_ERROR
    assert list(elsewhere.iterdir()) == []


def test_files_get_never_overwrites_without_force(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path
) -> None:
    target = tmp_path / "out.txt"
    target.write_bytes(b"mine")
    assert cli.main(["files", "get", "att-0042", "-o", str(target)]) == cli.EXIT_ERROR
    assert target.read_bytes() == b"mine"
    assert cli.main(["files", "get", "att-0042", "-o", str(target), "--force"]) == cli.EXIT_OK
    assert target.read_bytes() == b"hello"


def test_files_get_never_writes_through_a_link(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path
) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"keep")
    link = tmp_path / "link.txt"
    link.symlink_to(victim)
    for extra in ([], ["--force"]):
        assert cli.main(["files", "get", "att-0042", "-o", str(link), *extra]) == cli.EXIT_ERROR
    dangling = tmp_path / "dangling.txt"
    dangling.symlink_to(tmp_path / "nowhere")
    assert cli.main(["files", "get", "att-0042", "-o", str(dangling), "--force"]) == 1
    assert victim.read_bytes() == b"keep" and not (tmp_path / "nowhere").exists()


def test_files_get_on_a_mismatch_keeps_nothing(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path
) -> None:
    served.routes[("GET", f"{P}/attachments/att-0042/content")] = lambda s: (200, b"HELLO")
    assert cli.main(["files", "get", "att-0042", "-o", str(tmp_path / "o")]) == cli.EXIT_ERROR
    assert not (tmp_path / "o").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".part")]


def test_files_get_reads_no_more_than_the_size(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path
) -> None:
    served.routes[("GET", f"{P}/attachments/att-0042/content")] = lambda s: (200, b"hello" * 999)
    assert cli.main(["files", "get", "att-0042", "-o", str(tmp_path / "o")]) == cli.EXIT_ERROR
    assert not (tmp_path / "o").exists()


def test_files_get_hostile_name_stays_in_the_directory(
    joined: Path, served: fakehub.FakeHub
) -> None:
    served.routes[("GET", f"{P}/attachments/att-0042")] = lambda s: (
        200, attachment(name="../../‮evil:.sh"))  # fmt: skip
    assert cli.main(["files", "get", "att-0042"]) == cli.EXIT_OK
    assert (Path.cwd() / "maity-files" / "_.._evil.sh").read_bytes() == b"hello"


def test_files_get_to_stdout_keeps_stdout_for_the_bytes(
    joined: Path, served: fakehub.FakeHub, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    assert cli.main(["files", "get", "att-0042", "-o", "-"]) == cli.EXIT_OK
    out, err = capfdbinary.readouterr()
    assert out == b"hello" and b"build-log.txt, 5 bytes" in err
    served.routes[("GET", f"{P}/attachments/att-0042/content")] = lambda s: (200, b"HELLO")
    assert cli.main(["files", "get", "att-0042", "-o", "-"]) == cli.EXIT_ERROR
    out, err = capfdbinary.readouterr()
    assert out == b"HELLO" and b"SHA-256 mismatch" in err


def test_files_get_a_deleted_attachment(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{P}/attachments/att-0042")] = lambda s: (
        200, attachment(deleted_at="2026-10-22T14:00:00Z", deleted_reason="redacted"))  # fmt: skip
    assert cli.main(["files", "get", "att-0042"]) == cli.EXIT_ERROR
    assert not [s for s in fake.signed() if s.path.endswith("/content")]


@pytest.mark.parametrize(
    "raw, safe",
    [("a/b\\c.txt", "a_b_c.txt"), ("  ..hidden ", "hidden"), ("..", "attachment"),
     ("", "attachment"), (None, "attachment"), ("x\x00​⁦y", "xy"),
     ("é", "é"), ("a" * 300 + ".png", "a" * 196 + ".png"),
     ("ä" * 200 + ".txt", "ä" * 125 + ".txt"), ("\ud800.txt", "txt")],
)  # fmt: skip
def test_file_name(raw: Any, safe: str) -> None:
    assert cli.file_name(raw) == safe


def test_a_5xx_on_the_post_keeps_the_uploads_and_names_them(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.txt").write_bytes(b"x")
    fake.routes[("POST", f"{P}/attachments")] = lambda s: (201, attachment())
    fake.routes[("POST", f"{P}/events")] = lambda s: (
        504, {"error": {"code": "gateway", "message": "g", "details": {}}})  # fmt: skip
    argv = ["say", "all", "x", "--type", "notice", "--attach", str(tmp_path / "a.txt")]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert not [s for s in fake.signed() if s.method == "DELETE"]  # it may be stored
    assert "may have been sent; its attachments: att-0042" in capsys.readouterr().err


def test_a_lost_upload_answer_is_named(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.txt").write_bytes(b"x")
    fake.routes[("POST", f"{P}/attachments")] = lambda s: (
        502, {"error": {"code": "bad_gateway", "message": "b", "details": {}}})  # fmt: skip
    assert cli.main(["say", "human", "x", "--attach", str(tmp_path / "a.txt")]) == 1
    assert "an upload's answer was lost; it may be pending" in capsys.readouterr().err


def test_files_get_refuses_a_directory_and_a_missing_parent_before_fetching(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for extra in ([], ["--force"]):
        assert cli.main(["files", "get", "att-0042", "-o", str(tmp_path), *extra]) == 1
        assert "is a directory" in capsys.readouterr().err
    assert cli.main(["files", "get", "att-0042", "-o", str(tmp_path / "no" / "x")]) == 1
    assert "is not a directory" in capsys.readouterr().err
    assert not [s for s in served.signed() if s.path.endswith("/content")]


def test_files_get_without_hard_links_still_never_overwrites(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: Any, dst: Any) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)  # vfat, some SMB and FUSE mounts
    target = tmp_path / "out.txt"
    assert cli.main(["files", "get", "att-0042", "-o", str(target)]) == cli.EXIT_OK
    assert target.read_bytes() == b"hello"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert cli.main(["files", "get", "att-0042", "-o", str(target)]) == cli.EXIT_ERROR
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".part")]


def test_files_get_refuses_a_size_beyond_the_ceiling(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{P}/attachments/att-0042")] = lambda s: (
        200, attachment(size=10**12))  # fmt: skip
    assert cli.main(["files", "get", "att-0042", "-o", "-"]) == cli.EXIT_ERROR
    assert not [s for s in fake.signed() if s.path.endswith("/content")]
