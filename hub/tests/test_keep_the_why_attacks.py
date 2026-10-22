"""Attack tests for the Keep the Why family export (docs/api.md §11.3).

The forge is faked at `Forge._call` (so `Forge.file` and its caps run for real); the
state.json reads go through the real `outbound.read` with the resolver/connector seams
pointed at a loopback plain-TCP server (TLS is not under test). No external host is used.
Each test asserts what the contract asks for against one way of breaking it.
"""

from __future__ import annotations

import base64
import contextlib
import gzip
import ipaddress
import json
import socket
import threading
import time
import tracemalloc
from typing import Any

import pytest
from sqlalchemy import Engine, MetaData, func, select

from maity_hub import forge, ktw, outbound
from tests import flow
from tests.conftest import ClientFactory

REPO = "https://github.com/acme/widget"
HOST = "ktw.example"
BASE = f"https://{HOST}/d"
PUBLIC = ipaddress.ip_address("93.184.215.14")


# --- fakes -------------------------------------------------------------------------------------


def kfile(state: str | None, ident: str = "x", kids: list[str] | None = None) -> bytes:
    lines = ["<!-- keep-the-why:config -->", f"- id: {ident}"]
    if state is not None:
        lines.append(f"- dashboard-state: {state}")
    lines.append("<!-- /keep-the-why:config -->")
    if kids is not None:
        lines += ["<!-- keep-the-why:children -->", *kids, "<!-- /keep-the-why:children -->"]
    return ("\n".join(lines) + "\n").encode()


def doc(*entries: Any, **extra: Any) -> dict[str, Any]:
    return {"state-json": 2, "generated": "2026-10-22T11:33:15Z", "entries": list(entries), **extra}


class Repo:
    """The contents API: path -> bytes | dict (raw answer) | Exception."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.files: dict[str, Any] = {}
        self.reads: list[str] = []
        repo = self

        def call(self: forge.Forge, path: str, query: Any = None) -> Any:
            prefix = "/repos/acme/widget/contents/"
            assert path.startswith(prefix), path
            name = path[len(prefix) :]
            repo.reads.append(name)
            found = repo.files.get(name)
            if isinstance(found, BaseException):
                raise found
            if found is None or isinstance(found, (dict, list)):
                return found
            return {
                "type": "file",
                "size": len(found),
                "encoding": "base64",
                "content": base64.b64encode(found).decode(),
            }

        monkeypatch.setattr(forge.Forge, "_call", call)


class Web:
    """A loopback HTTP server for the state.json reads: path -> (status, body, headers)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.routes: dict[str, Any] = {}
        self.requests: list[str] = []
        self.connected: list[tuple[str, Any]] = []
        self.delay = 0.0
        self.in_flight = 0
        self.most = 0
        self.lock = threading.Lock()
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._run, daemon=True).start()
        self.addresses: dict[str, list[Any]] = {}
        web = self

        def resolve(host: str) -> list[Any]:
            return web.addresses.get(host, [PUBLIC])

        def connect(host: str, address: Any, timeout: float) -> socket.socket:
            web.connected.append((host, address))
            return socket.create_connection(("127.0.0.1", web.port), timeout)

        monkeypatch.setattr(outbound, "resolver", resolve)
        monkeypatch.setattr(outbound, "connector", connect)

    def _run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        with self.lock:
            self.in_flight += 1
            self.most = max(self.most, self.in_flight)
        try:
            data = b""
            conn.settimeout(15)
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            target = data.split(b" ", 2)[1].decode()
            self.requests.append(target)
            if self.delay:
                time.sleep(self.delay)
            found = self.routes.get(target)
            status, body, headers = 404, b"", {}
            if isinstance(found, tuple):
                status, body, headers = found
            elif isinstance(found, bytes):
                status, body = 200, found
            elif found is not None:
                status, body = 200, json.dumps(found).encode()
            head = f"HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\nConnection: close\r\n"
            head += "".join(f"{k}: {v}\r\n" for k, v in headers.items())
            conn.sendall(head.encode() + b"\r\n" + body)
        except OSError:
            pass
        finally:
            with self.lock:
                self.in_flight -= 1
            with contextlib.suppress(OSError):
                conn.close()

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> Repo:
    return Repo(monkeypatch)


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Any:
    server = Web(monkeypatch)
    yield server
    server.close()


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def get(owner: flow.Human, **params: Any) -> Any:
    return owner.get("/projects/widget/keep-the-why", params=params)


