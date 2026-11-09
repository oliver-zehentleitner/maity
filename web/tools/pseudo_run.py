#!/usr/bin/env python3
"""Every route in a real browser with a pseudo catalog: what the catalog's marks do not
reach is a text that does not come from the catalog (docs: web/README.md).

It serves the fixtures from file://, so it needs Playwright and no hub. The routes are the
ones tools/smoke.js visits. It sees a page as it opens: what only a click shows is not walked.

  python tools/pseudo_run.py [--strict] [--report FILE] [--route '#/chats']
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check  # noqa: E402

WEB = Path(__file__).resolve().parent.parent
TAG = "en-XA"  # the pseudo locale's usual tag; no person's language
OPEN, CLOSE = "⟦", "⟧"
ACCENTS = str.maketrans("AaEeIiOoUuCcNnYy", "ÀàÉéÎîÕõÜüÇçÑñÝý")

# What is on the page and in no catalog on purpose: each language's name in itself, product names.
KEPT = {"Afaraf", "العربية", "Deutsch", "English", "français", "日本語", "简体中文", "Maity", "GitHub", "GitLab", "Gitea",
        "English (Pseudo-Accents)"}  # the browser's own name for the pseudo tag

# Names in the fixtures that are also a word of the catalog: as data they would be taken
# out with the catalog's texts, and then count as a text of the interface.
FIXTURE_NAMES = {"Reviewer", "OZ Team"}

COLLECT = """() => {
  const SKIP = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "KBD", "SAMP", "TIME", "TEMPLATE", "NOSCRIPT"]);
  // translate="no" marks what stays as it is on purpose (an example, a tag, a technical
  // reason); aria-hidden is decoration such as a monogram, no text anyone reads.
  const kept = (e) => e.closest('[translate="no"], [aria-hidden="true"]');
  const found = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    let inside = kept(n.parentElement) !== null;
    for (let e = n.parentElement; e; e = e.parentElement) if (SKIP.has(e.tagName)) inside = true;
    if (!inside) found.push(n.textContent.trim());
  }
  for (const e of document.body.querySelectorAll("[title],[placeholder],[aria-label],[alt]")) {
    if (kept(e)) continue;
    for (const a of ["title", "placeholder", "aria-label", "alt"]) if (e.getAttribute(a)) found.push(e.getAttribute(a).trim());
  }
  if (document.title) found.push(document.title);
  return found;
}"""


def pseudo_text(text: str) -> str:
    """The text marked and accented, its placeholders as they are."""
    parts = re.split(r"(\{[A-Za-z_][A-Za-z0-9_]*\})", text)
    return OPEN + "".join(p if i % 2 else p.translate(ACCENTS) for i, p in enumerate(parts)) + CLOSE


def pseudo_catalog(english: dict[str, Any]) -> dict[str, Any]:
    def one(entry: Any) -> Any:
        return pseudo_text(entry) if isinstance(entry, str) else {form: pseudo_text(t) for form, t in entry.items()}

    return {key: one(entry) for key, entry in english.items()}


# A value under these keys is a word of the contract the interface has to put in words,
# so a page that shows it as it comes has a text outside the catalog.
ENUM_VALUE = re.compile(r"[a-z][a-z0-9_.-]*")
ENUM_KEYS = {"state", "status", "kind", "presence", "role", "trust", "type", "reason", "code", "scope", "severity", "mode"}


def strings_in(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()}
    if isinstance(value, dict):
        # An enum's value is no data, a page shows it through the catalog; the same keys
        # also carry prose (a decision's reason, a release's scope), and that is data.
        return {s for key, item in value.items() for s in strings_in(item) if key not in ENUM_KEYS or not ENUM_VALUE.fullmatch(s)}
    return {s for item in value for s in strings_in(item)} if isinstance(value, list) else set()


# What a page composes around words and is no word: a count in the title, a date in the
# browser's format, a handle, an instance, a card, an address, a path, a commit, a
# device code, a mail address, a domain, a media type.
NOT_WORDS = re.compile(
    r"""^\(\d+\)\s | \b[A-Z][a-z]{2}\ \d{1,2},\ \d{4}(?:,\ \d{1,2}:\d{2}(?:\s?[AP]M)?)? | \b\d{1,2}:\d{2}(?:\s?[AP]M)?
        | \b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\ [A-Z][a-z]+\ \d{1,2},\ \d{4}
        | (?:^|(?<=[\s(]))[@\#]\S+ | \b(?:tsk|req|agt|hum|att)-\S+ | \bhttps?://\S+
        | \b(?:text|image|application|audio|video)/[\w.+-]+ | \b[\w-]+\#[a-z0-9]{4}\b | \b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b
        | \b[A-Z0-9]{4}(?:-[A-Z0-9]{4}){2}\b | \S+@[\w-]+(?:\.[\w-]+)+ | \b[\w-]+(?:\.[\w-]+)*\.(?:org|net|com|dev|team|social|example)\b """,
    re.X,
)
MARKED = re.compile(f"{OPEN}[^{CLOSE}]*{CLOSE}")
ACCENTED = "".join(sorted(set("ÀàÉéÎîÕõÜüÇçÑñÝý")))


def _no_paths(text: str, data: set[str]) -> str:
    """Out with a path or a project's name; `Read/write` is two words and stays."""
    def keep(token: str) -> bool:
        return "/" not in token or (re.fullmatch(r"[^\W\d_]+/[^\W\d_]+[.,;:]?", token) is not None and token.strip(".,;:") not in data)

    return " ".join(t if keep(t) else " " for t in text.split())


def unmarked(text: str, data: set[str], data_text: str = "") -> bool:
    """A text of the interface the catalog's marks did not reach. What is marked comes out
    first, so a word beside a marked one still counts; each piece of a line composed with
    `·` is judged by itself, a piece as it stands before the stops come off it; data and
    what has no word are no text, nor is a list of data. Long pieces are data
    also inside a fixture's text, which markup splits into several nodes. An accent without
    a mark is a catalog text with its ends cut off."""
    if text.strip() in data or text.strip() in KEPT:
        return False
    rest = _no_paths(NOT_WORDS.sub(" ", MARKED.sub(" · ", text)), data)
    for piece in re.split(r"\s[·–—]\s|^[·–—]\s", rest):
        if " ".join(piece.split()).strip(" ·–—○()⟦⟧") in data:
            continue
        piece = piece.strip(" ·–—○,;:.()⟦⟧")
        if not re.search(r"[^\W\d_]{2}", piece) or piece in data or piece + "." in data:
            continue
        if any(c in ACCENTED for c in piece):
            continue
        if piece in KEPT or piece in check.NOT_PROSE or (len(piece.split()) > 2 and " ".join(piece.split()) in data_text):
            continue
        # A list of data, as `M.fmt.list` joins it (an untitled chat named after its people):
        # data, when every item is.
        items = [x.strip() for x in piece.split(", ")]
        if len(items) > 1 and all(x in data for x in items):
            continue
        return True
    return False


LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def literals(source: str) -> set[str]:
    return {m.strip() for m in LITERAL.findall(source) if m.strip()}


# Where a page splits what someone wrote into several nodes: a code span, a mention.
SPLIT = re.compile(r"`[^`]*`|(?:^|(?<=\s))@\S+")


def pieces_of(written: str) -> set[str]:
    """A fixture's text as the page shows it in pieces: each node between a code span and a
    mention, and the whole with what `unmarked` takes out of a page's text (a path, a
    date) taken out. Raw, with their stops: `Keep it;` is a piece, `Keep it` a button."""
    parts = SPLIT.split(written) + [_no_paths(NOT_WORDS.sub(" ", written), set())]
    return {" ".join(p.split()) for p in parts if re.search(r"[^\W\d_]{2}", p)}


def fixture_strings() -> set[str]:
    """What the fixtures say as data: the JSON files and the answers `api.js` writes itself.
    A catalog's text among them does not count, nor a literal a view also writes: a page
    that shows that wording without the catalog is what this run looks for. A fixture's
    name that is also a catalog's word comes back, it is a name there."""
    out: set[str] = set()
    for path in (WEB / "fixtures").rglob("*.json"):
        out |= strings_in(json.loads(path.read_text(encoding="utf-8")))
    views = set().union(*(literals(p.read_text(encoding="utf-8")) for p in (WEB / "js").glob("*.js") if p.name != "api.js"))
    out |= literals((WEB / "js" / "api.js").read_text(encoding="utf-8")) - views
    out |= {p for written in out for p in pieces_of(written)}
    english = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
    return (out - {t.strip() for e in english.values() for t in ([e] if isinstance(e, str) else e.values())}) | FIXTURE_NAMES


def routes_of_smoke() -> list[str]:
    source = (WEB / "tools" / "smoke.js").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'go\("(#/[^"]+)"', source)))


