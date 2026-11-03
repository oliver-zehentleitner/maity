"""Where an attachment's bytes live (docs/api.md §8.7): a blob store behind the hub.

The key is made from the project and the attachment id, never from the name. Two stores
are built, and the operator picks one:

- `local` (the default): a directory of the operator's volume. A blob is written whole to
  a file of its own and moved into place, so a reader never sees half of one. One hub
  process, or replicas that all mount the same directory, see the same bytes.
- `s3` (opt-in, hub/context/replicas.md a70d7269): an S3-compatible bucket, for replicas
  that share nothing else. An object is written by one `PutObject`, so a reader sees
  the old bytes or the new ones.

In both, a removal that finds nothing is a removal that is done, and a read streams the
bytes in pieces (`Blob`) instead of holding the whole file in memory. Nothing here logs
or raises a credential: an error of the S3 client becomes a `StoreError` that names the
operation and the error code only.
"""

from __future__ import annotations

import contextlib
import email.utils
import functools
import logging
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from maity_hub.config import AttachmentS3, Settings
from maity_hub.errors import ApiError

CHUNK = 64 * 1024


class StoreError(RuntimeError):
    """The store could not do what was asked. The message names the operation and, for
    `s3`, the error code; never a credential, never the endpoint's answer in full."""


class Blob(Protocol):
    """An open blob: its size as stored, its bytes in pieces, and `close`."""

    size: int

    def __iter__(self) -> Iterator[bytes]: ...

    def close(self) -> None: ...


class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def open(self, key: str) -> Blob | None: ...

    def get(self, key: str) -> bytes | None: ...

    def delete(self, key: str) -> None: ...

    def projects(self) -> list[str]: ...

    def age(self, key: str, now: float) -> float | None: ...

    def keys(self, project: str) -> list[str]: ...


def split_key(key: str) -> tuple[str, str]:
    """`<project>/<attachment>`, both plain names; anything else is not a blob key."""
    project, _, name = key.partition("/")
    if not project or not name or "/" in name or {".", ".."} & {project, name}:
        raise ValueError("not a blob key")
    return project, name


