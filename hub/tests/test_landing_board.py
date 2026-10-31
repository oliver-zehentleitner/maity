"""docs/api.md §16.7: the landing page as the designer's board has it: the header's links from
`nav_label`, the hero's online numbers, counters left out under the floor, the footer's columns,
the demo's answers and the scales' rings (tsk-7en17gygg3gf)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import clock, landing_files, landing_stats
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_landing_v3 import BAND, DEMO, OPENSOURCE, SCALES
from tests.test_pages import ADMIN, hero, publish

STATS = {"type": "stats", "enabled": True, "items": ["people", "agents", "people_online"]}
ONLINE = {
    "type": "stats",
    "enabled": True,
    "items": ["people_online", "agents_online"],
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    landing_stats.reset()
    landing_files.reset()
    return flow.human(make_client, migrated)


def text(title: str, label: str | None = None, *, enabled: bool = True) -> dict[str, Any]:
    section: dict[str, Any] = {"type": "text", "enabled": enabled, "title": title, "markdown": "x"}
    if label is not None:
        section["nav_label"] = label
    return section


def put(owner: flow.Human, *sections: dict[str, Any]) -> Any:
    return owner.patch(
        ADMIN,
        {
            "enabled": True,
            "default_language": "en",
            "pages": {"en": {"title": "Maity", "description": "", "sections": [hero(), *sections]}},
            "footer": {"operator": "Maity, Austria", "social": []},
        },
    )


def page(owner: flow.Human, make_client: ClientFactory, *sections: dict[str, Any]) -> str:
    publish(owner, [hero(), *sections])
    return make_client().get("/").text


def header(html: str) -> str:
    found = re.search(r'<header class="site-header dz">.*?</header>', html, re.S)
    assert found is not None
    return found.group(0)


def many_online(make_client: ClientFactory, migrated: Engine) -> None:
    for n in range(5):
        flow.human(make_client, migrated, f"person{n}")
    with migrated.begin() as conn:
        conn.execute(update(t.human).values(last_seen_at=clock.now()))
    landing_stats.reset()


# --- the header's links -------------------------------------------------------------------


def test_the_header_links_the_sections_that_carry_a_nav_label_and_never_a_title(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(
        owner,
        make_client,
        text("A very long title of a section that would break the header", "How it works"),
        text("Another long title that is no link text", "FAQ"),
        text("No label here"),
    )
    nav = re.search(r'<nav class="site-nav">(.*?)</nav>', header(html), re.S)
    assert nav is not None
    assert re.findall(r'<a href="#s(\d)">([^<]*)</a>', nav.group(1)) == [
        ("1", "How it works"),
        ("2", "FAQ"),
    ]
    assert "very long title" not in header(html) and "No label here" not in header(html)
    assert 'id="s1"' in html and 'id="s2"' in html  # the link points at the section


def test_a_section_that_draws_nothing_or_is_off_is_no_link(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    activity = {
        "type": "activity",
        "enabled": True,
        "title": "Activity",
        "count": 3,
        "nav_label": "Live",
    }
    html = page(
        owner,
        make_client,
        activity,  # renders nothing in this version
        text("Off", "Hidden", enabled=False),
        text("Shown", "Shown"),
    )
    assert re.findall(r'<a href="#s\d">([^<]*)</a>', header(html).split("</nav>")[0]) == ["Shown"]


def test_a_page_without_labels_has_a_header_without_links(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, text("Steps"), text("FAQ"))
    assert '<nav class="site-nav"></nav>' in header(html)


def test_a_label_of_blanks_is_one_error_and_counts_for_no_fifth(owner: flow.Human) -> None:
    four = [text(f"T{n}", f"L{n}") for n in range(3)]
    refused = put(owner, *four, text("Blank", "   "), text("Fourth", "L4"))
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {
        "pages.en.sections.4.nav_label": "invalid"
    }


def test_the_label_is_trimmed_and_one_to_twenty_four_characters(owner: flow.Human) -> None:
    assert put(owner, text("T", "  How it works  ")).status_code == 200
    stored = owner.get(ADMIN).json()["pages"]["en"]["sections"][1]
    assert stored["nav_label"] == "How it works"
    for bad in ("", "   ", "x" * 25):
        refused = put(owner, text("T", bad))
        assert refused.status_code == 400, bad
        assert refused.json()["error"]["details"]["fields"] == {
            "pages.en.sections.1.nav_label": "invalid"
        }
    assert put(owner, text("T", "x" * 24)).status_code == 200


def test_at_most_four_enabled_sections_have_a_label(owner: flow.Human) -> None:
    four = [text(f"T{n}", f"L{n}") for n in range(4)]
    assert put(owner, *four).status_code == 200
    fifth = put(owner, *four, text("T5", "L5"))
    assert fifth.status_code == 400
    assert fifth.json()["error"]["details"]["fields"] == {
        "pages.en.sections.5.nav_label": "too_many"
    }
    # a section that is off is no link, and does not count
    assert put(owner, *four, text("T5", "L5", enabled=False)).status_code == 200


def test_every_type_may_have_a_label(owner: flow.Human) -> None:
    assert (
        put(owner, {**DEMO, "nav_label": "Demo"}, {**OPENSOURCE, "nav_label": "Code"}).status_code
        == 200
    )


# --- the wordmark, the hero and the counters ---------------------------------------------


def test_the_wordmark_is_lowercase(owner: flow.Human, make_client: ClientFactory) -> None:
    brand = re.search(r'<a class="brand" href="/">.*?</a>', page(owner, make_client), re.S)
    assert brand is not None and brand.group(0).endswith("maity</a>")


def test_the_hero_shows_the_online_numbers_beside_a_one_line_note(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    many_online(make_client, migrated)
    html = page(owner, make_client, ONLINE)
    meta = re.search(r'<div class="hero-meta">(.*?)</div></div><div class="hide-m">', html, re.S)
    assert meta is not None
    assert '<div class="note">' in meta.group(1)
    assert re.search(
        r'<span class="online"><span class="dot pulse" aria-hidden="true"></span>'
        r'<span class="online-item"><b><span data-lp-count>6</span></b> People online</span>',
        meta.group(1),
    )


def test_the_online_numbers_are_left_out_under_the_floor(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    under = page(owner, make_client, ONLINE)  # one person, below the floor of five
    assert 'class="online"' not in under and "People online" not in under
    assert '<div class="hero-meta"><div class="note">' in under  # the note stays


def test_only_a_counter_an_enabled_stats_section_names_is_in_the_hero(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    many_online(make_client, migrated)  # six people online: above the floor
    unnamed = page(owner, make_client, {**STATS, "items": ["people"]})
    assert 'class="online"' not in unnamed and "People online" not in unnamed
    one = page(owner, make_client, {**STATS, "items": ["people_online"]})
    assert "People online" in one and "Agents online" not in one
    disabled = page(owner, make_client, {**ONLINE, "enabled": False})
    assert 'class="online"' not in disabled  # a section that is off names nothing
    both = page(owner, make_client, ONLINE)
    assert "People online" in both  # named and above the floor
    assert "Agents online" not in both  # named, but no agent is online: below the floor


def test_a_counter_below_the_floor_leaves_its_cell_out(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, STATS)
    cells = re.findall(r'<span class="label">([^<]*)</span>', html)
    assert cells == ["People", "Agents"]  # people online has no cell: no "< 5"


def test_the_counters_say_agents_in_german_too(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    many_online(make_client, migrated)
    de = {
        "title": "Maity",
        "description": "",
        "sections": [hero(), {**STATS, "items": ["agents", "people_online", "agents_online"]}],
    }
    en = {"title": "Maity", "description": "", "sections": [hero(), STATS]}
    answer = owner.patch(
        ADMIN,
        {
            "enabled": True,
            "default_language": "en",
            "pages": {"en": en, "de": de},
            "footer": {"operator": "x", "social": []},
        },
    )
    assert answer.status_code == 200, answer.text
    html = make_client().get("/?lang=de").text
    assert "Menschen online" in html and "Agenten" not in html
    assert '<span class="label">Agents</span>' in html


def test_a_band_without_text_is_a_title_and_a_button(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    bare = {k: v for k, v in BAND.items() if k != "text"}
    html = page(owner, make_client, bare)
    assert re.search(
        r'<h2>Start</h2><a class="btn btn-primary" href="/register">Go</a></div></div></section>',
        html,
    )
    assert "<p>Now.</p>" not in page(owner, make_client, bare)


def test_the_stats_are_a_strip(owner: flow.Human, make_client: ClientFactory) -> None:
    assert re.search(r'<section id="s1" class="section strip">', page(owner, make_client, STATS))


# --- the demo, the scales and the footer ------------------------------------------------


def test_the_demo_answers_are_yes_no_and_reply_in_the_pages_language(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    both = {
        lang: {"title": "Maity", "description": "", "sections": [hero(), DEMO]}
        for lang in ("en", "de")
    }
    answer = owner.patch(
        ADMIN,
        {
            "enabled": True,
            "default_language": "en",
            "pages": both,
            "footer": {"operator": "x", "social": []},
        },
    )
    assert answer.status_code == 200, answer.text
    client = make_client()
    assert '<span class="yes">Yes</span><span class="no">No</span>' in client.get("/").text
    german = client.get("/?lang=de").text
    assert '<span class="yes">Ja</span><span class="no">Nein</span>' in german
    assert '<span class="reply">Antworten</span>' in german


def test_the_scales_have_rings_beside_them_and_stay_complete_without_script(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, SCALES)
    assert '<div class="scales-layout"><div class="scales-grid">' in html
    art = re.search(r'<div class="scales-art hide-m">(.*?)</div></div>', html, re.S)
    assert art is not None
    assert [m for m in re.findall(r'data-ring="(\d)"', art.group(1))] == ["3", "2", "1"]
    assert 'class="is-active"' in art.group(1) and 'aria-hidden="true"' in art.group(1)
    # The active look comes from .is-active alone: no ring's own style is the accent, or a ring
    # the script leaves would stay marked (review of #911).
    rings = re.findall(r'<circle data-ring="\d"[^>]*>', art.group(1))
    assert len(rings) == 3 and not any("var(--accent)" in r for r in rings), rings


def test_the_footer_has_the_designers_columns_the_operator_line_and_the_language(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, text("T", "How it works"), OPENSOURCE)
    footer = re.search(r'<footer class="site-footer">(.*)</footer>', html, re.S)
    assert footer is not None
    columns = re.findall(r'<nav class="foot-col" aria-label="([^"]*)">', footer.group(1))
    assert columns == ["Platform", "Open source", "Follow"]
    platform = re.search(r'aria-label="Platform">(.*?)</nav>', footer.group(1), re.S)
    assert platform is not None
    assert re.findall(r"<a [^>]*>([^<]*)</a>", platform.group(1)) == [
        "How it works",
        "Sign in",
        "Create your account",
    ]
    assert '<a href="https://example.com/src" rel="noopener">Source</a>' in footer.group(1)
    assert 'rel="noopener me">Mastodon</a>' in footer.group(1)
    assert '<p class="operator">Maity, Austria</p>' in footer.group(1)
    assert (
        '<p class="langs"><a href="?lang=en">en</a> <a href="?lang=de">de</a></p>'
        in footer.group(1)
    )


def test_a_column_without_links_is_left_out(owner: flow.Human, make_client: ClientFactory) -> None:
    put(owner)
    html = make_client().get("/").text
    columns = re.findall(r'<nav class="foot-col" aria-label="([^"]*)">', html)
    assert columns == ["Platform"]  # no open-source links, no legal pages, no social links


def test_a_variants_page_follows_its_own_stats_sections(owner: flow.Human) -> None:
    """The rule is per rendered page: a variant that alone names `people_online` shows it, and
    the main page that does not name it does not (§16.7, §16.7.2)."""
    from maity_hub import render

    def page_of(*items: str) -> dict[str, Any]:
        stats = {"type": "stats", "enabled": True, "items": list(items)}
        return {"title": "Maity", "description": "", "sections": [hero(), stats]}

    setting = {
        "default_language": "en",
        "pages": {"en": page_of("people")},
        "variants": {"for-teams": {"pages": {"en": page_of("people", "people_online")}}},
        "footer": {"operator": None, "social": []},
    }
    counters = {"people": 9, "people_online": 7, "agents_online": 6, "online_floor": 5}
    legal: dict[str, Any] = {"pages": {}}

    def draw(variant: str | None) -> str:
        return render.landing_document(
            setting,
            "en",
            public_url="https://hub.example",
            legal=legal,
            stats=counters,
            variant=variant,
        )

    assert 'class="online"' not in draw(None)
    named = draw("for-teams")
    assert "People online" in named and "Agents online" not in named


def test_the_languages_are_listed_default_first_then_alphabetically(owner: flow.Human) -> None:
    """The order does not depend on how the database keeps the keys (jsonb sorts them)."""
    from maity_hub import render

    def page_in(title: str) -> dict[str, Any]:
        return {"title": title, "description": "", "sections": [hero()]}

    setting = {
        "default_language": "en",
        # the order PostgreSQL's jsonb would give: sorted keys
        "pages": {"de": page_in("D"), "en": page_in("E"), "fr": page_in("F")},
        "variants": {},
        "footer": {"operator": None, "social": []},
    }
    html = render.landing_document(
        setting, "en", public_url="https://hub.example", legal={"pages": {}}, stats=None
    )
    assert '<p class="langs"><a href="?lang=en">en</a> <a href="?lang=de">de</a> ' in html
    assert re.findall(r'<link rel="alternate" hreflang="([a-z-]+)"', html) == ["en", "de", "fr"]