def prepare(into: Path) -> None:
    """A copy of the site that also has the pseudo catalog; the repository stays without it."""
    shutil.copytree(WEB, into, ignore=shutil.ignore_patterns("tools", "context", "__pycache__"), dirs_exist_ok=True)
    english = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
    catalog = json.dumps(pseudo_catalog(english), ensure_ascii=False)
    (into / "js" / "i18n" / f"{TAG}.js").write_text(
        f'"use strict";\nwindow.MAITY_I18N = window.MAITY_I18N || {{}};\nwindow.MAITY_I18N["{TAG}"] = {catalog};\n',
        encoding="utf-8",
    )
    (into / "js" / "i18n" / "languages.js").write_text(
        f'"use strict";\nwindow.MAITY_I18N_LANGUAGES = ["en", "{TAG}"];\n', encoding="utf-8"
    )


def source_of(text: str) -> str:
    """The file that holds the words, so the report says where to look. `api.js` holds the
    fixtures' answers too, so it comes last: a text only there is data more often than not."""
    head = re.split(r"[\n{]", text)[0][:60]
    for path in sorted((WEB / "js").glob("*.js"), key=lambda p: (p.name == "api.js", p.name)):
        if head in path.read_text(encoding="utf-8"):
            return path.name
    return "(composed)"


