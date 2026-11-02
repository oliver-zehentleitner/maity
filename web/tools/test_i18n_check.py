"""The checks of a translated catalog (tools/check.py), on small stand-ins.
Python standard library only: python3 web/tools/test_i18n_check.py
"""

import importlib.util
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


EN = {
    "a.greeting": "Hello {name}",
    "a.files": {"one": "{count} file", "other": "{count} files"},
    "a.plain": "Plain",
}
problems = check.translation_problems

expect(problems("de", {"a.greeting": "Hallo {name}", "a.files": {"one": "{count} Datei", "other": "{count} Dateien"}}, EN) == [],
       "a right translation, and a key left out, are no problem")
expect(problems("xx", {}, EN) != [], "a language outside the ten is one")
expect("no such key" in problems("de", {"a.gone": "x"}, EN)[0], "a key English does not have")
expect("placeholders" in problems("de", {"a.greeting": "Hallo"}, EN)[0], "a placeholder of English lost")
expect("placeholders" in problems("de", {"a.plain": "Text {extra}"}, EN)[0], "a placeholder English does not have")
expect("stays" in problems("de", {"a.files": "Dateien {count}"}, EN)[0], "plural forms turned into a text")
expect("empty" in problems("de", {"a.plain": "  "}, EN)[0], "an empty text")
expect("empty" in problems("de", {"a.files": {"one": "{count} Datei", "other": "   "}}, EN)[0], "an empty plural form")
expect(any("`other`" in p for p in problems("de", {"a.files": {"one": "{count} Datei", "other": "Dateien"}}, EN)), "`other` without its placeholder")
expect(problems("de", {"a.files": {"one": "eine Datei", "other": "{count} Dateien"}}, EN) == [], "`one` may say the number in words")
expect("forms" in problems("de", {"a.files": {"other": "{count} Dateien"}}, EN)[0], "German needs `one`")
expect("forms" in problems("ja", {"a.files": {"one": "{count}", "other": "{count}"}}, EN)[0], "Japanese has only `other`")
expect(problems("ja", {"a.files": {"other": "{count} 件"}}, EN) == [], "Japanese with `other`")
expect(problems("fr", {"a.files": {"one": "{count} f", "other": "{count} fs"}}, EN) == []
       and problems("fr", {"a.files": {"one": "{count} f", "many": "{count} fs", "other": "{count} fs"}}, EN) == [],
       "French may have `many` or leave it to `other`")

de = {"a.plain": "Schlicht"}
meta = check.translation_meta(de, EN, {})
expect(check.translation_gaps(de, EN, meta) == (["a.files", "a.greeting"], []), "a key left out is missing, nothing is out of date")
newer = dict(EN, **{"a.plain": "Very plain"})
meta = check.translation_meta(de, newer, meta)
expect(check.translation_gaps(de, newer, meta)[1] == ["a.plain"], "a changed English marks its translation out of date")
de = {"a.plain": "Ganz schlicht"}
meta = check.translation_meta(de, newer, meta)
expect(check.translation_gaps(de, newer, meta)[1] == [], "a changed translation follows today's English")
expect(check.translation_meta({"a.gone": "x"}, EN, {"a.gone": {"en": "0", "text": "0"}}) == {}, "a key English dropped leaves the meta")

# The pseudo run's own judgement; the walk itself needs a browser.
import pseudo_run  # noqa: E402

marked = pseudo_run.pseudo_text("Hello {name}, Agent")
expect(marked.startswith("⟦") and marked.endswith("⟧") and "{name}" in marked and "Hello" not in marked,
       "pseudo: the text is marked and accented, its placeholder kept: " + marked)
forms = pseudo_run.pseudo_catalog({"a.b": {"one": "x", "other": "y"}, "c.d": "z"})
expect(set(forms["a.b"]) == {"one", "other"} and forms["c.d"].startswith("⟦"), "pseudo: plural forms are kept")
data = {"Agent D", "member"}
for text, outside in [
    ("Save", True),
    ("(11) All projects · Maity", True),
    ("Remove the uploaded banner", True),
    ("Agent D · Sep 14, 2026, 12:05 · online", True),
    ("⟦Sàvé⟧", False),
    ("· wàtçhéd bý", False),
    ("Agent D · member", False),
    ("Oct 21, 2026, 12:05", False),
    ("@maintainer/agent-b", False),
    ("#k3pa", False),
    ("tsk-0021", False),
    ("https://example.org/x", False),
    ("Maity", False),
    ("Deutsch", False),
    ("42", False),
    ("the lab notes today", False),
]:
    expect(pseudo_run.unmarked(text, data, "take over the lab notes today, please") is outside, "pseudo: %r outside the catalog: %s" % (text, outside))
expect(len(pseudo_run.routes_of_smoke()) > 50, "pseudo: the routes come from the smoke test")

raise SystemExit(1 if failures else 0)
