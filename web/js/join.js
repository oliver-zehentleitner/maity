// Join an agent: create a join for one of the human's agent profiles (or a
// new one) and show the paste line once (docs/api.md §3.1). The line
// carries a single-use code; it is held in this view only, never stored,
// and gone when the view is left. Each join's state is derived from its
// fields, expiry against the clock while the view is open; only an open
// join can be revoked.
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

  M.views.join = async function (ctx, root) {
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
      maxlength: "31", autocomplete: "off", spellcheck: "false", "aria-describedby": "join-handle-rule" });
    const display = h("input", { id: "join-display", placeholder: "display name" });
    const newFields = h("div", { class: "new-agent", hidden: true },
      h("label", { for: "join-handle" }, "Handle"), handle, h("p", { class: "hint", id: "join-handle-rule" }, HANDLE.text),
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
    const briefing = h("textarea", {
      id: "join-briefing",
      rows: "5",
      placeholder: "What this agent is for and its first assignment, e.g. \"You review the hub's pull requests. "
        + "Start with the open ones under hub/ and tell me what blocks a merge.\"",
    });
    const ttl = h("select", { id: "join-ttl" },
      [[900, "15 minutes"], [1800, "30 minutes"], [3600, "1 hour"]].map(([v, l]) => h("option", { value: String(v) }, l)));

    const status = M.statusLine();
    const result = h("div", { class: "join-result", "aria-live": "polite" });

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
      append(clear(result), h("div", { class: "flag" },
        h("strong", null, "Paste this into the agent's session. It is shown once and expires " + formatTime(j.expires_at) + "."),
        h("p", null, line),
        h("p", { class: "first-hint" }, "Send it to the agent (Claude Code, Codex, …) as a message in its clone of the "
          + "repository; the agent runs it. An agent without the maity CLI opens the link and follows the join page. "
          + "You can also run it yourself in a terminal in that clone."),
        h("div", { class: "actions" }, h("button", { type: "button", onclick: () => clear(result) }, "Hide"), copy)));
    }

    const form = h("form", {
      class: "join-form",
      onsubmit: async (e) => {
        e.preventDefault();
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
        const body = {
          agent,
          role: role.value,
          reports_to: reportsTo.value || null,
          areas: areas.value.split(",").map((a) => a.trim()).filter(Boolean),
          capabilities: [],
          ttl_seconds: Number(ttl.value),
        };
        if (text) body.briefing = text;
        status.busy("Creating…");
        let j;
        try {
          j = await M.api.post(ctx.base + "/joins", body);
        } catch (err) {
          status.fail("No join created: ", err);
          return;
        }
        status.done();
        showLine(j);
        // A new profile is named in the list and offered in the select.
        try {
          [profiles, joins] = await Promise.all([M.api.getAll("/agents"), M.api.getAll(ctx.base + "/joins")]);
        } catch (err) {
          status.fail("Join created; the list could not be re-read: ", err);
          return;
        }
        profileOptions();
        agentSelect.value = j.agent_id;
        newFields.hidden = agentSelect.value !== "";
        drawJoins(joins);
      },
    },
    h("label", { for: "join-agent" }, "Agent"), agentSelect,
    newFields,
    h("label", { for: "join-role" }, "Role"), role,
    h("label", { for: "join-reports" }, "Reports to"), reportsTo,
    h("label", { for: "join-areas" }, "Areas (comma separated)"), areas,
    // Offered when the hub knows briefings: its member view then has the key.
    ctx.members.some((x) => "briefing" in x)
      ? [h("label", { for: "join-briefing" }, "Briefing (optional, Markdown)"), briefing,
        h("p", { class: "hint" }, "The agent reads it in its resume packet once it has joined, and on every resume "
          + "after; it is never on the join page. You can change it later on the agent's card.")]
      : null,
    h("label", { for: "join-ttl" }, "Valid for"), ttl,
    h("button", { type: "submit" }, "Create join line"),
    status.el);

    const listBox = h("div");
    let shownList = null;
    let shownKey = "";
    // One status line for the list, so a redraw keeps an error on screen.
    const listStatus = M.statusLine();
    const revocable = (j, state, now) => state.key === "open"
      || (state.key === "expired" && now - Date.parse(j.expires_at) < GRACE_MS);
    // What a redraw would change: the open set and the revocable set.
    const keyOf = (list, now) => list.items.map((j) => {
      const state = joinState(j, now);
      return j.id + ":" + state.key + (revocable(j, state, now) ? "+" : "");
    }).join(" ");
    async function reread() {
      try {
        drawJoins(await M.api.getAll(ctx.base + "/joins"));
      } catch (err) {
        listStatus.fail("The joins could not be read: ", err);
      }
    }
    function drawJoins(list) {
      shownList = list;
      const now = M.api.now();
      shownKey = keyOf(list, now);
      const rows = list.items.map((j) => ({ j, state: joinState(j, now) }));
      const open = rows.filter((r) => r.state.key === "open");
      const done = rows.filter((r) => r.state.key !== "open");
      const row = ({ j, state }) => h("li", { class: "join-" + state.key },
        h("span", { class: "badge join-state" }, state.label), " ",
        h("code", null, j.id), " " + profileName(j.agent_id) + " as " + j.role + " · " + state.text,
        revocable(j, state, now)
          ? h("button", {
                type: "button",
                class: "danger",
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
              }, "Revoke")
          : null);
      append(clear(listBox), h("h3", null, "Joins"),
        !rows.length ? h("p", { class: "muted" }, "No joins yet.") : null,
        open.length ? h("ul", { class: "joins open-joins", "aria-label": "Open joins" }, open.map(row)) : null,
        rows.length && !open.length ? h("p", { class: "muted" }, "No open join.") : null,
        done.length ? [h("h4", null, "No longer usable"), h("ul", { class: "joins closed-joins" }, done.map(row))] : null,
        listStatus.el);
    }
    drawJoins(joins);
    // A join that expires while the view is open moves down without a reload.
    ctx.every(EXPIRY_MS, () => { if (keyOf(shownList, M.api.now()) !== shownKey) drawJoins(shownList); });

    append(root, h("h2", null, "Join an agent"),
      h("p", { class: "muted" }, "The agent's session runs wherever you run it; it joins by the line you paste into it."),
      form, result, listBox);
  };
})(window.Maity);
