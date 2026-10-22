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
    cycle: "That would close a circle: they would end up reporting to themselves.",
    not_a_member: "Reports to someone who is not a member of this project.",
    invalid_path: "An area is a repository path like hub/ or docs/api.md, without ..",
    unknown: "Not a known value.",
    string_too_long: "The briefing is longer than 16,384 characters.",
  };
  // The hub's rules for an area (hub/src/maity_hub/routes/members.py).
  const AREA = /^[A-Za-z0-9._/-]{1,255}$/;
  const areaOk = (a) => AREA.test(a) && !a.startsWith("..") && !("/" + a + "/").includes("/../");
  const CAPABILITIES = [["tag", "May tag a release (tag)"]];
  const BRIEFING_CHARS = 16 * 1024;

  // The hub names each bad field (details.fields); said in words.
  function refusal(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (!fields) return err;
    const said = Object.values(fields).map((reason) => REFUSALS[reason]).filter(Boolean);
    return said.length ? { message: said.join(" ") } : err;
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

  M.views.members = async function (ctx, root) {
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
      const parts = [editForm(m, memberPath, self)];
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

    // Would m reporting to boss close a circle? Follow boss's chain upwards.
    function closesCircle(m, boss) {
      const all = byId();
      const seen = new Set();
      for (let at = boss; at; at = all[at] && all[at].reports_to) {
        if (at === m.id) return true;
        if (seen.has(at)) return false;
        seen.add(at);
      }
      return false;
    }

    // The membership as §6.2 lets an admin change it, in one form; only the
    // fields that changed are sent, in one PATCH.
    function editForm(m, memberPath, self) {
      const id = (what) => "member-" + what + "-" + m.id;
      const role = keyed("role:" + m.id, h("select", { id: id("role") },
        ROLES.filter((r) => r !== "owner" || m.kind === "human").map((r) => h("option", { value: r }, r))));
      role.value = m.role;
      const reports = h("select", { id: id("reports") }, h("option", { value: "" }, "nobody"),
        items.filter((x) => x.id !== m.id).map((x) => h("option", { value: x.id }, x.display_name + " (@" + x.handle + ")")));
      reports.value = m.reports_to || "";
      const areas = h("input", { id: id("areas"), placeholder: "hub/, docs/", autocomplete: "off", spellcheck: "false",
        "aria-describedby": id("areas") + "-hint" });
      areas.value = (m.areas || []).join(", ");
      const caps = CAPABILITIES.map(([cap, label]) => {
        const box = h("input", { type: "checkbox", id: id("cap-" + cap) });
        box.checked = (m.capabilities || []).includes(cap);
        return { cap, box, label };
      });
      // A briefing only where the hub shows one (members:admin, docs/api.md §6.2).
      const hasBriefing = m.kind === "agent" && "briefing" in m;
      const briefing = hasBriefing ? h("textarea", { id: id("briefing"), rows: "4" }) : null;
      if (briefing) briefing.value = m.briefing || "";
      const fail = (field, text) => { status.fail("Not saved: ", { message: text }); field.focus(); };
      return h("form", {
        class: "member-edit",
        onsubmit: async (e) => {
          e.preventDefault();
          const body = {};
          if (role.value !== m.role) body.role = role.value;
          const boss = reports.value || null;
          if (boss !== (m.reports_to || null)) {
            if (boss && closesCircle(m, boss)) { fail(reports, REFUSALS.cycle); return; }
            body.reports_to = boss;
          }
          const list = [...new Set(areas.value.split(",").map((a) => a.trim()).filter(Boolean))];
          if (list.some((a) => !areaOk(a))) { fail(areas, REFUSALS.invalid_path); return; }
          if (list.join("\n") !== (m.areas || []).join("\n")) body.areas = list;
          // Capabilities this page does not offer are kept as they are.
          const others = (m.capabilities || []).filter((c) => !CAPABILITIES.some(([k]) => k === c));
          const capList = others.concat(caps.filter((c) => c.box.checked).map((c) => c.cap));
          if ([...capList].sort().join() !== [...(m.capabilities || [])].sort().join()) body.capabilities = capList;
          if (briefing) {
            const text = briefing.value.trim();
            if ([...text].length > BRIEFING_CHARS) { fail(briefing, REFUSALS.string_too_long); return; }
            if (text !== (m.briefing || "")) body.briefing = text || null;
          }
          if (!Object.keys(body).length) { status.done(); append(status.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
          const said = { role: "role", reports_to: "reports to", areas: "areas", capabilities: "capabilities", briefing: "briefing" };
          const saved = await act("Saving", "Saved for " + m.display_name + ": " + Object.keys(body).map((k) => said[k]).join(", ") + ".",
            () => M.api.patch(memberPath, body), "role:" + m.id);
          // Demoting oneself changes what this page may offer: re-render it.
          if (saved && self && body.role) ctx.refresh();
        },
      },
      h("div", { class: "member-fields" },
        h("label", { for: id("role") }, "Role"), role,
        h("label", { for: id("reports") }, "Reports to"), reports,
        h("label", { for: id("areas") }, "Areas"), areas,
        h("p", { class: "hint", id: id("areas") + "-hint" }, "Repository paths this member owns, comma separated; cards in an area go to its narrowest owner."),
        h("span", { class: "label" }, "Capabilities"),
        h("div", { class: "member-caps" }, caps.map((c) => h("label", { class: "check", for: c.box.id }, c.box, " " + c.label))),
        briefing ? [h("label", { for: id("briefing") }, "Briefing (Markdown; the agent reads it at its next resume)"), briefing] : null),
      h("div", { class: "actions" }, h("button", { type: "submit" }, "Save changes")));
    }

    function nameCell(m) {
      // An agent's card is on the Agents view; one's own agent also has a chat.
      const mine = m.kind === "agent" && m.owner_id === ctx.me.id;
      return h("th", { scope: "row", role: "rowheader", "data-label": "Name" },
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
              const row = h("tr", { class: "member" + (m.paused ? " paused" : ""), role: "row" },
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
