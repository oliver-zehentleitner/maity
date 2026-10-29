"""The landing page and the legal pages as static HTML (docs/api.md §16.7, §16.7.1).

The hub renders them itself: no script, no image, one `<style>` element, so that the
Content-Security-Policy of these documents can be `default-src 'none'; style-src
'unsafe-inline'`. Everything the operator wrote is text: it is escaped, and the Markdown is
turned into elements by the small renderer below, which knows exactly the constructs the
validator allows (`landing.markdown_problem`): headings, paragraphs, emphasis, lists, quotes,
fenced code and links whose target passes `landing.safe_target`.
"""

# ruff: noqa: E501  (the markup is written as strings, one element per line)

from __future__ import annotations

import re
from html import escape
from typing import Any

from maity_hub.landing import FENCE, safe_target

# --- the visitor's language (§16.7) ----------------------------------------------------------


def choose_language(
    offered: list[str], default: str, query: str | None, accept_language: str | None
) -> str:
    """`?lang=` if offered, else the best match of `Accept-Language` among the offered
    languages, else the default language; the default itself only when it is offered."""
    if query in offered:
        return str(query)
    ranked: list[tuple[float, int, str]] = []
    for position, part in enumerate((accept_language or "").split(",")):
        tag, _, rest = part.strip().partition(";")
        weight = 1.0
        if rest.strip().startswith("q="):
            try:
                weight = float(rest.strip()[2:])
            except ValueError:
                weight = 0.0
        primary = tag.strip().lower().split("-")[0]
        if primary in offered and weight > 0:
            ranked.append((-weight, position, primary))
    if ranked:
        return sorted(ranked)[0][2]
    return default if default in offered else (offered[0] if offered else default)


# --- Markdown ----------------------------------------------------------------------------------

_INLINE = re.compile(
    r"`(?P<code>[^`\n]+)`"
    r"|\[(?P<text>[^\[\]\n]*)\]\(\s*(?P<target>[^)\s]*)[^)]*\)"
    r"|(?P<bare>https://[^\s<>()]+)"
    r"|\*\*(?P<strong>[^*\n]+)\*\*"
    r"|\*(?P<em>[^*\n]+)\*"
    r"|(?<![A-Za-z0-9])_(?P<em2>[^_\n]+)_(?![A-Za-z0-9])"
)
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_QUOTE = re.compile(r"^ {0,3}>\s?(.*)$")
_BULLET = re.compile(r"^ {0,3}[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^ {0,3}\d{1,9}[.)]\s+(.*)$")


def _link(text: str, target: str, *, me: bool = False) -> str:
    if not safe_target(target):  # the validator refused these; a stored page never has one
        return escape(text)
    rel = "noopener me" if me else "noopener"
    return f'<a href="{escape(target, quote=True)}" rel="{rel}">{escape(text)}</a>'


def inline(text: str) -> str:
    out: list[str] = []
    last = 0
    for found in _INLINE.finditer(text):
        out.append(escape(text[last : found.start()]))
        last = found.end()
        if found["code"] is not None:
            out.append(f"<code>{escape(found['code'])}</code>")
        elif found["target"] is not None:
            out.append(_link(found["text"] or found["target"], found["target"]))
        elif found["bare"] is not None:
            url = found["bare"]
            trailing = ""
            while url and url[-1] in ".,;:!?'\"":
                trailing = url[-1] + trailing
                url = url[:-1]
            out.append(_link(url, url) + escape(trailing))
        elif found["strong"] is not None:
            out.append(f"<strong>{escape(found['strong'])}</strong>")
        else:
            out.append(f"<em>{escape(found['em'] or found['em2'])}</em>")
    out.append(escape(text[last:]))
    return "".join(out)


