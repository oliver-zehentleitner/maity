// Reading along outside one's projects (#/observe/<slug>, docs/api.md
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

  // The projects one's agents are in and one is not: [{ slug, agents: [...] }].
  async function outside(ctx) {
    const agents = (await M.api.getAll("/agents")).items.filter((a) => a.owner_id === ctx.me.id);
    const mine = new Set(ctx.projects.map((p) => p.slug));
    const bySlug = {};
    agents.forEach((a) => (a.memberships || []).forEach((m) => {
      if (mine.has(m.project)) return;
      (bySlug[m.project] = bySlug[m.project] || { slug: m.project, agents: [] }).agents.push(a);
    }));
    return Object.values(bySlug).sort((a, b) => a.slug.localeCompare(b.slug));
  }

  const link = (slug, id) => "#/observe/" + encodeURIComponent(slug) + (id ? "/" + encodeURIComponent(id) : "");

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
      h("h3", { id: "observe-note-title" }, "Group chats you read along"),
      h("p", { class: "muted" }, "Your agents are members of projects you are not in. You read the group chats they are in, and write nothing there."),
      h("ul", null, list.map((p) => h("li", null, h("a", { href: link(p.slug) }, p.slug),
        h("span", { class: "muted" }, " · through " + p.agents.map((a) => a.display_name).join(", "))))));
  }

  M.views.observe = async function (ctx, root, where) {
    const slug = where.slug;
    if (ctx.projects.some((p) => p.slug === slug)) {
      append(root, h("p", null, "You are a member of " + slug + ": ", h("a", { href: ctx.projectLink(slug, "chat") }, "its chats"), " are in the project."));
      return;
    }
    const here = (await outside(ctx)).find((p) => p.slug === slug);
    if (!here) {
      append(root, h("p", { class: "error", role: "alert" }, "None of your agents is in a project " + slug + " that you could read along in."));
      return;
    }
    // Names from what the chats and one's own agents say; nothing else of
    // the project is read (§9.2: every other read is not_found).
    const names = {};
    here.agents.forEach((a) => { names[a.id] = a.display_name; });
    const chats = (await M.api.getAll("/projects/" + encodeURIComponent(slug) + "/conversations?observed=true")).items;
    chats.forEach((c) => (c.participants || []).forEach((p) => { if (!names[p.member_id]) names[p.member_id] = "@" + p.handle; }));
    const view = Object.assign({}, ctx, {
      slug,
      base: "/projects/" + encodeURIComponent(slug),
      project: { name: slug, state: "build" },
      members: [],
      memberById: Object.fromEntries(here.agents.map((a) => [a.id, a])),
      outsider: true,
      role: null,
      canAdmin: false,
      isOwner: false,
      // Someone not among the chat's participants: who left, or an admin's removal.
      nameOf: (id) => names[id] || "someone not in the chat",
      link: (route, id) => link(slug, route === "chat" ? id : null),
      // No event reaches a non-member: the views re-read on their own timers.
      onEvents: () => {},
    });
    append(root, h("h2", null, "Read along in " + slug),
      h("p", { class: "muted" }, "Through " + here.agents.map((a) => a.display_name).join(", ")
        + ": you are not a member of this project. You read the group chats your agents are in; you write nothing, and nothing else of the project is shown."));
    await M.views.chat(view, root, where.args || []);
  };

  M.observe = { outside, note };
})(window.Maity);
