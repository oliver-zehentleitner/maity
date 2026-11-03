#!/usr/bin/env python3
"""The vendored Keep the Why views in a real browser under the hub's policy.

Serves vendor/keep-the-why/ with `Content-Security-Policy: default-src 'self'` (the header the
hub sends with the dashboard, hub/src/maity_hub/middleware.py) on a page that loads the files
the vendored manifest lists, in its order, and mounts the overview, graph, timeline, thoughts,
family, search and an entry from tools/ktw-fixture-state.json (tools/vendor_csp.js). Fails on
any policy violation, page error or rejected promise, on a place left empty, a graph canvas
without ink, or a stylesheet with no rules. Needs Playwright for Python and Chromium, no hub.

    python3 tools/vendor_csp.py
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
from functools import partial
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
VENDOR = WEB / "vendor" / "keep-the-why"
CSP = "default-src 'self'"  # as hub/src/maity_hub/middleware.py sends it
TOOLS = {"vendor_csp.js": WEB / "tools" / "vendor_csp.js",
         "ktw-fixture-state.json": WEB / "tools" / "ktw-fixture-state.json"}
PLACES = ("overview", "timeline", "thoughts", "family", "search", "entry")


def page():
    manifest = json.loads((VENDOR / "ktw-views.json").read_text(encoding="utf-8"))
    links = "".join('<link rel="stylesheet" href="%s">' % n for n in manifest["styles"])
    scripts = "".join('<script src="%s"></script>' % n for n in manifest["scripts"])
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>vendor check</title>%s</head>'
            '<body>%s<script src="vendor_csp.js"></script></body></html>' % (links, scripts)).encode()


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        name = self.path.split("?")[0].lstrip("/")
        if name in ("", "index.html"):
            body = page()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif name in TOOLS:
            body = TOOLS[name].read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript" if name.endswith(".js") else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, *args):
        pass


def main() -> int:
    from playwright.sync_api import sync_playwright

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(VENDOR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    problems = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_page(viewport={"width": 1200, "height": 900})
            console = []
            pg.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: problems.append("page error: %s" % e))
            pg.goto(url)
            result = pg.evaluate("() => window.KTW_VENDOR_RESULT")
            browser.close()
    finally:
        server.shutdown()
    for v in result["violations"]:
        problems.append("policy violation: %s" % v)
    for e in result["errors"]:
        problems.append("error: %s" % e)
    for c in console:
        problems.append("console error: %s" % c)
    for place in PLACES:
        if not result["places"].get(place):
            problems.append("%s: nothing rendered" % place)
    if not result.get("ink"):
        problems.append("graph: the canvas has no ink")
    if not result["rules"]:
        problems.append("ktw-views.css: not applied (no rules)")
    for line in problems:
        print(line)
    print("vendor csp: places %s, graph ink %s, %s css rules; %d problem(s)"
          % (json.dumps(result["places"], sort_keys=True), result.get("ink"), result["rules"], len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