# --- hostile .keep-the-why ---------------------------------------------------------------------

HOSTILE_LOCATIONS = [
    "../up",
    "a/../../up",
    "/etc",
    "//host/share",
    "https://evil.example/x",
    "file:///etc/passwd",
    "a\\b",
    "%2e%2e",
    "%2e%2e/x",
    ".",
    "./a",
    "a//b",
    "~",
    "ａ",  # fullwidth
    "a/./b",
    "C:/x",
    "context?x",
    "a#b",
]


def test_hostile_locations_are_never_followed(owner: flow.Human, repo: Repo, web: Web) -> None:
    kids = [f"- k{n}: {loc} — s" for n, loc in enumerate(HOSTILE_LOCATIONS)] + ["- ok: ok — s"]
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", kids)
    repo.files["ok/.keep-the-why"] = kfile(f"{BASE}/ok.json", "ok")
    web.routes["/d/s.json"] = doc()
    web.routes["/d/ok.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    body = get(owner).json()
    assert set(repo.reads) == {".keep-the-why", "ok/.keep-the-why"}, repo.reads
    reasons = [m["error"]["reason"] for m in body["members"][1:-1]]
    assert reasons == ["location_not_followed"] * len(HOSTILE_LOCATIONS)
    assert all(not r.startswith("/repos") for r in web.requests)


def test_only_dot_keep_the_why_files_are_read_never_context(
    owner: flow.Human, repo: Repo, web: Web
) -> None:
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- c: context — s"])
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    get(owner)
    assert all(r == ".keep-the-why" or r.endswith("/.keep-the-why") for r in repo.reads)


def test_a_location_of_control_characters_does_not_become_a_second_root(
    owner: flow.Human, repo: Repo, web: Web
) -> None:
    """`\\x01` is non-whitespace (matches `\\S+`), is not followed, and its shown
    path is text(...) == "" -> a second member with path "" next to the root."""
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- ghost: \x01\x02 — s"])
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    paths = [m["path"] for m in get(owner).json()["members"]]
    narrowed = get(owner, member="").json()["members"]
    print("PATHS", paths, "member='' ->", len(narrowed))
    assert paths.count("") == 1, paths
    assert len(narrowed) == 1


def test_one_thousand_children_stay_within_the_caps(
    owner: flow.Human, repo: Repo, web: Web
) -> None:
    kids = [f"- c{n}: c{n} — s" for n in range(1000)]
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", kids)
    for n in range(1000):
        repo.files[f"c{n}/.keep-the-why"] = kfile(f"{BASE}/s.json", f"c{n}")
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    body = get(owner).json()
    assert len(body["members"]) == ktw.MAX_MEMBERS and body["family_truncated"] is True
    assert len(repo.reads) <= ktw.MAX_MEMBERS
    assert len(web.requests) <= ktw.MAX_MEMBERS


def test_one_thousand_url_children_stay_within_the_caps(
    owner: flow.Human, repo: Repo, web: Web
) -> None:
    kids = [f"- c{n}: https://evil.example/{n} — s" for n in range(1000)]
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", kids)
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    body = get(owner).json()
    assert len(body["members"]) == ktw.MAX_MEMBERS and body["family_truncated"] is True
    assert repo.reads == [".keep-the-why"]


def test_deep_nesting_and_respellings_cannot_loop(owner: flow.Human, repo: Repo, web: Web) -> None:
    # every level lists itself under several spellings and a long chain below
    repo.files[".keep-the-why"] = kfile(
        f"{BASE}/s.json",
        "r",
        ["- a: a — s", "- a2: a/ — s", "- a3: a// — s", "- deep: a/a/a/a/a/a/a — s"],
    )
    path = "a"
    for _ in range(12):
        repo.files[f"{path}/.keep-the-why"] = kfile(
            f"{BASE}/s.json", "x", ["- a: a — s", "- a2: a/ — s", "- self: . — s"]
        )
        path += "/a"
    repo.files["a/a/a/a/a/a/a/.keep-the-why"] = kfile(f"{BASE}/s.json", "deep")
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    body = get(owner).json()
    assert body["family_truncated"] is True
    assert len(repo.reads) == len(set(repo.reads)), repo.reads  # nothing read twice
    assert max(r.count("/") for r in repo.reads) <= ktw.MAX_DEPTH + 7


def test_a_root_file_over_64_kib_fails_the_call(owner: flow.Human, repo: Repo, web: Web) -> None:
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json") + b"x" * (64 * 1024)
    flow.project(owner, "widget", repository={"url": REPO})
    answer = get(owner)
    assert answer.status_code == 503
    assert answer.json()["error"]["details"]["reason"] == "forge_unavailable"


def test_a_child_file_over_64_kib_is_that_members_too_large(
    owner: flow.Human, repo: Repo, web: Web
) -> None:
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- h: h — s"])
    repo.files["h/.keep-the-why"] = kfile(f"{BASE}/s.json") + b"x" * (64 * 1024)
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    member = get(owner).json()["members"][1]
    assert member["error"]["reason"] == "too_large"


def test_a_child_dot_keep_the_why_that_is_a_symlink_or_directory(
    owner: flow.Human, repo: Repo, web: Web
) -> None:
    """NIT: a non-file answer (symlink, directory listing) is reported as `too_large`."""
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- h: h — s", "- d: d — s"])
    repo.files["h/.keep-the-why"] = {"type": "symlink", "target": "../../etc/passwd", "size": 10}
    repo.files["d/.keep-the-why"] = [{"type": "file", "name": "x"}]
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    members = get(owner).json()["members"]
    print("NON-FILE REASONS", [m["error"] for m in members[1:]])
    assert members[1]["error"]["reason"] in ("config_missing", "forge_unavailable", "too_large")


def test_many_open_markers_do_not_make_the_parser_quadratic() -> None:
    source = "<!-- keep-the-why:config -->" * (64 * 1024 // 28)
    start = time.monotonic()
    ktw.config(source)
    ktw.children(source.replace("config", "children"))
    elapsed = time.monotonic() - start
    print("MARKERS", round(elapsed, 3))
    assert elapsed < 1.0


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("https://10.0.0.1/s.json", "state_url_invalid"),
        ("https://[::1]/s.json", "state_url_invalid"),
        ("https://169.254.169.254/latest", "state_url_invalid"),
        ("http://ktw.example/s.json", "state_url_invalid"),
        ("https://ktw.example:8443/s.json", "state_url_invalid"),
        ("https://ktw.example:443/d/s.json", None),
        ("https://user:pw@ktw.example/s.json", "state_url_invalid"),
        ("https://user@ktw.example/s.json", "state_url_invalid"),
        ("https://@ktw.example/s.json", "state_url_invalid"),
        ("javascript:alert(1)", "state_url_invalid"),
        ("https://" + "a" * 2050, "state_url_invalid"),
        ("https://internal.example/s.json", "address_refused"),  # resolves to 10.0.0.5
        ("https://127.1/s.json", "address_refused"),  # not a literal to ipaddress
        ("https://0x7f.0.0.1/s.json", "address_refused"),
    ],
)
def test_hostile_state_urls(
    owner: flow.Human, repo: Repo, web: Web, state: str, reason: str | None
) -> None:
    web.addresses["internal.example"] = [ipaddress.ip_address("10.0.0.5")]
    web.addresses["127.1"] = [ipaddress.ip_address("127.0.0.1")]
    web.addresses["0x7f.0.0.1"] = [ipaddress.ip_address("127.0.0.1")]
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- h: h — s"])
    repo.files["h/.keep-the-why"] = kfile(state)
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    member = get(owner).json()["members"][1]
    got = member["error"]["reason"] if member["error"] else None
    print("STATE-URL", state[:60], "->", got)
    assert got == reason
    assert all(host == HOST for host, _ in web.connected)


