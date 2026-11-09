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
    return check.path_pattern(src, code, src[begin:end], m.start()), check.asks_first(code, m.start(), src)


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

# A wrapper is tied to the binding it is given, not to its name anywhere in the file (xyfr at #1547).
pattern, asks = first_call(
    'function a(){ const call = () => M.api.post("/runners/enrollments", b); return call(); }\n'
    'function b(){ const call = () => M.api.get("/me"); return M.stepUp.run(call, slot); }'
)
expect(not asks, "another binding of the same name handed to M.stepUp.run elsewhere does not make this one ask")

pattern, asks = first_call(
    'function b(){ const call = () => M.api.get("/me"); return M.stepUp.run(call, slot); }\n'
    'function a(){ const call = () => M.api.post("/runners/enrollments", b); return M.stepUp.run(call, slot); }'
)
expect(asks, "the binding handed to M.stepUp.run in its own function asks, whatever another function names its own")

pattern, asks = first_call(
    'function a(){ const call = () => M.api.post("/runners/enrollments", b);\n'
    '  function c(){ const call = () => M.api.get("/me"); return M.stepUp.run(call, slot); } return call(); }'
)
expect(not asks, "a binding of the same name in a function inside does not make the outer one ask")

pattern, asks = first_call(
    'const call = () => M.api.post("/runners/enrollments", b);\n'
    'async function go(){ await M.stepUp.run(call, slot); }'
)
expect(asks, "a binding handed on from a function inside its scope asks")

pattern, asks = first_call(
    'const steps = [{ call: () => M.api.patch(LEGAL, v) }];\nawait M.stepUp.run(steps[i].call, slot);\nawait steps[0].call();'
)
expect(not asks, "a call: property also called outside M.stepUp.run does not ask")

pattern, asks = first_call(
    'const steps = [{ call: () => M.api.patch(LEGAL, v) }];\nconst { call } = steps[0];\nawait M.stepUp.run(steps[i].call, slot);'
)
expect(not asks, "a call: property that is destructured does not ask")

pattern, asks = first_call(
    'const steps = [{ call: () => M.api.patch(LEGAL, v) }];\nawait M.stepUp.run(other.items[k].call, slot);'
)
expect(asks, "a call: property read only into M.stepUp.run asks, through any path")

pattern, asks = first_call('const go = () => M.api.post(M.api.projectPath(slug) + "/requests/" + id + "/answer", b);')
expect(reaches(pattern, "/projects/{owner}/{slug}/requests/{id}/answer") and reaches(pattern, "/requests/{id}/answer") and not asks,
       "a part that cannot be read may stand for several segments: a project path before a personal route's tail")


def scan(name, src):
    """check_step_up's findings for one file js/<name> beside the real list and fixture."""
    import json
    import os
    import shutil
    import tempfile
    root = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(root, "js"))
        shutil.copy(os.path.join(check.ROOT, "js", "api.js"), os.path.join(root, "js", "api.js"))
        with open(os.path.join(root, "js", name), "w") as f:
            f.write('"use strict";\n' + src + "\n")
        saved = check.ROOT, list(check.findings)
        check.ROOT = root
        del check.findings[:]
        try:
            check.check_step_up()
            return [x for x in check.findings if name in x]
        finally:
            check.ROOT = saved[0]
            check.findings[:] = saved[1]
    finally:
        shutil.rmtree(root)


got = scan("collision.js", 'function a(){ const call = () => M.api.post("/runners/enrollments", b); return call(); }\n'
           'function b(){ const call = () => M.api.get("/me"); return M.stepUp.run(call, slot); }')
expect(len(got) == 1 and "POST /runners/enrollments" in got[0], "make check: xyfr's two bindings named call, the unwrapped one is a finding " + repr(got))

got = scan("hidden.js", 'const patch = { address: "a@b.c" };\nM.api.patch("/me/notification-settings", { email: patch });')
expect(len(got) == 1 and "/me/notification-settings" in got[0], "make check: the address behind a variable in the body is a finding " + repr(got))

got = scan("plain.js", 'M.api.patch("/me/notification-settings", { email: { muted: true } });')
expect(got == [], "make check: a notification-settings write without the address is none " + repr(got))

# 4hch at #1566: reads of a call: property the dotted scan does not see, and a body name shadowed elsewhere.
pattern, asks = first_call('const a = { call: () => M.api.post("/runners/enrollments", b) };\nawait M.stepUp.run(a.call, slot);\na["call"]();')
expect(not asks, "a call: property also read by a string in brackets does not ask")

pattern, asks = first_call('const a = { call: () => M.api.post("/runners/enrollments", b) };\nawait M.stepUp.run(a.call, slot);\na[key]();')
expect(not asks, "a call: property where a computed name is called does not ask")

# 4hch at #1566, delta 1: any call through brackets, not only a bare name in them.
for form in ('a["ca" + "ll"]()', 'a[key || "call"]()', 'a[(key)]()', 'a[key()]()'):
    pattern, asks = first_call('const a = { call: () => M.api.post("/runners/enrollments", b) };\nawait M.stepUp.run(a.call, slot);\n' + form + ';')
    expect(not asks, "a call: property where the file calls through brackets, " + form + ", does not ask")

got = scan("shadow.js", 'const patch = { address: "a@b.c" };\nfunction other(){ const patch = { muted: true }; return patch; }\n'
           'M.api.patch("/me/notification-settings", { email: patch });')
expect(len(got) == 1, "make check: the body's name is the binding around the call, not another function's of the same name " + repr(got))

print("%d failure(s)" % failures)
sys.exit(1 if failures else 0)
