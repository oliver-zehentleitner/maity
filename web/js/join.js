// Joining an agent, inside the Agents view (js/agents.js): a panel that
// creates a join for one of the human's agent profiles (or a new one) and
// shows the paste line once (docs/api.md §3.1); the open joins as seats at
// the front of the agents' grid; the others folded at the view's end. The
// line carries a single-use code; it is held in the view only, never
// stored, and gone when the view is left. Each join's state is derived from
// its fields, expiry against the clock while the view is open; only an open
// join (or one expired within the grace minute) can be revoked.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  // Expiry emits no event; the list re-judges it on this interval, by the
  // hub's clock (M.api.now). A join expired less than GRACE_MS ago keeps
  // Revoke: what the hub still accepts must stay revocable, and the hub
  // decides.
  const EXPIRY_MS = 10000;
  const GRACE_MS = 60000;

  const ROLES = ["member", "reviewer", "proxy", "admin"];
  const BRIEFING_CHARS = 16 * 1024; // docs/api.md §3: 16 KiB, in characters as the hub counts

  // A join's state from GET /joins (docs/api.md §3.1), in the hub's order:
  // revoked, used, burned, then the clock.
  function joinState(j, now) {
    if (j.revoked_at) return { key: "revoked", label: "revoked", text: "revoked " + formatTime(j.revoked_at) };
    if (j.used_at) return { key: "used", label: "used", text: "used " + formatTime(j.used_at) };
    if (j.burned) return { key: "burned", label: "burned", text: "refused after three wrong codes" };
    if (Date.parse(j.expires_at) <= now) return { key: "expired", label: "expired", text: "expired " + formatTime(j.expires_at) };
    return { key: "open", label: "open", text: "open until " + formatTime(j.expires_at) };
  }

  // hooks.changed(): the seats and the earlier joins changed (a join made,
  // revoked, expired); the Agents view draws them again where they stand.
  async function mount(ctx, hooks) {
    let [profiles, joins] = await Promise.all([
      M.api.getAll("/agents"),
      M.api.getAll(ctx.base + "/joins"),
    ]);
    const profileName = (id) => {
      const p = profiles.items.find((x) => x.id === id);
      return p ? p.display_name : id;
    };

    const agentSelect = h("select", { id: "join-agent" });
    const profileOptions = () => append(clear(agentSelect),
      profiles.items.map((p) => h("option", { value: p.id }, p.display_name + " (@" + p.handle + ")"
        + (p.memberships.some((x) => x.project === ctx.slug) ? " · already a member" : ""))),
      h("option", { value: "" }, "A new agent profile…"));
    profileOptions();
    const HANDLE = M.dom.NAME_RULES.handle;
    const handle = h("input", { id: "join-handle", placeholder: "handle, e.g. agent-e", pattern: HANDLE.pattern,
      maxlength: "31", autocomplete: "off", spellcheck: "false", "aria-describedby": "join-handle-rule join-handle-state" });
    const display = h("input", { id: "join-display", placeholder: "display name" });
    // Free or taken while it is typed (docs/api.md §6.3: unique among one's
    // profiles that are not deleted, and GET /agents lists exactly those).
    // A hint only: the hub's answer to the join is the final word.
    const handleState = h("p", { class: "hint handle-state", id: "join-handle-state", role: "status" });
    // Handles the hub refused as taken: its word stands even when the list
    // on screen could not be read again and does not show the profile.
    const refused = new Set();
    const checkHandle = () => {
      const v = handle.value.trim();
      const taken = v && profiles.items.find((p) => !p.deleted_at && p.handle === v);
      const bad = !HANDLE.test.test(v);
      handleState.className = "hint handle-state" + (!v ? "" : bad || taken || refused.has(v) ? " field-error" : " ok");
      handleState.textContent = !v ? ""
        : bad ? "Not a handle yet: " + HANDLE.text
        : taken ? "Taken: your agent " + taken.display_name + " has @" + v + ". Choose it above, or another handle."
        : refused.has(v) ? "Taken: the hub says you already have an agent with @" + v + "."
        : "@" + v + " is free.";
    };
    handle.addEventListener("input", checkHandle);
    const newFields = h("div", { class: "new-agent", hidden: true },
      h("label", { for: "join-handle" }, "Handle"), handle, h("p", { class: "hint", id: "join-handle-rule" }, HANDLE.text),
      handleState,
      h("label", { for: "join-display" }, "Display name"), display);
    agentSelect.addEventListener("change", () => { newFields.hidden = agentSelect.value !== ""; });
    if (!profiles.items.length) newFields.hidden = false;

    const role = h("select", { id: "join-role" }, ROLES.map((r) => h("option", { value: r }, r)));
    const reportsTo = h("select", { id: "join-reports" },
      h("option", { value: "" }, "nobody"),
      ctx.members.map((m) => h("option", { value: m.id }, m.display_name)));
    const areas = h("input", { id: "join-areas", placeholder: "hub/, docs/" });
    // docs/api.md §3: the briefing reaches the agent in its resume packet
    // after the exchange, never on the join page.
    const briefing = M.dom.sendOnCtrlEnter(h("textarea", {
      id: "join-briefing",
      rows: "5",
      placeholder: "What this agent is for and its first assignment, e.g. \"You review the hub's pull requests. "
        + "Start with the open ones under hub/ and tell me what blocks a merge.\"",
    }));
    const ttl = h("select", { id: "join-ttl" },
      [[900, "15 minutes"], [1800, "30 minutes"], [3600, "1 hour"]].map(([v, l]) => h("option", { value: String(v) }, l)));

    const status = M.statusLine();
    // The panel's body: the form, or once a join is made the line in its place.
    const body = h("div", { class: "join-body", "aria-live": "polite" });
    const panel = h("section", { class: "join-panel", "aria-labelledby": "join-title", hidden: true });
    panel.hidden = true;

    function showLine(j) {
      const line = h("code", { class: "paste-line" }, j.paste_line);
      const copy = h("button", {
        type: "button",
        onclick: async () => {
          try {
            await navigator.clipboard.writeText(j.paste_line);
            copy.textContent = "Copied";
          } catch (err) {
            copy.textContent = "Copy failed — select the line";
          }
        },
      }, "Copy");
      const again = h("button", { type: "button", onclick: () => { showForm(); agentSelect.focus(); } }, "Join another");
      append(clear(body), h("div", { class: "join-result" },
        h("p", null, h("strong", null, "Paste this into the agent's session. It is shown once and expires " + formatTime(j.expires_at) + ".")),
        h("div", { class: "paste-row" }, line, copy),
        h("p", { class: "first-hint" }, "Send it to the agent (Claude Code, Codex, …) as a message in its clone of the "
          + "repository; the agent runs it. An agent without the maity CLI opens the link and follows the join page. "
          + "You can also run it yourself in a terminal in that clone. Until then it waits below as an open seat."),
        h("div", { class: "actions" }, again, h("button", { type: "button", class: "primary", onclick: () => close(true) }, "Done"))));
      copy.focus();
    }

    // Held while a join is being created: one join per submission, by click or Ctrl+Enter.
    const create = h("button", { type: "submit", class: "primary" }, "Create join line");
    const form = h("form", {
      class: "join-form",
      onsubmit: async (e) => {
        e.preventDefault();
        if (create.disabled) return;
        let agent;
        if (agentSelect.value) {
          agent = { id: agentSelect.value };
        } else {
          if (!handle.value.trim()) { handle.focus(); return; }
          if (!HANDLE.test.test(handle.value.trim())) {
            status.fail("No join created: ", { message: "the handle: " + HANDLE.text });
            handle.focus();
            return;
          }
          agent = { handle: handle.value.trim(), display_name: display.value.trim() || handle.value.trim() };
        }
        const text = briefing.value.trim();
        if ([...text].length > BRIEFING_CHARS) {
          status.fail("No join created: ", { message: "the briefing is longer than 16,384 characters" });
          briefing.focus();
          return;
        }
        const req = {
          agent,
          role: role.value,
          reports_to: reportsTo.value || null,
          areas: areas.value.split(",").map((a) => a.trim()).filter(Boolean),
          capabilities: [],
          ttl_seconds: Number(ttl.value),
        };
        if (text) req.briefing = text;
        status.busy("Creating…");
        create.disabled = true;
        let j;
        try {
          j = await M.api.post(ctx.base + "/joins", req);
        } catch (err) {
          const why = err.code === "invalid" && err.details && err.details.fields && err.details.fields.handle;
          status.fail("No join created: ", why === "taken" ? { message: "you already have an agent with the handle @" + agent.handle } : err);
          if (why) {
            // The hub knows better than the list on screen: read it again, and say so at the field.
            if (why === "taken") refused.add(agent.handle);
            try { profiles = await M.api.getAll("/agents"); } catch (ignored) { /* the refusal above says enough */ }
            profileOptions();
            agentSelect.value = "";
            checkHandle();
            handle.focus();
          }
          return;
        } finally {
          create.disabled = false;
        }
        status.done();
        showLine(j);
        // A new profile is named in the select, the new join is a seat.
        try {
          [profiles, joins] = await Promise.all([M.api.getAll("/agents"), M.api.getAll(ctx.base + "/joins")]);
        } catch (err) {
          listStatus.fail("Join created; the list could not be re-read: ", err);
          return;
        }
        profileOptions();
        agentSelect.value = j.agent_id;
        newFields.hidden = agentSelect.value !== "";
        // The handle just created is one's own now: the hint says so.
        checkHandle();
        changed();
      },
    },
    h("div", { class: "join-columns" },
      h("div", { class: "join-fields" },
        h("div", { class: "field wide" }, h("label", { for: "join-agent" }, "Agent"), agentSelect),
        newFields,
        h("div", { class: "field" }, h("label", { for: "join-role" }, "Role"), role),
        h("div", { class: "field" }, h("label", { for: "join-reports" }, "Reports to"), reportsTo),
        h("div", { class: "field" }, h("label", { for: "join-areas" }, "Areas (comma separated)"), areas),
        h("div", { class: "field" }, h("label", { for: "join-ttl" }, "Valid for"), ttl)),
      // Offered when the hub knows briefings: its member view then has the key.
      ctx.members.some((x) => "briefing" in x)
        ? h("div", { class: "join-briefing" },
          h("label", { for: "join-briefing" }, "Briefing (optional, Markdown; " + M.dom.SEND_KEYS + " creates the link)"), briefing,
          h("p", { class: "hint" }, "The agent reads it in its resume packet once it has joined, and on every resume "
            + "after; it is never on the join page. You can change it later on the agent's card."))
        : null),
    h("div", { class: "actions" }, h("button", { type: "button", onclick: () => close(true) }, "Cancel"), create),
    status.el);

    function showForm() { append(clear(body), form); }
    showForm();
    const closeButton = h("button", { type: "button", class: "icon-button join-close", "aria-label": "Close", title: "Close", onclick: () => close(true) }, "×");
    append(panel,
      h("div", { class: "join-head" },
        h("h3", { id: "join-title" }, "Join an agent"), closeButton),
      h("p", { class: "muted" }, "The agent's session runs wherever you run it; it joins by the line you paste into it."),
      body);

    let opener = null;
    function open(from) {
      opener = from || null;
      panel.hidden = false;
      if (hooks.opened) hooks.opened(true);
      agentSelect.focus();
    }
    function close(refocus) {
      panel.hidden = true;
      showForm();
      if (hooks.opened) hooks.opened(false);
      if (refocus && opener && opener.focus) opener.focus();
    }

    // Seats and earlier joins, drawn by the Agents view where they stand.
    const listStatus = M.statusLine();
    let shownKey = "";
    const revocable = (j, state, now) => state.key === "open"
      || (state.key === "expired" && now - Date.parse(j.expires_at) < GRACE_MS);
    // What a redraw would change: the open set and the revocable set.
    const keyOf = (list, now) => list.items.map((j) => {
      const state = joinState(j, now);
      return j.id + ":" + state.key + (revocable(j, state, now) ? "+" : "");
    }).join(" ");
    function changed() {
      shownKey = keyOf(joins, M.api.now());
      hooks.changed();
    }
    // Leaves the status line alone: a refusal said just before stays said.
    async function reread() {
      try {
        joins = await M.api.getAll(ctx.base + "/joins");
      } catch (err) {
        listStatus.fail("The joins could not be read: ", err);
        return;
      }
      changed();
    }
    const profileOf = (id) => profiles.items.find((x) => x.id === id) || null;
    function revoke(j) {
      return h("button", {
        type: "button",
        class: "danger",
        "aria-label": "Revoke the join for " + profileName(j.agent_id),
        onclick: async () => {
          listStatus.busy("Revoking…");
          try {
            await M.api.del(ctx.base + "/joins/" + encodeURIComponent(j.id));
            listStatus.done();
            await reread();
          } catch (err) {
            listStatus.fail("Not revoked: ", err);
            // Used, burned or expired meanwhile: show it as the hub has it.
            if (err.code === "invalid_transition") await reread();
          }
        },
      }, "Revoke");
    }
    // An open join is a member who has not arrived yet: a seat in the grid.
    function seats() {
      const now = M.api.now();
      return joins.items.map((j) => ({ j, state: joinState(j, now) }))
        .filter(({ j, state }) => revocable(j, state, now))
        .map(({ j, state }) => {
          const p = profileOf(j.agent_id);
          return h("article", { class: "profile seat join-" + state.key, "aria-label": "Open seat: " + profileName(j.agent_id), "data-join": j.id },
            h("header", null,
              h("span", { class: "seat-mark", "aria-hidden": "true" }),
              h("h3", null, profileName(j.agent_id)),
              p ? h("span", { class: "handle" }, "@" + p.handle) : null,
              h("span", { class: "seat-label" }, state.key === "open" ? "open seat" : "expired")),
            h("dl", { class: "facts" },
              h("dt", null, "Role"), h("dd", null, j.role, j.reports_to ? " · reports to " + ctx.nameOf(j.reports_to) : null),
              h("dt", null, "Join"), h("dd", null, state.text + " · ", h("code", null, j.id))),
            h("p", { class: "muted" }, "Waiting for the agent to run its line."),
            h("div", { class: "seat-actions" }, revoke(j)));
        });
    }
    // The record: used, burned, revoked, expired past the grace minute.
    function earlier() {
      const now = M.api.now();
      const rows = joins.items.map((j) => ({ j, state: joinState(j, now) })).filter(({ j, state }) => !revocable(j, state, now));
      if (!rows.length) return null;
      return h("details", { class: "earlier-joins" },
        h("summary", null, "Earlier joins (" + rows.length + "): used, expired or revoked"),
        h("ul", { class: "joins closed-joins" }, rows.map(({ j, state }) => h("li", { class: "join-" + state.key },
          h("span", { class: "badge join-state" }, state.label), " ",
          h("code", null, j.id), " " + profileName(j.agent_id) + " as " + j.role + " · " + state.text))));
    }
    const openCount = () => { const now = M.api.now(); return joins.items.filter((j) => joinState(j, now).key === "open").length; };

    shownKey = keyOf(joins, M.api.now());
    // A join that expires while the view is open moves on without a reload.
    ctx.every(EXPIRY_MS, () => { if (keyOf(joins, M.api.now()) !== shownKey) changed(); });

    return { panel, open, close, seats, earlier, openCount, listStatus };
  }

  M.join = { mount };
  // #/p/<slug>/join, from before joining moved into Agents: the same place, panel open.
  M.views.join = async function (ctx, root) {
    const there = "#/p/" + encodeURIComponent(ctx.slug) + "/agents/join";
    if (window.history && window.history.replaceState) window.history.replaceState(null, "", there);
    await M.views.agents(ctx, root, ["join"]);
  };
})(window.Maity);