def test_a_state_url_with_control_or_bidi_characters_is_not_echoed(
    owner: flow.Human, repo: Repo, web: Web
) -> None:
    """the state URL is not cleaned nor refused; it is echoed raw as `state_url`
    and `dashboard_url`."""
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- h: h — s"])
    repo.files["h/.keep-the-why"] = kfile("https://ktw.example/\x01a\u202egpj.json")
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    member = get(owner).json()["members"][1]
    print("CTRL-URL", repr(member["state_url"]), member["error"])
    assert member["state_url"] is None or not any(c in member["state_url"] for c in "\x01\u202e")


# --- hostile state.json ------------------------------------------------------------------------


def one_member(repo: Repo, web: Web, body: Any) -> None:
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- h: h — s"])
    repo.files["h/.keep-the-why"] = kfile(f"{BASE}/h.json", "h")
    web.routes["/d/s.json"] = doc({"id": "ok", "status": "open"})
    web.routes["/d/h.json"] = body


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"[" * 200_000 + b"]" * 200_000, id="deep-array"),
        pytest.param(b'{"a":' * 100_000 + b"1" + b"}" * 100_000, id="deep-object"),
        pytest.param(
            b'{"state-json":2,"entries":[],"topics":' + b"[" * 100_000 + b"]" * 100_000 + b"}",
            id="deep-topics",
        ),
    ],
)
def test_deeply_nested_json_fails_that_member_only(
    owner: flow.Human, repo: Repo, web: Web, body: bytes
) -> None:
    """json.loads raises RecursionError, which read_state does not catch:
    the request is a 500 and nothing is cached, so every request reads the family again."""
    one_member(repo, web, body)
    flow.project(owner, "widget", repository={"url": REPO})
    try:
        answer = get(owner)
    except RecursionError:
        pytest.fail("RecursionError escaped to the client (500)")
    print("DEEP", answer.status_code, answer.text[:200])
    assert answer.status_code == 200
    assert answer.json()["members"][1]["error"]["reason"] in ("not_json", "shape")
    assert answer.json()["members"][0]["error"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"topics": 5},
        {"topics": True},
        {"topics": 1.5},
        {"topics": [{"file": ["x"], "title": "t"}]},
        {"topics": [{"file": "a", "title": "t"}], "entries": [{"id": "x", "file": ["a"]}]},
        {"findings": [1, 2]},
        {"entries": {"0": {}}},
        {
            "entries": [
                1,
                "x",
                None,
                [],
                {"id": 5},
                {"id": "ok", "type": {"a": 1}, "status": ["open"]},
            ]
        },
        {"generated": ["x"]},
        {"state-json": [2]},
        {"state-json": "2.x", "entries": [{"id": "x", "line": -1}]},
        {"state-json": True},
    ],
)
def test_wrong_types_never_fail_the_call(
    owner: flow.Human, repo: Repo, web: Web, extra: dict[str, Any]
) -> None:
    """`topics` that is a truthy non-iterable (5, true, 1.5) raises
    TypeError in digest(): 500."""
    one_member(repo, web, {**doc(), **extra})
    flow.project(owner, "widget", repository={"url": REPO})
    try:
        answer = get(owner)
    except TypeError as error:
        pytest.fail(f"TypeError escaped to the client (500): {error}")
    print("TYPES", json.dumps(extra)[:60], answer.status_code, answer.json()["members"][1]["error"])
    assert answer.status_code == 200
    assert answer.json()["members"][0]["error"] is None


