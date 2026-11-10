from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from maity_hub import API_VERSION, __version__
from maity_hub.app import SchemaNotCurrentError, create_app
from maity_hub.config import ConfigError, Settings
from maity_hub.db import downgrade, head_revision, migrate


def test_health_reports_a_migrated_database(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["api"] == API_VERSION
    head = head_revision(client.app.state.engine)  # type: ignore[attr-defined]
    assert body["database"] == {"reachable": True, "revision": head, "head": head}


def test_health_does_not_read_the_migration_files_per_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_engine: Engine) -> None:
        raise AssertionError("the head is read once, when the app is made")

    monkeypatch.setattr("maity_hub.app.head_revision", boom)
    monkeypatch.setattr("maity_hub.db.head_revision", boom)
    assert client.get("/api/v1/health").status_code == 200


def test_health_turns_503_when_the_schema_falls_behind(client: TestClient, engine: Engine) -> None:
    downgrade(engine)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.headers["Maity-Error"] == "schema_outdated"
    error = response.json()["error"]
    assert error["code"] == "schema_outdated"
    assert error["details"] == {"revision": None, "head": head_revision(engine)}


@pytest.mark.wheel
def test_help_is_markdown_and_names_the_api_version(client: TestClient) -> None:
    response = client.get("/api/v1/help")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text.startswith("# Maity hub API")
    assert f"API version: {API_VERSION} · hub {__version__} · https://hub.example" in response.text


@pytest.mark.wheel
def test_help_keeps_literal_braces(client: TestClient) -> None:
    text = client.get("/api/v1/help").text
    assert "`/api/v1/projects/{project_id}`" in text
    assert '`{"title": "…"}`' in text