def markdown(source: str) -> str:
    """The HTML of a Markdown text; fenced code is text, a block is one element."""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    index = 0

    def flush() -> None:
        if paragraph:
            out.append("<p>" + inline("\n".join(paragraph)).replace("\n", "<br>") + "</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        opened = FENCE.match(line)
        if opened and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            flush()
            mark = re.escape(opened.group(1)[0])
            close = re.compile(rf"^ {{0,3}}{mark}{{{len(opened.group(1))},}}\s*$")
            body: list[str] = []
            index += 1
            while index < len(lines) and not close.match(lines[index]):
                body.append(lines[index])
                index += 1
            index += 1  # past the closing fence (or the end: code to the end)
            out.append("<pre><code>" + escape("\n".join(body)) + "</code></pre>")
            continue
        if not line.strip():
            flush()
            index += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        if _QUOTE.match(line):
            flush()
            quoted: list[str] = []
            while index < len(lines) and (quote := _QUOTE.match(lines[index])):
                quoted.append(quote.group(1))
                index += 1
            out.append("<blockquote>" + markdown("\n".join(quoted)) + "</blockquote>")
            continue
        for pattern, tag in ((_BULLET, "ul"), (_NUMBER, "ol")):
            if pattern.match(line):
                flush()
                items: list[str] = []
                while index < len(lines) and (item := pattern.match(lines[index])):
                    items.append(f"<li>{inline(item.group(1))}</li>")
                    index += 1
                out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
                break
        else:
            paragraph.append(line.strip())
            index += 1
    flush()
    return "\n".join(out)


# --- the words of the pages' own frame ------------------------------------------------------------

WORDS: dict[str, dict[str, str]] = {
    "en": {
        "sign_in": "Sign in",
        "register": "Create your account",
        "legal": "Legal",
        "as_of": "As of {version}",
        "draft": "Draft",
        "earlier": "Earlier versions",
        "older": "This is an earlier version, as of {version}. The current one is at {current}.",
        "language": "Language",
        "people": "People",
        "agents": "Agents",
        "public_projects": "Public projects",
        "cards_done_week": "Cards done this week",
        "people_online": "People online",
        "agents_online": "Agents online",
        "imprint": "Imprint",
        "privacy": "Privacy",
        "terms": "Terms",
        "preview": "Preview of an unsaved draft",
    },
    "de": {
        "sign_in": "Anmelden",
        "register": "Konto anlegen",
        "legal": "Rechtliches",
        "as_of": "Stand {version}",
        "draft": "Entwurf",
        "earlier": "Frühere Fassungen",
        "older": "Dies ist eine frühere Fassung, Stand {version}. Die aktuelle steht unter {current}.",
        "language": "Sprache",
        "people": "Menschen",
        "agents": "Agenten",
        "public_projects": "Öffentliche Projekte",
        "cards_done_week": "Karten diese Woche erledigt",
        "people_online": "Menschen online",
        "agents_online": "Agenten online",
        "imprint": "Impressum",
        "privacy": "Datenschutz",
        "terms": "Nutzungsbedingungen",
        "preview": "Vorschau eines ungespeicherten Entwurfs",
    },
}
LEGAL_ADDRESS = {"imprint": "impressum", "privacy": "privacy", "terms": "terms"}

STYLE = """
:root{color-scheme:light dark;--fg:#1c1d21;--muted:#5d6068;--bg:#fff;--card:#f4f5f7;--line:#dcdee3;
--accent:#3b5bdb;--accent-fg:#fff}
@media (prefers-color-scheme:dark){:root{--fg:#ececf1;--muted:#a3a6b0;--bg:#16171b;--card:#202228;
--line:#33363f;--accent:#8da2fb;--accent-fg:#101114}}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
color:var(--fg);background:var(--bg)}a{color:var(--accent)}
.wrap{max-width:60rem;margin:0 auto;padding:0 1.25rem}
header.top{border-bottom:1px solid var(--line)}header.top .wrap{display:flex;flex-wrap:wrap;
align-items:center;gap:1rem;padding-top:.8rem;padding-bottom:.8rem}
.mark{font-weight:700;font-size:1.2rem;text-decoration:none;color:var(--fg);margin-right:auto}
nav a{margin-right:1rem;text-decoration:none;color:var(--muted)}
.btn{display:inline-block;padding:.55rem 1.1rem;border-radius:.5rem;text-decoration:none;
border:1px solid var(--accent);color:var(--accent);font-weight:600}
.btn.primary{background:var(--accent);color:var(--accent-fg)}
section{padding:2.5rem 0}section+section{border-top:1px solid var(--line)}
h1{font-size:2.4rem;line-height:1.15;margin:.3rem 0 1rem}h2{font-size:1.5rem;margin:0 0 1rem}
.eyebrow{color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-size:.8rem;margin:0}
.sub{font-size:1.2rem;color:var(--muted);max-width:42rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:1rem;padding:0;
margin:0;list-style:none}.card{background:var(--card);border:1px solid var(--line);
border-radius:.7rem;padding:1rem 1.1rem}.card h3{margin:.2rem 0 .4rem;font-size:1.05rem}
.tag{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.stats{display:flex;flex-wrap:wrap;gap:2rem}.stat b{display:block;font-size:2rem;line-height:1.1}
.stat span{color:var(--muted);font-size:.9rem}
pre{background:var(--card);border:1px solid var(--line);border-radius:.5rem;padding:.7rem .9rem;
overflow:auto}code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.92em}
blockquote{margin:1rem 0;padding-left:1rem;border-left:3px solid var(--line);color:var(--muted)}
details{border-top:1px solid var(--line);padding:.7rem 0}summary{cursor:pointer;font-weight:600}
.band{background:var(--card);border-radius:.8rem;padding:1.5rem;text-align:center}
footer{border-top:1px solid var(--line);padding:1.5rem 0 3rem;color:var(--muted);font-size:.9rem}
footer a{color:var(--muted);margin-right:1rem}.note{background:var(--card);padding:.6rem .9rem;
border-radius:.5rem;border:1px solid var(--line)}
"""


def _document(
    *, lang: str, title: str, description: str, head: str, body: str, languages: list[str]
) -> str:
    alternates = "".join(
        f'<link rel="alternate" hreflang="{escape(tag)}" href="?lang={escape(tag)}">'
        for tag in languages
        if len(languages) > 1
    )
    meta = f'<meta name="description" content="{escape(description, quote=True)}">'
    return (
        f'<!doctype html><html lang="{escape(lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>{meta if description else ''}{head}{alternates}"
        f"<style>{STYLE}</style></head><body>{body}</body></html>"
    )


def _counter(stats: dict[str, Any] | None, key: str, words: dict[str, str]) -> str | None:
    if not stats or key not in stats:
        return None
    value = stats[key]
    if value is None:
        if key in ("people_online", "agents_online"):
            return f'<div class="stat"><b>&lt; {int(stats.get("online_floor", 5))}</b><span>{escape(words[key])}</span></div>'
        return None
    return f'<div class="stat"><b>{int(value)}</b><span>{escape(words[key])}</span></div>'


def _section(index: int, section: dict[str, Any], words: dict[str, str], stats: Any) -> str:
    kind = section["type"]
    anchor = f' id="s{index}"'
    title = section.get("title")
    heading = f"<h2>{escape(title)}</h2>" if title else ""
    if kind == "hero":
        parts = []
        if section.get("eyebrow"):
            parts.append(f'<p class="eyebrow">{escape(section["eyebrow"])}</p>')
        parts.append(f"<h1>{escape(section['title'])}</h1>")
        if section.get("subline"):
            parts.append(f'<p class="sub">{escape(section["subline"])}</p>')
        buttons = [("btn primary", section["cta_primary"])]
        if section.get("cta_secondary"):
            buttons.append(("btn", section["cta_secondary"]))
        parts.append(
            "<p>"
            + " ".join(
                f'<a class="{cls}" href="{escape(cta["href"], quote=True)}">{escape(cta["label"])}</a>'
                for cls, cta in buttons
            )
            + "</p>"
        )
        if section.get("note"):
            parts.append(f'<div class="note">{markdown(section["note"])}</div>')
        return f"<section{anchor}><div class=\"wrap\">{''.join(parts)}</div></section>"
    if kind == "stats":
        cells = [c for c in (_counter(stats, k, words) for k in section["items"]) if c]
        if not cells:
            return ""
        return f'<section{anchor}><div class="wrap"><div class="stats">{"".join(cells)}</div></div></section>'
    if kind == "steps":
        items = "".join(
            '<li class="card"><h3>{}</h3><p>{}</p>{}</li>'.format(
                escape(item["title"]),
                escape(item["text"]),
                f"<pre><code>{escape(item['code'])}</code></pre>" if item.get("code") else "",
            )
            for item in section["items"]
        )
        return f'<section{anchor}><div class="wrap">{heading}<ol class="cards">{items}</ol></div></section>'
    if kind == "scales":
        cards = "".join(
            '<li class="card"><span class="tag">{}</span><h3>{}</h3><p>{}</p>{}</li>'.format(
                escape(item["tag"]),
                escape(item["title"]),
                escape(item["text"]),
                (
                    "<ul>" + "".join(f"<li>{escape(p)}</li>" for p in item["points"]) + "</ul>"
                    if item.get("points")
                    else ""
                ),
            )
            for item in section["items"]
        )
        return f'<section{anchor}><div class="wrap">{heading}<ul class="cards">{cards}</ul></div></section>'
    if kind == "faq":
        rows = "".join(
            f"<details><summary>{escape(item['q'])}</summary>{markdown(item['a'])}</details>"
            for item in section["items"]
        )
        return f'<section{anchor}><div class="wrap">{heading}{rows}</div></section>'
    if kind == "cta_band":
        text = f"<p>{escape(section['text'])}</p>" if section.get("text") else ""
        cta = section["cta"]
        button = f'<a class="btn primary" href="{escape(cta["href"], quote=True)}">{escape(cta["label"])}</a>'
        return (
            f'<section{anchor}><div class="wrap"><div class="band"><h2>{escape(section["title"])}</h2>'
            f"{text}<p>{button}</p></div></div></section>"
        )
    if kind == "text":
        return f'<section{anchor}><div class="wrap">{heading}{markdown(section["markdown"])}</div></section>'
    return ""  # activity, profiles, explore, collab: nothing to show in this version


def landing_document(
    setting: dict[str, Any],
    lang: str,
    *,
    public_url: str,
    legal: dict[str, Any],
    stats: dict[str, Any] | None,
    preview: bool = False,
) -> str:
    """The landing page in `lang` (a missing field falls back to the default language's page)."""
    pages: dict[str, Any] = setting["pages"]
    default = pages.get(setting["default_language"]) or next(iter(pages.values()))
    page = pages.get(lang) or default
    words = WORDS.get(lang, WORDS["en"])
    sections = [(i, s) for i, s in enumerate(page["sections"]) if s["enabled"]]
    nav = "".join(
        f'<a href="#s{i}">{escape(s["title"])}</a>'
        for i, s in sections
        if s["type"] in ("steps", "scales", "faq") and s.get("title")
    )
    hero = next((s for _, s in sections if s["type"] == "hero"), None)
    cta = (
        f'<a class="btn primary" href="{escape(hero["cta_primary"]["href"], quote=True)}">'
        f'{escape(hero["cta_primary"]["label"])}</a>'
        if hero
        else ""
    )
    banner = (
        f'<div class="wrap"><p class="note">{escape(words["preview"])}</p></div>' if preview else ""
    )
    header = (
        '<header class="top"><div class="wrap"><a class="mark" href="/">Maity</a>'
        f'<nav>{nav}</nav><a href="/login">{escape(words["sign_in"])}</a>{cta}</div></header>'
    )
    main = "<main>" + "".join(_section(i, s, words, stats) for i, s in sections) + "</main>"
    footer = _footer(setting, words, legal, lang, list(pages))
    return _document(
        lang=lang,
        title=page["title"],
        description=page.get("description") or "",
        head=f'<link rel="canonical" href="{escape(public_url.rstrip("/"), quote=True)}/">',
        body=banner + header + main + footer,
        languages=list(pages),
    )


def _footer(
    setting: dict[str, Any],
    words: dict[str, str],
    legal: dict[str, Any],
    lang: str,
    tags: list[str],
) -> str:
    links = []
    for key, address in LEGAL_ADDRESS.items():
        if legal["pages"].get(key):
            links.append(f'<a href="/{address}">{escape(words[key])}</a>')
    footer = setting["footer"]
    parts = []
    if footer.get("operator"):
        parts.append(f"<p>{escape(footer['operator'])}</p>")
    social = "".join(
        _link(
            item["label"],
            item["href"],
            me="mastodon" in item["label"].lower() or "/@" in item["href"],
        )
        + " "
        for item in footer.get("social", [])
    )
    switch = (
        " ".join(f'<a href="?lang={escape(tag)}">{escape(tag)}</a>' for tag in tags)
        if len(tags) > 1
        else ""
    )
    row = (
        "".join(links)
        + f'<a href="/login">{escape(words["sign_in"])}</a>'
        + (f'<a href="/register">{escape(words["register"])}</a>')
    )
    return (
        f'<footer><div class="wrap"><p>{row}</p>{"".join(parts)}'
        f'{"<p>" + social + "</p>" if social else ""}{"<p>" + switch + "</p>" if switch else ""}</div></footer>'
    )


def legal_document(
    *,
    page: str,
    lang: str,
    title: str,
    source: str,
    version: str | None,
    earlier: list[str],
    current: str | None,
    languages: list[str],
    legal: dict[str, Any],
    setting: dict[str, Any],
    public_url: str,
) -> str:
    """One legal page in one language: its text, its version and the earlier versions.
    `version` is `None` for a draft; `current` is the served version when this is an earlier one."""
    words = WORDS.get(lang, WORDS["en"])
    stamp = words["draft"] if version is None else words["as_of"].format(version=version)
    address = f"/{LEGAL_ADDRESS[page]}"
    older = (
        f'<p class="note">{escape(words["older"].format(version=version, current=address))}</p>'
        if current is not None and version is not None and version != current
        else ""
    )
    history = ""
    if earlier:
        items = "".join(
            f'<li><a href="{address}/{escape(v, quote=True)}">{escape(v)}</a></li>' for v in earlier
        )
        history = f'<h2>{escape(words["earlier"])}</h2><ul>{items}</ul>'
    header = (
        '<header class="top"><div class="wrap"><a class="mark" href="/">Maity</a>'
        f'<a href="/login">{escape(words["sign_in"])}</a></div></header>'
    )
    banner = f'<p class="note">{escape(words["preview"])}</p>' if version is None else ""
    body = (
        f'{header}<main><section><div class="wrap">{banner}<h1>{escape(title)}</h1>'
        f'<p class="eyebrow">{escape(stamp)}</p>{older}{markdown(source)}{history}</div></section></main>'
        + _footer(setting, words, legal, lang, languages)
    )
    return _document(
        lang=lang,
        title=title,
        description="",
        head=f'<link rel="canonical" href="{escape(public_url.rstrip("/"), quote=True)}{address}">',
        body=body,
        languages=languages,
    )
