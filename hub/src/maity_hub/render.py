"""The landing page and the legal pages as static HTML (docs/api.md §16.7, §16.7.1).

The hub renders them itself. The legal pages carry one `<style>` element and no script
(`default-src 'none'; style-src 'unsafe-inline'`); the landing page adds the hub's own
stylesheet, fonts and script (`landing_files`), all the same for every instance and none of
them needed to read it. Everything the operator wrote is text: it is escaped, and the Markdown is
turned into elements by the small renderer below, which knows exactly the constructs the
validator allows (`landing.markdown_problem`): headings, paragraphs, emphasis, lists, quotes,
fenced code and links whose target passes `landing.safe_target`.
"""

# ruff: noqa: E501  (the markup is written as strings, one element per line)

from __future__ import annotations

import re
from collections.abc import Iterable
from html import escape, unescape
from typing import Any
from urllib.parse import urlsplit

from maity_hub import landing_files
from maity_hub.landing import AGENTS, ALPHA_MARKS, FENCE, safe_target

# --- the visitor's language (§16.7) ----------------------------------------------------------


def ordered_languages(pages: Iterable[str], default: str) -> list[str]:
    """The languages of a setting in one fixed order, the default first and the rest
    alphabetically: never the order a database keeps the keys in (PostgreSQL's jsonb sorts them,
    MySQL's JSON does too), so the language bar, `hreflang`, the fallback page and the choice of
    a language when nothing matches are the same on every database (§16.7)."""
    return sorted(pages, key=lambda tag: (tag != default, tag))


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


def _link(text: str, target: str, *, me: bool = False, ugc: bool = False) -> str:
    if not safe_target(target):  # the validator refused these; a stored page never has one
        return escape(text)
    # A public page's words are its owner's, not the operator's: no endorsement (§16.9).
    rel = "nofollow ugc" if ugc else "noopener me" if me else "noopener"
    return f'<a href="{escape(target, quote=True)}" rel="{rel}">{escape(text)}</a>'


def inline(text: str, *, ugc: bool = False) -> str:
    out: list[str] = []
    last = 0
    for found in _INLINE.finditer(text):
        out.append(escape(text[last : found.start()]))
        last = found.end()
        if found["code"] is not None:
            out.append(f"<code>{escape(found['code'])}</code>")
        elif found["target"] is not None:
            out.append(_link(found["text"] or found["target"], found["target"], ugc=ugc))
        elif found["bare"] is not None:
            url = found["bare"]
            trailing = ""
            while url and url[-1] in ".,;:!?'\"":
                trailing = url[-1] + trailing
                url = url[:-1]
            out.append(_link(url, url, ugc=ugc) + escape(trailing))
        elif found["strong"] is not None:
            out.append(f"<strong>{escape(found['strong'])}</strong>")
        else:
            out.append(f"<em>{escape(found['em'] or found['em2'])}</em>")
    out.append(escape(text[last:]))
    return "".join(out)


