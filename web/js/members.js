// Members (#/p/<slug>/members): everyone in the project, humans and agents,
// with role, owner, presence, when they joined and whether they are paused
// (docs/api.md §6.2). With members:admin each row can be managed: the role,
// an agent's pause, and removal. Where the hub sends them, an admin also
// sees each agent's owner and a credentials summary (counts and times only).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const ROLES = ["owner", "admin", "member", "reviewer", "proxy"];
  const PRESENCE_LABELS = { online: "Online", away: "Away", offline: "Offline", paused: "Paused" };
  // Presence emits no event (docs/api.md §5.3): the view re-reads it.
  const PRESENCE_MS = 30000;
  // The hub's refusals, in words; anything else is shown as it comes.
  const REFUSALS = {
    last_owner: "The project's last owner cannot be demoted or removed.",
    owner_is_human: "Only a human can be an owner.",
  };

  function refusal(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    const reason = fields && (fields.role || fields.member);
    return reason && REFUSALS[reason] ? { message: REFUSALS[reason] } : err;
  }

  function credentialsText(c) {
    if (!c) return "—";
    const parts = [c.active + " active"];
    if (c.never_resumed) parts.push(c.never_resumed + " never used");
    if (c.revoked_recent) parts.push(c.revoked_recent + " revoked lately");
    if (c.last_used_at) parts.push("last used " + formatAgo(c.last_used_at) + (c.last_used_via === "bearer" ? " (bearer token)" : ""));
    return parts.join(" · ");
  }

  function pausedText(ctx, p) {
    return p ? "paused by " + ctx.nameOf(p.by) + " " + formatAgo(p.since) + (p.reason ? ": " + p.reason : "") : "";
  }

  M.views.members = async function (ctx, root) {
    const status = M.statusLine();
    const box = h("div", { class: "members-box" });
    // Rows open for managing stay open across a re-read.
    const open = new Set();

    async function act(label, call) {
      status.busy(label + "…");
      try {
        await call();
        status.done();
        await reload();
        return true;
      } catch (err) {
        status.fail(label + " failed: ", refusal(err));
        return false;
      }
    }

    function manage(m, colspan) {
      const memberPath = ctx.base + "/members/" + encodeURIComponent(m.id);
      const roleId = "member-role-" + m.id;
      const role = h("select", { id: roleId },
        ROLES.filter((r) => r !== "owner" || m.kind === "human").map((r) => h("option", { value: r }, r)));
      role.value = m.role;
      const forms = [
        h("form", {
          class: "inline-form member-role",
          onsubmit: (e) => {
            e.preventDefault();
            if (role.value !== m.role) act("Changing the role", () => M.api.patch(memberPath, { role: role.value }));
          },
        }, h("label", { for: roleId }, "Role"), role, h("button", { type: "submit" }, "Change role")),
      ];
      if (m.kind === "agent") {
        const reasonId = "member-pause-" + m.id;
        const reason = h("input", { id: reasonId, placeholder: "Why it stops, e.g. quota", autocomplete: "off" });
        forms.push(m.paused
          ? h("div", { class: "member-pause" }, h("span", null, pausedText(ctx, m.paused) + " "),
            h("button", { type: "button", onclick: () => act("Clearing the pause", () => M.api.patch(memberPath, { paused: null })) }, "Clear pause"))
          : h("form", {
            class: "inline-form member-pause",
            onsubmit: (e) => {
              e.preventDefault();
              if (!reason.value.trim()) { reason.focus(); return; }
              act("Pausing", () => M.api.patch(memberPath, { paused: { reason: reason.value.trim() } }));
            },
          }, h("label", { for: reasonId }, "Pause with a reason"), reason, h("button", { type: "submit" }, "Pause")));
      }
      const self = m.id === ctx.me.id;
      forms.push(h("div", { class: "member-remove" }, h("button", {
        type: "button",
        class: "danger",
        onclick: async () => {
          const what = m.kind === "agent"
            ? "Its credentials are revoked and the cards it claimed are released."
            : self ? "You lose access to this project." : "They lose access to this project.";
          if (!window.confirm("Remove " + m.display_name + " from " + (ctx.project.name || ctx.slug) + "? " + what)) return;
          const done = await act("Removing", () => M.api.del(memberPath));
          if (done && self) window.location.hash = "#/all";
        },
      }, "Remove from the project")));
      return h("tr", { class: "member-manage" }, h("td", { colspan: String(colspan) }, forms));
    }

    function table(kind, items, columns) {
      const label = kind === "human" ? "Humans" : "Agents";
      const colspan = columns.length + (ctx.canAdmin ? 1 : 0);
      return [h("h3", null, label + " (" + items.length + ")"),
        h("table", { class: "members", tabindex: "0", "aria-label": label },
          h("thead", null, h("tr", null, columns.map((c) => h("th", { scope: "col" }, c.title)),
            ctx.canAdmin ? h("th", { scope: "col" }, "Actions") : null)),
          h("tbody", null, items.map((m) => {
            const expanded = open.has(m.id);
            const row = h("tr", { class: "member" + (m.paused ? " paused" : "") },
              columns.map((c) => h("td", { "data-label": c.title }, c.cell(m))),
              ctx.canAdmin ? h("td", { class: "member-actions" }, h("button", {
                type: "button",
                class: "small",
                "aria-expanded": expanded ? "true" : "false",
                "aria-label": "Manage " + m.display_name,
                onclick: () => { if (open.has(m.id)) open.delete(m.id); else open.add(m.id); draw(); },
              }, expanded ? "Done" : "Manage")) : null);
            return expanded ? [row, manage(m, colspan)] : row;
          })))];
    }

    let items = ctx.members;
    function draw() {
      const humans = items.filter((m) => m.kind === "human");
      const agents = items.filter((m) => m.kind === "agent");
      // Owner and credentials only where the hub sends them (members:admin).
      const hasCreds = agents.some((m) => "credentials" in m);
      const name = { title: "Name", cell: (m) => [h("span", { class: "member-name" }, m.display_name), h("span", { class: "muted" }, " @" + m.handle)] };
      const role = { title: "Role", cell: (m) => m.role };
      const presence = { title: "Presence", cell: (m) => [h("span", { class: "dot " + m.presence, "aria-hidden": "true" }), " ",
        PRESENCE_LABELS[m.presence] || m.presence, m.last_seen_at && m.presence !== "online" ? h("span", { class: "muted" }, " · seen " + formatAgo(m.last_seen_at)) : null] };
      const joined = { title: "Joined", cell: (m) => formatTime(m.joined_at) };
      const owner = { title: "Owner", cell: (m) => (m.owner ? m.owner.display_name : ctx.nameOf(m.owner_id)) };
      const paused = { title: "Paused", cell: (m) => pausedText(ctx, m.paused) || "—" };
      const creds = { title: "Credentials", cell: (m) => credentialsText(m.credentials) };
      append(clear(box),
        table("human", humans, [name, role, presence, joined]),
        agents.length
          ? table("agent", agents, [name, role, owner, presence, joined, paused].concat(hasCreds ? [creds] : []))
          : [h("h3", null, "Agents (0)"), h("p", { class: "muted" }, "No agents yet. ", ctx.canAdmin ? h("a", { href: ctx.link("join") }, "Join one.") : null)]);
    }

    async function reload() {
      items = (await M.api.getAll(ctx.base + "/members")).items;
      draw();
    }

    append(root, h("h2", null, "Members"),
      h("p", { class: "muted" }, "Everyone in " + (ctx.project.name || ctx.slug) + ", humans first."
        + (ctx.canAdmin ? " Manage a row to change its role, pause an agent or remove a member." : "")),
      status.el, box);
    draw();
    // A row being managed is not redrawn under the human's hands.
    ctx.every(PRESENCE_MS, () => (open.size ? null : reload().catch((err) => status.fail("Could not refresh: ", err))));
  };
})(window.Maity);
