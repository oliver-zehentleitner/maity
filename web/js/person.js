// A person or an organisation at /<handle> (docs/api.md §6.27, §16.11), for
// a signed-in human: one read, GET /people/{handle}, shown as the hub
// answers it for this reader. Name, handle and picture (a neutral
// placeholder where the hub gives none); for a person the bio while the
// public page is served and the links as far as the person's
// links_visible admits this reader; the projects the hub lists, the
// shared ones marked; for an organisation its members with their roles
// for a member. **View public page** only where the hub serves one,
// opened at ?as=public (§16.9).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  // §16.9 "A person's links": each built from the name, so a link goes
  // where its label says; Discord has no public profile address and is text.
  const NETWORKS = [
    ["github", "GitHub", (n) => "https://github.com/" + encodeURIComponent(n)],
    ["gitlab", "GitLab", (n) => "https://gitlab.com/" + n.split("/").map(encodeURIComponent).join("/")],
    ["x", "X", (n) => "https://x.com/" + encodeURIComponent(n)],
    ["mastodon", "Mastodon", (n) => {
      const m = /^@([A-Za-z0-9_]{1,30})@([a-z0-9.-]+)$/.exec(n);
      return m ? "https://" + m[2] + "/@" + m[1] : null;
    }],
    ["bluesky", "Bluesky", (n) => "https://bsky.app/profile/" + encodeURIComponent(n)],
    ["linkedin", "LinkedIn", (n) => "https://www.linkedin.com/in/" + encodeURIComponent(n)],
    ["discord", "Discord", () => null],
  ];

  // The website and the networks the hub sent for this reader, as a list;
  // null when it sent none. rel="me nofollow" as on the public page.
  function links(website, social) {
    const items = [];
    if (typeof website === "string" && /^https:\/\//.test(website)) {
      items.push(h("li", null, h("a", { href: website, rel: "me nofollow noopener", target: "_blank" }, website.replace(/^https:\/\//, ""))));
    }
    NETWORKS.forEach(([key, label, url]) => {
      const name = social && social[key];
      if (typeof name !== "string" || !name) return;
      const href = url(name);
      items.push(h("li", null, label + ": ", href ? h("a", { href, rel: "me nofollow noopener", target: "_blank" }, name) : name));
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
      h("span", { class: "muted" }, " " + x.full_name + (x.shared ? " · yours too" : " · public page"))))),
    p.projects_total > list.length ? h("p", { class: "muted" }, list.length + " of " + p.projects_total + " shown.") : null];
  }

  const ROLE_WORDS = { owner: "owner", admin: "admin", member: "member" };

  M.views.person = async function (ctx, root, handle) {
    let p;
    try {
      p = await M.api.get("/people/" + encodeURIComponent(handle));
    } catch (err) {
      if (err.code !== "not_found") throw err;
      append(root, h("h2", null, "@" + handle), h("p", null, "There is no person or organisation @" + handle + " that you can see."));
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
          h("p", { class: "muted" }, "@" + p.handle + (org ? " · organisation" : own ? " · you" : "")))),
      p.page_served ? h("p", null, h("a", { class: "button-link", href: "/" + encodeURIComponent(p.handle) + "?as=public", target: "_blank", rel: "noopener" }, "View public page")) : null,
      typeof p.public_bio === "string" && p.public_bio ? h("p", { class: "person-bio" }, p.public_bio) : null,
      org ? null : links(p.website, p.social));
    append(root, h("h3", null, own ? "Your projects" : "Projects"),
      projectList(p, org ? "No public project, and none of yours in it." : own ? "You are in no project." : "No project you share, and no public one."));
    if (org && Array.isArray(p.members)) {
      append(root, h("h3", null, "Members"),
        h("ul", { class: "person-members" }, p.members.map((m) => h("li", null,
          picture(m, 20), " ",
          m.display_name || m.handle, h("span", { class: "muted" }, " @" + m.handle + " · " + (ROLE_WORDS[m.role] || m.role))))));
    }
  };

  M.person = { links };
})(window.Maity);
