"""docs/api.md §8.7, hub/context/replicas.md: the `s3` attachment store, against a local S3
(moto's server on loopback, no network), and its settings."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto.server import ThreadedMotoServer
from sqlalchemy import Engine

from maity_hub import attachment_store
from maity_hub.attachment_store import S3Store, StoreError
from maity_hub.config import AttachmentS3, ConfigError, Settings, cluster_internal
from tests import flow
from tests.conftest import ClientFactory
from tests.test_attachments import _fresh_limits, put  # noqa: F401  (the autouse fixture)

KEY_ID, SECRET = "AKIAMAITYTEST0000000", "maity-test-secret-never-shown"


@pytest.fixture(scope="module")
def endpoint() -> Iterator[str]:
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def config(endpoint: str, request: pytest.FixtureRequest) -> AttachmentS3:
    """A bucket of its own for each test, made empty."""
    bucket = "maity-" + hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20]
    made = AttachmentS3(
        bucket=bucket,
        endpoint=endpoint,
        region="us-east-1",
        access_key_id=KEY_ID,
        secret_access_key=SECRET,
    )
    raw(made).create_bucket(Bucket=bucket)
    return made


def raw(config: AttachmentS3) -> Any:
    return boto3.session.Session().client(
        "s3",
        endpoint_url=config.endpoint,
        region_name="us-east-1",
        aws_access_key_id=KEY_ID,
        aws_secret_access_key=SECRET,
    )


# --- the store ----------------------------------------------------------------------------------


def test_the_s3_store_keeps_blobs_whole_and_refuses_odd_keys(config: AttachmentS3) -> None:
    store = S3Store(config)
    store.put("prj-1/att-1", b"one")
    store.put("prj-1/att-1", b"two")  # replaced whole
    assert store.get("prj-1/att-1") == b"two" and store.keys("prj-1") == ["prj-1/att-1"]
    store.put("prj-2/att-2", b"x")
    assert sorted(store.projects()) == ["prj-1", "prj-2"]
    age = store.age("prj-1/att-1", time.time())
    assert age is not None and -5 < age < 60
    store.delete("prj-1/att-1")
    store.delete("prj-1/att-1")  # a removal that finds nothing is done
    assert store.get("prj-1/att-1") is None and store.open("prj-1/att-1") is None
    assert store.age("prj-1/att-1", 0.0) is None and store.keys("prj-1") == []
    for key in ("../x", "prj-1/../x", "prj-1/a/b", "/abs", "prj-1/", ""):
        with pytest.raises(ValueError):
            store.put(key, b"x")


def test_a_blob_is_read_in_pieces_with_its_stored_size(config: AttachmentS3) -> None:
    store = S3Store(config)
    data = os.urandom(3 * attachment_store.CHUNK + 5)
    store.put("prj-1/att-1", data)
    blob = store.open("prj-1/att-1")
    assert blob is not None and blob.size == len(data)
    try:
        pieces = list(blob)
    finally:
        blob.close()
    assert b"".join(pieces) == data and all(len(p) <= attachment_store.CHUNK for p in pieces)
    assert len(pieces) > 1


def test_a_prefix_keeps_the_hubs_objects_apart_and_others_are_left_alone(
    config: AttachmentS3,
) -> None:
    store = S3Store(replace(config, prefix="maity/attachments"))
    store.put("prj-1/att-1", b"x")
    names = [o["Key"] for o in raw(config).list_objects_v2(Bucket=config.bucket)["Contents"]]
    assert names == ["maity/attachments/prj-1/att-1"]
    # Another tool's object under the prefix is not a blob key: not listed, never swept.
    raw(config).put_object(Bucket=config.bucket, Key="maity/attachments/prj-1/a/b", Body=b"y")
    raw(config).put_object(Bucket=config.bucket, Key="elsewhere/prj-9/att-9", Body=b"z")
    assert store.keys("prj-1") == ["prj-1/att-1"] and store.projects() == ["prj-1"]


def test_an_error_of_the_service_names_the_operation_and_code_never_a_credential(
    config: AttachmentS3, caplog: pytest.LogCaptureFixture
) -> None:
    missing = S3Store(replace(config, bucket="no-such-bucket-here"))
    caplog.set_level(logging.DEBUG)  # the root at DEBUG after the client was made
    with pytest.raises(StoreError) as raised:
        missing.put("prj-1/att-1", b"x")
    text = str(raised.value)
    assert "store a blob" in text and "NoSuchBucket" in text
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert SECRET not in text and KEY_ID not in text
    # botocore logs the request headers at DEBUG: the store never lets it below INFO.
    assert all(
        SECRET not in r.getMessage() and KEY_ID not in r.getMessage() for r in caplog.records
    )
    assert logging.getLogger("botocore").getEffectiveLevel() >= logging.INFO


def test_one_store_per_configuration_and_shared_only_for_s3(
    config: AttachmentS3, settings: Settings, tmp_path: Path
) -> None:
    s3 = replace(settings, attachment_store="s3", attachment_s3=config)
    assert attachment_store.store_of(s3) is attachment_store.optional_store(s3)
    assert isinstance(attachment_store.store_of(s3), S3Store)
    assert attachment_store.shared(s3) is True
    local = replace(settings, attachment_dir=tmp_path)
    assert isinstance(attachment_store.store_of(local), attachment_store.LocalStore)
    assert attachment_store.shared(local) is False
    assert attachment_store.optional_store(replace(settings, attachment_dir=None)) is None


# --- the routes on the s3 store -----------------------------------------------------------------


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine, config: AttachmentS3) -> flow.Human:
    def stored(**overrides: Any) -> Any:
        return make_client(attachment_store="s3", attachment_s3=config, **overrides)

    owner = flow.human(stored, migrated)
    flow.project(owner, "maity")
    return owner


def _content(owner: flow.Human, attachment_id: str) -> Any:
    return owner.get(f"/projects/maintainer/maity/attachments/{attachment_id}/content")


def test_a_file_goes_to_the_bucket_and_comes_back_byte_for_byte(
    owner: flow.Human, config: AttachmentS3
) -> None:
    shown = put(owner, "a.txt", b"hello s3")
    assert shown.status_code == 201, shown.text
    attachment_id = shown.json()["id"]
    [obj] = raw(config).list_objects_v2(Bucket=config.bucket)["Contents"]
    assert obj["Key"].endswith(f"/{attachment_id}")
    read = _content(owner, attachment_id)
    assert read.status_code == 200 and read.content == b"hello s3"
    assert (
        owner.delete(f"/projects/maintainer/maity/attachments/{attachment_id}").status_code == 200
    )
    assert raw(config).list_objects_v2(Bucket=config.bucket).get("Contents") is None


def test_a_large_file_streams_with_its_length(owner: flow.Human) -> None:
    data = os.urandom(attachment_store.CHUNK * 20 + 7)  # past `WHOLE`: streamed
    attachment_id = put(owner, "big.bin", data, "application/octet-stream").json()["id"]
    read = _content(owner, attachment_id)
    assert read.status_code == 200 and read.content == data
    assert read.headers["content-length"] == str(len(data))


def test_bytes_that_do_not_match_their_digest_are_never_served_whole(
    owner: flow.Human, config: AttachmentS3
) -> None:
    small = put(owner, "a.txt", b"original").json()["id"]
    big_data = os.urandom(attachment_store.CHUNK * 20)
    big = put(owner, "b.bin", big_data, "application/octet-stream").json()["id"]
    objects = {
        o["Key"].rsplit("/", 1)[1]: o["Key"]
        for o in raw(config).list_objects_v2(Bucket=config.bucket)["Contents"]
    }
    raw(config).put_object(Bucket=config.bucket, Key=objects[small], Body=b"swapped!")
    broken = _content(owner, small)
    assert broken.status_code == 500 and broken.json()["error"]["code"] == "internal"
    # Same size, other bytes: the answer has begun, so it ends short and never whole.
    swapped = big_data[:-1] + bytes([big_data[-1] ^ 1])
    raw(config).put_object(Bucket=config.bucket, Key=objects[big], Body=swapped)
    with pytest.raises(StoreError):
        _content(owner, big)
    # A size other than the row's is refused before anything is sent.
    raw(config).put_object(Bucket=config.bucket, Key=objects[big], Body=big_data + b"x")
    longer = _content(owner, big)
    assert longer.status_code == 500 and longer.json()["error"]["code"] == "internal"


# --- the settings -------------------------------------------------------------------------------

BASE = {"MAITY_ATTACHMENT_STORE": "s3", "MAITY_ATTACHMENT_S3_BUCKET": "maity-files"}


def _env(tmp_path: Path, **more: str) -> dict[str, str]:
    return {"MAITY_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}", **BASE, **more}


def test_the_s3_settings_need_a_bucket_and_take_credentials_as_a_pair(tmp_path: Path) -> None:
    ok = Settings.from_env(
        _env(
            tmp_path,
            MAITY_ATTACHMENT_S3_REGION="eu-central-1",
            MAITY_ATTACHMENT_S3_PREFIX="/maity/files/",
            MAITY_ATTACHMENT_S3_ACCESS_KEY_ID=KEY_ID,
            MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY=SECRET,
        )
    )
    assert ok.attachment_store == "s3" and ok.attachment_s3 is not None
    assert ok.attachment_s3.bucket == "maity-files" and ok.attachment_s3.prefix == "maity/files"
    assert ok.attachment_s3.endpoint is None and ok.attachment_s3.region == "eu-central-1"
    assert SECRET not in repr(ok) and KEY_ID not in repr(ok)
    chain = Settings.from_env(_env(tmp_path))  # no pair: boto3's own chain
    assert chain.attachment_s3 is not None and chain.attachment_s3.access_key_id is None
    unset = Settings.from_env({"MAITY_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}"})
    assert unset.attachment_store == "local" and unset.attachment_s3 is None  # the default
    ignored = Settings.from_env(
        {"MAITY_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}", "MAITY_ATTACHMENT_S3_BUCKET": "b"}
    )
    assert ignored.attachment_s3 is None  # read only when the store is `s3`
    for bad in (
        {"MAITY_ATTACHMENT_S3_BUCKET": ""},
        {"MAITY_ATTACHMENT_S3_BUCKET": "a/b"},
        {"MAITY_ATTACHMENT_S3_ACCESS_KEY_ID": KEY_ID},
        {"MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY": SECRET},
        {"MAITY_ATTACHMENT_S3_PREFIX": "a/../b"},
    ):
        with pytest.raises(ConfigError) as raised:
            Settings.from_env(_env(tmp_path, **bad))
        assert SECRET not in str(raised.value) and KEY_ID not in str(raised.value)


@pytest.mark.parametrize(
    ("endpoint", "allow_http", "kept"),
    [
        ("https://s3.example", "", "https://s3.example"),
        ("https://s3.example:9000/", "", "https://s3.example:9000"),
        ("http://127.0.0.1:9000", "1", "http://127.0.0.1:9000"),
        ("http://minio:9000", "1", "http://minio:9000"),
        (
            "http://minio.storage.svc.cluster.local:9000",
            "1",
            "http://minio.storage.svc.cluster.local:9000",
        ),
        ("http://10.0.0.5", "1", "http://10.0.0.5"),
    ],
)
def test_an_endpoint_is_https_or_plain_http_inside_the_cluster(
    tmp_path: Path, endpoint: str, allow_http: str, kept: str
) -> None:
    found = Settings.from_env(
        _env(
            tmp_path,
            MAITY_ATTACHMENT_S3_ENDPOINT=endpoint,
            MAITY_ATTACHMENT_S3_ALLOW_HTTP=allow_http,
        )
    )
    assert found.attachment_s3 is not None and found.attachment_s3.endpoint == kept


@pytest.mark.parametrize(
    ("endpoint", "allow_http"),
    [
        ("http://127.0.0.1:9000", ""),  # plain http needs the switch
        ("http://s3.example", "1"),  # and a host that stays inside
        ("http://203.0.113.9", "1"),
        ("ftp://s3.example", ""),
        ("https://s3.example/bucket", ""),
        ("https://user:pw@s3.example", ""),
        ("https://s3.example?x=1", ""),
        ("https://s3.example:port", ""),
        ("s3.example", ""),
    ],
)
def test_an_endpoint_that_could_leave_the_cluster_in_clear_stops_the_hub(
    tmp_path: Path, endpoint: str, allow_http: str
) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(
            _env(
                tmp_path,
                MAITY_ATTACHMENT_S3_ENDPOINT=endpoint,
                MAITY_ATTACHMENT_S3_ALLOW_HTTP=allow_http,
            )
        )


def test_cluster_internal_hosts() -> None:
    for host in (
        "localhost",
        "127.0.0.1",
        "::1",
        "10.1.2.3",
        "192.168.0.9",
        "fd00::5",
        "minio",
        "s3.ns.svc",
    ):
        assert cluster_internal(host), host
    for host in ("s3.example", "203.0.113.9", "s3.amazonaws.com", "8.8.8.8"):
        assert not cluster_internal(host), host


# --- the copy from a volume into the bucket ----------------------------------------------------


def test_the_copy_to_s3_is_idempotent_and_counts_first_without_apply(
    config: AttachmentS3, tmp_path: Path
) -> None:
    source = attachment_store.LocalStore(tmp_path)
    for key, data in (("prj-1/att-1", b"one"), ("prj-1/att-2", b"two"), ("prj-2/att-3", b"3")):
        source.put(key, data)
    target = S3Store(config)
    counted = attachment_store.copy_local_to_s3(source, target, apply=False)
    assert counted == {"copied": 3, "present": 0, "failed": 0}
    assert raw(config).list_objects_v2(Bucket=config.bucket).get("Contents") is None
    first = attachment_store.copy_local_to_s3(source, target, apply=True)
    assert first == {"copied": 3, "present": 0, "failed": 0}
    assert target.get("prj-1/att-2") == b"two" and target.get("prj-2/att-3") == b"3"
    again = attachment_store.copy_local_to_s3(source, target, apply=True)
    assert again == {"copied": 0, "present": 3, "failed": 0}
    source.put("prj-1/att-1", b"changed")  # other bytes under the same key are copied again
    assert attachment_store.copy_local_to_s3(source, target, apply=True)["copied"] == 1
    assert target.get("prj-1/att-1") == b"changed"
    assert sorted(p.name for p in tmp_path.glob("*/*")) == ["att-1", "att-2", "att-3"]


def test_a_blob_without_the_hubs_digest_is_copied_again(
    config: AttachmentS3, tmp_path: Path
) -> None:
    source = attachment_store.LocalStore(tmp_path)
    source.put("prj-1/att-1", b"one")
    raw(config).put_object(Bucket=config.bucket, Key="prj-1/att-1", Body=b"one")  # no metadata
    target = S3Store(config)
    assert target.digest("prj-1/att-1") is None and target.digest("prj-1/nope") is None
    assert attachment_store.copy_local_to_s3(source, target, apply=True)["copied"] == 1
    assert target.digest("prj-1/att-1") == hashlib.sha256(b"one").hexdigest()


def test_the_copy_command_needs_both_stores_and_fails_on_a_failed_copy(
    config: AttachmentS3,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from maity_hub import cli

    attachment_store.LocalStore(tmp_path).put("prj-1/att-1", b"one")
    env = {
        "MAITY_DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}",
        "MAITY_ATTACHMENT_STORE": "s3",
        "MAITY_ATTACHMENT_S3_BUCKET": config.bucket,
        "MAITY_ATTACHMENT_S3_ENDPOINT": str(config.endpoint),
        "MAITY_ATTACHMENT_S3_ALLOW_HTTP": "1",
        "MAITY_ATTACHMENT_S3_REGION": "us-east-1",
        "MAITY_ATTACHMENT_S3_ACCESS_KEY_ID": KEY_ID,
        "MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY": SECRET,
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MAITY_ATTACHMENT_DIR", raising=False)
    assert cli.main(["attachments", "copy-to-s3", "--apply"]) == cli.EXIT_CONFIG  # no source
    monkeypatch.setenv("MAITY_ATTACHMENT_DIR", str(tmp_path))
    assert cli.main(["attachments", "copy-to-s3"]) == 0
    assert "to copy: 1, already there: 0, failed: 0" in capsys.readouterr().out
    assert cli.main(["attachments", "copy-to-s3", "--apply"]) == 0
    assert "copied: 1" in capsys.readouterr().out
    monkeypatch.setenv("MAITY_ATTACHMENT_S3_BUCKET", "no-such-bucket-here")
    assert cli.main(["attachments", "copy-to-s3", "--apply"]) == cli.EXIT_FAILURE
    out = capsys.readouterr()
    assert "failed: 1" in out.out and SECRET not in out.out + out.err
    monkeypatch.setenv("MAITY_ATTACHMENT_STORE", "local")
    assert cli.main(["attachments", "copy-to-s3"]) == cli.EXIT_CONFIG  # no target