def test_a_lone_surrogate_does_not_break_the_answer_or_the_project_view(
    owner: flow.Human, repo: Repo, web: Web
) -> None:
    """json.loads accepts "\\ud800"; text() keeps it; Starlette's
    JSONResponse encodes to UTF-8 and raises UnicodeEncodeError. The snapshot is cached,
    so the export 500s for 600 s, and so do GET /projects/{slug} and GET /projects once
    the view's cache holds it (§6.1: the project view never fails on the export)."""
    one_member(repo, web, doc({"id": "x", "title": "\\ud800", "status": "open"}))
    web.routes["/d/h.json"] = (
        200,
        b'{"state-json":2,"entries":[{"id":"x","title":"\\ud800","status":"open"}]}',
        {},
    )
    flow.project(owner, "widget", repository={"url": REPO})
    outcomes = {}
    for name, path in (
        ("export", "/projects/widget/keep-the-why"),
        ("view", "/projects/widget"),
        ("list", "/projects"),
    ):
        try:
            outcomes[name] = owner.get(path).status_code
        except UnicodeEncodeError:
            outcomes[name] = "UnicodeEncodeError(500)"
    print("SURROGATE", outcomes)
    assert outcomes == {"export": 200, "view": 200, "list": 200}


def test_a_lone_surrogate_in_state_json_version(owner: flow.Human, repo: Repo, web: Web) -> None:
    one_member(repo, web, None)
    web.routes["/d/h.json"] = (200, b'{"state-json":"\\udfff","entries":[]}', {})
    flow.project(owner, "widget", repository={"url": REPO})
    statuses = {}
    for name, path in (
        ("export", "/projects/widget/keep-the-why"),
        ("view", "/projects/widget"),
        ("list", "/projects"),
    ):
        try:
            statuses[name] = owner.get(path).status_code
        except UnicodeEncodeError:
            statuses[name] = 500
    print("SURROGATE-VERSION", statuses)
    assert statuses == {"export": 200, "view": 200, "list": 200}


