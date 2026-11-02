"""The load test's own parts that run without k6: the signature in `loadtest/sign.js`, its refusal
of anything but a test system, and the seed (hub/context/replicas.md cac80c88)."""

from __future__ import annotations

import importlib.util
import json
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub.auth import credentials
from tests.conftest import ClientFactory

LOADTEST = Path(__file__).resolve().parent.parent / "loadtest"
spec = importlib.util.spec_from_file_location("loadtest_seed", LOADTEST / "seed.py")
assert spec is not None and spec.loader is not None
seed: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

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
    ("url", "confirmed", "refused"),
    [
        ("postgresql://u@db.example/maity", None, True),
        ("postgresql://u@db.example/maity", "other.example", True),
        ("postgresql://u@db.example/maity", "db.example", True),
        ("postgresql://u@db.example:5433/maity", "db.example:5433/maity", False),
        ("postgresql://u@db.example/maity", "db.example:/maity", False),
        ("postgresql://u@localhost/m?host=prod.example", "localhost:/m", True),
        ("postgresql://u@localhost/m?host=prod.example", "prod.example:/m", True),
        ("postgresql://u@localhost/m?hostaddr=192.0.2.9", "localhost:/m", True),
        ("postgresql://u@db.example:5432/test?dbname=prod", "db.example:5432/test", True),
        ("postgresql://u@db.example:5432/test?port=5433", "db.example:5432/test", True),
        ("postgresql://u@db.maity.team,other.example/m", "other.example:/m", True),
        ("sqlite://", "", True),
        ("postgresql:///loadtest", "/loadtest", True),
        ("postgresql://u@db.example/m?sslmode=require", "db.example:/m", True),
        ("postgresql://u:secret@db.maity.team/m", "db.maity.team:/m", True),
        ("sqlite:///x.db", None, True),
        ("sqlite:////tmp/x.db", "//tmp/x.db", False),
    ],
)
def test_the_seed_touches_only_a_database_named_as_a_test_system(
    url: str, confirmed: str | None, refused: bool
) -> None:
    assert (seed.refusal(url, confirmed) is not None) is refused


def test_a_refusal_never_prints_a_password() -> None:
    why = seed.refusal("postgresql://u:secret@db.example/m?password=secret&host=/run", None)
    assert why is not None and "secret" not in why


@pytest.mark.parametrize(
    ("target", "confirmed", "refused"),
    [
        ("https://test.example", "test.example", False),
        ("https://a.example:8443", "b.example,a.example", False),
        ("https://TEST.example", "test.example", False),
        ("https://test.example.", "test.example", True),
        ("https://test.example", "", True),
        ("http://:8000", "", True),
        ("https://test.example:x@maity.team", "test.example", True),
        ("https://test.example/path", "test.example", True),
        ("https://MAITY.TEAM", "maity.team", True),
        ("https://maity.team.", "maity.team", True),
        ("https://maity.team..", "maity.team.", True),
        ("https://join.maity.team", "join.maity.team", True),
        ("HTTPS://staging.maity.team", "staging.maity.team", True),
    ],
)
def test_the_script_reaches_only_a_named_test_system(
    tmp_path: Path, target: str, confirmed: str, refused: bool
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this machine")
    driver = tmp_path / "driver.mjs"
    module = (LOADTEST / "target.js").as_uri()
    driver.write_text(
        f'import {{ refusal }} from "{module}";\n'
        "console.log(JSON.stringify(refusal(process.argv[2], process.argv[3])));\n"
    )
    made = subprocess.run(
        [node, str(driver), target, confirmed], capture_output=True, text=True, check=True
    )
    assert (json.loads(made.stdout) is not None) is refused


def test_the_seed_refuses_before_it_connects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", "postgresql://u@prod.example/maity")
    monkeypatch.delenv("LOADTEST_CONFIRMED_TEST_SYSTEM", raising=False)
    out = tmp_path / "accounts.json"
    assert seed.main(["--humans", "1", "--out", str(out)]) == 2
    assert not out.exists()


def test_the_seeds_secrets_go_to_a_new_file_only_its_owner_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "x.db"
    monkeypatch.setenv("MAITY_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("LOADTEST_CONFIRMED_TEST_SYSTEM", seed.identity_of(f"sqlite:///{database}"))
    there = tmp_path / "there.json"
    there.write_text("kept")
    assert seed.main(["--humans", "0", "--out", str(there)]) == 2
    assert there.read_text() == "kept"
    new = tmp_path / "new.json"
    monkeypatch.setattr(seed, "first_free", lambda engine: 0)
    assert seed.main(["--humans", "0", "--out", str(new)]) == 0
    assert new.stat().st_mode & 0o777 == 0o600


def test_a_seeded_human_makes_the_calls_of_the_scripts(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Each answer's field that `run.js` reads, on accounts of the seed."""
    one = seed.seed_one(migrated, seed.first_free(migrated))
    other = seed.seed_one(migrated, seed.first_free(migrated))
    assert (one["handle"], other["handle"]) == ("load-0", "load-1")
    client = make_client()
    path = f"/api/v1/projects/{one['owner']}/{one['slug']}"
    writer, waiter = (SimpleNamespace(**a, value="") for a in one["agents"])

    def call(who: Any, method: str, route: str, query: str = "", **body: Any) -> Any:
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
