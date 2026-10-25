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
  // The hub's refusals in words, by field and reason; a reason the page
  // does not know is shown as it comes.
  const REFUSALS = {
    "role:last_owner": "The project's last owner cannot be demoted or removed.",
    "member:last_owner": "The project's last owner cannot be demoted or removed.",
    "role:owner_is_human": "Only a human can be an owner.",
    "role:unknown": "Not a role of this hub.",
    "reports_to:cycle": "That would close a circle: they would end up reporting to themselves.",
    "reports_to:not_a_member": "Reports to someone who is not a member of this project.",
    "areas:invalid_path": "An area is a repository path like hub/ or docs/api.md, without ..",
    "areas:too_long": "At most 50 areas.",
    "capabilities:unknown": "A capability this hub does not know.",
    "capabilities:too_long": "At most 20 capabilities.",
    "paused.reason:string_too_long": "The pause's reason is too long.",
  };
  const CYCLE = REFUSALS["reports_to:cycle"];
  const BAD_AREA = REFUSALS["areas:invalid_path"];
  // The hub's rules for an area (hub/src/maity_hub/routes/members.py).
  const AREA = /^[A-Za-z0-9._/-]{1,255}$/;
  const areaOk = (a) => AREA.test(a) && !a.startsWith("..") && !("/" + a + "/").includes("/../");
  const CAPABILITIES = [["tag", "May tag a release (tag)"]];

  // The hub names each bad field (details.fields); said in words.
  function refusal(err) {
    if (err.code === "forbidden" && err.details && err.details.reason === "humans_only") {
      return { message: "only a human may make this change" };
    }
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (!fields) return err;
    const said = Object.entries(fields).map(([f, reason]) => REFUSALS[f + ":" + reason] || f.replace("_", " ") + ": " + reason);
    return { message: said.join(" ") };
  }

  // A change an agent's rule holds for a human's go answers 202 with the
  // consent request (docs/api.md §2.3), not with the member.
  const isConsent = (answer) => !!answer && answer.class === "consent" && /^req-/.test(answer.id || "");

  function credentialsText(c) {
    if (!c) return "—";
    const parts = [c.active + " active"];
    if (c.never_resumed) parts.push(c.never_resumed + " never used");
    if (c.revoked_recent) parts.push(c.revoked_recent + " revoked in the last 30 days");
    if (c.last_used_at) parts.push("last used " + formatAgo(c.last_used_at) + (c.last_used_via === "bearer" ? " (bearer token)" : ""));
    return parts.join(" · ");
  }

  // A presence the page knows gets its dot; anything else is said as it comes.
  function presenceNodes(m, warn) {
    const known = Object.prototype.hasOwnProperty.call(PRESENCE_LABELS, m.presence);
    return [known ? h("span", { class: "dot " + m.presence, "aria-hidden": "true" }) : null, known ? " " : null,
      known ? PRESENCE_LABELS[m.presence] : String(m.presence || "unknown"),
      M.dom.isSilentAgent(m) ? [" · ", M.dom.silentSince(m, warn)]
        : m.last_seen_at && m.presence !== "online" ? h("span", { class: "muted" }, " · seen " + formatAgo(m.last_seen_at)) : null];
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

    // Who paused it is a member like any other: a link to them.
    function pausedText(m) {
      const p = m.paused;
      if (!p) return "";
      const by = p.by === m.id ? "paused itself" : ["paused by ", M.dom.memberRef(ctx, p.by)];
      return [by, " " + formatAgo(p.since) + (p.reason ? ": " + p.reason : "")];
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
    // `settled` runs once the hub has taken the call (a change or a consent
    // request), before the list is read again and drawn. The outcome is said
    // once the list is drawn again, so "Saved" means the rows show it and
    // nothing is replaced under the next click.
    async function act(label, done, call, focusKey, settled) {
      status.busy(label + "…");
      let answer;
      try {
        answer = await call();
      } catch (err) {
        status.fail(label + " failed: ", refusal(err));
        return false;
      }
      if (settled) settled();
      try {
        await reload();
        redraw(focusKey);
      } catch (err) {
        status.fail(done + " Could not refresh: ", err);
        return isConsent(answer) ? "consent" : true;
      }
      status.done();
      // Waiting for a human's go is no change yet: said as such.
      append(status.el, isConsent(answer)
        ? h("span", { class: "flag" }, "Not changed yet: waiting for " + (answer.to === "owner" ? "the owner" : ctx.nameOf(answer.to))
          + "'s consent (" + answer.id + (answer.title ? ", " + answer.title : "") + ").")
        : h("span", { class: "ok" }, done));
      return isConsent(answer) ? "consent" : true;
    }

    function manage(m, rowId) {
      const memberPath = ctx.base + "/members/" + encodeURIComponent(m.id);
      const self = m.id === ctx.me.id;
      const parts = [editForm(m, memberPath, self)];
      if (m.kind === "agent") {
        const reasonId = "member-pause-" + m.id;
        const reason = keyed("reason:" + m.id, h("input", { id: reasonId, placeholder: "Why it stops, e.g. quota", autocomplete: "off" }));
        reason.value = (edits.get(m.id) || {}).reason || "";
        reason.addEventListener("input", () => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { reason: reason.value })); });
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
              act("Pausing", m.display_name + " is paused.", () => M.api.patch(memberPath, { paused: { reason: reason.value.trim() } }), "unpause:" + m.id,
                () => { const d = edits.get(m.id); if (d) delete d.reason; });
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
    // The rows' unsaved edits, by member id: a redraw (an action elsewhere,
    // the presence refresh) rebuilds the form from them, not from the member.
    const edits = new Map();

    function editForm(m, memberPath, self) {
      const id = (what) => "member-" + what + "-" + m.id;
      const draft = edits.get(m.id) || {};
      const keep = (k, v) => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { [k]: v })); };
      const role = keyed("role:" + m.id, h("select", { id: id("role") },
        ROLES.filter((r) => r !== "owner" || m.kind === "human").map((r) => h("option", { value: r }, r))));
      role.value = draft.role !== undefined ? draft.role : m.role;
      // The current boss stays offered even if it is not in the list read.
      const others = items.filter((x) => x.id !== m.id);
      const listed = !m.reports_to || others.some((x) => x.id === m.reports_to);
      const reports = keyed("reports:" + m.id, h("select", { id: id("reports") }, h("option", { value: "" }, "nobody"),
        others.map((x) => h("option", { value: x.id }, x.display_name + " (@" + x.handle + ")")),
        listed ? null : h("option", { value: m.reports_to }, nameOf(m.reports_to) + " (not in this list)")));
      reports.value = m.reports_to || "";
      // A drafted boss who has left since is dropped, and said: a select that
      // fell back to "nobody" would clear the member's boss on the next save.
      let bossGone = null;
      if (draft.reports !== undefined) {
        if (!draft.reports || others.some((x) => x.id === draft.reports) || draft.reports === m.reports_to) reports.value = draft.reports;
        else { bossGone = nameOf(draft.reports); delete draft.reports; }
      }
      const areas = keyed("areas:" + m.id, h("input", { id: id("areas"), placeholder: "hub/, docs/", autocomplete: "off", spellcheck: "false" }));
      areas.value = draft.areas !== undefined ? draft.areas : (m.areas || []).join(", ");
      const caps = CAPABILITIES.map(([cap, label]) => {
        const box = h("input", { type: "checkbox", id: id("cap-" + cap) });
        box.checked = draft["cap:" + cap] !== undefined ? draft["cap:" + cap] : (m.capabilities || []).includes(cap);
        box.addEventListener("change", () => keep("cap:" + cap, box.checked));
        return { cap, box, label };
      });
      role.addEventListener("change", () => keep("role", role.value));
      reports.addEventListener("change", () => keep("reports", reports.value));
      areas.addEventListener("input", () => keep("areas", areas.value));
      // Each field says its own error, tied to it (as on the account view).
      const errorOf = (what) => h("p", { class: "field-error", id: id(what) + "-error", role: "alert" });
      const errors = { role: errorOf("role"), reports: errorOf("reports"), areas: errorOf("areas") };
      if (bossGone) errors.reports.textContent = bossGone + ", whom you picked, is no longer a member; reports to is back to what it is.";
      [[role, "role"], [reports, "reports"], [areas, "areas"]].forEach(([f, k]) => f.setAttribute("aria-describedby", id(k) + "-error"
        + (k === "areas" ? " " + id("areas") + "-hint" : "")));
      const clearErrors = () => [[role, "role"], [reports, "reports"], [areas, "areas"]].forEach(([f, k]) => { errors[k].textContent = ""; f.removeAttribute("aria-invalid"); });
      const fieldFail = (f, k, text) => { errors[k].textContent = text; f.setAttribute("aria-invalid", "true"); status.fail("Not saved: ", { message: text }); f.focus(); };
      const save = h("button", { type: "submit" }, "Save changes");
      return h("form", {
        class: "member-edit",
        onsubmit: async (e) => {
          e.preventDefault();
          if (save.disabled) return;
          clearErrors();
          const body = {};
          if (role.value !== m.role) body.role = role.value;
          const boss = reports.value || null;
          if (boss !== (m.reports_to || null)) {
            if (boss && closesCircle(m, boss)) { fieldFail(reports, "reports", CYCLE); return; }
            body.reports_to = boss;
          }
          const list = [...new Set(areas.value.split(",").map((a) => a.trim()).filter(Boolean))];
          if (list.some((a) => !areaOk(a))) { fieldFail(areas, "areas", BAD_AREA); return; }
          if (list.join("\n") !== (m.areas || []).join("\n")) body.areas = list;
          // Capabilities this page does not offer are kept as they are.
          const kept = (m.capabilities || []).filter((c) => !CAPABILITIES.some(([k]) => k === c));
          const capList = kept.concat(caps.filter((c) => c.box.checked).map((c) => c.cap));
          if ([...capList].sort().join() !== [...(m.capabilities || [])].sort().join()) body.capabilities = capList;
          if (!Object.keys(body).length) { status.done(); append(status.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
          const said = { role: "role", reports_to: "reports to", areas: "areas", capabilities: "capabilities" };
          save.disabled = true;
          const saved = await act("Saving", "Saved for " + m.display_name + ": " + Object.keys(body).map((k) => said[k]).join(", ") + ".",
            () => M.api.patch(memberPath, body), "role:" + m.id, () => edits.delete(m.id));
          save.disabled = false;
          // Demoting oneself changes what this page may offer: re-render it.
          if (saved === true && self && body.role) ctx.refresh();
        },
      },
      h("div", { class: "member-fields" },
        h("label", { for: id("role") }, "Role"), role, errors.role,
        h("label", { for: id("reports") }, "Reports to"), reports, errors.reports,
        h("label", { for: id("areas") }, "Areas"), areas,
        h("p", { class: "hint", id: id("areas") + "-hint" }, "Repository paths this member owns, comma separated; cards in an area go to its narrowest owner."),
        errors.areas,
        h("fieldset", { class: "member-caps" }, h("legend", null, "Capabilities"),
          caps.map((c) => h("label", { class: "check", for: c.box.id }, c.box, " " + c.label))),
        // One briefing editor: on the agent's card.
        m.kind === "agent" && "briefing" in m
          ? h("p", { class: "muted member-briefing" }, "The briefing is edited on ", h("a", { href: ctx.link("agents") }, "the agent's card"),
            m.briefing_by ? " · set by @" + m.briefing_by.handle : "", ".")
          : null),
      h("div", { class: "actions" }, save));
    }

    function nameCell(m) {
      // An agent's card is on the Agents view; one's own agent also has a chat.
      const mine = m.kind === "agent" && m.owner_id === ctx.me.id;
      return h("th", { scope: "row", role: "rowheader", "data-label": "Name", tabindex: m.id === wanted ? "-1" : null },
        h("span", { class: "member-name" }, M.dom.memberRef(ctx, m.id)), h("span", { class: "muted" }, " @" + m.handle),
        m.kind === "human" && !m.removed_at && m.language
          ? h("p", { class: "muted member-language" }, "Language: " + (m.language === "de" ? "Deutsch" : "English")) : null,

        m.kind === "agent" && m.briefing != null && ctx.project.settings && "onboarding" in ctx.project.settings
          ? h("span", { class: "badge briefing-override", title: "This member uses its own briefing instead of the project default." }, "Own briefing") : null,
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
                    // Done closes the row and drops its unsaved edits.
                    if (open.has(m.id)) { open.delete(m.id); edits.delete(m.id); redraw("manage:" + m.id); } else { open.add(m.id); redraw("role:" + m.id); }
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
      const presence = { title: "Presence", presence: true, cell: (m) => presenceNodes(m, ctx.canAdmin) };
      const joined = { title: "Joined", cell: (m) => formatTime(m.joined_at) };
      const owner = { title: "Owner", cell: (m) => M.dom.memberRef(ctx, m.owner ? Object.assign({ member_id: m.owner_id }, m.owner) : m.owner_id) };
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
        fresh.forEach((m) => { const td = presenceCells.get(m.id); if (td) append(clear(td), presenceNodes(m, ctx.canAdmin)); });
        status.done();
      } catch (err) {
        status.fail("Could not refresh: ", err);
      }
    });
  };
})(window.Maity);