def test_links_come_from_the_state_url_only(owner: flow.Human, repo: Repo, web: Web) -> None:
    one_member(
        repo,
        web,
        doc(
            {"id": "a", "uuid": "javascript:alert(1)", "status": "open", "link": "javascript:x"},
            {"id": "https://evil.example/#x", "status": "open", "url": "https://evil.example"},
            {"id": "c", "uuid": "../../x?y#z", "status": "needs-review"},
        ),
    )
    flow.project(owner, "widget", repository={"url": REPO})
    attention = get(owner).json()["attention"]
    links = [a["link"] for a in attention]
    print("LINKS", links)
    assert all(link.startswith(f"{BASE}/#entry/") for link in links)
    assert all(
        "/" not in link.split("#entry/")[1] and ":" not in link.split("#entry/")[1]
        for link in links
    )
    assert all(
        set(a)
        == {"member", "id", "uuid", "title", "type", "status", "file", "line", "topic", "link"}
        for a in attention
    )


def test_long_and_control_strings_are_cut(owner: flow.Human, repo: Repo, web: Web) -> None:
    one_member(
        repo,
        web,
        doc(
            {
                "id": "i\x00\x1b" + "i" * 5000,
                "uuid": "u" * 5000,
                "title": "\u202et" * 5000,
                "type": ["x" * 500] * 50,
                "file": "f\n" * 5000,
                "status": "open",
            }
        ),
    )
    flow.project(owner, "widget", repository={"url": REPO})
    a = get(owner, member="h").json()["attention"][0]
    assert len(a["id"]) == 300 and len(a["uuid"]) == 64 and len(a["title"]) == 200
    assert len(a["type"]) == 8 and all(len(t) == 40 for t in a["type"])
    assert len(a["file"]) == 200 and "\n" not in a["file"] and "\u202e" not in a["title"]
    assert "\x00" not in a["id"] and "\x1b" not in a["id"]


def test_bidi_marks_outside_the_control_class(owner: flow.Human, repo: Repo, web: Web) -> None:
    """NIT: U+200E/U+200F/U+061C (bidi marks) and U+FEFF/U+200B stay in titles."""
    one_member(
        repo, web, doc({"id": "x", "title": "a\u200fb\u061cc\ufeffd\u200be", "status": "open"})
    )
    flow.project(owner, "widget", repository={"url": REPO})
    title = get(owner, member="h").json()["attention"][0]["title"]
    print("BIDI-MARKS", [hex(ord(c)) for c in title])


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ((200, b"[" + b"1," * (600 * 1024) + b"1]", {}), "too_large"),
        ((200, gzip.compress(b" " * (8 * 1024 * 1024)), {"Content-Encoding": "gzip"}), "too_large"),
        ((200, b"\xff\xfe\x00garbage", {}), "not_json"),
        ((200, b"NaN", {}), "shape"),
        ((302, b"", {"Location": "https://evil.example/s.json"}), "redirect_refused"),
        ((302, b"", {"Location": "http://ktw.example/d/s.json"}), "redirect_refused"),
        ((302, b"", {"Location": "https://ktw.example:8443/d/s.json"}), "redirect_refused"),
        ((302, b"", {"Location": "https://u:p@ktw.example/d/s.json"}), "redirect_refused"),
        ((200, json.dumps(doc(**{"state-json": "3.0"})).encode(), {}), "state_json_version"),
    ],
)
def test_hostile_answers(owner: flow.Human, repo: Repo, web: Web, body: Any, reason: str) -> None:
    one_member(repo, web, body)
    flow.project(owner, "widget", repository={"url": REPO})
    member = get(owner).json()["members"][1]
    print("ANSWER", reason, member["error"])
    assert member["error"]["reason"] == reason