def test_no_swagger_ui_but_the_openapi_document(client: TestClient) -> None:
    assert client.get("/api/v1/docs").status_code == 404
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_the_shell_is_served_at_the_root_and_at_every_dashboard_path(
    client: TestClient, web_dir: Path
) -> None:
    for path in ("/", "/login", "/maintainer/maity/board", "/a/b/c/d", "/no-such-page"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "<title>dashboard</title>" in response.text
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "default-src 'self'"
        assert "set-cookie" not in response.headers
    # The root's `noindex` is the middleware's, while the landing page is off (§16.7); every
    # other path of the shell carries its own.
    assert client.get("/maintainer/maity/board").headers["x-robots-tag"] == "noindex"
    assert client.head("/login").status_code == 200


def test_the_invitation_page_sends_no_referrer_and_the_others_keep_theirs(
    client: TestClient, web_dir: Path
) -> None:
    # Its token is in the path: a link it opens must not carry it along (docs/api.md §16.13).
    assert client.get("/invite/some-token").headers["referrer-policy"] == "no-referrer"
    assert "referrer-policy" not in client.get("/maintainer/maity/board").headers


def test_the_shell_carries_a_base_so_its_relative_files_load_from_assets_at_any_depth(
    client: TestClient, web_dir: Path
) -> None:
    (web_dir / "js").mkdir()
    (web_dir / "js" / "app.js").write_text("// dashboard")
    for path in ("/", "/a/b/c", "/maintainer/maity/board"):
        page = client.get(path).text
        assert page.index("<head>") + len("<head>") == page.index('<base href="/assets/">'), path
        assert 'src="js/app.js"' in page  # the file itself stays relative (fixture mode)
    assert client.get("/assets/js/app.js").text == "// dashboard"


URL = "https://hub.example/"


def test_the_social_image_gets_a_whole_address() -> None:
    from maity_hub.shell import shell_document

    page = b'<head><meta property="og:image" content="brand/x.png"><link href="brand/y.svg">'
    served = shell_document(page, URL)
    assert b'content="https://hub.example/assets/brand/x.png"' in served
    assert b'<link href="brand/y.svg">' in served  # the base serves the rest


def test_a_page_without_a_head_is_served_as_it_is() -> None:
    from maity_hub.shell import shell_document

    assert shell_document(b"<p>x</p>", URL) == b"<p>x</p>"
    assert (
        shell_document(b"<HEAD lang=x><title/>", URL)
        == b'<HEAD lang=x><base href="/assets/"><title/>'
    )


def test_built_files_are_served_under_assets(client: TestClient, web_dir: Path) -> None:
    (web_dir / "js").mkdir()
    (web_dir / "js" / "app.js").write_text("// dashboard")
    (web_dir / "brand").mkdir()
    (web_dir / "brand" / "logo.svg").write_text("<svg/>")
    assert client.get("/assets/js/app.js").text == "// dashboard"
    assert client.get("/assets/brand/logo.svg").status_code == 200
    (web_dir / "vendor" / "keep-the-why").mkdir(parents=True)
    (web_dir / "vendor" / "keep-the-why" / "ktw-core.js").write_text("// library")
    assert client.get("/assets/vendor/keep-the-why/ktw-core.js").text == "// library"
    # The old place of a file is not a file any more: it is a dashboard path, the shell.
    old = client.get("/js/app.js")
    assert old.status_code == 200 and "<title>dashboard</title>" in old.text


GZIP = {"Accept-Encoding": "gzip"}
IDENTITY = {"Accept-Encoding": "identity"}


def _css(web_dir: Path) -> str:
    # Above 1024 bytes, so it has a gzip form (serving.md 5cfd29b6, c6768529).
    content = "body{}\n" * 300
    (web_dir / "css").mkdir()
    (web_dir / "css" / "app.css").write_text(content)
    return content


def test_a_built_file_is_revalidated_by_the_etag_of_its_content(
    client: TestClient, web_dir: Path
) -> None:
    # docs/api.md §1 and §16.11 (req-s246xb6k1mpp): `no-cache`, a content ETag, 304 on a match.
    content = _css(web_dir)
    plain = client.get("/assets/css/app.css", headers=IDENTITY)
    assert plain.status_code == 200 and plain.text == content
    assert "content-encoding" not in plain.headers
    assert plain.headers["cache-control"] == "no-cache"
    assert plain.headers["vary"] == "Accept-Encoding"
    etag = plain.headers["etag"]
    assert etag.startswith('"') and not etag.startswith("W/") and len(etag) == 34
    assert "last-modified" not in plain.headers
    again = client.get("/assets/css/app.css", headers={"If-None-Match": etag} | IDENTITY)
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == etag and again.headers["cache-control"] == "no-cache"
    assert again.headers["vary"] == "Accept-Encoding"
    other = client.get("/assets/css/app.css", headers={"If-None-Match": '"0"'} | IDENTITY)
    assert other.status_code == 200 and other.headers["etag"] == etag
    # Only the ETag decides: a date alone never answers 304.
    dated = client.get(
        "/assets/css/app.css",
        headers={"If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT"} | IDENTITY,
    )
    assert dated.status_code == 200


def test_the_gzip_form_has_its_own_etag(client: TestClient, web_dir: Path) -> None:
    content = _css(web_dir)
    plain = client.get("/assets/css/app.css", headers=IDENTITY)
    packed = client.get("/assets/css/app.css", headers=GZIP)
    assert packed.status_code == 200 and packed.headers["content-encoding"] == "gzip"
    assert packed.text == content  # gzipped once: the client's one decoding gives the file
    assert int(packed.headers["content-length"]) < len(content)
    assert packed.headers["vary"] == "Accept-Encoding"  # the middleware added nothing
    tag = packed.headers["etag"]
    assert tag == plain.headers["etag"][:-1] + '-gzip"'
    assert client.get("/assets/css/app.css", headers=GZIP).headers["etag"] == tag  # stable
    match = client.get("/assets/css/app.css", headers={"If-None-Match": tag} | GZIP)
    assert match.status_code == 304 and match.content == b""
    assert match.headers["vary"] == "Accept-Encoding" and match.headers["etag"] == tag
    # Each form's tag validates only that form.
    crossed = client.get("/assets/css/app.css", headers={"If-None-Match": tag} | IDENTITY)
    assert crossed.status_code == 200 and crossed.text == content
    crossed = client.get(
        "/assets/css/app.css", headers={"If-None-Match": plain.headers["etag"]} | GZIP
    )
    assert crossed.status_code == 200 and crossed.headers["content-encoding"] == "gzip"
    refused = client.get("/assets/css/app.css", headers={"Accept-Encoding": "gzip;q=0"})
    assert (
        "content-encoding" not in refused.headers
        and refused.headers["etag"] == plain.headers["etag"]
    )


def test_a_range_is_selected_by_the_etag_alone(client: TestClient, web_dir: Path) -> None:
    content = _css(web_dir)
    etag = client.get("/assets/css/app.css", headers=IDENTITY).headers["etag"]
    asked = {"Range": "bytes=0-9"} | IDENTITY
    part = client.get("/assets/css/app.css", headers={"If-Range": etag} | asked)
    assert part.status_code == 206 and part.text == content[:10]
    assert part.headers["content-range"] == f"bytes 0-9/{len(content)}"
    for stale in ('"0"', "Fri, 01 Jan 2100 00:00:00 GMT", "W/" + etag):
        whole = client.get("/assets/css/app.css", headers={"If-Range": stale} | asked)
        assert whole.status_code == 200 and whole.text == content, stale
    assert client.get("/assets/css/app.css", headers=asked).status_code == 206


def test_a_small_file_has_one_form(client: TestClient, web_dir: Path) -> None:
    (web_dir / "js").mkdir()
    (web_dir / "js" / "app.js").write_text("// small")
    for headers in (GZIP, IDENTITY):
        response = client.get("/assets/js/app.js", headers=headers)
        assert response.status_code == 200 and response.text == "// small"
        assert "content-encoding" not in response.headers and "vary" not in response.headers
        assert response.headers["cache-control"] == "no-cache"
        assert not response.headers["etag"].endswith('-gzip"')


def test_a_changed_file_with_the_same_time_and_size_gets_a_new_etag(
    client: TestClient, web_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub import shell

    target = web_dir / "js" / "app.js"
    target.parent.mkdir()
    target.write_text("// one")
    old = client.get("/assets/js/app.js").headers["etag"]
    stamp = target.stat().st_mtime_ns
    target.write_text("// two")
    os.utime(target, ns=(stamp, stamp))
    # A new image with normalised file times starts a new process: nothing is remembered.
    monkeypatch.setattr(shell, "_FORMS", {})
    response = client.get("/assets/js/app.js", headers={"If-None-Match": old})
    assert response.status_code == 200 and response.text == "// two"
    assert response.headers["etag"] != old


def test_the_middleware_leaves_the_dashboards_files_to_assetfiles() -> None:
    from maity_hub import compression, shell

    assert {path.split("/")[2] for path in compression.OWN_ENCODING} == shell.ASSET_DIRS
    assert not compression.compressed("GET", "/assets/js/app.js")
    assert compression.compressed("GET", "/assets/landing/landing.css")
    assert compression.compressed("GET", "/api/v1/health")
    for accepted in ("gzip", "br, gzip;q=0.5", "*", "GZIP ; Q=1.000", "gzip;q=0, gzip;q=1"):
        assert compression.accepts_gzip(accepted), accepted
    # An explicit refusal wins over `*` wherever it stands (RFC 9110 §12.5.3); a weight
    # outside the grammar accepts nothing.
    for refused in (
        "gzip;q=0",
        "identity",
        "",
        "gzip;q=0, *",
        "*;q=1, gzip;q=0",
        "*;q=0",
        "gzip;q=2",
        "gzip;q=inf",
        "gzip;q=NaN",
        "gzip;q=-1",
        "gzip;q=0.0001",
        "gzip;q=bogus",
        "gzip;q=0.\u0661",  # an Arabic-Indic digit one
        "gzip;q=0.\uff11",  # a full-width digit one
    ):
        assert not compression.accepts_gzip(refused), refused


def test_a_refused_gzip_is_not_sent_even_beside_a_wildcard(
    client: TestClient, web_dir: Path
) -> None:
    content = _css(web_dir)
    for header in ("gzip;q=0, *", "*;q=1, gzip;q=0", "gzip;q=2"):
        response = client.get("/assets/css/app.css", headers={"Accept-Encoding": header})
        assert response.status_code == 200 and response.text == content, header
        assert "content-encoding" not in response.headers, header
        assert not response.headers["etag"].endswith('-gzip"'), header
    wanted = client.get("/assets/css/app.css", headers={"Accept-Encoding": "br;q=1, *;q=0.5"})
    assert wanted.headers["content-encoding"] == "gzip"


def test_a_request_without_accept_encoding_gets_the_plain_form_and_its_etag(
    client: TestClient, web_dir: Path
) -> None:
    """No header at all is not a gzip request (RFC 9110 §12.5.3): the plain body comes with the
    plain tag. The test client sends `Accept-Encoding` by default, so it is removed here."""
    content = _css(web_dir)
    plain = client.get("/assets/css/app.css", headers=IDENTITY).headers["etag"]
    del client.headers["accept-encoding"]
    bare = client.get("/assets/css/app.css")
    assert "accept-encoding" not in bare.request.headers
    assert bare.status_code == 200 and bare.text == content
    assert "content-encoding" not in bare.headers and bare.headers["etag"] == plain
    assert bare.headers["vary"] == "Accept-Encoding"


def test_only_the_built_files_leave_no_store(client: TestClient, web_dir: Path) -> None:
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"
    missing = client.get("/assets/js/none.js")
    assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"
    assert "etag" not in missing.headers


@pytest.mark.parametrize(
    "path",
    [
        "/assets/index.html",
        "/assets/.env",
        "/assets/js/.secret",
        "/assets/fixtures/me.json",
        "/assets/tools/serve.py",
        "/assets/README.md",
        "/assets/",
        "/assets",
        "/api/v1/page.html",
        "/api/x",
    ],
)
def test_nothing_but_the_built_files_is_served_as_a_file(
    client: TestClient, web_dir: Path, path: str
) -> None:
    for name in (".env", "js/.secret", "fixtures/me.json", "tools/serve.py", "README.md"):
        target = web_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("must not leak")
    response = client.get(path)
    assert response.status_code == 404
    assert "must not leak" not in response.text and "<title>dashboard</title>" not in response.text


def test_a_hub_path_that_names_nothing_is_not_the_shell(client: TestClient) -> None:
    for path in ("/mail/nothing/here", "/badge/x", "/join", "/r/token", "/impressum/1"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "<title>dashboard</title>" not in response.text, path


def test_any_other_method_on_a_shell_path_is_not_found(client: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/maintainer/maity/board")
        assert response.status_code == 404, method
        assert response.json()["error"]["code"] == "not_found"


def test_refuses_to_start_on_an_unmigrated_database(settings: Settings, engine: Engine) -> None:
    with (
        pytest.raises(SchemaNotCurrentError, match="maity-hub migrate"),
        TestClient(create_app(settings, engine)),
    ):
        pass


def test_a_missing_explicit_web_dir_fails(settings: Settings, engine: Engine) -> None:
    broken = Settings.from_env(
        {"MAITY_DATABASE_URL": settings.database_url, "MAITY_WEB_DIR": "/nonexistent/web"}
    )
    with pytest.raises(ConfigError, match="MAITY_WEB_DIR"):
        create_app(broken, engine)


@pytest.mark.parametrize("web_dir", ["absent", None])
def test_without_a_dashboard_the_api_still_serves(
    settings: Settings, engine: Engine, tmp_path: Path, web_dir: str | None
) -> None:
    migrate(engine)
    api_only = replace(
        settings,
        web_dir=tmp_path / web_dir if web_dir else None,
        web_dir_required=False,
    )
    with TestClient(create_app(api_only, engine)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/").status_code == 404


@pytest.mark.wheel
def test_the_default_dashboard_is_served(database_url: str, migrated: Engine) -> None:
    """Whatever this runs from, a checkout or the installed wheel (CI's hub-wheel job), the
    hub serves a dashboard without MAITY_WEB_DIR."""
    settings = Settings.from_env({"MAITY_DATABASE_URL": database_url})
    with TestClient(create_app(settings, migrated)) as client:
        root = client.get("/")
        assert root.status_code == 200 and "<title>" in root.text
        assert client.get("/assets/js/app.js").status_code == 200


def test_driver_reason_names_a_category_and_never_the_driver_text() -> None:
    from sqlalchemy.exc import OperationalError

    from maity_hub.errors import driver_reason

    class ConnectionTimeout(Exception):
        pass

    cases = {
        "dns": "failed to resolve host 'db': [Errno -2] Name or service not known",
        "timeout": 'connection to server at "10.0.0.5", port 5432 failed: timeout expired',
        "refused": "connection failed: Connection refused",
        "closed": "consuming input failed: server closed the connection unexpectedly",
        "no_slots": "FATAL: remaining connection slots are reserved",
        "unclassified": "something no list knows",
    }
    for category, text in cases.items():
        reason = driver_reason(OperationalError("SELECT 1", {}, ConnectionTimeout(text)))
        assert reason.endswith(f" {category}"), (category, reason)
        assert reason.startswith("tests.test_app.") or ".ConnectionTimeout " in reason
    assert driver_reason(Exception("no orig")) == ""


def test_driver_reason_never_carries_the_driver_text() -> None:
    """Every form in which a driver could quote a credential, however it is escaped or encoded."""
    from sqlalchemy.exc import OperationalError

    from maity_hub.errors import driver_reason

    texts = [
        "host=db password='prefix\\'LEAK_MARKER'",
        "password=prefix\\ LEAK_MARKER",
        "postgresql://user:prefix'LEAK_MARKER@db/name",
        "postgresql%3A%2F%2Fuser%3ALEAK_MARKER%40db%2Fname",
        "{'password': 'LEAK_MARKER'}",
        "failed to resolve host 'LEAK_MARKER' user=LEAK_MARKER",
        "timeout expired LEAK_MARKER\n" + "x" * 5000,
    ]
    for text in texts:
        reason = driver_reason(OperationalError("SELECT 1", {}, Exception(text)))
        assert "LEAK_MARKER" not in reason and "\n" not in reason and len(reason) < 120, reason


def test_the_database_error_handler_logs_the_cause_not_the_secret(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    from sqlalchemy.exc import OperationalError

    def broken() -> None:
        raise OperationalError(
            "SELECT 1", {}, Exception("failed to resolve host 'db' postgresql://u:pw-in-dsn@db/x")
        )

    client.app.add_api_route("/api/v1/_broken", broken)  # type: ignore[attr-defined]
    with caplog.at_level("ERROR", logger="maity_hub.errors"):
        response = client.get("/api/v1/_broken")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert logged.endswith(" dns") and "pw-in-dsn" not in logged
    assert "pw-in-dsn" not in response.text
