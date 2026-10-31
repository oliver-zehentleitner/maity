// Reading along outside one's projects (/observe/<owner>/<slug>, docs/api.md
// §9.2): an agent of the human is a member of a project the human is not
// in. Its owner reads the group chats that agent is in, read only, and
// nothing else of the project: no header, no members, no events. The
// projects come from the agents' memberships (GET /agents, §6.3); the
// chats from GET …/conversations?observed=true; the view is the chat
// view's own (js/chat.js, js/group-chat.js) in a context without a project.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  // The projects one's agents are in and one is not: [{ slug: its full name, agents: [...] }].
  async function outside(ctx) {
    const agents = (await M.api.getAll("/agents")).items.filter((a) => a.owner_id === ctx.me.id);
    const mine = new Set(ctx.projects.map((p) => p.full_name));
    const bySlug = {};
    agents.forEach((a) => (a.memberships || []).forEach((m) => {
      if (mine.has(m.project)) return;
      (bySlug[m.project] = bySlug[m.project] || { slug: m.project, agents: [] }).agents.push(a);
    }));
    return Object.values(bySlug).sort((a, b) => a.slug.localeCompare(b.slug));
  }

  const names = (list) => new Intl.ListFormat(M.i18n.language, { type: "unit" }).format(list.map((a) => a.display_name));
  const link = (full, id) => "/observe/" + M.api.projectPath(full) + (id ? "/" + encodeURIComponent(id) : "");

  // On everything waiting: where one also reads along, if anywhere.
  async function note(ctx) {
    let list;
    try {
      list = await outside(ctx);
    } catch (err) {
      return null;
    }
    if (!list.length) return null;
    return h("section", { class: "observe-note", "aria-labelledby": "observe-note-title" },
      h("h3", { id: "observe-note-title" }, M.t("observe.note.title")),
      h("p", { class: "muted" }, M.t("observe.note.hint")),
      h("ul", null, list.map((p) => h("li", null, h("a", { href: link(p.slug) }, p.slug),
        h("span", { class: "muted" }, " · ", M.t("observe.note.through", { names: names(p.agents) }))))));
  }

  M.views.observe = async function (ctx, root, where) {
    const slug = where.slug;
    if (ctx.projects.some((p) => p.full_name === slug)) {
      append(root, h("p", null, M.tn("observe.member", { project: slug, chats: h("a", { href: ctx.projectLink(slug, "chat") }, M.t("observe.member.chats")) })));
      return;
    }
    const here = (await outside(ctx)).find((p) => p.slug === slug);
    if (!here) {
      append(root, h("p", { class: "error", role: "alert" }, M.t("observe.none", { project: slug })));
      return;
    }
    // Names from what the chats and one's own agents say; nothing else of
    // the project is read (§9.2: every other read is not_found).
    const shown = {};
    here.agents.forEach((a) => { shown[a.id] = a.display_name; });
    const chats = (await M.api.getAll("/projects/" + M.api.projectPath(slug) + "/conversations?observed=true")).items;
    chats.forEach((c) => (c.participants || []).forEach((p) => { if (!shown[p.member_id]) shown[p.member_id] = "@" + p.handle; }));
    const view = Object.assign({}, ctx, {
      slug,
      base: "/projects/" + M.api.projectPath(slug),
      project: { name: slug, state: "build" },
      members: [],
      memberById: Object.fromEntries(here.agents.map((a) => [a.id, a])),
      outsider: true,
      role: null,
      canAdmin: false,
      isOwner: false,
      // Someone not among the chat's participants: who left, or an admin's removal.
      nameOf: (id) => shown[id] || M.t("observe.someone"),
      link: (route, id) => link(slug, route === "chat" ? id : null),
      // No event reaches a non-member: the views re-read on their own timers.
      onEvents: () => {},
    });
    append(root, h("h2", null, M.t("observe.title", { project: slug })),
      h("p", { class: "muted" }, M.t("observe.hint", { names: names(here.agents) })));
    await M.views.chat(view, root, where.args || []);
  };

  M.observe = { outside, note };
})(window.Maity);
