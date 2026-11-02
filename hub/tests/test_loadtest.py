"""The load test's own parts that run without k6: the signature in `loadtest/sign.js`, its refusal
of anything not named, and the seed, `maity-hub loadtest seed` (hub/context/replicas.md cac80c88).
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy import Engine, select

from maity_hub import cli
from maity_hub import loadtest as seed
from maity_hub import tables as t
from maity_hub.auth import credentials
from maity_hub.auth.passwords import verify_password
from maity_hub.config import Settings
from tests.conftest import ClientFactory

LOADTEST = Path(__file__).resolve().parent.parent / "loadtest"

VERIFIER = "ab" * 32
DRIVER = """
import { createHash, createHmac } from "node:crypto";
import { signedHeaders } from "%s";
const hash = {
  sha256Hex: (text) => createHash("sha256").update(text).digest("hex"),
  hmacHex: (key, text) => createHmac("sha256", Buffer.from(key, "hex")).update(text).digest("hex"),
};
const [method, path, pairs, body] = JSON.parse(process.argv[2]);
const account = { credential_id: "crd", verifier: "%s" };
const made = signedHeaders(account, method, path, pairs, body, 1700000000, "n0nce", hash);
console.log(JSON.stringify(made));
"""


@pytest.mark.parametrize(
    ("method", "pairs", "raw_query", "body"),
    [
        ("GET", [["wait", "55"], ["after", "12"]], b"wait=55&after=12", ""),
        ("POST", [], b"", '{"body":"sent:1 ü"}'),
        ("GET", [["after", "a b/c"]], b"after=a%20b%2Fc", ""),
    ],
)
def test_the_scripts_signature_is_the_one_the_hub_expects(
    tmp_path: Path, method: str, pairs: list[list[str]], raw_query: bytes, body: str
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this machine")
    driver = tmp_path / "driver.mjs"
    driver.write_text(DRIVER % ((LOADTEST / "sign.js").as_uri(), VERIFIER))
    path = "/api/v1/projects/o/s/events"
    made = subprocess.run(
        [node, str(driver), json.dumps([method, path, pairs, body])],
        capture_output=True,
        text=True,
        check=True,
    )
    headers = json.loads(made.stdout)
    canonical = credentials.canonical_string(
        method, path.encode(), raw_query, "1700000000", "n0nce", body.encode()
    )
    assert headers["Maity-Signature"] == credentials.sign(VERIFIER, canonical)


@pytest.mark.parametrize(
    ("public_url", "test_system", "production", "refused"),
    [
        ("https://test.example", "test.example", None, False),
        ("https://TEST.example:8443/", "test.example", None, False),
        ("https://test.example", None, None, True),
        ("https://test.example", "other.example", None, True),
        ("https://test.example", None, "test.example", True),  # not a production name
        ("https://maity.team", None, "maity.team", False),
        ("https://join.maity.team", None, "join.maity.team", False),
        ("https://maity.team", "maity.team", None, True),  # production is only confirmed so
        ("https://join.maity.team", None, "maity.team", True),
        ("https://", "", "", True),
        # Both are lists, as run.js reads the same variables: one setting for seed and run.
        ("https://maity.team", None, "lt.maity.team, maity.team", False),
        ("https://test.example", "a.example,test.example", None, False),
        ("https://maity.team", None, "lt.maity.team,", True),
        ("https://maity.team", None, "maity.team.team", True),
    ],
)
def test_the_seed_runs_only_on_a_hub_named_for_it(
    public_url: str, test_system: str | None, production: str | None, refused: bool
) -> None:
    assert (seed.refusal(public_url, test_system, production) is not None) is refused


@pytest.mark.parametrize(
    ("target", "confirmed", "production", "refused"),
    [
        ("https://test.example", "test.example", "", False),
        ("https://a.example:8443", "b.example,a.example", "", False),
        ("https://TEST.example", "test.example", "", False),
        ("https://test.example.", "test.example", "", True),
        ("https://test.example", "", "", True),
        ("http://:8000", "", "", True),
        ("https://test.example:x@maity.team", "test.example", "", True),
        ("https://test.example/path", "test.example", "", True),
        ("https://MAITY.TEAM", "maity.team", "", True),
        ("https://maity.team.", "maity.team", "", True),
        ("https://maity.team..", "maity.team.", "", True),
        ("https://join.maity.team", "join.maity.team", "", True),
        ("HTTPS://staging.maity.team", "staging.maity.team", "", True),
        ("https://maity.team", "", "maity.team", False),
        ("https://MAITY.team", "", "maity.team", False),
        ("https://join.maity.team", "", "maity.team", True),
        ("https://maity.team.", "", "maity.team", True),
        ("https://test.example", "", "test.example", True),
        ("https://lt.maity.team", "", "maity.team,lt.maity.team", False),
        ("https://lt.maity.team", "", "maity.team", True),
    ],
)
def test_the_script_reaches_only_a_named_system(
    tmp_path: Path, target: str, confirmed: str, production: str, refused: bool
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this machine")
    driver = tmp_path / "driver.mjs"
    module = (LOADTEST / "target.js").as_uri()
    driver.write_text(
        f'import {{ refusal }} from "{module}";\n'
        "console.log(JSON.stringify(refusal(...process.argv.slice(2))));\n"
    )
    made = subprocess.run(
        [node, str(driver), target, confirmed, production],
        capture_output=True,
        text=True,
        check=True,
    )
    assert (json.loads(made.stdout) is not None) is refused


@pytest.mark.parametrize(
    ("targets", "confirmed", "production", "refused"),
    [
        # A test system: each pod by itself, every host named.
        (["https://a.example", "https://b.example"], "a.example,b.example", "", False),
        (["https://a.example", "https://b.example"], "a.example", "", True),
        (["https://a.example", "https://A.example"], "a.example", "", True),  # one pod twice
        # Production: one target for each confirmed name, the balancers of the run.
        (["https://maity.team"], "", "maity.team", False),
        (["https://maity.team", "https://lt.maity.team"], "", "maity.team,lt.maity.team", False),
        (["https://maity.team", "https://lt.maity.team"], "", "maity.team", True),
        (["https://maity.team"], "", "maity.team,lt.maity.team", True),  # a name left unused
        (["https://maity.team", "https://maity.team:8443"], "", "maity.team", True),
        (["https://maity.team", "https://MAITY.team"], "", "maity.team", True),  # twice
        (["https://maity.team", "https://a.example"], "a.example", "maity.team", True),  # mixed
        ([], "", "", True),
    ],
)
def test_the_script_reaches_production_only_through_its_named_balancers(
    tmp_path: Path, targets: list[str], confirmed: str, production: str, refused: bool
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this machine")
    driver = tmp_path / "driver.mjs"
    module = (LOADTEST / "target.js").as_uri()
    driver.write_text(
        f'import {{ targetsRefusal }} from "{module}";\n'
        "const [targets, ...rest] = process.argv.slice(2);\n"
        "console.log(JSON.stringify(targetsRefusal(JSON.parse(targets), ...rest)));\n"
    )
    made = subprocess.run(
        [node, str(driver), json.dumps(targets), confirmed, production],
        capture_output=True,
        text=True,
        check=True,
    )
    assert (json.loads(made.stdout) is not None) is refused


def test_the_seed_refuses_before_it_connects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", "postgresql://u@unreachable.invalid/maity")
    monkeypatch.setenv("MAITY_PUBLIC_URL", "https://maity.team")
    monkeypatch.setenv("LOADTEST_CONFIRMED_TEST_SYSTEM", "maity.team")
    monkeypatch.delenv("LOADTEST_CONFIRMED_PRODUCTION", raising=False)
    out = tmp_path / "accounts.json"
    assert cli.main(["loadtest", "seed", "--humans", "1", "--out", str(out)]) == 2
    assert not out.exists()


def test_the_seed_refuses_a_public_url_it_derived(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, migrated: Engine
) -> None:
    """Without MAITY_PUBLIC_URL the hub derives one from its bind address; that is no name."""
    monkeypatch.setenv("MAITY_DATABASE_URL", migrated.url.render_as_string(hide_password=False))
    monkeypatch.delenv("MAITY_PUBLIC_URL", raising=False)
    monkeypatch.delenv("MAITY_BIND", raising=False)
    derived = urlsplit(Settings.from_env().public_url).hostname
    monkeypatch.setenv("LOADTEST_CONFIRMED_TEST_SYSTEM", str(derived))
    out = tmp_path / "accounts.json"
    assert cli.main(["loadtest", "seed", "--humans", "1", "--out", str(out)]) == 2
    assert not out.exists()


def test_the_seeds_secrets_go_to_a_new_file_only_its_owner_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, migrated: Engine
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", migrated.url.render_as_string(hide_password=False))
    monkeypatch.setenv("MAITY_PUBLIC_URL", "https://test.example")
    monkeypatch.setenv("LOADTEST_CONFIRMED_TEST_SYSTEM", "test.example")
    there = tmp_path / "there.json"
    there.write_text("kept")
    assert cli.main(["loadtest", "seed", "--humans", "1", "--out", str(there)]) == 2
    assert there.read_text() == "kept"
    new = tmp_path / "new.json"
    assert cli.main(["loadtest", "seed", "--humans", "2", "--out", str(new)]) == 0
    assert new.stat().st_mode & 0o777 == 0o600
    assert [h["handle"] for h in json.loads(new.read_text())] == ["lt-0", "lt-1"]
    again = tmp_path / "again.json"
    assert cli.main(["loadtest", "seed", "--humans", "1", "--out", str(again)]) == 0
    assert [h["handle"] for h in json.loads(again.read_text())] == ["lt-2"]


def test_a_seeded_human_has_no_mail_address_and_no_password(migrated: Engine) -> None:
    """Nothing the run does can send a mail, and nobody signs in as a seeded human."""
    one = seed.seed_one(migrated, 0)
    with migrated.connect() as conn:
        human = conn.execute(select(t.human).where(t.human.c.handle == one["handle"])).one()
        address = conn.execute(
            select(t.notification_settings.c.address).where(
                t.notification_settings.c.human_id == human.id
            )
        ).scalar()
    assert address is None
    assert not verify_password("loadtest", human.password_hash)


def signed_call(
    client: Any, who: Any, method: str, route: str, query: str = "", **body: Any
) -> Any:
    """A request signed with a seeded agent's key, as `run.js` signs it."""
    text = json.dumps(body).encode() if body else b""
    stamp, nonce = str(int(time.time())), secrets.token_hex(16)
    canonical = credentials.canonical_string(
        method, route.encode(), query.encode(), stamp, nonce, text
    )
    headers = {
        "Authorization": f"Maity-HMAC {who.credential_id}",
        "Maity-Timestamp": stamp,
        "Maity-Nonce": nonce,
        "Maity-Signature": credentials.sign(who.verifier, canonical),
    }
    if body:
        headers |= {"Content-Type": "application/json", "Idempotency-Key": nonce}
    return client.request(
        method, route + (f"?{query}" if query else ""), content=text, headers=headers
    )


