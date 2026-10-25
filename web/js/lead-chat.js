// A route into an existing direct chat, never a new conversation or wider audience.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append } = M.dom;
  const ordered = (members) => members.slice().sort((a, b) => {
    const left = a.handle || "", right = b.handle || "";
    return left < right ? -1 : left > right ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
  const available = (m) => m && m.availability && m.availability.state === "available";

  function resolve(project, members) {
    const agents = ordered(members.filter((m) => m.kind === "agent" && !m.removed_at));
    const policy = project.policy || {};
    // Older hubs cannot tell us which admin or substitute holds the seat now.
    if (!("coordinator" in policy)) return null;
    let lead;
    if (policy.coordinator === "role:admin") {
      const admins = agents.filter((m) => m.role === "admin");
      if (admins.some((m) => !m.availability)) return null;
      lead = admins.find(available) || admins[0];
    } else lead = agents.find((m) => m.id === policy.coordinator);
    if (!lead || !lead.availability) return null;
    if (available(lead)) return lead;
    const substitute = agents.find((m) => m.id === policy.coordinator_substitute);
    if (available(substitute)) return substitute;
    const cover = agents.find((m) => m.id === (lead.covered_by || {}).member_id);
    return available(cover) ? cover : lead;
  }

  function control(ctx) {
    if (ctx.me.kind !== "human") return null;
    const members = ctx.members || [];
    const lead = resolve(ctx.project, members);
    const own = ordered(members.filter((m) => m.kind === "agent" && !m.removed_at && m.owner_id === ctx.me.id));
    const policy = ctx.project.policy || {};
    const routingKnown = "coordinator" in policy && members.filter((m) => m.kind === "agent" && m.role === "admin" && !m.removed_at)
      .every((m) => !!m.availability);
    const choices = ordered(members.filter((m) => m.kind === "agent" && !m.removed_at
      && (routingKnown || m.owner_id === ctx.me.id)
      && (m.role === "admin" || (m.role === "proxy" && m.owner_id === ctx.me.id))));
    const box = h("section", { class: "lead-chat", "aria-label": "Talk to the lead" });
    const person = (m) => h("span", { class: "lead-person" },
      h("span", { class: "presence " + (m.presence || "offline"), "aria-label": m.presence || "unknown presence" }, "● "),
      M.dom.memberRef(ctx, m));
    const status = M.statusLine();
    let opening = false;
    async function open(member) {
      if (opening) return;
      if (member.owner_id === ctx.me.id) { window.location.hash = ctx.link("chat", member.id); return; }
      opening = true;
      status.busy("Opening chat…");
      try {
        if (M.groupChat && !(await M.groupChat.served())) throw new Error("This hub does not support group chats yet.");
        const page = await M.api.getAll(ctx.base + "/conversations");
        const existing = page.items.find((c) => c.kind === "group" && !c.closed_at && c.access === "participant"
          && Array.isArray(c.participants) && c.participants.length === 2
          && c.participants.some((p) => p.member_id === ctx.me.id)
          && c.participants.some((p) => p.member_id === member.id));
        const chat = existing || await M.api.post(ctx.base + "/conversations",
          { title: "Talk to the lead", participants: [member.id] });
        status.done();
        window.location.hash = ctx.link("chat", chat.id);
      } catch (err) { status.fail("Could not open chat: ", err); }
      finally { opening = false; }
    }
    const action = (member, label) => member.owner_id === ctx.me.id
      ? h("a", { class: "button", href: ctx.link("chat", member.id) }, label)
      : h("button", { type: "button", onclick: () => open(member) }, label);
    if (lead) {
      append(box, h("span", null, "Lead: ", person(lead)), action(lead, "Talk to the lead"));
      if (lead.owner_id !== ctx.me.id) append(box, h("span", { class: "muted" }, "Opens a group chat with you and this agent; its owner can read along."));
      own.filter((m) => m.role === "proxy" && m.id !== lead.id).forEach((m) => {
        append(box, h("span", null, "Your proxy: ", person(m)), action(m, "Talk to your proxy"));
      });
    } else if (choices.length) {
      const select = h("select", { "aria-label": "Choose an admin or your proxy agent" },
        choices.map((m) => h("option", { value: m.id }, m.display_name + " · " + m.role + " · " + (m.presence || "unknown"))));
      select.value = choices[0].id;
      const preview = h("span", null, person(choices[0]));
      select.addEventListener("change", () => {
        const chosen = choices.find((m) => m.id === select.value);
        if (chosen) { M.dom.clear(preview); append(preview, person(chosen)); }
      });
      append(box, h("span", null, "Talk to the lead: choose an agent"), select, preview,
        h("button", { type: "button", onclick: () => { const chosen = choices.find((m) => m.id === select.value); if (chosen) open(chosen); } }, "Open chat"),
        h("span", { class: "muted" }, "Your agent opens in direct chat; another owner's agent opens in a group chat, which its owner can read."));
    } else append(box, h("span", { class: "muted" }, routingKnown
      ? "No admin or proxy agent is available in this project."
      : "No admin or proxy agent of yours is available for this shortcut yet."));
    append(box, status.el);
    return box;
  }

  async function all(ctx) {
    if (ctx.me.kind !== "human") return null;
    const box = h("section", { class: "lead-projects", "aria-label": "Talk to your project leads" }, h("h2", null, "Talk to the lead"));
    await Promise.all(ctx.projects.map(async (p) => {
      const row = h("div", { class: "lead-project" }, h("h3", null, p.name));
      append(box, row);
      const base = "/projects/" + encodeURIComponent(p.slug);
      try {
        const [project, page] = await Promise.all([M.api.get(base), M.api.getAll(base + "/members")]);
        const memberById = Object.fromEntries(page.items.map((m) => [m.id, m]));
        append(row, control({ ...ctx, base, project, members: page.items, memberById,
          nameOf: (id) => (memberById[id] || {}).display_name || id,
          link: (view, id) => ctx.projectLink(p.slug, view, id) }));
      } catch (err) { append(row, h("p", { class: "muted" }, "Could not read this project's agents: " + err.message)); }
    }));
    return box;
  }
  M.leadChat = { resolve, control, all };
})(window.Maity);
