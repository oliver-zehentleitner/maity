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
finally:
    vendor_ktw.urllib.request.urlopen = real_urlopen
    vendor_ktw.time.monotonic = real_monotonic

print("all ok" if not failures else "%d failure(s)" % failures)
sys.exit(1 if failures else 0)