def test_a_seeded_human_makes_the_calls_of_the_scripts(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Each answer's field that `run.js` reads, on accounts of the seed."""
    one = seed.seed_one(migrated, seed.first_free(migrated))
    other = seed.seed_one(migrated, seed.first_free(migrated))
    assert (one["handle"], other["handle"]) == ("lt-0", "lt-1")
    client = make_client()
    path = f"/api/v1/projects/{one['owner']}/{one['slug']}"
    writer, waiter = (SimpleNamespace(**a, value="") for a in one["agents"])

    def call(who: Any, method: str, route: str, query: str = "", **body: Any) -> Any:
        return signed_call(client, who, method, route, query, **body)

    first = call(waiter, "GET", f"{path}/events", "after=latest")
    assert first.status_code == 200, first.text
    cursor = first.json()["cursor"]
    sent = call(
        writer,
        "POST",
        f"{path}/events",
        kind="message",
        type="notice",
        to=waiter.agent_id,
        body="load sent:1700000000000",
    )
    assert sent.status_code == 201, sent.text
    woken = call(waiter, "GET", f"{path}/events", f"after={cursor}").json()
    assert [i["payload"]["body"] for i in woken["items"]] == ["load sent:1700000000000"]
    assert call(writer, "GET", f"{path}/tasks").status_code == 200

    client.cookies.set("maity_session", one["session"])
    bell = client.get("/api/v1/me/notifications", params={"limit": 0})
    assert bell.status_code == 200 and bell.json()["next_after"]
