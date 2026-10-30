// A person or an organisation at /<handle> (docs/api.md §6.27, §16.11), for
// a signed-in reader: one read, GET /people/{handle}, shown as the hub
// answers it for this reader. Name, handle and picture; for a person the
// bio while the public page is served, the links as far as the person's
// links_visible admits this reader, and the projects both are in; for an
// organisation its public projects and the reader's own in it, and its
// members with their roles for a member. **View public page** only where
// the hub serves one, opened at ?as=public (§16.9).
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

  const projectList = (ctx, list, none) => (list && list.length
    ? h("ul", { class: "person-projects" }, list.map((p) => h("li", null,
      ctx.projects.some((x) => x.full_name === p.full_name)
        ? h("a", { href: "/" + M.api.projectPath(p.full_name) + "/overview" }, p.name || p.full_name)
        : h("a", { href: "/" + M.api.projectPath(p.full_name) + "?as=public", target: "_blank", rel: "noopener" }, p.name || p.full_name),
      h("span", { class: "muted" }, " " + p.full_name))))
    : h("p", { class: "muted" }, none));

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
    // An alias answers with the current handle: the address follows it.
    if (p.handle && p.handle !== handle) M.route.go("/" + encodeURIComponent(p.handle), { replace: true });
    const org = p.kind === "organisation";
    const own = !org && ctx.me && ctx.me.handle === p.handle;
    append(root,
      h("div", { class: "person-head" },
        M.avatar ? M.avatar(Object.assign({ kind: org ? "organisation" : "human" }, p), 64) : null,
        h("div", null,
          h("h2", null, p.display_name || p.handle),
          h("p", { class: "muted" }, "@" + p.handle + (org ? " · organisation" : own ? " · you" : "")))),
      p.public_page ? h("p", null, h("a", { class: "button-link", href: "/" + encodeURIComponent(p.handle) + "?as=public", target: "_blank", rel: "noopener" }, "View public page")) : null,
      typeof p.public_bio === "string" && p.public_bio ? h("p", { class: "person-bio" }, p.public_bio) : null,
      org ? null : links(p.website, p.social));
    if (org) {
      append(root, h("h3", null, "Projects"),
        projectList(ctx, p.projects, "No public project, and none of yours in it."));
      if (Array.isArray(p.members)) {
        append(root, h("h3", null, "Members"),
          h("ul", { class: "person-members" }, p.members.map((m) => h("li", null,
            M.avatar ? M.avatar(Object.assign({ kind: "human" }, m), 20) : null, " ",
            m.display_name || m.handle, h("span", { class: "muted" }, " @" + m.handle + " · " + (ROLE_WORDS[m.role] || m.role))))));
      }
    } else if (!own) {
      append(root, h("h3", null, "Projects you share"),
        projectList(ctx, p.shared_projects, "You are in no project together."));
    }
  };

  M.person = { links };
})(window.Maity);
