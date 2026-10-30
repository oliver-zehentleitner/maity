"""docs/api.md §11.4: which source reads a project's repository.

The App's reads (`installation_of`, `token`) and the forge's answers (`Forge._send`) are
faked; the choice, the confirmation it depends on and what each reader may read run
for real.
"""

from __future__ import annotations

import base64
from collections import OrderedDict
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, forge, forge_access, github_app, probe, secretbox
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import factory, flow
from tests.conftest import ClientFactory

URL = "https://github.com/maintainer-gh/private-thing"
REPO = "maintainer-gh/private-thing"
OPERATOR = "operator-token"
OWNER_TOKEN = "github_pat_owner_secret"
KEY = secretbox.parse_key(base64.b64encode(b"k" * 32).decode())
APP = github_app.GitHubApp("1", "maity-test", "unused", "client", "secret")


class FakeForge:
    """The forge by credential and path: what each token sees."""

    def __init__(self) -> None:
        self.private = True
        self.installation: int | None = 7
        self.gone: str | None = None  # the installation was suspended or removed
        self.owner_token_status = 200
        self.sent: list[tuple[str | None, str]] = []

    def send(self, fg: forge.Forge, path: str, query: Any = None) -> Any:
        self.sent.append((fg.token, path))
        if fg.token == OWNER_TOKEN and self.owner_token_status != 200:
            raise forge.ForgeUnavailableError("refused", self.owner_token_status)
        if path == f"/repos/{REPO}":
            if fg.token in (OPERATOR, None) and self.private:
                return {"private": True} if fg.token == OPERATOR else None
            return {"private": self.private, "full_name": REPO}
        if path.startswith(f"/repos/{REPO}/branches/"):
            if fg.token in (OPERATOR, None) and self.private:
                return None
            return {"commit": {"sha": "a" * 40}}
        return None

    def token(self, _app: Any, installation_id: int) -> str:
        if self.gone is not None:
            raise github_app.InstallationGoneError(self.gone)
        return f"ghs_installation_{installation_id}"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    fg = FakeForge()
    monkeypatch.setattr(
        forge.Forge, "_send", lambda self, path, query=None: fg.send(self, path, query)
    )
    monkeypatch.setattr(github_app.GitHubApp, "installation_of", lambda _app, repo: fg.installation)
    monkeypatch.setattr(github_app.GitHubApp, "token", lambda _app, i: fg.token(_app, i))
    monkeypatch.setattr(forge, "_public", {})
    monkeypatch.setattr(forge_access, "_last_via", OrderedDict())
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)  # the tests read themselves
    return fg


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, forge_github_token=OPERATOR, github_app=APP, secret_key=KEY)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity", repository={"url": URL})
    return human


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


def _link(engine: Engine, human_id: str, installation_id: int = 7, status: str = "active") -> None:
    now = clock.now()
    with engine.begin() as conn:
        conn.execute(
            insert(t.forge_link).values(
                id=f"fgl-{human_id[-6:]}{installation_id}",
                human_id=human_id,
                forge="github",
                installation_id=installation_id,
                account_id=42,
                account_login="maintainer-gh",
                account_type="User",
                repository_selection="selected",
                status=status,
                linked_at=now,
                checked_at=now,
            )
        )


def _token(engine: Engine, human_id: str) -> None:
    assert KEY is not None
    now = clock.now()
    with engine.begin() as conn:
        conn.execute(
            insert(t.forge_token).values(
                human_id=human_id,
                forge="github",
                login="maintainer-gh",
                token_sealed=secretbox.seal(KEY, f"forge_token:{human_id}", OWNER_TOKEN.encode()),
                status="active",
                set_at=now,
                checked_at=now,
            )
        )


def _reader(engine: Engine) -> forge.Forge:
    access = forge_access.ForgeAccess(engine, APP, KEY)
    return forge.Forge(OPERATOR, access=access).for_project(_project_id(engine))


def _confirm(owner: flow.Human) -> None:
    assert (
        owner.post("/projects/maintainer/maity/repository/confirm", {"url": URL}).status_code == 200
    )


# --- the owner's grants count only with the confirmation ---------------------------------


