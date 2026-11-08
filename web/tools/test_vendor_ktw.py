"""make check: vendor_ktw.py's network failures end in one `refused:` line, never a traceback, and
one run's network time is bounded in all (web P3 roll-up, tsk-gsk31zvpfv02). No network is used."""

import contextlib
import io
import os
import sys
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
real_monotonic = vendor_ktw.time.monotonic
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

    # Each attempt is capped, and none starts once the run's time is spent.
    seen = []

    def answer(url, timeout):
        seen.append(timeout)
        raise urllib.error.URLError("unreachable")

    clock = [1000.0]
    vendor_ktw.time.monotonic = lambda: clock[0]
    vendor_ktw.urllib.request.urlopen = answer
    vendor_ktw._deadline = None
    run(["--latest"])
    clock[0] += vendor_ktw.DEADLINE_SECONDS + 1
    code, err = run(["--latest"])
    check(seen == [vendor_ktw.ATTEMPT_SECONDS] and code == 1 and "no answer within" in err,
          "an attempt waits at most ATTEMPT_SECONDS, and none starts after the run's DEADLINE_SECONDS " + repr((seen, err)))
    # A peer that answers one byte per receive, each just inside the socket timeout: the read
    # stops at the run's deadline instead of lasting as long as the peer keeps sending.
    class Trickle:
        def __init__(self):
            self.reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read1(self, n):
            self.reads += 1
            clock[0] += vendor_ktw.ATTEMPT_SECONDS - 1
            return b"x"

        def read(self, n=-1):
            # A whole-body read, as an HTTPResponse loops over receives: here 100 of them.
            return b"".join(self.read1(1) for _ in range(100))

    trickle = Trickle()
    clock[0] = 5000.0
    vendor_ktw.urllib.request.urlopen = lambda url, timeout: trickle
    vendor_ktw._deadline = None
    code, err = run(["--latest"])
    limit = vendor_ktw.DEADLINE_SECONDS // (vendor_ktw.ATTEMPT_SECONDS - 1) + 2
    check(code == 1 and "no answer within" in err and trickle.reads <= limit,
          "a peer trickling bytes inside the socket timeout is cut at the run's deadline " + repr((trickle.reads, limit, err)))
    # The same against a real local server whose body drips one byte every 0.05 s for 2 s: with a
    # deadline of 0.3 s and 0.15 s per attempt, the read ends at the deadline (#1497 review).
    vendor_ktw.urllib.request.urlopen = real_urlopen
    vendor_ktw.time.monotonic = real_monotonic
    import http.server
    import threading
    import time as _time

    class Drip(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "40")
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    _time.sleep(0.05)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Drip)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    saved = (vendor_ktw.DEADLINE_SECONDS, vendor_ktw.ATTEMPT_SECONDS)
    vendor_ktw.DEADLINE_SECONDS, vendor_ktw.ATTEMPT_SECONDS = 0.3, 0.15
    vendor_ktw._deadline = None
    started = _time.monotonic()
    said = None
    try:
        with real_urlopen("http://127.0.0.1:%d/" % server.server_address[1], timeout=vendor_ktw.ATTEMPT_SECONDS) as r:
            # The previous head had no read_within: it read the whole body, then checked the deadline.
            getattr(vendor_ktw, "read_within", lambda resp: (resp.read(), vendor_ktw.remaining()))(r)
    except vendor_ktw.Refused as e:
        said = str(e)
    except OSError as e:
        said = "timeout: %s" % e
    took = _time.monotonic() - started
    vendor_ktw.DEADLINE_SECONDS, vendor_ktw.ATTEMPT_SECONDS = saved
    server.shutdown()
    check(said is not None and took < 0.3 + 0.15 + 0.1,
          "a real dripping server: the body read ends at the run's deadline " + repr((round(took, 2), said)))
finally:
    vendor_ktw.urllib.request.urlopen = real_urlopen
    vendor_ktw.time.monotonic = real_monotonic

print("all ok" if not failures else "%d failure(s)" % failures)
sys.exit(1 if failures else 0)
