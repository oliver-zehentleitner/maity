"""docs/api.md §16.7.2: the variants and campaigns of the landing page, as the admin sets them,
as a visitor reaches them, and as the admin sees them before saving."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_landing import GOOD, HERO, text

ADMIN = "/admin/settings/landing"
PREVIEW = "/admin/settings/landing/preview"


def page(title: str, *sections: dict[str, Any]) -> dict[str, Any]:
    return {"title": title, "description": f"{title} page", "sections": list(sections)}


def main_page() -> dict[str, Any]:
    return {"en": page("The main page", HERO, text(GOOD))}


def variant(title: str, *sections: dict[str, Any], **more: dict[str, Any]) -> dict[str, Any]:
    return {"pages": {"en": page(title, *(sections or (HERO,))), **more}}


def fields(response: Any) -> dict[str, str]:
    found: dict[str, str] = response.json()["error"]["details"]["fields"]
    return found


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)  # the first human: the instance admin


def publish(owner: flow.Human, **setting: Any) -> Any:
    return owner.patch(
        ADMIN, {"enabled": True, "default_language": "en", "pages": main_page(), **setting}
    )


def test_the_setting_has_no_variants_and_no_campaigns_by_default(owner: flow.Human) -> None:
    got = owner.get(ADMIN).json()
    assert (got["variants"], got["campaigns"]) == ({}, [])


def test_the_admin_saves_variants_and_campaigns_and_reads_them_back(owner: flow.Human) -> None:
    variants = {"maintainers": variant("For maintainers"), "teams": variant("For teams")}
    campaigns = [{"code": "x-h1-w1", "label": "X, hook 1, week 1"}]
    saved = publish(owner, variants=variants, campaigns=campaigns)
    assert saved.status_code == 200, saved.text
    got = owner.get(ADMIN).json()
    assert got["variants"].keys() == {"maintainers", "teams"}
    assert got["variants"]["teams"]["pages"]["en"]["title"] == "For teams"
    assert got["campaigns"] == campaigns


def test_a_field_left_out_stays_and_an_empty_one_clears(owner: flow.Human) -> None:
    publish(owner, variants={"a": variant("A")}, campaigns=[{"code": "c1", "label": "One"}])
    owner.patch(ADMIN, {"footer": {"operator": "Op"}})
    got = owner.get(ADMIN).json()
    assert list(got["variants"]) == ["a"] and got["campaigns"][0]["code"] == "c1"
    owner.patch(ADMIN, {"variants": {}, "campaigns": []})
    got = owner.get(ADMIN).json()
    assert (got["variants"], got["campaigns"]) == ({}, [])


def test_the_public_setting_has_neither(owner: flow.Human, make_client: ClientFactory) -> None:
    publish(owner, variants={"a": variant("A")}, campaigns=[{"code": "c1", "label": "Secret"}])
    shown = make_client().get("/api/v1/landing").json()
    assert shown["enabled"] is True and "variants" not in shown and "campaigns" not in shown
    assert "Secret" not in str(shown)


@pytest.mark.parametrize(
    ("slug", "ok"),
    [
        ("maintainers", True),
        ("a", True),
        ("a" * 40, True),
        ("a-b-1", True),
        ("a" * 41, False),
        ("-a", False),
        ("a-", False),
        ("A", False),
        ("a_b", False),
        ("default", False),
        ("a b", False),
    ],
)
def test_a_slug_is_lower_case_letters_digits_and_hyphens(
    owner: flow.Human, slug: str, ok: bool
) -> None:
    answer = publish(owner, variants={slug: variant("V")})
    assert (answer.status_code == 200) is ok, answer.text
    if not ok:
        assert fields(answer) == {f"variants.{slug}": "invalid"}


def test_at_most_five_variants(owner: flow.Human) -> None:
    five = {f"v{n}": variant("V") for n in range(5)}
    assert publish(owner, variants=five).status_code == 200
    six = {**five, "v5": variant("V")}
    assert fields(publish(owner, variants=six)) == {"variants": "invalid"}


def test_a_variants_pages_follow_the_rules_of_the_main_page(owner: flow.Human) -> None:
    bad = variant("V", text("a <script>alert(1)</script>"))
    refused = publish(owner, variants={"x": bad})
    assert fields(refused) == {"variants.x.pages.en.sections.0.markdown": "line 1"}
    nothing = publish(owner, variants={"x": {"pages": {"en": {"description": "no title"}}}})
    assert fields(nothing) == {"variants.x.pages.en.title": "required"}
    extra = publish(owner, variants={"x": {"pages": {"en": page("T")}, "theme": "dark"}})
    assert fields(extra) == {"variants.x.theme": "extra_forbidden"}
    assert fields(publish(owner, variants={"x": {}})) == {"variants.x.pages": "required"}


def test_a_variant_needs_its_page_in_the_default_language_while_enabled(
    owner: flow.Human,
) -> None:
    only_german = {"pages": {"de": page("Nur deutsch", HERO)}}
    refused = publish(owner, variants={"x": only_german})
    assert fields(refused) == {"variants.x.pages.en": "required"}
    off = owner.patch(
        ADMIN, {"enabled": False, "pages": main_page(), "variants": {"x": only_german}}
    )
    assert off.status_code == 200, off.text  # a draft may wait


def test_campaign_codes_and_labels(owner: flow.Human) -> None:
    ok = [{"code": "a-1", "label": "X, hook 1, week 1"}, {"code": "b", "label": "B"}]
    assert publish(owner, campaigns=ok).status_code == 200
    bad = publish(
        owner,
        campaigns=[
            {"code": "A", "label": "upper"},
            {"code": "a" * 41, "label": "long"},
            {"code": "dup", "label": "one"},
            {"code": "dup", "label": "two"},
            {"code": "nolabel"},
            {"code": "x", "label": "a\x00b"},
            {"code": "y", "label": "z" * 121},
            {"label": "no code"},
        ],
    )
    assert bad.status_code == 400
    assert fields(bad) == {
        "campaigns.0.code": "invalid",
        "campaigns.1.code": "invalid",
        "campaigns.3.code": "duplicate",
        "campaigns.4.label": "required",
        "campaigns.5.label": "control_character",
        "campaigns.6.label": "invalid",
        "campaigns.7.code": "required",
    }


def test_at_most_200_campaigns(owner: flow.Human) -> None:
    many = [{"code": f"c{n}", "label": "L"} for n in range(200)]
    assert publish(owner, campaigns=many).status_code == 200
    over = [*many, {"code": "c200", "label": "L"}]
    assert fields(publish(owner, campaigns=over)) == {"campaigns": "invalid"}


def test_the_variants_count_towards_the_cap_of_the_setting(owner: flow.Human) -> None:
    big = "x" * 15000  # a text section of at most 16 KiB; five variants of five of them
    sections = [text(big)] * 5
    pages = {f"v{n}": variant("V", *sections) for n in range(5)}
    refused = publish(owner, variants=pages)
    assert refused.status_code == 400
    assert fields(refused) == {"pages": "too_large"}


def test_variants_and_campaigns_are_the_admin_s_alone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "other")
    assert other.get(ADMIN).status_code == 403
    assert other.patch(ADMIN, {"variants": {}}).status_code == 403
    assert make_client().get(f"/api/v1{ADMIN}").status_code in (401, 403)


def test_a_variant_is_served_at_its_address_to_every_visitor(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner, variants={"maintainers": variant("For maintainers")})
    visitor = make_client()
    got = visitor.get("/for/maintainers")
    assert got.status_code == 200
    assert "<title>For maintainers</title>" in got.text and "The main page" not in got.text
    assert '<link rel="canonical" href="https://hub.example/">' in got.text
    assert '<meta name="robots" content="noindex">' in got.text
    assert got.headers["content-type"].startswith("text/html")
    assert got.headers["cache-control"] == "private, max-age=60"
    assert "script-src 'self'" in got.headers["content-security-policy"]
    # a signed-in admin sees a visitor's page here, not the app shell
    again = owner.client.get("/for/maintainers")
    assert again.status_code == 200 and "<title>For maintainers</title>" in again.text
    # the main page is the main page
    root = visitor.get("/")
    assert "<title>The main page</title>" in root.text
    assert '<meta name="robots" content="noindex">' not in root.text


def test_an_unknown_variant_or_a_disabled_page_is_the_app_shell_never_another_status(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    visitor = make_client()
    before = visitor.get("/for/nothing")
    publish(owner, variants={"x": variant("X")})
    unknown = visitor.get("/for/nothing")
    assert (unknown.status_code, unknown.text) == (before.status_code, before.text)
    owner.patch(ADMIN, {"enabled": False})
    off = visitor.get("/for/x")
    assert (off.status_code, off.text) == (before.status_code, before.text)
    assert "For maintainers" not in off.text


def test_a_language_a_variant_lacks_falls_back_to_its_own_default_page(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    german_main = {**main_page(), "de": page("Die Hauptseite", HERO)}
    owner.patch(
        ADMIN,
        {
            "enabled": True,
            "default_language": "en",
            "pages": german_main,
            "variants": {"only-en": variant("Only English")},
        },
    )
    got = make_client().get("/for/only-en?lang=de")
    assert "<title>Only English</title>" in got.text  # never the main page's German page
    assert "Die Hauptseite" not in got.text


def test_the_variants_are_in_neither_robots_nor_the_sitemap(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner, variants={"maintainers": variant("For maintainers")})
    visitor = make_client()
    assert "/for/maintainers" not in visitor.get("/sitemap.xml").text
    robots = visitor.get("/robots.txt").text
    assert "Allow: /for" not in robots and "/for/maintainers" not in robots


def test_a_campaign_link_carries_the_origin_to_every_register_link(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(
        owner,
        variants={"maintainers": variant("For maintainers")},
        campaigns=[{"code": "x-h1-w1", "label": "X, hook 1, week 1"}],
    )
    visitor = make_client()
    on_variant = visitor.get("/for/maintainers?c=x-h1-w1").text
    assert 'href="/register?v=maintainers&amp;c=x-h1-w1"' in on_variant
    assert 'href="/register"' not in on_variant
    on_main = visitor.get("/?c=x-h1-w1").text
    assert 'href="/register?v=default&amp;c=x-h1-w1"' in on_main
    # the language switch keeps the campaign
    assert "?lang=" not in on_main or "&amp;c=x-h1-w1" in on_main
    # no campaign: `v` alone
    assert 'href="/register?v=maintainers"' in visitor.get("/for/maintainers").text


def test_an_unknown_or_malformed_code_is_treated_as_none_and_not_echoed(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner, campaigns=[{"code": "known", "label": "K"}])
    visitor = make_client()
    plain = visitor.get("/").text
    for code in ("unknown", "UP", "a b", "x" * 80, "<script>"):
        answer = visitor.get("/", params={"c": code})
        assert answer.status_code == 200
        assert answer.text == plain
        assert code not in answer.text
    assert 'href="/register?v=default"' in plain


def test_nothing_changes_while_neither_is_configured(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    visitor = make_client()
    got = visitor.get("/?c=anything")
    assert 'href="/register"' in got.text and "v=default" not in got.text
    assert got.headers["cache-control"] == "public, max-age=60"
    publish(owner, campaigns=[{"code": "k", "label": "K"}])
    assert visitor.get("/").headers["cache-control"] == "private, max-age=60"
    owner.patch(ADMIN, {"campaigns": []})  # emptying both stops it at once
    assert visitor.get("/").headers["cache-control"] == "public, max-age=60"


def test_a_variant_is_seen_before_it_is_saved(owner: flow.Human) -> None:
    publish(owner)
    draft = owner.post(
        PREVIEW, {"variants": {"teams": variant("A draft for teams")}, "pages": main_page()}
    )
    assert draft.status_code == 201, draft.text
    url = draft.json()["url"]
    got = owner.client.get(f"{url}?variant=teams")
    assert got.status_code == 200 and "<title>A draft for teams</title>" in got.text
    assert got.headers["cache-control"] == "no-store" and "noindex" in got.headers["x-robots-tag"]
    assert "<title>The main page</title>" in owner.client.get(url).text  # without `variant`
    assert owner.client.get(f"{url}?variant=missing").status_code == 404
    assert owner.get(ADMIN).json()["variants"] == {}  # nothing was saved