def markdown(source: str, *, ugc: bool = False) -> str:
    """The HTML of a Markdown text; fenced code is text, a block is one element. With `ugc`
    every link is `rel="nofollow ugc"`, as on the public pages (§16.9)."""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    index = 0

    def flush() -> None:
        if paragraph:
            out.append("<p>" + inline("\n".join(paragraph), ugc=ugc).replace("\n", "<br>") + "</p>")
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
            out.append(f"<h{level}>{inline(heading.group(2), ugc=ugc)}</h{level}>")
            index += 1
            continue
        if _QUOTE.match(line):
            flush()
            quoted: list[str] = []
            while index < len(lines) and (quote := _QUOTE.match(lines[index])):
                quoted.append(quote.group(1))
                index += 1
            out.append("<blockquote>" + markdown("\n".join(quoted), ugc=ugc) + "</blockquote>")
            continue
        for pattern, tag in ((_BULLET, "ul"), (_NUMBER, "ol")):
            if pattern.match(line):
                flush()
                items: list[str] = []
                while index < len(lines) and (item := pattern.match(lines[index])):
                    items.append(f"<li>{inline(item.group(1), ugc=ugc)}</li>")
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
        "theme": "Switch between the light and the dark theme",
        "rings": "People and agents in three rings: you, your team, the community",
        "you": "you",
        "yes": "Yes",
        "no": "No",
        "reply": "Reply",
        "platform": "Platform",
        "open_source": "Open source",
        "follow": "Follow",
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
        "agents": "Agents",
        "public_projects": "Öffentliche Projekte",
        "cards_done_week": "Karten diese Woche erledigt",
        "people_online": "Menschen online",
        "agents_online": "Agents online",
        "imprint": "Impressum",
        "privacy": "Datenschutz",
        "terms": "Nutzungsbedingungen",
        "preview": "Vorschau eines ungespeicherten Entwurfs",
        "theme": "Zwischen hellem und dunklem Farbschema wechseln",
        "rings": "Menschen und Agents in drei Ringen: du, dein Team, die Community",
        "you": "du",
        "yes": "Ja",
        "no": "Nein",
        "reply": "Antworten",
        "platform": "Plattform",
        "open_source": "Open Source",
        "follow": "Folgen",
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
    *,
    lang: str,
    title: str,
    description: str,
    head: str,
    body: str,
    languages: list[str],
    style: str = STYLE,
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
        f"{f'<style>{style}</style>' if style else ''}</head><body>{body}</body></html>"
    )


def _counter(stats: dict[str, Any] | None, key: str, words: dict[str, str]) -> str | None:
    if not stats or key not in stats:
        return None
    value = stats[key]
    label = f'<span class="label">{escape(words[key])}</span>'
    if value is None:
        return None  # not computed: the counter is left out
    dot = (
        '<span class="dot pulse" aria-hidden="true"></span>'
        if key in ("people_online", "agents_online")
        else ""
    )  # the board has a live dot before an online number
    return f'<div class="stat"><b>{dot}<span data-lp-count>{int(value)}</span></b>{label}</div>'


def _button(cta: dict[str, Any], kind: str) -> str:
    return (
        f'<a class="btn {kind}" href="{escape(cta["href"], quote=True)}">{escape(cta["label"])}</a>'
    )


def _wrap(index: int, classes: str, inner: str, extra: str = "") -> str:
    return (
        f'<section id="s{index}" class="{classes}"{extra}><div class="wrap">{inner}</div></section>'
    )


def _demo(index: int, section: dict[str, Any], words: dict[str, str]) -> str:
    """The terminal's lines are `d1`…, the inbox item follows the fourth, the rest after it
    (`landing.css` times them); everything is in the HTML, so that without script the end
    state shows (§16.7)."""
    lines = section["terminal_lines"]
    rows = []
    for position, line in enumerate(lines):
        step = position + 1 if position < 4 else position + 2  # `d5` is the inbox item
        rows.append(
            f'<li class="d{step} {escape(line["kind"])}" data-kind="{escape(line["kind"])}">'
            f"{escape(line['text'])}</li>"
        )
    inbox = ""
    if section.get("inbox"):
        item = section["inbox"]
        context = f'<p class="context">{escape(item["context"])}</p>' if item.get("context") else ""
        inbox = (
            '<div class="inbox-item card d5" data-lp-inbox>'
            f'<div class="from">{escape(item["from"])}</div>'
            f'<p class="question">{escape(item["question"])}</p>{context}'
            '<div class="answers" aria-hidden="true">'
            f'<span class="yes">{escape(words["yes"])}</span>'
            f'<span class="no">{escape(words["no"])}</span>'
            f'<span class="reply">{escape(words["reply"])}</span></div></div>'
        )
    steps = "".join(
        f'<li class="step s{n}"><h3>{escape(step["title"])}</h3><p>{escape(step["text"])}</p></li>'
        for n, step in enumerate(section["steps"], start=1)
    )
    lead = f'<p class="lead">{escape(section["subline"])}</p>' if section.get("subline") else ""
    inner = (
        f'<h2>{escape(section["title"])}</h2>{lead}<div class="demo-grid"><div>'
        f'<ol class="term" data-lp-terminal>{"".join(rows)}</ol>{inbox}</div>'
        f'<ol class="steps3">{steps}</ol></div>'
    )
    return _wrap(index, "section demo", inner, " data-lp-demo")