def walk(site: Path, routes: list[str], data: set[str], data_text: str) -> tuple[dict[str, set[str]], dict[str, str], int]:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    found: dict[str, set[str]] = defaultdict(set)
    broken: dict[str, str] = {}
    marked = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(locale="en-US")  # dates in one form, whatever the machine's
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for route in routes:
            errors.clear()
            try:
                page.goto("about:blank")
                page.goto((site / "index.html").as_uri() + f"?lang={TAG}" + route)
                page.wait_for_load_state("load")
                page.wait_for_timeout(250)
                if page.evaluate("document.documentElement.lang") != TAG:
                    broken[route] = "the page is not in the pseudo language: this run would prove nothing"
                    continue
                texts = page.evaluate(COLLECT)
            except PlaywrightError as err:
                broken[route] = str(err).splitlines()[0]
                continue
            if errors:
                broken[route] = errors[0]
            marked += sum(OPEN in t for t in texts)
            for text in texts:
                if unmarked(text, data, data_text):
                    found[text].add(route)
        browser.close()
    return found, broken, marked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="fail on any text outside the catalog")
    parser.add_argument("--report", help="write the report as JSON")
    parser.add_argument("--route", action="append", help="only this route; may repeat")
    args = parser.parse_args()
    routes = args.route or routes_of_smoke()
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        prepare(site)
        data = fixture_strings()
        found, broken, marked = walk(site, routes, data, "\n".join(data))
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for text, where in sorted(found.items()):
        by_file[source_of(text)].append({"text": text, "routes": sorted(where)})
    for name in sorted(by_file):
        print(f"{name}: {len(by_file[name])}")
        for item in by_file[name]:
            print(f"  {item['text'][:100]!r}  ({len(item['routes'])} route(s), first {item['routes'][0]})")
    for route, why in sorted(broken.items()):
        print(f"broken {route}: {why}")
    print(f"pseudo: {len(routes)} route(s), {marked} marked text(s), {len(found)} outside the catalog, {len(broken)} broken")
    if args.report:
        Path(args.report).write_text(
            json.dumps({"files": by_file, "broken": broken, "marked": marked}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    if not marked:
        print("no text carried the mark: the catalog did not load, and this run proves nothing")
        return 1
    return 1 if args.strict and (found or broken) else 0


if __name__ == "__main__":
    raise SystemExit(main())
