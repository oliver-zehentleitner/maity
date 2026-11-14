// A person or an organisation at /<handle> (docs/api.md §6.27, §16.11), for
// a signed-in human: one read, GET /people/{handle}, shown as the hub
// answers it for this reader. Name, handle and picture (a neutral
// placeholder where the hub gives none); for a person the bio while the
// public page is served and the links (built by the hub) as far as the
// person's links_visible admits this reader; the projects the hub lists, the
// shared ones marked; for an organisation its members with their roles
// for a member. **View public page** only where the hub serves one,
// opened at ?as=public (§16.9). A person's view has two tabs, as their public
// page has (§16.9, "A person's agents"): **Profile** at /<handle> and
// **Agents** at /<handle>/agents, the agents the same answer lists (§6.27).
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

  // The tabs a person's view and both their public pages carry (§16.9): Profile and Agents.
  const tabs = (handle, chosen) => h("nav", { class: "view-tabs person-tabs", "aria-label": M.t("person.tabs.label") },
    [["profile", "/" + encodeURIComponent(handle), M.t("person.tab.profile")],
      ["agents", "/" + encodeURIComponent(handle) + "/agents", M.t("person.tab.agents")]].map(([k, href, label]) =>
      h("a", { href, class: "view-tab", "aria-current": k === chosen ? "page" : null }, label)));

  // One listed agent as the agents page shows it (§16.9, "A person's agents"): the picture at
  // 64 px from its public address, the name, linked where it has a page, and the handle; with a
  // page also its roles, model and harness. Shared with js/visitor.js, whose entries name the
  // name `name` and the picture `picture` (the visitors' route) where §6.27 says `display_name`
  // and `avatar_url`.
  function agentItem(a) {
    const name = a.display_name || a.name || a.handle;
    const pic = a.avatar_url !== undefined ? a.avatar_url : a.picture;
    const shownPic = picture({ avatar_url: typeof pic === "string" && pic ? pic + (pic.includes("?") ? "&" : "?") + "s=64" : null }, 64);
    const facts = [a.model ? M.t("visitor.model", { model: a.model }) : null, a.harness ? M.t("visitor.harness", { harness: a.harness }) : null].filter(Boolean);
    return h("li", { class: "person-agent", "data-agent": a.handle },
      shownPic,
      h("div", null,
        M.route.isRoute(a.page) ? h("a", { href: a.page }, name) : h("span", null, name),
        " (" + a.handle + ")",
        (a.page && Array.isArray(a.roles) ? a.roles : []).map((role) => [" ", h("span", { class: "label-tag" }, M.trust.roleLabel(role))]),
        facts.length ? h("p", { class: "muted" }, facts.join(" · ")) : null));
  }
  const agentList = (agents) => (agents && agents.length
    ? h("ul", { class: "person-agents" }, agents.map(agentItem))
    : h("p", { class: "muted" }, M.t("person.agents.none")));

  M.views.person = async function (ctx, root, handle, tab) {
    let p;
    try {
      p = await M.api.get("/people/" + encodeURIComponent(handle));
    } catch (err) {
      if (err.code !== "not_found") throw err;
      append(root, h("h2", null, "@" + handle), h("p", null, M.t("person.not_found", { handle })));
      return;
    }
    // An alias answers with the current handle: the address follows it, the
    // tab kept, and the view drawn there reads it; this one stops.
    if (p.handle && p.handle !== handle) {
      M.route.go("/" + encodeURIComponent(p.handle) + (tab === "agents" ? "/agents" : ""), { replace: true });
      return;
    }
    const org = p.kind === "organisation";
    // An organisation has no agents (§16.9): /<org>/agents names nothing.
    if (org && tab === "agents") { M.notFound.view(root); return; }
    const own = !org && ctx.me && ctx.me.handle === p.handle;
    // Report this person to the instance's admins (§16.8, tsk-7ze5w6ymf7bw) by the current handle, the
    // name this reader has; not oneself, and not an organisation, which §16.8 does not take yet.
    const reporting = M.report && !org && !own ? M.report.control({ type: "profile", id: p.handle }, "person") : null;
    append(root,
      h("div", { class: "person-head" },
        picture(p, 64),
        h("div", null,
          h("h2", { class: "person-name" }, p.display_name || p.handle),
          h("p", { class: "muted" }, org ? M.t("person.handle.organisation", { handle: p.handle })
            : own ? M.t("person.handle.you", { handle: p.handle }) : M.t("person.handle", { handle: p.handle })))),
      org ? null : tabs(p.handle, tab === "agents" ? "agents" : "profile"));
    const publicAt = "/" + encodeURIComponent(p.handle) + (tab === "agents" ? "/agents" : "");
    const viewPublic = p.page_served ? h("p", null, h("a", { class: "button-link", href: publicAt + "?as=public", target: "_blank", rel: "noopener" }, M.t("person.view_public"))) : null;
    // Agents: the list of §6.27's `agents`, the one the public agents page shows (§16.9), so a
    // reader sees at this address what a visitor sees at it.
    if (tab === "agents") {
      append(root, viewPublic, h("h3", null, M.t("person.tab.agents")), agentList(p.agents));
      return;
    }
    append(root,
      viewPublic,
      typeof p.public_bio === "string" && p.public_bio ? h("p", { class: "person-bio" }, p.public_bio) : null,
      org ? null : links(p.website, p.social),
      reporting ? [h("p", { class: "report-row" }, reporting.button), reporting.slot] : null);
    append(root, h("h3", null, own ? M.t("person.projects.yours") : M.t("person.projects")),
      projectList(p, org ? M.t("person.projects.none_org") : own ? M.t("person.projects.none_own") : M.t("person.projects.none")));
    if (org && Array.isArray(p.members)) {
      append(root, h("h3", null, M.t("person.members")),
        h("ul", { class: "person-members" }, p.members.map((m) => h("li", null,
          picture(m, 20), " ",
          m.display_name || m.handle, h("span", { class: "muted" }, " " + M.t("person.member", { handle: m.handle, role: roleWords(m.role) }))))));
    }
    if (reporting && M.report.asked()) reporting.open();
  };

  M.person = { links, tabs, agentList };
})(window.Maity);