def test_a_host_that_does_not_answer_is_reported_as_unavailable(
    owner: flow.Human, repo: Repo, web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reason `unavailable` for a refused connection or failed TLS, not `timeout`."""

    def refused(host: str, address: Any, timeout: float) -> socket.socket:
        raise ConnectionRefusedError

    monkeypatch.setattr(outbound, "connector", refused)
    one_member(repo, web, doc())
    flow.project(owner, "widget", repository={"url": REPO})
    member = get(owner).json()["members"][0]
    print("NO-ANSWER", member["error"])
    assert member["error"]["reason"] == "unavailable"


def test_memory_of_32_members_with_a_1_mib_export_each(repo: Repo, web: Web) -> None:
    """Only counts and attention candidates stay in the cache (and in last_good), since
    nothing else is ever served."""
    entries: list[dict[str, Any]] = []
    size = 40
    while size < 1024 * 1024 - 64:
        entries.append({"id": str(len(entries))})
        size += len(entries[-1]["id"]) + 10
    payload = json.dumps(doc(*entries), separators=(",", ":")).encode()
    assert len(payload) <= ktw.STATE_CAP
    kids = [f"- c{n}: c{n} — s" for n in range(31)]
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", kids)
    for n in range(31):
        repo.files[f"c{n}/.keep-the-why"] = kfile(f"{BASE}/s.json", f"c{n}")
    web.routes["/d/s.json"] = (200, payload, {})
    tracemalloc.start()
    entry, _ = ktw.CACHE.get(forge.Forge(None), "p1", REPO)
    held, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert entry.snapshot is not None
    kept = sum(len(m.read.entries) if m.read else 0 for m in entry.snapshot.members)
    print(
        "MEMORY entries/member",
        len(entries),
        "kept",
        kept,
        "held MiB",
        round(held / 2**20),
        "peak MiB",
        round(peak / 2**20),
    )
    assert held < 256 * 2**20, f"{held / 2**20:.0f} MiB held for one project's export"


# --- concurrency and the cache ----------------------------------------------------------------


def test_simultaneous_reads_are_single_flight_and_release_their_threads(
    repo: Repo, web: Web
) -> None:
    """One upstream read; the others wait at most LOCK_WAIT and get `Busy`."""
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r")
    web.routes["/d/s.json"] = doc()
    web.delay = 1.5
    results: list[Any] = []
    started = time.monotonic()

    def call() -> None:
        try:
            results.append(ktw.CACHE.get(forge.Forge(None), "p1", REPO)[1])
        except ktw.Busy:
            results.append("busy")

    threads = [threading.Thread(target=call) for _ in range(30)]
    for t in threads:
        t.start()
    time.sleep(ktw.LOCK_WAIT + 0.5)
    blocked = sum(t.is_alive() for t in threads)
    for t in threads:
        t.join()
    print(
        "SINGLE-FLIGHT upstream",
        len(web.requests),
        "fresh",
        results.count(True),
        "threads blocked at 0.5 s",
        blocked,
        "total",
        round(time.monotonic() - started, 2),
    )
    assert len(web.requests) == 1 and results.count(True) == 1
    assert results.count("busy") == 29 and blocked == 1


def test_max_age_below_30_does_not_bypass_the_forced_read_interval(
    owner: flow.Human, repo: Repo, web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`?max_age=1` is held to one read per 30 s, like `0`."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r")
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    get(owner)
    fresh = []
    for _ in range(10):
        now[0] += 2
        fresh.append(get(owner, max_age=1).json()["fresh"])
    print("MAX-AGE-1 fresh reads in 20 s:", fresh.count(True), "forge reads", len(repo.reads))
    assert fresh.count(True) <= 1


def test_forced_reads_within_30_s_answer_from_cache(
    owner: flow.Human, repo: Repo, web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r")
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    get(owner)
    seen = []
    for _ in range(14):
        now[0] += 5
        seen.append(get(owner, max_age=0).json()["fresh"])
    assert seen.count(True) == 2  # at 30 and 60 s (the read at 0 starts the clock)


def test_a_failing_read_is_not_throttled(
    owner: flow.Human, repo: Repo, web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the RecursionError/TypeError above nothing is cached: every GET reads the whole
    family again, with no 30 s or 600 s bound."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    one_member(repo, web, (200, b'{"state-json":2,"entries":[],"topics":5}', {}))
    flow.project(owner, "widget", repository={"url": REPO})
    for _ in range(5):
        with contextlib.suppress(Exception):
            get(owner)
    print("UNTHROTTLED forge reads after 5 GETs:", len(repo.reads))
    assert len(repo.reads) <= 2


def test_the_cache_is_per_project(
    make_client: ClientFactory, migrated: Engine, repo: Repo, web: Web
) -> None:
    alice = flow.human(make_client, migrated, "alice")
    bob = flow.human(make_client, migrated, "bob")
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r")
    web.routes["/d/s.json"] = doc({"id": "secret", "status": "open"})
    flow.project(alice, "widget", repository={"url": REPO})
    assert alice.get("/projects/widget/keep-the-why").status_code == 200
    flow.project(bob, "other")
    assert bob.get("/projects/other/keep-the-why").status_code == 409
    assert bob.get("/projects/widget/keep-the-why").status_code == 404
    assert "secret" not in json.dumps(bob.get("/projects").json())


def test_nothing_is_written_to_the_database(
    owner: flow.Human, repo: Repo, web: Web, migrated: Engine
) -> None:
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- h: h — s"])
    repo.files["h/.keep-the-why"] = kfile(f"{BASE}/s.json", "h")
    web.routes["/d/s.json"] = doc({"id": "MARKER-ENTRY", "title": "MARKER-TITLE", "status": "open"})
    flow.project(owner, "widget", repository={"url": REPO})
    meta = MetaData()
    meta.reflect(migrated)

    def snapshot() -> dict[str, Any]:
        with migrated.connect() as conn:
            return {
                name: conn.execute(select(func.count()).select_from(table)).scalar_one()
                for name, table in meta.tables.items()
            }

    before = snapshot()
    for params in ({}, {"max_age": 0}, {"member": "h"}):
        assert get(owner, **params).status_code == 200
    owner.get("/projects/widget")
    after = snapshot()
    changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    print("DB CHANGES", changed)
    assert not {k for k in changed if k not in ("session", "auth_session", "rate_limit")}
    with migrated.connect() as conn:
        for name, table in meta.tables.items():
            for row in conn.execute(select(table)):
                assert "MARKER" not in repr(tuple(row)), name


def test_waiters_on_a_slow_family_do_not_starve_the_request_threadpool(
    owner: flow.Human, repo: Repo, web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route is a sync def: each waiter on the per-project lock holds one of anyio's 40
    worker threads for the whole read. A family read has no total deadline (32 sequential
    contents reads + 8 rounds of 10 s state reads). Here: a 4 s upstream, 45 waiters,
    then an unrelated sync GET /projects/widget."""
    monkeypatch.setattr(outbound, "TIMEOUT", 10.0)
    repo.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r")
    web.routes["/d/s.json"] = doc()
    flow.project(owner, "widget", repository={"url": REPO})
    web.delay = 4.0
    threads = [threading.Thread(target=lambda: get(owner)) for _ in range(45)]
    for t in threads:
        t.start()
    time.sleep(0.5)
    start = time.monotonic()
    status = owner.get("/projects/widget").status_code
    waited = time.monotonic() - start
    for t in threads:
        t.join()
    print("STARVATION unrelated GET waited", round(waited, 2), "s, status", status)
    assert waited < 1.0
