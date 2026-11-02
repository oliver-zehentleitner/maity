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
        ("postgresql://u@db.example/maity", "db.example", False),
        ("sqlite:///x.db", None, False),
    ],
)
def test_the_seed_touches_only_a_database_named_as_a_test_system(
    url: str, confirmed: str | None, refused: bool
) -> None:
    assert (seed.refusal(url, confirmed) is not None) is refused


def test_the_seed_refuses_before_it_connects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", "postgresql://u@prod.example/maity")
    monkeypatch.delenv("LOADTEST_CONFIRMED_TEST_SYSTEM", raising=False)
    out = tmp_path / "accounts.json"
    assert seed.main(["--humans", "1", "--out", str(out)]) == 2
    assert not out.exists()


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
