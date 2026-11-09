"""The step-up check of tools/check.py (tsk-6dk86ej9s0fq), on small stand-ins: which call it reads
as going to a route that asks for the second factor, and which it reads as asking first.
Python standard library only: python3 web/tools/test_step_up_check.py
"""

import importlib.util
import re
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("check", Path(__file__).with_name("check.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

failures = 0


def expect(ok, what):
    global failures
    if not ok:
        failures += 1
    print(("ok   " if ok else "FAIL ") + what)


def first_call(src):
    """The pattern of the file's first M.api call and whether it asks first."""
    code, error = check.strip_js(src)
    assert error is None, error
    m = re.search(r"\bM\.api\.(get|post|patch|put|del)\(", code)
    begin, end = check.first_argument(code, m.end())
    return check.path_pattern(src, code, src[begin:end], m.start()), check.asks_first(code, m.start())


def reaches(pattern, path):
    return pattern is not None and re.fullmatch(pattern, re.sub(r"\{[^}]*\}", "x", path)) is not None


pattern, asks = first_call('const go = () => M.api.post("/runners/enrollments", { name });')
expect(reaches(pattern, "/runners/enrollments") and not asks, "a bare call to the route is read, and does not ask")

pattern, asks = first_call('await M.stepUp.run(() => M.api.post("/runners/enrollments", b), slot, what);')
expect(asks, "inside M.stepUp.run's first argument it asks")

pattern, asks = first_call('const call = () => M.api.post("/x/" + id + "/approve", b);\nawait M.stepUp.run(call, slot);')
expect(asks and reaches(pattern, "/x/{id}/approve"), "an arrow handed to M.stepUp.run by its name asks")

pattern, asks = first_call('const call = () => M.api.post("/x", b);\nawait M.stepUp.run(other, slot);')
expect(not asks, "an arrow with a name M.stepUp.run is not given does not ask")

pattern, asks = first_call(
    'const act = async (busy, call, what) => { await M.stepUp.run(call, ask, what); };\n'
    'act("…", () => M.api.del("/auth/second-factor"), "w");'
)
expect(asks, "an arrow handed to a local function that hands it on asks")

pattern, asks = first_call(
    'async function act(busy, fn) { await fn(); }\nact("…", () => M.api.post("/auth/password", b));'
)
expect(not asks, "a local function that calls it itself does not ask")

pattern, asks = first_call('const steps = [{ call: () => M.api.patch(LEGAL, v) }];\nawait M.stepUp.run(steps[i].call, slot);')
expect(asks, "a call: property M.stepUp.run is given asks")

pattern, asks = first_call('await M.stepUp.run(M.api.post("/auth/password", b), slot, what);')
expect(not asks, "a call made to work out M.stepUp.run's first argument does not ask: it is sent first")

pattern, asks = first_call('await M.stepUp.run(() => go(), M.api.post("/auth/password", b));')
expect(not asks, "a call in another argument of M.stepUp.run does not ask")

pattern, asks = first_call('await M.stepUp.run(async function () { return M.api.post("/auth/password", b); }, slot);')
expect(asks, "inside a function expression given as the first argument it asks")

pattern, asks = first_call(
    'const act = async (busy, call, what) => { await what(); await M.stepUp.run(call, ask, what); };\n'
    'act("…", () => M.api.del("/x"), () => M.api.del("/auth/second-factor"));'
)
expect(asks, "the arrow in the place of the parameter handed on asks")

pattern, asks = first_call(
    'const act = async (busy, call, what) => { await what(); await M.stepUp.run(call, ask); };\n'
    'act("…", () => go(), () => M.api.del("/auth/second-factor"));'
)
expect(not asks, "an arrow in the place of a parameter that is not handed on does not ask")

pattern, asks = first_call('await M.stepUp.run(function () { return M.api.post("/auth/password", b); }(), slot);')
expect(not asks, "a function called where it is written, as the first argument, does not ask: it runs first")

pattern, asks = first_call('await M.stepUp.run(async function () { return go(); }.bind(M.api.post("/auth/password", b)), slot);')
expect(not asks, "a call in what binds the first argument's function does not ask: it is sent first")

pattern, asks = first_call('await M.stepUp.run(async () => { await M.api.post("/auth/password", b); }, slot);')
expect(asks, "inside an arrow's block given as the first argument it asks")

src = 'const MAIL = "/admin/settings/mail";\nM.api.patch(MAIL, body);'
pattern, asks = first_call(src)
expect(reaches(pattern, "/admin/settings/mail"), "a path held in a const is read")

src = 'const orgPath = (org) => "/orgs/" + encodeURIComponent(org);\nM.api.del(orgPath(h), b);'
pattern, asks = first_call(src)
expect(reaches(pattern, "/orgs/{org}"), "a path made by a helper arrow is read")

src = ('const path = (personal ? "" : "/projects/" + p)\n  + "/requests/" + encodeURIComponent(id) + "/" + (verb || "answer");\n'
       'M.api.post(path, payload);')
pattern, asks = first_call(src)
expect(reaches(pattern, "/requests/{request_id}/answer"), "a path over two lines, with a choice and a default, is read")

pattern, asks = first_call("M.api.get(path);")
expect(pattern is None, "a path nothing of which can be read is left alone")

pattern, asks = first_call('M.api.get(ctx.base + "/members");')
expect(not reaches(pattern, "/projects/{owner}/{slug}"), "another route under the project is not the project's own")

print("%d failure(s)" % failures)
sys.exit(1 if failures else 0)
