// (4) Members (#/p/<slug>/members): everyone in the project, humans and
// agents, with role, owner, presence, when they joined and whether they are
// paused (docs/api.md §6.2). With members:admin each row can be managed: the
// role, an agent's pause, and removal. Where the hub sends them (an admin,
// or an agent's owner on their own agents), an agent's owner and a
// credentials summary are shown: counts and times only.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const ROLES = ["owner", "admin", "member", "reviewer", "proxy"];
  const PRESENCE_LABELS = { online: "Online", away: "Away", offline: "Offline", paused: "Paused" };
  // Presence emits no event (docs/api.md §5.3): the view re-reads it and
  // updates the presence cells in place, so focus and forms stay.
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
    if (c.revoked_recent) parts.push(c.revoked_recent + " revoked in the last 30 days");
    if (c.last_used_at) parts.push("last used " + formatAgo(c.last_used_at) + (c.last_used_via === "bearer" ? " (bearer token)" : ""));
    return parts.join(" · ");
  }

  // A presence the page knows gets its dot; anything else is said as it comes.
  function presenceNodes(m) {
    const known = Object.prototype.hasOwnProperty.call(PRESENCE_LABELS, m.presence);
    return [known ? h("span", { class: "dot " + m.presence, "aria-hidden": "true" }) : null, known ? " " : null,
      known ? PRESENCE_LABELS[m.presence] : String(m.presence || "unknown"),
      m.last_seen_at && m.presence !== "online" ? h("span", { class: "muted" }, " · seen " + formatAgo(m.last_seen_at)) : null];
  }

  // args[0]: a member to show (#/p/<slug>/members/<id>, a mention's link):
  // its row is marked and takes the focus.
  M.views.members = async function (ctx, root, args) {
    const wanted = args && args[0];
    const status = M.statusLine();
    const box = h("div", { class: "members-box" });
    // Rows open for managing stay open across a redraw.
    const open = new Set();
    // member id -> its presence cell, updated in place by the refresh.
    const presenceCells = new Map();
    // focus key -> the element drawn for it, so focus survives a redraw.
    const focusables = new Map();
    const keyed = (key, el) => { focusables.set(key, el); el.setAttribute("data-focus", key); return el; };
    let items = ctx.members;
    const byId = () => Object.fromEntries(items.map((m) => [m.id, m]));
    const nameOf = (id) => { const m = byId()[id]; return m ? m.display_name : ctx.nameOf(id); };

    function pausedText(m) {
      const p = m.paused;
      if (!p) return "";
      const by = p.by === m.id ? "paused itself" : "paused by " + nameOf(p.by);
      return by + " " + formatAgo(p.since) + (p.reason ? ": " + p.reason : "");
    }

    // Focus survives a redraw by key: the element drawn for the same key.
    function redraw(focusKey) {
      const active = document.activeElement;
      const key = focusKey || (active && active.getAttribute ? active.getAttribute("data-focus") : null);
      draw();
      const again = key && focusables.get(key);
      if (again) again.focus();
    }

    async function reload() {
      items = (await M.api.getAll(ctx.base + "/members")).items;
    }

    // A write and the re-read after it are told apart: a write that went
    // through is said as done even when the list cannot be read afterwards.
    async function act(label, done, call, focusKey) {
      status.busy(label + "…");
      try {
        await call();
      } catch (err) {
        status.fail(label + " failed: ", refusal(err));
        return false;
      }
      status.done();
      append(status.el, h("span", { class: "ok" }, done));
      try {
        await reload();
        redraw(focusKey);
      } catch (err) {
        status.fail(done + " Could not refresh: ", err);
      }
      return true;
    }

    function manage(m, rowId) {
      const memberPath = ctx.base + "/members/" + encodeURIComponent(m.id);
      const self = m.id === ctx.me.id;
      const roleId = "member-role-" + m.id;
      const role = keyed("role:" + m.id, h("select", { id: roleId },
        ROLES.filter((r) => r !== "owner" || m.kind === "human").map((r) => h("option", { value: r }, r))));
      role.value = m.role;
      const parts = [
        h("form", {
          class: "inline-form member-role",
          onsubmit: async (e) => {
            e.preventDefault();
            if (role.value === m.role) return;
            const changed = await act("Changing the role", m.display_name + " is now " + role.value + ".",
              () => M.api.patch(memberPath, { role: role.value }), "role:" + m.id);
            // Demoting oneself changes what this page may offer: re-render it.
            if (changed && self) ctx.refresh();
          },
        }, h("label", { for: roleId }, "Role"), role, h("button", { type: "submit" }, "Change role")),
      ];
      if (m.kind === "agent") {
        const reasonId = "member-pause-" + m.id;
        const reason = keyed("reason:" + m.id, h("input", { id: reasonId, placeholder: "Why it stops, e.g. quota", autocomplete: "off" }));
        const words = M.pauseWords || { effect: "", paused: "" };
        parts.push(m.paused
          ? h("div", { class: "member-pause" }, h("span", null, pausedText(m)),
            m.paused.by === m.id ? null : h("p", { class: "hint" }, words.paused),
            keyed("unpause:" + m.id, h("button", {
              type: "button",
              onclick: () => act("Clearing the pause", "The pause of " + m.display_name + " is cleared.",
                () => M.api.patch(memberPath, { paused: null }), "reason:" + m.id),
            }, "Clear pause")))
          : h("form", {
            class: "inline-form member-pause",
            onsubmit: (e) => {
              e.preventDefault();
              if (!reason.value.trim()) { reason.focus(); return; }
              act("Pausing", m.display_name + " is paused.", () => M.api.patch(memberPath, { paused: { reason: reason.value.trim() } }), "unpause:" + m.id);
            },
          }, h("label", { for: reasonId }, "Pause with a reason"), reason,
          h("button", { type: "submit" }, "Pause"),
          h("p", { class: "hint" }, words.effect)));
      }
      parts.push(h("div", { class: "member-remove" }, h("button", {
        type: "button",
        class: "danger",
        onclick: async () => {
          const what = m.kind === "agent"
            ? "Its credentials are revoked and the cards it claimed are released."
            : self ? "You lose access to this project." : "They lose access to this project.";
          if (!window.confirm("Remove " + m.display_name + " from " + (ctx.project.name || ctx.slug) + "? " + what)) return;
          open.delete(m.id);
          const removed = await act("Removing", m.display_name + " was removed.", () => M.api.del(memberPath));
          if (removed && self) window.location.hash = "#/all";
        },
      }, "Remove from the project")));
      return h("tr", { class: "member-manage", id: rowId, role: "row" }, h("td", { colspan: "99", role: "cell" }, parts));
    }

    function nameCell(m) {
      // An agent's card is on the Agents view; one's own agent also has a chat.
      const mine = m.kind === "agent" && m.owner_id === ctx.me.id;
      return h("th", { scope: "row", role: "rowheader", "data-label": "Name", tabindex: m.id === wanted ? "-1" : null },
        h("span", { class: "member-name" }, m.display_name), h("span", { class: "muted" }, " @" + m.handle),
        mine ? h("span", { class: "member-links" }, " · ", h("a", { href: ctx.link("chat", m.id) }, "Chat")) : null);
    }

    function table(kind, list, columns) {
      const label = kind === "human" ? "Humans" : "Agents";
      const headingId = "members-" + kind;
      return [h("h3", { id: headingId }, label + " (" + list.length + ")"),
        h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-labelledby": headingId },
          h("table", { class: "members", role: "table", "aria-labelledby": headingId },
            h("thead", { role: "rowgroup" }, h("tr", { role: "row" },
              h("th", { scope: "col", role: "columnheader" }, "Name"),
              columns.map((c) => h("th", { scope: "col", role: "columnheader" }, c.title)),
              ctx.canAdmin ? h("th", { scope: "col", role: "columnheader" }, "Actions") : null)),
            h("tbody", { role: "rowgroup" }, list.map((m) => {
              const expanded = open.has(m.id);
              const rowId = "member-manage-" + m.id;
              const row = h("tr", { class: "member" + (m.paused ? " paused" : "") + (m.id === wanted ? " wanted" : ""), role: "row", "data-member": m.id },
                nameCell(m),
                columns.map((c) => {
                  const td = h("td", { "data-label": c.title, role: "cell" }, c.cell(m));
                  if (c.presence) presenceCells.set(m.id, td);
                  return td;
                }),
                ctx.canAdmin ? h("td", { class: "member-actions", "data-label": "Actions", role: "cell" }, keyed("manage:" + m.id, h("button", {
                  type: "button",
                  class: "small",
                  "aria-expanded": expanded ? "true" : "false",
                  "aria-controls": expanded ? rowId : null,
                  "aria-label": (expanded ? "Done managing " : "Manage ") + m.display_name,
                  onclick: () => {
                    if (open.has(m.id)) { open.delete(m.id); redraw("manage:" + m.id); } else { open.add(m.id); redraw("role:" + m.id); }
                  },
                }, expanded ? "Done" : "Manage"))) : null);
              return expanded ? [row, manage(m, rowId)] : row;
            }))))];
    }

    function draw() {
      presenceCells.clear();
      focusables.clear();
      const humans = items.filter((m) => m.kind === "human");
      const agents = items.filter((m) => m.kind === "agent");
      // Owner and credentials only where the hub sends them.
      const hasCreds = agents.some((m) => "credentials" in m);
      const role = { title: "Role", cell: (m) => m.role };
      const presence = { title: "Presence", presence: true, cell: presenceNodes };
      const joined = { title: "Joined", cell: (m) => formatTime(m.joined_at) };
      const owner = { title: "Owner", cell: (m) => (m.owner ? m.owner.display_name : nameOf(m.owner_id)) };
      const paused = { title: "Paused", cell: (m) => pausedText(m) || "—" };
      const creds = { title: "Credentials", cell: (m) => credentialsText(m.credentials) };
      append(clear(box),
        table("human", humans, [role, presence, joined]),
        agents.length
          ? table("agent", agents, [role, owner, presence, joined, paused].concat(hasCreds ? [creds] : []))
          : [h("h3", null, "Agents (0)"), h("p", { class: "muted" }, "No agents yet. ", ctx.canAdmin ? h("a", { href: ctx.link("join") }, "Join one.") : null)]);
    }

    append(root, h("h2", null, "Members"),
      h("p", { class: "muted" }, "Everyone in " + (ctx.project.name || ctx.slug) + ", humans first."
        + (ctx.canAdmin ? " Manage a row to change its role, pause an agent or remove a member." : "")),
      status.el, box);
    draw();
    // A member asked for by the URL: its row takes the focus once the view is
    // in the page; an id that is no member here is said.
    if (wanted) {
      const row = Array.from(box.querySelectorAll("tr.member")).find((tr) => tr.getAttribute("data-member") === wanted);
      const th = row && row.childNodes[0];
      if (th) window.setTimeout(() => th.focus(), 0);
      else append(status.el, h("span", null, "No member with the id " + wanted + " in this project."));
    }
    ctx.every(PRESENCE_MS, async () => {
      try {
        const fresh = (await M.api.getAll(ctx.base + "/members")).items;
        const ids = (list) => list.map((m) => m.id).sort().join(" ");
        const same = ids(fresh) === ids(items);
        items = fresh;
        // Someone joined or left: redraw (focus kept); else presence in place.
        if (!same) { redraw(); return; }
        fresh.forEach((m) => { const td = presenceCells.get(m.id); if (td) append(clear(td), presenceNodes(m)); });
        status.done();
      } catch (err) {
        status.fail("Could not refresh: ", err);
      }
    });
  };
})(window.Maity);
