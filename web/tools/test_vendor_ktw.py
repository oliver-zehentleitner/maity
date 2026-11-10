"""make check: vendor_ktw.py's network failures end in one `refused:` line, never a traceback, and
one run's network time has a hard deadline, whatever a fetch is doing when it passes (web P3
roll-up, tsk-gsk31zvpfv02; #1497 review). The slow peers are real servers on 127.0.0.1; nothing
leaves the machine."""

import contextlib
import http.client
import http.server
import io
import os
import sys
import threading
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vendor_ktw  # noqa: E402

failures = 0


def check(ok, what):
    global failures
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures += 1


def run(argv):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = vendor_ktw.main(argv)
    return code, err.getvalue()


real_urlopen = vendor_ktw.urllib.request.urlopen
try:
    # A connection that fails: refused, one line naming the address and the cause.
    def refused(url, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    vendor_ktw.urllib.request.urlopen = refused
    vendor_ktw._deadline = None
    code, err = run(["--latest"])
    check(code == 1 and err.startswith("refused: network: https://pypi.org/") and "Connection refused" in err
          and "Traceback" not in err, "a refused connection is one refused: line " + repr(err))

    # A timeout, as an attempt that never connects ends.
    def slow(url, timeout):
        raise TimeoutError("timed out")

    vendor_ktw.urllib.request.urlopen = slow
    vendor_ktw._deadline = None
    code, err = run(["--latest"])
    check(code == 1 and "refused: network:" in err and "timed out" in err, "a timeout is one refused: line " + repr(err))

    # Each socket wait is capped, and no fetch starts once the run's time is spent.
    seen = []

    def answer(url, timeout):
        seen.append(timeout)
        raise urllib.error.URLError("unreachable")

    vendor_ktw.urllib.request.urlopen = answer
    vendor_ktw._deadline = None
    run(["--latest"])
    vendor_ktw._deadline = time.monotonic() - 1
    code, err = run(["--latest"])
    check(seen == [vendor_ktw.ATTEMPT_SECONDS] and code == 1 and "no answer within" in err,
          "a socket wait is capped at ATTEMPT_SECONDS, and no fetch starts after the deadline " + repr((seen, err)))
    # A body cut short (IncompleteRead) and a body that is not JSON: each one refused: line,
    # never a traceback (#1497 review).
    class Answer:
        def __init__(self, read):
            self.read = read

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def cut(n=-1):
        raise http.client.IncompleteRead(b'{"info": {"vers', 200)

    for what, body in (("a body cut short", cut), ("a body that is not JSON", lambda n=-1: b"<html>busy</html>")):
        vendor_ktw.urllib.request.urlopen = lambda url, timeout, body=body: Answer(body)
        vendor_ktw._deadline = None
        try:
            code, err = run(["--latest"])
        except Exception as e:  # an earlier head let it through
            code, err = None, "%s: %s" % (type(e).__name__, e)
        check(code == 1 and err.startswith("refused: ") and "Traceback" not in err and "\n" == err[-1:],
              "%s is one refused: line %r" % (what, err))
finally:
    vendor_ktw.urllib.request.urlopen = real_urlopen


# Two slow peers, each dripping one byte every 0.05 s for 2 s, just inside a 0.15 s wait: one a
# body with a Content-Length, one inside chunk framing (a chunk extension), which http.client
# reads itself. With a 0.3 s deadline both fetches must be refused at the deadline.
class Drip(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.send_response(200)
        chunked = self.path == "/chunked"
        self.send_header("Transfer-Encoding", "chunked") if chunked else self.send_header("Content-Length", "40")
        self.end_headers()
        try:
            if chunked:
                self.wfile.write(b"1;ext=")
            for _ in range(40):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.05)
            if chunked:
                self.wfile.write(b"\r\nx\r\n0\r\n\r\n")
        except OSError:
            pass

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Drip)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % server.server_address[1]


def old_within(url):
    # An earlier head's fetch without its https check, for the counter-check: e766d42f read the
    # body with read_within (one receive at a time); 082e32a6 read it whole, then checked the deadline.
    with vendor_ktw.urllib.request.urlopen(url, timeout=min(vendor_ktw.ATTEMPT_SECONDS, vendor_ktw.remaining())) as r:
        if hasattr(vendor_ktw, "read_within"):
            return vendor_ktw.read_within(r)
        data = r.read()
    vendor_ktw.remaining()
    return data


saved = (vendor_ktw.DEADLINE_SECONDS, vendor_ktw.ATTEMPT_SECONDS)
vendor_ktw.DEADLINE_SECONDS, vendor_ktw.ATTEMPT_SECONDS = 0.3, 0.15
try:
    for path in ("/body", "/chunked"):
        vendor_ktw._deadline = None
        started = time.monotonic()
        said = None
        try:
            getattr(vendor_ktw, "within", old_within)(base + path)
        except vendor_ktw.Refused as e:
            said = str(e)
        except OSError as e:  # an earlier head's socket timeout at the deadline
            said = "timeout: %s" % e
        took = time.monotonic() - started
        check(said is not None and "no answer within 0.3 s" in said and took < 0.3 + 0.1,
              "a peer dripping %s is refused at the run's deadline %r" % (path[1:], (round(took, 2), said)))
finally:
    vendor_ktw.DEADLINE_SECONDS, vendor_ktw.ATTEMPT_SECONDS = saved
    server.shutdown()

print("all ok" if not failures else "%d failure(s)" % failures)
sys.exit(1 if failures else 0)
