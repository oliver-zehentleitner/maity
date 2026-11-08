#!/usr/bin/env python3
"""Turn the catalogs' failure prefixes into whole sentences with {reason} (tsk-0zbms0wwqhmm).

    python3 tools/reason_sentences.py          # rewrite i18n/*.json, print the keys per catalog
    python3 tools/reason_sentences.py --check  # print only; exit 1 while a prefix is left

A prefix is an English entry whose text (each plural form, for a plural entry) ends in ": ".
web/js joined such a text and the error's message ("Not saved: " + reason); the language could
not put the reason elsewhere. Each such entry, in every catalog that has it, gets {reason} where
its text ends today, so every language reads exactly as before and a translator can move it.
LABELS stand before an element, not a reason: they get the placeholder named there instead,
filled with that element through M.tn.
Run `make fixtures` after it: js/i18n/*.js and i18n/*.meta.json follow the catalogs.
"""
import json
import os
import sys

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N = os.path.join(WEB, "i18n")
# Text before an inbox entry's own parts, a diff line or the list of what blocks a release.
LABELS = {
    "inbox.label.project": "entry", "inbox.label.personal": "entry", "inbox.label.personal_alone": "entry",
    "inbox.label.personal_into": "entry", "prefs.diff.added": "line", "prefs.diff.removed": "line",
    "board.release.not_ready": "reasons",
}


def forms(entry):
    return [entry] if isinstance(entry, str) else list(entry.values())


def is_prefix(entry):
    return all(text.endswith(": ") for text in forms(entry))


def with_placeholder(entry, name):
    mark = "{" + name + "}"
    if isinstance(entry, str):
        return entry + mark
    return {form: text + mark for form, text in entry.items()}


def needs(english_entry, entry, name):
    """The English ends in the placeholder (or still in ": "), the catalog's entry lacks it."""
    mark = "{" + name + "}"
    ends = all(text.endswith(mark) or text.endswith(": ") for text in forms(english_entry))
    return ends and mark not in "".join(forms(entry))


def main(argv):
    check = "--check" in argv
    path = lambda lang: os.path.join(I18N, lang + ".json")
    english = json.load(open(path("en"), encoding="utf-8"))
    keys = sorted(k for k, v in english.items() if is_prefix(v))
    name = lambda k: LABELS.get(k, "reason")
    langs = ["en"] + sorted(n[:-5] for n in os.listdir(I18N)
                            if n.endswith(".json") and not n.endswith(".meta.json") and n != "en.json")
    for lang in langs:
        data = json.load(open(path(lang), encoding="utf-8"))
        # A text that has its placeholder already (rewritten before, or translated so) is left as it
        # is: the script runs again after a catalog comes in from main (#1489's ja, #1498).
        hit = [k for k in sorted(english) if k in data and needs(english[k], data[k], name(k))]
        if not check:
            for k in hit:
                data[k] = with_placeholder(data[k], name(k))
            with open(path(lang), "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print("%-8s %3d key(s)%s" % (lang, len(hit), " to rewrite" if check else " rewritten"))
    return 1 if check and keys else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