def _section(index: int, section: dict[str, Any], words: dict[str, str], stats: Any) -> str:
    kind = section["type"]
    title = section.get("title")
    heading = f"<h2>{escape(title)}</h2>" if title else ""
    if kind == "hero":
        return ""  # drawn with the header, in the dark zone
    if kind == "stats":
        cells = [c for c in (_counter(stats, k, words) for k in section["items"]) if c]
        if not cells:
            return ""
        return _wrap(index, "section strip", f'<div class="stats">{"".join(cells)}</div>')
    if kind == "steps":
        items = "".join(
            '<li class="card"><h3>{}</h3><p>{}</p>{}</li>'.format(
                escape(item["title"]),
                escape(item["text"]),
                f"<pre><code>{escape(item['code'])}</code></pre>" if item.get("code") else "",
            )
            for item in section["items"]
        )
        return _wrap(index, "section", f'{heading}<ol class="grid3">{items}</ol>')
    if kind == "scales":
        cards = "".join(
            '<article class="card"><span class="tag">{}</span><h3>{}</h3><p>{}</p>{}</article>'.format(
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
        rings = landing_files.svg("scales-rings.svg")
        return _wrap(
            index,
            "section section-alt scales",
            f'{heading}<div class="scales-body"><div class="scales-grid">{cards}</div>'
            f'<div class="scales-art hide-m">{rings}</div></div>',
        )
    if kind == "demo":
        return _demo(index, section, words)
    if kind == "opensource":
        lead = (
            f'<div class="lead">{markdown(section["markdown"])}</div>'
            if section.get("markdown")
            else ""
        )
        tiles = "".join(
            f'<div class="tile card"><h3>{escape(tile["title"])}</h3><p>{escape(tile["text"])}</p></div>'
            for tile in section["tiles"]
        )
        links = "".join(
            f'<a class="btn btn-secondary" href="{escape(link["href"], quote=True)}">{escape(link["label"])}</a>'
            for link in section.get("links", [])
        )
        return _wrap(
            index,
            "section section-alt",
            f'{heading}{lead}<div class="tiles">{tiles}</div>'
            + (f'<div class="links">{links}</div>' if links else ""),
        )
    if kind == "faq":
        rows = "".join(
            f"<details><summary>{escape(item['q'])}</summary>{markdown(item['a'])}</details>"
            for item in section["items"]
        )
        return _wrap(index, "section", f'{heading}<div class="faq">{rows}</div>')
    if kind == "cta_band":
        text = f"<p>{escape(section['text'])}</p>" if section.get("text") else ""
        return (
            f'<section id="s{index}" class="band dz"><div class="wrap cta-band">'
            f'{landing_files.svg("band-loader.svg")}<div><h2>{escape(section["title"])}</h2>'
            f'{text}{_button(section["cta"], "btn-primary")}</div></div></section>'
        )
    if kind == "works_with":
        return _works_with(index, section)
    if kind == "text":
        return _wrap(index, "section", f'{heading}{markdown(section["markdown"])}')
    return ""  # activity, profiles, explore, collab: nothing to show in this version


def _works_with(index: int, section: dict[str, Any]) -> str:
    """The label and a band of the agents' logos. Each agent is named once for screen readers;
    the second copy of the list, which makes the loop seamless, is `aria-hidden` and inert. The
    logos are the hub's own files, drawn by a CSS mask so one color serves both themes; the
    names and files come from `landing.AGENTS`, never from the page (§16.7)."""

    def logos(copy: str) -> str:
        cells = []
        for slug in section["items"]:
            address = landing_files.url(f"agents/{slug}.svg")
            if address is None:
                continue
            mask = f"-webkit-mask-image:url({address});mask-image:url({address})"
            shape = "agent-logo agent-alpha" if slug in ALPHA_MARKS else "agent-logo"
            cells.append(
                f'<li class="agent" tabindex="0">'
                f'<span class="{shape}" style="{escape(mask, quote=True)}"></span>'
                f'<span class="agent-name">{escape(AGENTS[slug])}</span></li>'
                if copy == "first"
                else f'<li class="agent"><span class="{shape}" style="{escape(mask, quote=True)}"></span></li>'
            )
        return "".join(cells)

    more = f'<p class="agents-more">{escape(section["more"])}</p>' if section.get("more") else ""
    return _wrap(
        index,
        "section works-with",
        f'<p class="agents-label">{escape(section["label"])}</p>'
        f'<div class="agents-band"><ul class="agents-list agents-first">{logos("first")}</ul>'
        f'<ul class="agents-list agents-copy" aria-hidden="true" inert>{logos("copy")}</ul></div>{more}',
    )


def _online(stats: dict[str, Any] | None, words: dict[str, str]) -> str:
    """The hero's line of who is online, from the shared stats; a counter that
    no enabled `stats` section names is left out, and the line with it when none is left."""
    cells = []
    for key in ("people_online", "agents_online"):
        value = (stats or {}).get(key)
        if value is not None:
            cells.append(
                f'<span class="online-item"><b><span data-lp-count>{int(value)}</span></b> '
                f"{escape(words[key])}</span>"
            )
    if not cells:
        return ""
    return f'<span class="online"><span class="dot pulse" aria-hidden="true"></span>{"".join(cells)}</span>'


def _hero(index: int, section: dict[str, Any], words: dict[str, str], stats: Any = None) -> str:
    parts = []
    if section.get("eyebrow"):
        parts.append(f'<p class="eyebrow">{escape(section["eyebrow"])}</p>')
    parts.append(f"<h1>{escape(section['title'])}</h1>")
    if section.get("subline"):
        parts.append(f'<p class="sub">{escape(section["subline"])}</p>')
    buttons = [_button(section["cta_primary"], "btn-primary")]
    if section.get("cta_secondary"):
        buttons.append(_button(section["cta_secondary"], "btn-secondary"))
    parts.append(f'<div class="cta">{"".join(buttons)}</div>')
    note = f'<div class="note">{markdown(section["note"])}</div>' if section.get("note") else ""
    online = _online(stats, words)
    if note or online:  # the online numbers first, then the note: one plain line (§16.7)
        parts.append(f'<div class="hero-meta">{online}{note}</div>')
    rings = (
        landing_files.svg("hero-rings.svg")
        .replace("{label}", escape(words["rings"], quote=True))
        .replace("{you}", escape(words["you"]))
    )
    return (
        f'<section id="s{index}" class="hero dz"><div class="wrap"><div>{"".join(parts)}</div>'
        f'<div class="hide-m">{rings}</div></div></section>'
    )


_SWITCH = re.compile(r'(<a href=")(\?lang=[A-Za-z-]+)(")')


def carry_origin(html: str, variant: str, campaign: str | None, public_url: str) -> str:
    """Every link to `/register` on this host, a path or this hub's own address, carries the
    visitor's origin, `v` and (for a known campaign) `c`, so the registration knows where they
    came from (§16.7.2); the visible language switch keeps the campaign (not the `alternate`
    links of the head, which are for search engines). The page is otherwise as it was: nothing
    set in the browser."""
    origin = f"v={variant}" + (f"&amp;c={campaign}" if campaign else "")
    here = re.escape(escape(public_url.rstrip("/"), quote=True))
    pattern = re.compile(rf'href="((?:{here})?/register)((?:\?[^"#]*)?)((?:#[^"]*)?)"')

    def register(found: re.Match[str]) -> str:
        joined = "&amp;" if found.group(2) else "?"
        return f'href="{found.group(1)}{found.group(2)}{joined}{origin}{found.group(3)}"'

    html = pattern.sub(register, html)
    if campaign:
        html = _SWITCH.sub(
            lambda found: f"{found.group(1)}{found.group(2)}&amp;c={campaign}{found.group(3)}", html
        )
    return html


def landing_document(
    setting: dict[str, Any],
    lang: str,
    *,
    public_url: str,
    legal: dict[str, Any],
    stats: dict[str, Any] | None,
    preview: bool = False,
    variant: str | None = None,
) -> str:
    """The landing page in `lang` (a missing field falls back to the default language's page).

    Its look is the hub's own code (`landing_assets/`, §16.7, "Progressive enhancement"): the
    stylesheet and the fonts it names, a script that only adds motion and the theme switch, and
    the design's pictures inline. Every word of the operator's is escaped text; the page reads
    completely without the script and without the stylesheet."""
    # A variant has pages of its own, and a language it lacks falls back to its own page in the
    # default language, never to the main page's (§16.7.2).
    pages: dict[str, Any] = setting["variants"][variant]["pages"] if variant else setting["pages"]
    tags = ordered_languages(pages, setting["default_language"])
    default = pages.get(setting["default_language"]) or pages[tags[0]]
    page = pages.get(lang) or default
    words = WORDS.get(lang, WORDS["en"])
    sections = [(i, s) for i, s in enumerate(page["sections"]) if s["enabled"]]
    # The hero's online numbers follow the rule of `GET /landing`: only a counter that an enabled
    # `stats` section of this page names is shown, so one the operator left off is published
    # nowhere (§16.7); the page is handed every counter, the renderer filters.
    named = {item for _, s in sections if s["type"] == "stats" for item in s["items"]}
    hero_stats = {k: v for k, v in (stats or {}).items() if k in named}
    drawn = [
        (
            i,
            s,
            _hero(i, s, words, hero_stats) if s["type"] == "hero" else _section(i, s, words, stats),
        )
        for i, s in sections
    ]
    # The header's links are the shown sections that carry a `nav_label`, in their order (§16.7):
    # a section that draws nothing is no link, and a title is never a link text.
    links = [(i, s["nav_label"]) for i, s, html in drawn if s.get("nav_label") and html]
    nav = "".join(f'<a href="#s{i}">{escape(label)}</a>' for i, label in links)
    hero = next(((i, s) for i, s in sections if s["type"] == "hero"), None)
    cta = _button(hero[1]["cta_primary"], "btn-primary") if hero else ""
    banner = (
        f'<div class="preview-note"><div class="wrap">{escape(words["preview"])}</div></div>'
        if preview
        else ""
    )
    header = (
        '<header class="site-header dz"><div class="wrap">'
        f'<a class="brand" href="/">{landing_files.svg("mark.svg")}maity</a>'
        f'<nav class="site-nav">{nav}</nav>'
        f'<button type="button" class="theme-toggle" data-lp-theme hidden aria-pressed="false" '
        f'aria-label="{escape(words["theme"], quote=True)}">◐</button>'
        f'<a class="signin" href="/login">{escape(words["sign_in"])}</a>{cta}</div></header>'
    )
    body = "".join(html for _, _, html in drawn)
    open_source = [
        link for _, s, _ in drawn if s["type"] == "opensource" for link in s.get("links", [])
    ]
    footer = _landing_footer(setting, words, legal, lang, tags, links, open_source)
    sheet, script = landing_files.url("landing.css"), landing_files.url("landing.js")
    head = f'<link rel="canonical" href="{escape(public_url.rstrip("/"), quote=True)}/">'
    if variant:  # a variant is for a link; search engines index the main page only (§16.7.2)
        head += '<meta name="robots" content="noindex">'
    if sheet:
        head += f'<link rel="stylesheet" href="{escape(sheet, quote=True)}">'
    if script:
        head += f'<script src="{escape(script, quote=True)}" defer></script>'
    return _document(
        lang=lang,
        title=page["title"],
        description=page.get("description") or "",
        head=head,
        body=banner + header + f"<main>{body}</main>" + footer,
        languages=tags,
        style="" if sheet else STYLE,
    )


def _on_github(href: str) -> bool:
    """Whether a link points at github.com, the host compared without case."""
    host = urlsplit(href).hostname or ""
    return host.lower() in ("github.com", "www.github.com")


def _column(title: str, items: list[str]) -> str:
    if not items:
        return ""
    rows = "".join(f"<li>{item}</li>" for item in items)
    return f'<nav class="foot-col" aria-label="{escape(title, quote=True)}"><h3>{escape(title)}</h3><ul>{rows}</ul></nav>'


def _landing_footer(
    setting: dict[str, Any],
    words: dict[str, str],
    legal: dict[str, Any],
    lang: str,
    tags: list[str],
    sections: list[tuple[int, str]] | None = None,
    open_source: list[dict[str, Any]] | None = None,
) -> str:
    """Columns as the design has them: the platform (the header's links, sign-in and
    registration), open source (the links of the `opensource` sections), the legal pages and the
    social links; below them the operator's line and the language switch (§16.7)."""
    platform = [f'<a href="#s{i}">{escape(label)}</a>' for i, label in sections or []]
    platform.append(f'<a href="/login">{escape(words["sign_in"])}</a>')
    platform.append(f'<a href="/register">{escape(words["register"])}</a>')
    source = [_link(item["label"], item["href"]) for item in open_source or []]
    legal_links = [
        f'<a href="/{address}">{escape(words[key])}</a>'
        for key, address in LEGAL_ADDRESS.items()
        if legal["pages"].get(key)
    ]
    footer = setting["footer"]
    # A GitHub link belongs once, in Open source: it is left out of Follow when that column has one.
    github_in_source = any(_on_github(item["href"]) for item in open_source or [])
    social = [
        _link(
            item["label"],
            item["href"],
            me="mastodon" in item["label"].lower() or "/@" in item["href"],
        )
        for item in footer.get("social", [])
        if not (github_in_source and _on_github(item["href"]))
    ]
    columns = (
        _column(words["platform"], platform)
        + _column(words["open_source"], source)
        + _column(words["legal"], legal_links)
        + _column(words["follow"], social)
    )
    operator = (
        f'<p class="operator">{escape(footer["operator"])}</p>' if footer.get("operator") else ""
    )
    switch = (
        '<p class="langs">'
        + " ".join(f'<a href="?lang={escape(tag)}">{escape(tag)}</a>' for tag in tags)
        + "</p>"
        if len(tags) > 1
        else ""
    )
    return (
        f'<footer class="site-footer"><div class="wrap"><div class="foot-cols">{columns}</div>'
        f"{operator}{switch}</div></footer>"
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


# --- a public page (§16.9) --------------------------------------------------------------------

DESCRIPTION_MAX = 160
_TAG = re.compile(r"<[^>]*>")


def text_of(html: str) -> str:
    """The text of rendered HTML, one space between its words."""
    return " ".join(unescape(_TAG.sub(" ", html)).split())


def page_document(*, lang: str, title: str, canonical: str, content: str) -> str:
    """A public page: its own `<title>`, a `<meta name="description">` from the first 160
    characters of its text (cut first, then escaped) and the absolute canonical link (§16.9).
    `content` is the HTML of the page's body, already made of escaped text and elements."""
    description = text_of(content)[:DESCRIPTION_MAX]
    return _document(
        lang=lang,
        title=title,
        description=description,
        head=f'<link rel="canonical" href="{escape(canonical, quote=True)}">',
        body=f'<main class="wrap">{content}</main>',
        languages=[],
    )