class _FileBlob:
    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle
        self.size = os.fstat(handle.fileno()).st_size

    def __iter__(self) -> Iterator[bytes]:
        while chunk := self._handle.read(CHUNK):
            yield chunk

    def close(self) -> None:
        self._handle.close()


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        project, name = split_key(key)
        return self.root / project / name

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        scratch = path.with_name(f".{path.name}.{secrets.token_hex(6)}")
        try:
            with open(scratch, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(scratch, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                scratch.unlink()
            raise

    def open(self, key: str) -> Blob | None:
        try:
            return _FileBlob(open(self._path(key), "rb"))
        except FileNotFoundError:
            return None

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(key).unlink()

    def projects(self) -> list[str]:
        """The projects that have a folder, for the sweep."""
        return [p.name for p in self.root.iterdir() if p.is_dir()]

    def age(self, key: str, now: float) -> float | None:
        """Seconds since the blob was written, or None when it is gone."""
        try:
            return now - self._path(key).stat().st_mtime
        except FileNotFoundError:
            return None

    def keys(self, project: str) -> list[str]:
        """The blobs of one project, for the sweep."""
        folder = self.root / project
        if not folder.is_dir():
            return []
        return [f"{project}/{p.name}" for p in folder.iterdir() if not p.name.startswith(".")]


# The S3 client's own errors, by code, that mean "there is no such object".
_MISSING = {"NoSuchKey", "404", "NotFound"}


def _code(error: Exception) -> str:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code") or "unknown")
    return type(error).__name__


class _S3Blob:
    def __init__(self, body: Any, size: int) -> None:
        self._body = body
        self.size = size

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self._body.iter_chunks(CHUNK)
        except Exception as error:
            raise StoreError(
                f"the attachment store could not read a blob ({_code(error)})"
            ) from None

    def close(self) -> None:
        self._body.close()


class S3Store:
    """A bucket of an S3-compatible service through boto3 (hub/context/replicas.md
    a70d7269). One client per process; boto3's clients are safe to share between
    threads."""

    def __init__(self, config: AttachmentS3, client: Any = None) -> None:
        self.bucket = config.bucket
        self.base = f"{config.prefix}/" if config.prefix else ""
        self.client = client if client is not None else _client(config)

    def _object(self, key: str) -> str:
        split_key(key)
        return self.base + key

    def _fail(self, what: str, error: Exception) -> StoreError:
        return StoreError(f"the attachment store could not {what} ({_code(error)})")

    def put(self, key: str, data: bytes) -> None:
        name = self._object(key)
        try:
            self.client.put_object(Bucket=self.bucket, Key=name, Body=data)
        except Exception as error:
            raise self._fail("store a blob", error) from None

    def open(self, key: str) -> Blob | None:
        name = self._object(key)
        try:
            answer = self.client.get_object(Bucket=self.bucket, Key=name)
        except Exception as error:
            if _code(error) in _MISSING:
                return None
            raise self._fail("read a blob", error) from None
        return _S3Blob(answer["Body"], int(answer["ContentLength"]))

    def get(self, key: str) -> bytes | None:
        blob = self.open(key)
        if blob is None:
            return None
        try:
            return b"".join(blob)
        finally:
            blob.close()

    def delete(self, key: str) -> None:
        name = self._object(key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=name)
        except Exception as error:
            if _code(error) in _MISSING:
                return
            raise self._fail("remove a blob", error) from None

    def _list(self, prefix: str, **more: Any) -> Iterator[dict[str, Any]]:
        try:
            pages = self.client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefix, **more
            )
            yield from pages
        except Exception as error:
            raise self._fail("list blobs", error) from None

    def projects(self) -> list[str]:
        """The projects that have a blob, for the sweep."""
        found = []
        for page in self._list(self.base, Delimiter="/"):
            for common in page.get("CommonPrefixes", []):
                project = common["Prefix"][len(self.base) :].rstrip("/")
                if project and "/" not in project and project not in (".", ".."):
                    found.append(project)
        return found

    def age(self, key: str, now: float) -> float | None:
        name = self._object(key)
        try:
            answer = self.client.head_object(Bucket=self.bucket, Key=name)
        except Exception as error:
            if _code(error) in _MISSING:
                return None
            raise self._fail("look at a blob", error) from None
        written = float(answer["LastModified"].timestamp())
        # Both times from the store's clock: the answer's `Date` against the object's
        # LastModified, so the hub's clock may differ from the store's by any amount
        # (hub/context/attachments.md 7dcd4850). Without a usable `Date`, the hub's `now`.
        store_now = _date(answer)
        age = (store_now if store_now is not None else now) - written
        if age < -1:
            logging.getLogger(__name__).warning("a blob's age is negative: the clocks disagree")
        return age

    def keys(self, project: str) -> list[str]:
        """The blobs of one project, for the sweep; an object under the prefix that is
        not a blob key (a folder marker, another tool's file) is not the hub's and is
        left alone."""
        found = []
        for page in self._list(f"{self.base}{project}/"):
            for item in page.get("Contents", []):
                key = item["Key"][len(self.base) :]
                try:
                    split_key(key)
                except ValueError:
                    continue
                found.append(key)
        return found


def _date(answer: dict[str, Any]) -> float | None:
    """The `Date` header of a store's answer, in seconds since the epoch, or None."""
    raw = answer.get("ResponseMetadata", {}).get("HTTPHeaders", {}).get("date")
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(str(raw)).timestamp()
    except (TypeError, ValueError):
        return None


def _client(config: AttachmentS3) -> Any:
    import boto3
    from botocore.config import Config

    # botocore logs each request's headers at DEBUG, the access key id among them: its own
    # loggers are set to INFO, so that a root logger at DEBUG (now or later) does not reach them.
    for name in ("botocore", "boto3", "s3transfer", "urllib3"):
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET or logger.level < logging.INFO:
            logger.setLevel(logging.INFO)
    options: dict[str, Any] = {
        "retries": {"mode": "standard", "max_attempts": 3},
        "connect_timeout": 5,
        "read_timeout": 60,
    }
    if config.endpoint is not None:
        # An S3-compatible service (MinIO, Ceph, a hoster's): bucket in the path, and
        # checksums only where the API requires them, which every such service accepts.
        options["s3"] = {"addressing_style": "path"}
        options["request_checksum_calculation"] = "when_required"
        options["response_checksum_validation"] = "when_required"
    return boto3.session.Session().client(
        "s3",
        endpoint_url=config.endpoint,
        region_name=config.region,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        config=Config(**options),
    )


@functools.lru_cache(maxsize=4)
def _s3(config: AttachmentS3) -> S3Store:
    return S3Store(config)


def key_of(project_id: str, attachment_id: str) -> str:
    return f"{project_id}/{attachment_id}"


def optional_store(settings: Settings) -> BlobStore | None:
    """The configured store, or None where attachments are switched off: for the code
    that removes bytes when it can and has nothing to remove when it cannot."""
    if settings.attachment_s3 is not None:
        return _s3(settings.attachment_s3)
    return LocalStore(settings.attachment_dir) if settings.attachment_dir is not None else None


def store_of(settings: Settings) -> BlobStore:
    """The configured store, or `attachments_not_configured` (409) when the operator has
    set neither `MAITY_ATTACHMENT_STORE=s3` nor a `MAITY_ATTACHMENT_DIR`."""
    store = optional_store(settings)
    if store is None:
        raise ApiError(
            409,
            "attachments_not_configured",
            "this hub has no attachment store: the operator sets MAITY_ATTACHMENT_DIR",
        )
    return store


def configured(settings: Settings | None) -> bool:
    """Whether the hub has an attachment store, without building one (no client, no network):
    `s3`, or `local` with its directory."""
    return settings is not None and (
        settings.attachment_s3 is not None or settings.attachment_dir is not None
    )


def shared(settings: Settings) -> bool:
    """Whether every replica sees the same bytes without a shared volume: true for `s3`.
    `local` is one directory, shared only when the operator mounts the same one in
    every replica, which the hub cannot see."""
    return settings.attachment_s3 is not None
