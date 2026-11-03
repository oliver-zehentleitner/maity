#!/usr/bin/env python3
"""Vendor the Keep the Why views library into web/vendor/keep-the-why/, from a pinned release.

    python3 tools/vendor_ktw.py --version 0.11.39   fetch that release and write its files
    python3 tools/vendor_ktw.py --check             the files on disk match the lock (offline)
    python3 tools/vendor_ktw.py --latest            print the newest release on PyPI

The library ships inside the `keep-the-why-dashboard` wheel on PyPI (ktw_dashboard/web/). The
wheel's address and sha256 come from PyPI's JSON API; a wheel whose digest differs is refused.
From it, exactly the files its `ktw-views.json` lists (scripts, styles, and the manifest itself)
are written, nothing else; a listed name that is not a plain `ktw-*.js`/`ktw-*.css` file name, or
a listed file the wheel lacks, is refused. The licence text comes from the release's tag in the
Keep the Why repository. `VENDOR.json` records the version, the wheel's sha256 and every
file's sha256; `tools/check.py` verifies them (context/stack.md).

Python standard library only.
"""

import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "vendor", "keep-the-why")
LOCK = os.path.join(DEST, "VENDOR.json")
PACKAGE = "keep-the-why-dashboard"
REPOSITORY = "https://github.com/oliver-zehentleitner/keep-the-why"
LICENSE_URL = "https://raw.githubusercontent.com/oliver-zehentleitner/keep-the-why/dashboard-v{version}/LICENSE"
CHANGELOG_URL = REPOSITORY + "/blob/dashboard-v{version}/dashboard/CHANGELOG.md"
PREFIX = "ktw_dashboard/web/"
MANIFEST = "ktw-views.json"
NAME = re.compile(r"^ktw-[a-z0-9-]+\.(js|css)$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
# What the lock itself and the human-written note are; every other file in DEST is the lock's.
OWN = ("VENDOR.json", "README.md", "LICENSE")
MAX_BYTES = 20 * 1024 * 1024


class Refused(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url):
    if not url.startswith("https://"):
        raise Refused("not an https address: %s" % url)
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise Refused("larger than %d bytes: %s" % (MAX_BYTES, url))
    return data


def release(version):
    """The wheel's address and sha256 for a version, from PyPI."""
    if not VERSION.match(version):
        raise Refused("not a release version: %r" % version)
    info = json.loads(fetch("https://pypi.org/pypi/%s/%s/json" % (PACKAGE, version)))
    wheels = [u for u in info["urls"] if u.get("packagetype") == "bdist_wheel"]
    if len(wheels) != 1:
        raise Refused("%s %s has %d wheels, expected one" % (PACKAGE, version, len(wheels)))
    w = wheels[0]
    if not w["url"].startswith("https://files.pythonhosted.org/"):
        raise Refused("the wheel is not on files.pythonhosted.org: %s" % w["url"])
    return w["filename"], w["url"], w["digests"]["sha256"]


def latest():
    info = json.loads(fetch("https://pypi.org/pypi/%s/json" % PACKAGE))
    return info["info"]["version"]


def files_of(wheel):
    """The manifest and the files it lists, as {name: bytes}, from the wheel's bytes."""
    z = zipfile.ZipFile(io.BytesIO(wheel))
    names = set(z.namelist())

    def member(name):
        if PREFIX + name not in names:
            raise Refused("the wheel has no %s%s" % (PREFIX, name))
        return z.read(PREFIX + name)

    raw = member(MANIFEST)
    manifest = json.loads(raw)
    listed = list(manifest.get("scripts", [])) + list(manifest.get("styles", []))
    if not listed:
        raise Refused("%s lists no files" % MANIFEST)
    out = {MANIFEST: raw}
    for name in listed:
        if not isinstance(name, str) or not NAME.match(name):
            raise Refused("%s lists %r, not a plain ktw-*.js or ktw-*.css name" % (MANIFEST, name))
        if name in out:
            raise Refused("%s lists %s twice" % (MANIFEST, name))
        out[name] = member(name)
    return manifest, out


def vendor(version):
    filename, url, digest = release(version)
    wheel = fetch(url)
    if sha256(wheel) != digest:
        raise Refused("%s: sha256 %s, PyPI says %s" % (filename, sha256(wheel), digest))
    manifest, files = files_of(wheel)
    licence = fetch(LICENSE_URL.format(version=version))
    if b"MIT License" not in licence[:200]:
        raise Refused("the licence at the tag is not the MIT licence; look before vendoring")
    os.makedirs(DEST, exist_ok=True)
    # Files of an earlier release that this one no longer lists go.
    for name in os.listdir(DEST):
        if name not in OWN and name not in files:
            os.remove(os.path.join(DEST, name))
    for name, data in files.items():
        with open(os.path.join(DEST, name), "wb") as f:
            f.write(data)
    with open(os.path.join(DEST, "LICENSE"), "wb") as f:
        f.write(licence)
    lock = {
        "comment": "Written by tools/vendor_ktw.py; do not edit. Checked by tools/check.py.",
        "package": PACKAGE,
        "version": version,
        "wheel": filename,
        "wheel_sha256": digest,
        "api": manifest.get("api"),
        "state": manifest.get("state"),
        "scripts": manifest.get("scripts"),
        "styles": manifest.get("styles"),
        "files": {name: sha256(files[name]) for name in sorted(files)},
        "license_sha256": sha256(licence),
        "changelog": CHANGELOG_URL.format(version=version),
    }
    with open(LOCK, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2)
        f.write("\n")
    return lock


def problems(dest=DEST):
    """What differs between the vendored files and their lock; [] when they agree."""
    lock_path = os.path.join(dest, "VENDOR.json")
    if not os.path.exists(lock_path):
        return ["no VENDOR.json: run tools/vendor_ktw.py --version X"]
    with open(lock_path, encoding="utf-8") as f:
        lock = json.load(f)
    out = []
    files = lock.get("files", {})
    listed = [MANIFEST] + list(lock.get("scripts") or []) + list(lock.get("styles") or [])
    if sorted(listed) != sorted(files):
        out.append("VENDOR.json's files are not the manifest and the files it lists")
    for name in listed:
        if not NAME.match(name) and name != MANIFEST:
            out.append("%s: not a plain ktw-*.js or ktw-*.css name" % name)
    present = set(os.listdir(dest))
    for name in sorted(present - set(files) - set(OWN)):
        out.append("%s: not listed by the vendored manifest" % name)
    for name in OWN:
        if name not in present:
            out.append("%s is missing" % name)
    for name, digest in sorted(files.items()):
        path = os.path.join(dest, name)
        if not os.path.exists(path):
            out.append("%s is missing" % name)
            continue
        with open(path, "rb") as f:
            data = f.read()
        if sha256(data) != digest:
            out.append("%s: sha256 differs from VENDOR.json (edited by hand?)" % name)
    path = os.path.join(dest, "LICENSE")
    if os.path.exists(path):
        with open(path, "rb") as f:
            if sha256(f.read()) != lock.get("license_sha256"):
                out.append("LICENSE: sha256 differs from VENDOR.json")
    path = os.path.join(dest, MANIFEST)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        if manifest.get("scripts") != lock.get("scripts") or manifest.get("styles") != lock.get("styles"):
            out.append("%s and VENDOR.json list different files" % MANIFEST)
    return out


def main(argv):
    try:
        if argv[:1] == ["--version"] and len(argv) == 2:
            lock = vendor(argv[1])
            print("vendored %s %s: %d files" % (PACKAGE, lock["version"], len(lock["files"])))
            return 0
        if argv == ["--check"]:
            found = problems()
            for p in found:
                print("vendor/keep-the-why/" + p)
            return 1 if found else 0
        if argv == ["--latest"]:
            print(latest())
            return 0
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return 1
    print(__doc__.strip().split("\n\n")[1])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
