"""docs/api.md §6.10 and §16.9: a picture a public page shows, its sizes, an agent's motif and
its generated picture, and the public pages that draw them."""

from __future__ import annotations

import io
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import Engine, select, update

from maity_hub import avatar_generated, avatars, clock, images, motifs, public_pages
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_avatars import image, put_agent, put_human
from tests.test_public_project_views import World

PUBLIC = "/api/v1/avatars/public"


@pytest.fixture(autouse=True)
def _fresh_changes() -> None:
    avatars.CHANGES.reset()


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, settings: Any) -> World:
    public_pages.configure(replace(settings, public_pages=True))
    return World(make_client, migrated)


def digest(url: str) -> str:
    """The digest an `avatar_url` names (`?v=`) or a public address ends in."""
    return url.split("?v=")[1] if "?v=" in url else url.rsplit("/", 1)[1]


def main(client: Any, path: str) -> str:
    got = client.get(path)
    assert got.status_code == 200, got.text
    assert "<title>dashboard</title>" not in got.text, f"{path} answered the app shell"
    return str(got.text)


def _changed(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.event).where(t.event.c.kind == "avatar_changed").order_by(t.event.c.seq)
            )
        )


# --- the generated picture ----------------------------------------------------------------


def test_the_generated_picture_is_the_dashboards_identicon() -> None:
    picture = Image.open(io.BytesIO(avatar_generated.draw("agt-23ghr1hc6qxx")))
    assert (picture.format, picture.size, picture.mode) == ("PNG", (256, 256), "RGBA")
    assert picture.getpixel((0, 0)) == (0, 0, 0, 0)  # the margin: transparent
    # The pattern of `web/js/avatar.js` for this id, and its hue at 60 % and 50 %.
    assert avatar_generated.cells("agt-23ghr1hc6qxx") == {
        (0, 0), (0, 1), (1, 0), (1, 2), (1, 4), (2, 2), (3, 0), (3, 2), (3, 4), (4, 0), (4, 1),
    }  # fmt: skip
    assert avatar_generated.hue("agt-23ghr1hc6qxx") == 198
    cell = 256 / 7
    assert picture.getpixel((int(1.5 * cell), int(1.5 * cell))) == (51, 158, 204, 255)
    assert picture.getpixel((int(3.5 * cell), int(1.5 * cell))) == (0, 0, 0, 0)  # (2, 0) is off
    assert avatar_generated.cells("x") and avatar_generated.draw("x") == avatar_generated.draw("x")


def test_an_agent_has_its_generated_picture_from_the_start(world: World, migrated: Engine) -> None:
    me = world.bot.get("/me").json()["member"]
    png = avatar_generated.draw(me["id"])
    assert (me["avatar_source"], me["avatar_motif"]) == ("generated", None)
    assert me["avatar_url"] == avatars.url_of(me["id"], images.etag(png))
    served = world.owner.client.get(me["avatar_url"])
    assert served.status_code == 200 and served.content == png
    created = world.owner.post("/agents", {"handle": "fresh", "display_name": "Fresh"})
    assert created.status_code == 201, created.text
    assert created.json()["avatar_source"] == "generated"


# --- the public address -------------------------------------------------------------------


def test_a_persons_picture_is_public_while_their_profile_is(world: World) -> None:
    url = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    public = f"{PUBLIC}/{digest(url)}"
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    got = world.anyone.get(public)  # no session
    assert got.status_code == 200, got.text
    assert got.headers["cache-control"] == "public, max-age=86400, s-maxage=60"
    assert got.headers["content-type"] == "image/png"
    assert got.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert got.headers["etag"] == f'"{digest(url)}"'
    # The id address keeps its readers: a stranger never reads it, whatever the page.
    assert world.anyone.get(url).status_code in (401, 404)
    assert world.owner.client.get(url).headers["cache-control"] == "private, no-cache"
    assert world.owner.patch("/me", {"public_profile": False}).status_code == 200
    gone = world.anyone.get(public)
    assert gone.status_code == 404
    assert "public" not in gone.headers["cache-control"]  # a refusal is never kept
    assert world.anyone.get(f"{PUBLIC}/{'0' * 32}").status_code == 404
    assert world.anyone.get(f"{PUBLIC}/not-a-digest").status_code == 404


def test_the_address_stops_with_the_page(world: World, migrated: Engine) -> None:
    url = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    world.owner.patch("/me", {"public_profile": True})
    public = f"{PUBLIC}/{digest(url)}"
    assert world.anyone.get(public).status_code == 200
    with migrated.begin() as conn:  # a suspended account has no page (§16.9)
        conn.execute(
            update(t.human)
            .where(t.human.c.id == world.owner.id)
            .values(suspended_at=clock.now(), suspended_report="rpt-x")
        )
    assert world.anyone.get(public).status_code == 404


