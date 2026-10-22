// Join an agent: create a join for one of the human's agent profiles (or a
// new one) and show the paste line once (docs/api.md §3.1). The line
// carries a single-use code; it is held in this view only, never stored,
// and gone when the view is left. Open joins can be revoked.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const ROLES = ["member", "reviewer", "proxy", "admin"];

  function joinState(j) {
    if (j.revoked_at) return "revoked " + formatTime(j.revoked_at);
    if (j.burned) return "burned";
    if (j.used_at) return "used " + formatTime(j.used_at);
    return "open until " + formatTime(j.expires_at);
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
    const handle = h("input", { id: "join-handle", placeholder: "handle, e.g. agent-e", pattern: "[a-z0-9][a-z0-9\\-]{1,30}" });
    const display = h("input", { id: "join-display", placeholder: "display name" });
    const newFields = h("div", { class: "new-agent", hidden: true },
      h("label", { for: "join-handle" }, "Handle"), handle,
      h("label", { for: "join-display" }, "Display name"), display);
    agentSelect.addEventListener("change", () => { newFields.hidden = agentSelect.value !== ""; });
    if (!profiles.items.length) newFields.hidden = false;

    const role = h("select", { id: "join-role" }, ROLES.map((r) => h("option", { value: r }, r)));
    const reportsTo = h("select", { id: "join-reports" },
      h("option", { value: "" }, "nobody"),
      ctx.members.map((m) => h("option", { value: m.id }, m.display_name)));
    const areas = h("input", { id: "join-areas", placeholder: "hub/, docs/" });
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
        h("p", { class: "first-hint" }, "Send it to the agent as a message (Claude Code, Codex, …) in its clone of the "
          + "repository; the agent runs it. An agent without the maity CLI opens the link and follows the join page. "
          + "You can also run it yourself in a terminal in that clone."),
        copy,
        h("button", { type: "button", onclick: () => clear(result) }, "Hide")));
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
          agent = { handle: handle.value.trim(), display_name: display.value.trim() || handle.value.trim() };
        }
        const body = {
          agent,
          role: role.value,
          reports_to: reportsTo.value || null,
          areas: areas.value.split(",").map((a) => a.trim()).filter(Boolean),
          capabilities: [],
          ttl_seconds: Number(ttl.value),
        };
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
    h("label", { for: "join-ttl" }, "Valid for"), ttl,
    h("button", { type: "submit" }, "Create join line"),
    status.el);

    const listBox = h("div");
    function drawJoins(list) {
      const listStatus = M.statusLine();
      append(clear(listBox), h("h3", null, "Joins"),
        list.items.length
          ? h("ul", { class: "joins" }, list.items.map((j) => h("li", null,
            h("code", null, j.id), " " + profileName(j.agent_id) + " as " + j.role + " · " + joinState(j),
            !j.used_at && !j.revoked_at && !j.burned
              ? h("button", {
                type: "button",
                class: "danger",
                onclick: async () => {
                  listStatus.busy("Revoking…");
                  try {
                    await M.api.del(ctx.base + "/joins/" + encodeURIComponent(j.id));
                    drawJoins(await M.api.getAll(ctx.base + "/joins"));
                  } catch (err) {
                    listStatus.fail("Not revoked: ", err);
                  }
                },
              }, "Revoke")
              : null)))
          : h("p", { class: "muted" }, "No joins yet."),
        listStatus.el);
    }
    drawJoins(joins);

    append(root, h("h2", null, "Join an agent"),
      h("p", { class: "muted" }, "The agent's session runs wherever you run it; it joins by the line you paste into it."),
      form, result, listBox);
  };
})(window.Maity);