def test_no_owner_grant_is_used_without_the_confirmation(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    """The contract's main point: an App installation and a token of the owner both
    cover the repository, and neither reads it while the URL is unconfirmed."""
    _link(migrated, owner.id)
    _token(migrated, owner.id)
    reader = _reader(migrated)
    assert (reader.granted, reader.via, reader.token) == (None, "instance", OPERATOR)
    with pytest.raises(forge.NotCoveredError) as raised:
        reader.branch(REPO, "main")
    assert raised.value.reason == "unconfirmed"
    assert all(token == OPERATOR for token, _ in fake.sent)


def test_a_confirmed_installation_reads_with_its_token(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    _link(migrated, owner.id)
    _confirm(owner)
    reader = _reader(migrated)
    assert (reader.granted, reader.via) == ("app", "app")
    assert reader.branch(REPO, "main")["found"] is True
    assert fake.sent[-1] == ("ghs_installation_7", f"/repos/{REPO}/branches/main")


def test_a_grant_reads_its_projects_repository_and_no_other(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    _link(migrated, owner.id)
    _confirm(owner)
    reader = _reader(migrated)
    reader.file("someone/else", "README.md", 100)
    assert fake.sent[-1] == (None, "/repos/someone/else/contents/README.md")  # anonymous
    with pytest.raises(forge.NotCoveredError):
        reader.items("someone/else", [1])


def test_a_confirmed_owner_token_reads_when_no_installation_covers(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    fake.installation = None
    _link(migrated, owner.id)
    _token(migrated, owner.id)
    _confirm(owner)
    reader = _reader(migrated)
    assert reader.via == "owner_token"
    assert reader.branch(REPO, "main")["found"] is True
    assert fake.sent[-1] == (OWNER_TOKEN, f"/repos/{REPO}/branches/main")


def test_an_installation_of_another_human_is_never_tried(
    owner: flow.Human, migrated: Engine, fake: FakeForge, make_client: ClientFactory
) -> None:
    """The App names installation 7, which is linked, but to a co-owner: only the
    namespace owner's grants count."""
    anna = flow.human(make_client, migrated, "anna")
    factory.membership(migrated, _project_id(migrated), "owner", human_id=anna.id)
    _link(migrated, anna.id)
    _confirm(owner)
    reader = _reader(migrated)
    assert reader.via == "instance"
    with pytest.raises(forge.NotCoveredError) as raised:
        reader.branch(REPO, "main")
    assert raised.value.reason == "private_without_grant"


# --- a repository that turns private, a grant that goes away ------------------------------


def test_a_repository_that_turns_private_falls_back_and_is_no_longer_read(
    owner: flow.Human, migrated: Engine, fake: FakeForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.private = False
    reader = _reader(migrated)
    assert reader.via == "instance"
    assert reader.branch(REPO, "main")["found"] is True
    fake.private = True
    forge._public.clear()  # the next check is due (10 minutes, or a refusal)
    reads_before = len(fake.sent)
    with pytest.raises(forge.NotCoveredError) as raised:
        _reader(migrated).branch(REPO, "main")
    assert raised.value.reason == "private_without_grant"
    assert fake.sent[reads_before:] == [(OPERATOR, f"/repos/{REPO}")]  # the check, no read
    assert forge_access.probe_via(_project_id(migrated), URL, OPERATOR) is None


def test_a_rejected_owner_token_falls_back_to_the_operators_token(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    fake.installation = None
    _token(migrated, owner.id)
    _confirm(owner)
    fake.owner_token_status = 401
    reader = _reader(migrated)
    assert reader.via == "instance"
    with pytest.raises(forge.NotCoveredError) as raised:
        reader.branch(REPO, "main")
    assert raised.value.reason == "token_rejected"
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_token.c.status)).scalar_one() == "rejected"
        [record] = conn.execute(
            select(t.account_record.c.data).where(
                t.account_record.c.type == "forge_access_changed",
                t.account_record.c.human_id == owner.id,
            )
        ).scalars()
    assert record["change"] == "token_rejected"


def _replace_token(engine: Engine, human_id: str, value: str) -> None:
    """The owner stores a new token: sealed anew, active again."""
    assert KEY is not None
    with engine.begin() as conn:
        conn.execute(
            update(t.forge_token)
            .where(t.forge_token.c.human_id == human_id)
            .values(
                token_sealed=secretbox.seal(KEY, f"forge_token:{human_id}", value.encode()),
                status="active",
            )
        )


def _token_state(engine: Engine, human_id: str) -> tuple[str, int]:
    """The token's status and how many `token_rejected` records its owner has."""
    with engine.connect() as conn:
        status = conn.execute(
            select(t.forge_token.c.status).where(t.forge_token.c.human_id == human_id)
        ).scalar_one()
        records = conn.execute(
            select(t.account_record.c.data).where(
                t.account_record.c.type == "forge_access_changed",
                t.account_record.c.human_id == human_id,
            )
        ).scalars()
        return status, sum(1 for r in records if r["change"] == "token_rejected")


def test_a_refusal_of_a_replaced_token_leaves_the_new_one_alone(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    """A read still under way with the old token is refused after the owner stored a
    new one: the new token stays active, no record, and the next choice uses it."""
    fake.installation = None
    _token(migrated, owner.id)
    _confirm(owner)
    reader = _reader(migrated)
    assert reader.via == "owner_token"
    _replace_token(migrated, owner.id, "github_pat_new_one")
    fake.owner_token_status = 401  # the old token, revoked at the forge
    with pytest.raises(forge.ForgeUnavailableError):
        reader.branch(REPO, "main")
    assert _token_state(migrated, owner.id) == ("active", 0)
    again = _reader(migrated)
    assert (again.via, again.token) == ("owner_token", "github_pat_new_one")


def test_a_token_replaced_during_the_choice_is_not_marked(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    """The choice read the token, the owner replaced it, then the forge refused the
    old one: the choice falls back and the new token stays active."""
    fake.installation = None
    _token(migrated, owner.id)
    _confirm(owner)
    send = fake.send

    def replaced_then_refused(fg: forge.Forge, path: str, query: Any = None) -> Any:
        if fg.token == OWNER_TOKEN:
            _replace_token(migrated, owner.id, "github_pat_new_one")
            raise forge.ForgeUnavailableError("refused", 401)
        return send(fg, path, query)

    fake.send = replaced_then_refused  # type: ignore[method-assign]
    assert _reader(migrated).via == "instance"
    assert _token_state(migrated, owner.id) == ("active", 0)


def test_a_refusal_after_a_transfer_marks_the_grant_it_was_read_with(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, fake: FakeForge
) -> None:
    """The project moved to another owner while a read with the former owner's token
    was under way: the refusal marks the former owner's token, never the new owner's."""
    fake.installation = None
    _token(migrated, owner.id)
    _confirm(owner)
    reader = _reader(migrated)
    assert reader.via == "owner_token"
    anna = flow.human(make_client, migrated, "anna")
    _token(migrated, anna.id)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(owner_id=anna.id))
    fake.owner_token_status = 401
    with pytest.raises(forge.ForgeUnavailableError):
        reader.branch(REPO, "main")
    assert _token_state(migrated, owner.id) == ("rejected", 1)
    assert _token_state(migrated, anna.id) == ("active", 0)


@pytest.mark.parametrize("state", ["suspended", "removed"])
def test_a_gone_installation_falls_back_with_its_reason(
    owner: flow.Human, migrated: Engine, fake: FakeForge, state: str
) -> None:
    _link(migrated, owner.id)
    _confirm(owner)
    fake.gone = state
    reader = _reader(migrated)
    with pytest.raises(forge.NotCoveredError) as raised:
        reader.branch(REPO, "main")
    assert raised.value.reason == f"installation_{state}"
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_link.c.status)).scalar_one() == state


def test_a_new_url_takes_the_grant_away_at_once(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    _link(migrated, owner.id)
    _confirm(owner)
    assert _reader(migrated).via == "app"
    owner.patch(
        "/projects/maintainer/maity",
        {"repository": {"url": "https://github.com/maintainer-gh/other"}},
    )
    reader = _reader(migrated)
    assert reader.via == "instance" and reader.granted is None


# --- what the API says ------------------------------------------------------------------


def test_the_probe_names_the_reason_to_an_admin(
    owner: flow.Human, migrated: Engine, fake: FakeForge
) -> None:
    _link(migrated, owner.id)
    refused = owner.get("/projects/maintainer/maity/probe?branch=main")
    assert refused.status_code == 409
    assert refused.json()["error"]["details"] == {"reason": "unconfirmed"}
    _confirm(owner)
    answer = owner.get("/projects/maintainer/maity/probe?branch=main")
    assert answer.status_code == 200, answer.text
    repository = owner.get("/projects/maintainer/maity").json()["repository"]
    assert (repository["probe_via"], repository["probe_configured"]) == ("app", True)
