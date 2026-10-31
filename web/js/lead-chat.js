// The header's Lead button and whom it reaches: the project's lead, one's
// own proxy, else one's own admin agents (js/app.js). It opens an existing
// direct chat, or a group of exactly the reader and another owner's agent,
// or of the reader and all leads.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append } = M.dom;
  const ordered = (members) => members.slice().sort((a, b) => {
    const left = a.handle || "", right = b.handle || "";
    return left < right ? -1 : left > right ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
  const available = (m) => m && m.availability && m.availability.state === "available";

  // An admin agent: trust admin, not the owner's proxy (§2.3).
  const adminAgent = (m) => m.trust === "admin" && m.role !== "proxy";

  function resolve(project, members) {
    const agents = ordered(members.filter((m) => m.kind === "agent" && !m.removed_at));
    const policy = project.policy || {};
    let lead;
    // trust:admin (§2.3): the admin agents, the proxy aside.
    if (policy.coordinator === "trust:admin") {
      const admins = agents.filter(adminAgent);
      lead = admins.find(available) || admins[0];
    } else lead = agents.find((m) => m.id === policy.coordinator);
    if (!lead) return null;
    if (available(lead)) return lead;
    const substitute = agents.find((m) => m.id === policy.coordinator_substitute);
    if (available(substitute)) return substitute;
    const cover = agents.find((m) => m.id === (lead.covered_by || {}).member_id);
    return available(cover) ? cover : lead;
  }

  // Whom the header's Lead button reaches in one project (tsk-g2qe0fyqqmmq):
  // the lead the policy names now and one's own proxy; without one, the
  // admin agents and one's own proxy. Agents get none.
  function targets(ctx) {
    if (!ctx.me || ctx.me.kind !== "human") return [];
    const members = ctx.members || [];
    const live = (m) => m.kind === "agent" && !m.removed_at;
    const lead = resolve(ctx.project, members);
    if (lead) {
      return [lead].concat(ordered(members.filter((m) => live(m) && m.role === "proxy" && m.owner_id === ctx.me.id && m.id !== lead.id)));
    }
    return ordered(members.filter((m) => live(m) && (adminAgent(m) || (m.role === "proxy" && m.owner_id === ctx.me.id))));
  }

  // Into the chat with `member`: one's own agent's direct chat; another
  // owner's agent in a group of exactly the two (an open one reused, else
  // made), which its owner can read. Never a wider existing chat, never a
  // direct chat with someone else's agent. A chat made here is titled from
  // the catalog in the maker's language and keeps that title; it is found
  // again by its participants, never by its title.
  async function open(ctx, member) {
    if (member.owner_id === ctx.me.id) { M.route.go(ctx.link("chat", member.id)); return; }
    const page = await M.api.getAll(ctx.base + "/conversations");
    const existing = page.items.find((c) => c.kind === "group" && !c.closed_at && c.access === "participant"
      && Array.isArray(c.participants) && c.participants.length === 2
      && c.participants.some((p) => p.member_id === ctx.me.id)
      && c.participants.some((p) => p.member_id === member.id));
    const chat = existing || await M.api.post(ctx.base + "/conversations",
      { title: M.t("lead.chat_title"), participants: [member.id] });
    M.route.go(ctx.link("chat", chat.id));
  }

  // Every project's targets, for the header outside a project: each
  // project's view and members read once per page drawn (per ctx), so the
  // counts' refresh asks nothing again.
  const everywhereOf = new WeakMap();
  function targetsEverywhere(ctx) {
    if (!everywhereOf.has(ctx)) {
      everywhereOf.set(ctx, Promise.all(ctx.projects.map(async (p) => {
        const base = "/projects/" + M.api.projectPath(p.full_name);
        try {
          const [project, page] = await Promise.all([M.api.get(base), M.api.getAll(base + "/members")]);
          const memberById = Object.fromEntries(page.items.map((m) => [m.id, m]));
          const pctx = { ...ctx, slug: p.full_name, base, project, members: page.items, memberById,
            nameOf: (id) => (memberById[id] || {}).display_name || id,
            link: (view, id) => ctx.projectLink(p.full_name, view, id) };
          return targets(pctx).map((member) => ({ ctx: pctx, member, project: p }));
        } catch (err) { return []; }
      })).then((lists) => [].concat(...lists)));
    }
    return everywhereOf.get(ctx);
  }

  // A group chat of exactly the reader and these agents, an open one
  // reused, else made (§9.2), titled as in open(); their owners can read along.
  async function openGroup(ctx, members) {
    const want = new Set([ctx.me.id].concat(members.map((m) => m.id)));
    const page = await M.api.getAll(ctx.base + "/conversations");
    const existing = page.items.find((c) => c.kind === "group" && !c.closed_at && c.access === "participant"
      && Array.isArray(c.participants) && c.participants.length === want.size
      && c.participants.every((p) => want.has(p.member_id)));
    const chat = existing || await M.api.post(ctx.base + "/conversations",
      { title: M.t("lead.group_title"), participants: members.map((m) => m.id) });
    M.route.go(ctx.link("chat", chat.id));
  }

  // The header's Lead button, beside Chat (the maintainer's decision on
  // tsk-g2qe0fyqqmmq, req-4rpd7vqb6xe3): with one lead or proxy to reach
  // it opens that chat; with several a small menu lists them, and per
  // project with more than one a group chat with all of them. None: no
  // button. Chat itself stays the way to every chat.
  function leadControl(ctx, found) {
    const list = found.list;
    if (!list.length) return null;
    const status = (err) => {
      const header = document.getElementById("header");
      const old = header && header.querySelector(".chat-open-failed");
      if (old) old.remove();
      if (header && err) append(header, h("p", { class: "send-status failed chat-open-failed", role: "alert" }, M.t("lead.open_failed", { reason: err.message })));
    };
    const name = (t) => {
      const shown = t.member.display_name + (found.multiProject ? " · " + t.project.name : "");
      return t.member.role === "proxy" ? M.t("lead.proxy", { name: shown }) : shown;
    };
    // One opening at a time: a second click while a chat is being found or
    // made does nothing, so no second group chat is made (H on #459).
    let opening = false;
    const once = (act) => {
      if (opening) return;
      opening = true;
      status(null);
      act().catch(status).finally(() => { opening = false; });
    };
    const face = [M.icons && M.icons.lead ? M.icons.lead(18) : null, h("span", { class: "lead-button-label" }, M.t("lead.button"))];
    if (list.length === 1) {
      const t = list[0];
      const own = t.member.owner_id === ctx.me.id;
      const a = h("a", { class: "bell lead-button", href: own ? t.ctx.link("chat", t.member.id) : t.ctx.link("chat"),
        "aria-label": M.t("lead.talk_to", { name: name(t) }), title: M.t("lead.talk_to", { name: name(t) }) }, face);
      if (!own) a.addEventListener("click", (e) => { e.preventDefault(); once(() => open(t.ctx, t.member)); });
      return a;
    }
    // Per project, its leads and, with more than one, a group chat with all.
    const projects = [];
    list.forEach((t) => {
      let p = projects.find((x) => x.slug === t.project.full_name);
      if (!p) { p = { slug: t.project.full_name, name: t.project.name, ctx: t.ctx, members: [] }; projects.push(p); }
      p.members.push(t.member);
    });
    const menu = M.menuButton({
      label: M.t("lead.menu"),
      class: "bell lead-button",
      face,
      items: () => {
        const items = [];
        projects.forEach((p, i) => {
          if (i) items.push({ separator: true });
          list.filter((t) => t.project.full_name === p.slug).forEach((t) => items.push({ label: name(t), onSelect: () => once(() => open(t.ctx, t.member)) }));
          if (p.members.length > 1) {
            items.push({ label: M.t("lead.group") + (found.multiProject ? " · " + p.name : ""),
              onSelect: () => once(() => openGroup(p.ctx, p.members)) });
          }
        });
        return items;
      },
    });
    menu.el.className += " lead-button-box";
    return menu.el;
  }

  // Whom the Lead button reaches from this page: the project's, or every
  // project's outside one (then each named with its project).
  async function found(ctx) {
    if (!ctx.me || ctx.me.kind !== "human") return { list: [], multiProject: false };
    if (ctx.scope === "project") return { list: targets(ctx).map((member) => ({ ctx, member, project: ctx.project })), multiProject: false };
    const list = await targetsEverywhere(ctx);
    return { list, multiProject: new Set(list.map((t) => t.project.full_name)).size > 1 };
  }

  M.leadChat = { resolve, targets, open, openGroup, found, leadControl };
})(window.Maity);
