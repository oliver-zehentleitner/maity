// A person or an organisation at /<handle> (docs/api.md §6.27, §16.11), for
// a signed-in human: one read, GET /people/{handle}, shown as the hub
// answers it for this reader. Name, handle and picture (a neutral
// placeholder where the hub gives none); for a person the bio while the
// public page is served and the links (built by the hub) as far as the
// person's links_visible admits this reader; the projects the hub lists, the
// shared ones marked; for an organisation its members with their roles
// for a member. **View public page** only where the hub serves one,
// opened at ?as=public (§16.9).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  // §16.9 "A person's links": the hub sends each network's link already
  // built from the name (#764), so a link goes where its label says, and
  // Discord, which has no public profile address, as the name. Only a
  // plain https address is a link; anything else is text.
  const NETWORKS = [["github", () => M.t("person.network.github")], ["gitlab", () => M.t("person.network.gitlab")],
    ["x", () => M.t("person.network.x")], ["mastodon", () => M.t("person.network.mastodon")],
    ["bluesky", () => M.t("person.network.bluesky")], ["linkedin", () => M.t("person.network.linkedin")],
    ["discord", () => M.t("person.network.discord")]];
  const REL_ME = ["me", "nofollow", "noopener"].join(" ");
  const shown = (url) => url.replace(/^https:\/\//, "").replace(/\/$/, "");
  const linkTo = (url) => h("a", { href: url, rel: REL_ME, target: "_blank" }, shown(url));

  // The website and the networks the hub sent for this reader, as a list;
  // null when it sent none. rel="me nofollow" as on the public page.
  function links(website, social) {
    const items = [];
    if (typeof website === "string" && /^https:\/\//.test(website)) items.push(h("li", null, linkTo(website)));
    NETWORKS.forEach(([key, label]) => {
      const value = social && social[key];
      if (typeof value !== "string" || !value) return;
      items.push(h("li", null, label() + ": ", /^https:\/\//.test(value) ? linkTo(value) : value));
    });
    return items.length ? h("ul", { class: "person-links" }, items) : null;
  }

  // The picture where the hub gives its address; otherwise, and when it
  // does not load, a neutral placeholder: the answer carries no account id
  // for §6.10's generated avatar (§6.27).
  function picture(x, px) {
    const none = () => h("span", { class: "person-picture-none size-" + px, "aria-hidden": "true" });
    if (!x.avatar_url) return none();
    try {
      const img = h("img", { class: "avatar-img", src: x.avatar_url, alt: "", width: String(px), height: String(px) });
      img.addEventListener("error", () => { if (img.parentNode) img.parentNode.replaceChild(none(), img); });
      return img;
    } catch (refused) {
      return none();
    }
  }

  // The projects the hub lists: one's own (shared) to its overview, any
  // other to its public page; a cut list said with its total.
  function projectList(p, none) {
    const list = p.projects || [];
    if (!list.length) return h("p", { class: "muted" }, none);
    return [h("ul", { class: "person-projects" }, list.map((x) => h("li", null,
      x.shared
        ? h("a", { href: "/" + M.api.projectPath(x.full_name) + "/overview" }, x.name || x.full_name)
        : h("a", { href: "/" + M.api.projectPath(x.full_name) + "?as=public", target: "_blank", rel: "noopener" }, x.name || x.full_name),
      h("span", { class: "muted" }, " " + (x.shared ? M.t("person.project.shared", { full_name: x.full_name }) : M.t("person.project.public", { full_name: x.full_name })))))),
    p.projects_total > list.length ? h("p", { class: "muted" }, M.t("person.projects.cut", { shown: list.length, total: p.projects_total })) : null];
  }

  // The organisation's roles of §6.26, in words.
  const ROLE_WORDS = { owner: () => M.t("person.role.owner"), admin: () => M.t("person.role.admin"), member: () => M.t("person.role.member") };
  const roleWords = (role) => (Object.hasOwn(ROLE_WORDS, role) ? ROLE_WORDS[role]() : role);

  M.views.person = async function (ctx, root, handle) {
    let p;
    try {
      p = await M.api.get("/people/" + encodeURIComponent(handle));
    } catch (err) {
      if (err.code !== "not_found") throw err;
      append(root, h("h2", null, "@" + handle), h("p", null, M.t("person.not_found", { handle })));
      return;
    }
    // An alias answers with the current handle: the address follows it, and
    // the view drawn there reads it; this one stops.
    if (p.handle && p.handle !== handle) { M.route.go("/" + encodeURIComponent(p.handle), { replace: true }); return; }
    const org = p.kind === "organisation";
    const own = !org && ctx.me && ctx.me.handle === p.handle;
    append(root,
      h("div", { class: "person-head" },
        picture(p, 64),
        h("div", null,
          h("h2", { class: "person-name" }, p.display_name || p.handle),
          h("p", { class: "muted" }, org ? M.t("person.handle.organisation", { handle: p.handle })
            : own ? M.t("person.handle.you", { handle: p.handle }) : M.t("person.handle", { handle: p.handle })))),
      p.page_served ? h("p", null, h("a", { class: "button-link", href: "/" + encodeURIComponent(p.handle) + "?as=public", target: "_blank", rel: "noopener" }, M.t("person.view_public"))) : null,
      typeof p.public_bio === "string" && p.public_bio ? h("p", { class: "person-bio" }, p.public_bio) : null,
      org ? null : links(p.website, p.social));
    append(root, h("h3", null, own ? M.t("person.projects.yours") : M.t("person.projects")),
      projectList(p, org ? M.t("person.projects.none_org") : own ? M.t("person.projects.none_own") : M.t("person.projects.none")));
    if (org && Array.isArray(p.members)) {
      append(root, h("h3", null, M.t("person.members")),
        h("ul", { class: "person-members" }, p.members.map((m) => h("li", null,
          picture(m, 20), " ",
          m.display_name || m.handle, h("span", { class: "muted" }, " " + M.t("person.member", { handle: m.handle, role: roleWords(m.role) }))))));
    }
  };

  M.person = { links };
})(window.Maity);
