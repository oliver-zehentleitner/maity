"""`maity ticker` (§13, §17) and the resume packet's Ticker section, against the fake hub."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

import fakehub
import pytest
from test_onboarding import packet

from maity import cli, onboarding

BASE = "/api/v1/projects/oliver/maity/ticker"
MERGE = {"id": "tck-4302", "seq": 4302, "type": "merge", "text": "#212 hub: lease survives",
         "url": "https://github.com/o/r/pull/212", "for_me": True,
         "why": ["area_owner:hub/", "card_holder:tsk-0031"], "muted": False}  # fmt: skip
NOTE = {"id": "tck-4303", "seq": 4303, "type": "note", "text": "Staging runs rc.2",
        "url": None, "for_me": True, "why": ["follow:web/"], "muted": True}  # fmt: skip
DEPLOY = {"id": "tck-4304", "seq": 4304, "type": "deploy", "text": "Deployed 0.3.0 to staging",
          "url": None, "for_me": False, "why": [], "muted": False}  # fmt: skip


def test_the_text_form_follows_the_contract() -> None:
    assert onboarding.ticker_lines(MERGE) == [
        "[ticker] merge: #212 hub: lease survives https://github.com/o/r/pull/212",
        "  for you: area_owner:hub/, card_holder:tsk-0031",
    ]
    assert onboarding.ticker_lines(NOTE) == [
        "[ticker] note: Staging runs rc.2", "  for you: follow:web/ (muted)",
    ]  # fmt: skip
    assert onboarding.ticker_lines(DEPLOY) == ["[ticker] deploy: Deployed 0.3.0 to staging"]


def test_the_listing_sends_the_filters_and_names_the_next_page(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", BASE)] = lambda s: (200, {"items": [MERGE, DEPLOY], "next_cursor": "c2"})
    args = ["ticker", "--mine", "--type", "merge", "--type", "deploy", "--area", "hub/",
            "--since", "2026-10-22T17:00:00+02:00", "--limit", "20"]  # fmt: skip
    assert cli.main(args) == cli.EXIT_OK
    query = dict(p.split("=", 1) for p in fake.signed()[-1].query.split("&"))
    assert query == {"limit": "20", "for": "me", "type": "merge%2Cdeploy", "area": "hub%2F",
                     "since": "2026-10-22T15%3A00%3A00Z"}  # fmt: skip
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("[ticker] merge: #212") and out[1].startswith("  for you:")
    more = shlex.split(out[-1].removeprefix("more: "))
    assert more == ["maity", "ticker", "--mine", "--type", "merge", "--type", "deploy",
                    "--area", "hub/", "--since", "2026-10-22T15:00:00Z", "--limit", "20",
                    "--cursor", "c2"]  # fmt: skip


def test_a_duration_since_is_resolved_once(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", BASE)] = lambda s: (200, {"items": [DEPLOY], "next_cursor": "c2"})
    assert cli.main(["ticker", "--since", "90m"]) == cli.EXIT_OK
    since = dict(p.split("=", 1) for p in fake.signed()[-1].query.split("&"))["since"]
    more = capsys.readouterr().out.splitlines()[-1]
    assert since.replace("%3A", ":") in more  # the next page asks with the same time


def test_the_last_page_has_no_more_line_and_json_is_the_page(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    page = {"items": [DEPLOY], "next_cursor": None}
    fake.routes[("GET", BASE)] = lambda s: (200, page)
    assert cli.main(["ticker"]) == cli.EXIT_OK
    assert "more:" not in capsys.readouterr().out
    assert cli.main(["ticker", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == page


@pytest.mark.parametrize("since", ["2026-10-22T17:00", "yesterday", "0h"])
def test_a_since_without_an_offset_or_unreadable_is_refused(
    since: str, joined: Path, fake: fakehub.FakeHub
) -> None:
    before = len(fake.seen)
    assert cli.main(["ticker", f"--since={since}"]) == cli.EXIT_USAGE
    assert len(fake.seen) == before


def test_post_maps_every_flag_to_its_field(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", BASE)] = lambda s: (201, {"id": "tck-4310", "seq": 4310})
    args = ["ticker", "post", "Deployed 0.3.0 to staging", "--type", "deploy", "--env",
            "staging", "--version", "0.3.0", "--log-url", "https://x/runs/1",
            "--to", "role:admin", "--to", "area:cli/"]  # fmt: skip
    assert cli.main(args) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {
        "type": "deploy", "text": "Deployed 0.3.0 to staging",
        "to": ["role:admin", "area:cli/"],
        "deploy": {"environment": "staging", "version": "0.3.0", "log_url": "https://x/runs/1"},
    }  # fmt: skip
    assert capsys.readouterr().out.strip() == "posted tck-4310 (seq 4310)"


def test_post_a_note_to_its_areas_and_a_release(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", BASE)] = lambda s: (201, {"id": "tck-1", "seq": 1})
    cli.main(["ticker", "post", "rc.2 on staging", "--type", "note", "--area", "hub/",
              "--area", "web/", "--to", "computed"])  # fmt: skip
    assert fake.signed()[-1].json() == {"type": "note", "text": "rc.2 on staging",
                                        "to": "computed", "areas": ["hub/", "web/"]}  # fmt: skip
    cli.main(["ticker", "post", "Released 0.3.0", "--type", "release", "--release", "tsk-0050",
              "--url", "https://maity.team/#/p/maity/board?task=tsk-0050"])  # fmt: skip
    body = fake.signed()[-1].json()
    assert body["release_task_id"] == "tsk-0050" and "to" not in body


@pytest.mark.parametrize(
    "to", [["computed", "all"], ["all", "role:admin"], ["computed", "computed"]]
)
def test_computed_and_all_stand_alone(to: list[str], joined: Path, fake: fakehub.FakeHub) -> None:
    before = len(fake.seen)
    args = ["ticker", "post", "x", "--type", "note", *[w for t in to for w in ("--to", t)]]
    assert cli.main(args) == cli.EXIT_USAGE and len(fake.seen) == before


def test_merge_is_never_posted_by_hand(joined: Path) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["ticker", "post", "x", "--type", "merge"])
    assert exited.value.code == cli.EXIT_USAGE


def test_a_hub_without_the_ticker_gets_the_interim_line(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", BASE)] = lambda s: (
        404, {"error": {"code": "not_found", "message": "not_found", "details": {}}}
    )  # fmt: skip
    args = ["ticker", "post", "rc.2 on staging", "--type", "note", "--url", "https://x/1"]
    assert cli.main(args) == cli.EXIT_USAGE
    out = capsys.readouterr()
    assert shlex.split(out.out.strip()) == [
        "maity", "say", "all", "--type", "notice", "[ticker] note: rc.2 on staging https://x/1"
    ]  # fmt: skip
    assert "no ticker yet" in out.err
    says = [s for s in fake.signed() if "events" in s.path]
    assert not says  # it never sends the message on its own


def test_a_real_not_found_on_a_hub_with_the_ticker_is_an_error(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.openapi = {"paths": {"/projects/{owner}/{slug}/ticker": {"get": {}, "post": {}}}}
    fake.routes[("POST", BASE)] = lambda s: (
        404, {"error": {"code": "not_found", "message": "not_found", "details": {}}}
    )  # fmt: skip
    code = cli.main(["ticker", "post", "x", "--type", "release", "--release", "tsk-9"])
    assert code not in (cli.EXIT_OK, cli.EXIT_USAGE)
    assert "maity say" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("verb", "body"),
    [
        ("follow", {"add": {"follow": {"areas": ["web/"], "types": ["release"]}}}),
        ("mute", {"add": {"mute": {"areas": ["web/"], "types": ["release"]}}}),
        ("unfollow", {"remove": {"follow": {"areas": ["web/"], "types": ["release"]}}}),
        ("unmute", {"remove": {"mute": {"areas": ["web/"], "types": ["release"]}}}),
    ],
)
def test_subscription_changes_are_one_patch(
    verb: str, body: dict[str, Any], joined: Path, fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    answer = {"follow": {"areas": ["web/"], "types": ["release"]},
              "mute": {"areas": ["web/"], "types": []}}  # fmt: skip
    fake.routes[("PATCH", f"{BASE}/subscription")] = lambda s: (200, answer)
    args = ["ticker", verb, "--area", "web/", "--type", "release"]
    assert cli.main(args) == cli.EXIT_OK
    assert fake.signed()[-1].json() == body
    assert [s.method for s in fake.signed() if "subscription" in s.path] == ["PATCH"]  # no GET
    out = capsys.readouterr().out
    assert "follow: areas web/; types release" in out
    assert "web/: followed and muted — listed for you, never woken" in out


def test_a_subscription_change_needs_a_flag(joined: Path, fake: fakehub.FakeHub) -> None:
    assert cli.main(["ticker", "follow"]) == cli.EXIT_USAGE


def test_resume_prints_the_ticker_section_and_not_the_events_twice() -> None:
    ticker = {"items": [MERGE, DEPLOY], "for_me": 1, "others": 3, "truncated": True}
    events = {"after": 0, "cursor": 4304, "truncated": False,
              "items": [{"seq": 4302, "kind": "ticker", "type": "ticker", "payload": {}},
                        {"seq": 4305, "kind": "message", "type": "notice", "actor": "agt-a",
                         "payload": {"body": "hello"}}]}  # fmt: skip
    text = onboarding.render(packet(ticker=ticker, events=events))
    section = text[text.index("Ticker (1 for you, 3 others)") :].split("\n\n")[0].splitlines()
    assert section == [
        "Ticker (1 for you, 3 others)",
        "  [ticker] merge: #212 hub: lease survives https://github.com/o/r/pull/212",
        "    for you: area_owner:hub/, card_holder:tsk-0031",
        "  [ticker] deploy: Deployed 0.3.0 to staging",
        "  2 more: maity ticker",
    ]
    assert "#4302" not in text  # the ticker event is not among the missed events


def test_no_ticker_section_without_items() -> None:
    assert "Ticker (" not in onboarding.render(packet())


def test_a_cursor_that_is_not_printable_ascii_is_not_offered(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", BASE)] = lambda s: (
        200, {"items": [DEPLOY], "next_cursor": "c2\x1b]52;c;aGk=\x07"}
    )  # fmt: skip
    assert cli.main(["ticker"]) == cli.EXIT_OK
    out = capsys.readouterr()
    assert "more:" not in out.out and "\x1b" not in out.out
    assert "not offering it" in out.err


@pytest.mark.parametrize("openapi", ["not json", None])
def test_an_unreadable_openapi_keeps_the_original_not_found(
    openapi: str | None, joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", BASE)] = lambda s: (
        404, {"error": {"code": "not_found", "message": "no such project", "details": {}}}
    )  # fmt: skip
    if openapi is None:
        fake.redirects["/api/v1/openapi.json"] = "http://elsewhere.example/x"  # a failed fetch
    else:
        fake.openapi = openapi  # type: ignore[assignment]
    code = cli.main(["ticker", "post", "x", "--type", "note", "--area", "hub/"])
    out = capsys.readouterr()
    assert code not in (cli.EXIT_OK, cli.EXIT_USAGE)
    assert "not_found" in out.err and "maity say" not in out.out and "Traceback" not in out.err


def test_since_without_an_offset_is_refused_outside_a_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no clone, no session: refused before any of that
    assert cli.main(["ticker", "--since=2026-10-22T17:00"]) == cli.EXIT_USAGE