def test_a_replaced_picture_leaves_its_old_address(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    old = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    new = put_human(world.owner, "/me/avatar", image(size=(90, 90))).json()["avatar_url"]
    assert digest(old) != digest(new)
    assert world.anyone.get(f"{PUBLIC}/{digest(old)}").status_code == 404
    assert world.anyone.get(f"{PUBLIC}/{digest(new)}").status_code == 200


def test_an_agents_picture_is_public_while_its_owners_agents_page_lists_it(
    world: World, make_client: ClientFactory
) -> None:
    listed = world.bot.get("/me").json()["member"]["avatar_url"]  # in a public project
    assert world.anyone.get(f"{PUBLIC}/{digest(listed)}").status_code == 200
    flow.project(world.owner, "secret")
    hidden = flow.agent(
        make_client, world.owner, "secret", agent={"handle": "hidden", "display_name": "Hidden"}
    )
    url = put_agent(hidden, image(size=(80, 80))).json()["avatar_url"]
    assert world.anyone.get(f"{PUBLIC}/{digest(url)}").status_code == 404  # no page, not listed
    assert world.owner.patch("/me", {"public_agents": "all"}).status_code == 200
    assert world.anyone.get(f"{PUBLIC}/{digest(url)}").status_code == 200  # listed now


def test_an_organisations_picture_is_never_public(world: World, migrated: Engine) -> None:
    from tests.test_orgs import make_org

    org = make_org(world.owner)
    put = put_human(world.owner, f"/orgs/{org['handle']}/avatar", image())
    assert put.status_code == 200, put.text
    assert world.anyone.get(f"{PUBLIC}/{digest(put.json()['avatar_url'])}").status_code == 404


def test_nothing_is_public_while_the_hub_serves_no_pages(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    url = put_human(owner, "/me/avatar", image()).json()["avatar_url"]
    owner.patch("/me", {"public_profile": True})
    assert make_client().get(f"{PUBLIC}/{digest(url)}").status_code == 404


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


# --- sizes --------------------------------------------------------------------------------


def test_every_size_is_scaled_once_and_kept(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = put_human(owner, "/me/avatar", image(size=(300, 300))).json()["avatar_url"]
    scaled: list[str] = []
    decode = avatars.decode

    def counted(settings: Any, data: bytes, kind: str, mode: str = "avatar") -> bytes:
        scaled.append(mode)
        return decode(settings, data, kind, mode)

    monkeypatch.setattr(avatars, "decode", counted)
    tags = {}
    for side in (32, 64, 128, 256):
        got = owner.client.get(f"{url}&s={side}")
        assert got.status_code == 200, got.text
        assert Image.open(io.BytesIO(got.content)).size == (side, side)
        tags[side] = got.headers["etag"]
    assert len(set(tags.values())) == 4  # each size its own ETag
    assert tags[256] == f'"{digest(url)}"'
    assert scaled == ["size32", "size64", "size128"]
    again = owner.client.get(f"{url}&s=64")
    assert again.headers["etag"] == tags[64] and scaled == ["size32", "size64", "size128"]
    assert owner.client.get(f"{url}&s=64", headers={"If-None-Match": tags[64]}).status_code == 304
    with migrated.connect() as conn:
        kept = conn.execute(select(t.avatar_size.c.size).order_by(t.avatar_size.c.size)).all()
    assert [row.size for row in kept] == [32, 64, 128]
    # A new picture drops the sizes of the old one.
    put_human(owner, "/me/avatar", image(size=(90, 90)))
    with migrated.connect() as conn:
        assert conn.execute(select(t.avatar_size)).first() is None


def test_a_small_picture_is_never_scaled_up(owner: flow.Human) -> None:
    url = put_human(owner, "/me/avatar", image(size=(50, 50))).json()["avatar_url"]
    for side, shown in ((32, 32), (64, 50), (128, 50), (256, 50)):
        got = owner.client.get(f"{url}&s={side}")
        assert Image.open(io.BytesIO(got.content)).size == (shown, shown), side


@pytest.mark.parametrize("size", ["", "0", "48", "512", "64px", "064"])
def test_another_size_is_invalid_only_once_the_image_is_found(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, size: str
) -> None:
    url = put_human(owner, "/me/avatar", image()).json()["avatar_url"]
    refused = owner.client.get(f"{url}&s={size}")
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"s": "unsupported"}
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.client.get(f"{url}&s={size}").status_code == 404  # not told
    assert owner.client.get(f"/api/v1/avatars/{'hum-' + 'x' * 12}?s={size}").status_code == 404
    assert make_client().get(f"{PUBLIC}/{'0' * 32}?s={size}").status_code == 404


def test_two_values_of_s_are_invalid(owner: flow.Human) -> None:
    url = put_human(owner, "/me/avatar", image()).json()["avatar_url"]
    assert owner.client.get(f"{url}&s=32&s=64").status_code == 400


# --- motifs -------------------------------------------------------------------------------


def test_the_motifs_are_listed_by_theme(world: World) -> None:
    answer = world.bot.client.get("/api/v1/avatars/motifs", headers=world.bot.auth)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    names = [m["name"] for m in body["motifs"]]
    assert body["version"] and len(names) == len(set(names)) == 36
    themes = [m["theme"] for m in body["motifs"]]
    assert themes[0] == "classic" and themes == sorted(themes, key=themes.index)
    assert set(body["motifs"][0]) == {"name", "theme", "label", "alt", "url"}
    first = body["motifs"][0]
    got = world.anyone.get(first["url"])  # a motif's digest answers at every time
    assert got.status_code == 200 and Image.open(io.BytesIO(got.content)).size == (256, 256)
    small = world.anyone.get(f"{first['url']}?s=32")
    assert Image.open(io.BytesIO(small.content)).size == (32, 32)
    assert world.owner.get("/avatars/motifs").status_code == 200
    assert world.anyone.get("/api/v1/avatars/motifs").status_code == 401


def test_an_agent_chooses_its_motif_and_an_upload_shows_over_it(
    world: World, migrated: Engine
) -> None:
    bot = world.bot
    motif = motifs.current().motifs[3]
    before = len(_changed(migrated))
    chose = bot.patch("/me", {"avatar_motif": motif.name})
    assert chose.status_code == 200, chose.text
    me = bot.get("/me").json()["member"]
    assert (me["avatar_source"], me["avatar_motif"]) == ("motif", motif.name)
    assert digest(me["avatar_url"]) == motif.digest
    served = world.owner.client.get(me["avatar_url"])
    assert served.content == motif.data
    events = _changed(migrated)[before:]
    assert [e.payload["avatar_url"] for e in events] == [me["avatar_url"]]
    assert events[0].actor_membership is not None  # the agent's own change names it (§6.10)
    # An upload shows over the choice, which stays; deleting the upload brings it back.
    put_agent(bot, image())
    me = bot.get("/me").json()["member"]
    assert (me["avatar_source"], me["avatar_motif"]) == ("uploaded", motif.name)
    removed = bot.client.delete("/api/v1/me/avatar", headers=bot.auth).json()
    assert removed["avatar_source"] == "motif"
    # Cleared: the generated picture again.
    assert bot.patch("/me", {"avatar_motif": None}).status_code == 200
    me = bot.get("/me").json()["member"]
    assert (me["avatar_source"], me["avatar_motif"]) == ("generated", None)


def test_the_owner_chooses_a_motif_and_an_unknown_one_is_invalid(world: World) -> None:
    me = world.bot.get("/me").json()["member"]
    name = motifs.current().motifs[-1].name
    chose = world.owner.patch(f"/agents/{me['id']}", {"avatar_motif": name})
    assert chose.status_code == 200, chose.text
    assert (chose.json()["avatar_source"], chose.json()["avatar_motif"]) == ("motif", name)
    for wrong in ("no-such-motif", 7, ""):
        refused = world.owner.patch(f"/agents/{me['id']}", {"avatar_motif": wrong})
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["details"]["fields"] == {"avatar_motif": "unknown"}
    human = world.owner.patch("/me", {"avatar_motif": name})
    assert human.status_code == 400
    assert human.json()["error"]["details"]["fields"] == {"avatar_motif": "agents_only"}


def test_a_choice_counts_under_the_limit_a_repeat_too(world: World) -> None:
    me = world.bot.get("/me").json()["member"]
    name = motifs.current().motifs[0].name
    for _ in range(avatars.CHANGES.limit):
        assert world.owner.patch(f"/agents/{me['id']}", {"avatar_motif": name}).status_code == 200
    limited = world.owner.patch(f"/agents/{me['id']}", {"avatar_motif": name})
    assert limited.status_code == 429


def _copy_set(tmp: Path) -> Path:
    folder = tmp / "motifs"
    shutil.copytree(motifs.FOLDER, folder)
    return folder


def _manifest(folder: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((folder / "manifest.json").read_text())
    return loaded


@pytest.mark.parametrize(
    "break_it",
    [
        lambda m, f: m["motifs"][1].update(name=m["motifs"][0]["name"]),  # not unique
        lambda m, f: m["motifs"][0].update(name="Fox"),  # the syntax
        lambda m, f: m["motifs"][0].update(theme="x"),  # a theme too short
        lambda m, f: m["motifs"][0].update(label="x" * 41),
        lambda m, f: m["motifs"][0].update(alt="x" * 121),
        lambda m, f: m["motifs"][0].update(file="../manifest.json"),
        # a NUL in the file name: refused like a separator, not a traceback at the start
        lambda m, f: m["motifs"][0].update(file="fox.png\x00"),
        lambda m, f: (f / m["motifs"][0]["file"]).write_bytes(image(size=(512, 500))),
        lambda m, f: (f / m["motifs"][0]["file"]).write_bytes(b"\x89PNG" + bytes(70 * 1024)),
        # a PNG signature without an IHDR: the header check refuses it, the start goes on
        lambda m, f: (f / m["motifs"][0]["file"]).write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(40)),
        # a valid header over broken data: the decoder refuses it
        lambda m, f: (f / m["motifs"][0]["file"]).write_bytes(
            (f / m["motifs"][0]["file"]).read_bytes()[:33] + bytes(200)
        ),
    ],
)
def test_a_set_that_fails_the_check_is_not_served(
    tmp_path: Path, break_it: Any, caplog: pytest.LogCaptureFixture
) -> None:
    folder = _copy_set(tmp_path)
    manifest = _manifest(folder)
    break_it(manifest, folder)
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert motifs.load(folder) == motifs.EMPTY
    assert "the avatar motifs are not served" in caplog.text


def test_the_shipped_set_passes_the_check(tmp_path: Path) -> None:
    loaded = motifs.load(_copy_set(tmp_path))
    assert len(loaded.motifs) == 36
    assert all(Image.open(io.BytesIO(m.data)).size == (256, 256) for m in loaded.motifs)


def test_a_motif_the_set_no_longer_holds_stops_applying(
    world: World, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = world.bot.get("/me").json()["member"]
    name = motifs.current().motifs[0].name
    world.owner.patch(f"/agents/{me['id']}", {"avatar_motif": name})
    monkeypatch.setattr(motifs, "current", lambda folder=None: motifs.EMPTY)
    after = world.bot.get("/me").json()["member"]
    assert (after["avatar_source"], after["avatar_motif"]) == ("generated", name)


# --- the public pages ---------------------------------------------------------------------


def test_the_pages_draw_the_pictures_from_their_public_addresses(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    url = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    page = world.anyone.get("/maintainer")
    assert page.headers["content-security-policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'"
    )
    html = page.text
    assert f'<img class="pic" src="{PUBLIC}/{digest(url)}?s=128" alt=""' in html
    assert world.owner.id not in html
    bot = world.bot.get("/me").json()["member"]
    bot_public = f"{PUBLIC}/{digest(bot['avatar_url'])}"
    handle = bot["handle"]
    agent_page = main(world.anyone, f"/maintainer/agents/{handle}")
    assert f'src="{bot_public}?s=128"' in agent_page and bot["id"] not in agent_page
    agents = main(world.anyone, "/maintainer/agents")
    assert f'src="{bot_public}?s=64"' in agents
    assert "<img" not in html.split("<h2>Agents</h2>")[1]  # the profile shows no agent's picture
    data = world.anyone.get(f"/api/v1/public/pages/maintainer/agents/{handle}").json()["data"]
    assert data["picture"] == bot_public
    person = world.anyone.get("/api/v1/public/pages/maintainer").json()["data"]
    assert person["picture"] == f"{PUBLIC}/{digest(url)}"


def test_a_private_profile_shows_the_placeholder(world: World) -> None:
    put_human(world.owner, "/me/avatar", image())
    world.owner.patch("/me", {"public_profile": False})
    html = main(world.anyone, "/maintainer")
    assert '<span class="pic none" style="width:128px;height:128px"' in html
    assert "<img" not in html
    assert world.anyone.get("/api/v1/public/pages/maintainer").json()["data"]["picture"] is None


def test_a_new_picture_renders_the_pages_again(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    bot = world.bot.get("/me").json()["member"]
    handle = bot["handle"]
    assert digest(bot["avatar_url"]) in main(world.anyone, f"/maintainer/agents/{handle}")
    new = put_agent(world.bot, image()).json()["avatar_url"]
    assert digest(new) in main(world.anyone, f"/maintainer/agents/{handle}")
    assert digest(new) in main(world.anyone, "/maintainer/agents")
    old = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    assert digest(old) in main(world.anyone, "/maintainer")
    world.owner.delete("/me/avatar")
    html = main(world.anyone, "/maintainer")
    assert digest(old) not in html and "pic none" in html
