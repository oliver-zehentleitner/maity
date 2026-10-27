// (3) Agents and presence: profile, human owner, role, areas, live
// session, presence as the hub computes it, paused reason; credentials as
// id, dates and a revoke button, never their value. A human with
// members:admin pauses an agent that cannot say so itself.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const PRESENCE_LABELS = { online: "Online", away: "Away", offline: "Offline", paused: "Paused" };

  // Presence is computed by the hub on every read and emits no event
  // (docs/api.md §5.3); the view re-reads it on this interval, in place.
  const PRESENCE_MS = 30000;

  function presenceNodes(m) {
    const label = PRESENCE_LABELS[m.presence] || m.presence;
    return {
      dot: h("span", { class: "dot " + m.presence, "aria-hidden": "true" }),
      label: h("span", { class: "presence " + m.presence }, label),
      seen: h("dd", null, formatAgo(m.last_seen_at)),
    };
  }

  // How a credential was last used (docs/api.md §10): what signing:
  // required would refuse is the bearer kind.
  const VIA = { signed: "(signed)", bearer: "(bearer token)" };

  function credentials(ctx, m, list) {
    const box = h("div", { class: "credentials" }, h("h4", null, "Credentials"));
    if (!list.items.length) {
      append(box, h("p", { class: "muted" }, "None."));
      return box;
    }
    const status = M.statusLine();
    // Active ones first, as the hub lists them; revoked ones stay visible.
    // The text flows as one line that wraps; the button stays beside it.
    append(box, h("ul", null, list.items.map((c) => h("li", { class: c.revoked_at ? "revoked" : "" },
      h("span", { class: "credential-text" },
        h("code", null, c.id),
        " " + (c.client || "") + " · created " + formatTime(c.created_at),
        c.revoked_at
          ? h("span", { class: "muted" }, " · revoked " + formatTime(c.revoked_at) + " by ", M.dom.memberRef(ctx, c.revoked_by),
            c.revoked_reason ? " (" + c.revoked_reason + ")" : "")
          : (c.resumed_at
            ? h("span", null, " · last used " + formatAgo(c.last_used_at)
              + (c.last_used_via ? " " + (VIA[c.last_used_via] || "(" + c.last_used_via + ")") : ""))
            : h("span", { class: "never" }, " · never resumed"))),
      c.revoked_at
        ? null
        : [
          h("button", {
            type: "button",
            class: "danger",
            onclick: async (e) => {
              if (!window.confirm("Revoke " + c.id + " of " + m.display_name + "? Its session loses access at once.")) return;
              e.target.disabled = true;
              status.busy("Revoking…");
              try {
                await M.api.post(ctx.base + "/credentials/" + encodeURIComponent(c.id) + "/revoke", {});
                ctx.refresh();
              } catch (err) {
                e.target.disabled = false;
                status.fail("Not revoked: ", err);
              }
            },
          }, "Revoke"),
        ]))), status.el);
    return box;
  }

  // What a pause by a human does (docs/api.md §5.3), in one line.
  const PAUSE_EFFECT = "A pause tells the agent at once and refuses it new work (claims, new cards); "
    + "it can still checkpoint, report, give a card back and talk to you.";
  const PAUSED_EFFECT = "The agent was told at once and gets no new work (claims, new cards); "
    + "it can still checkpoint, report, give a card back and talk to you.";

  // The briefing (docs/api.md §6.2): shown to members:admin, edited in
  // place. The view re-reads presence in place, so an open editor stays.
  const BRIEFING_CHARS = 16 * 1024;
  function briefingControl(ctx, m) {
    const box = h("div", { class: "briefing" });
    const status = M.statusLine();
    const show = () => {
      M.dom.clear(box);
      append(box, h("h4", null, "Briefing"),
        m.briefing ? h("p", { class: "pre" }, m.briefing) : h("p", { class: "muted" }, "No briefing yet."),
        // Who wrote the current text, where the hub says (docs/api.md §6.2).
        m.briefing && m.briefing_by ? h("p", { class: "muted" }, "Set by @" + m.briefing_by.handle
          + (m.briefing_version ? " · version " + m.briefing_version : "")) : null,
        h("button", { type: "button", class: "small", onclick: edit }, m.briefing ? "Edit briefing" : "Write a briefing"),
        status.el);
    };
    box.edit = () => edit();
    box.hasText = () => !!m.briefing;
    const edit = () => {
      const id = "briefing-" + m.id;
      const text = M.dom.sendOnCtrlEnter(h("textarea", { id, rows: "6" }));
      text.value = m.briefing || "";
      const saveButton = h("button", { type: "submit" }, "Save briefing");
      const save = async (e) => {
        e.preventDefault();
        if (saveButton.disabled) return;
        // Markdown keeps its spaces: only line ends are made the same; a
        // briefing of nothing but space is no briefing.
        const value = text.value.replace(/\r\n?/g, "\n");
        if ([...value].length > BRIEFING_CHARS) {
          status.fail("Not saved: ", { message: "the briefing is longer than 16,384 characters" });
          return;
        }
        status.busy("Saving…");
        // Held while it is saved: one PATCH per submission, by click or Ctrl+Enter.
        saveButton.disabled = true;
        try {
          const updated = await M.api.patch(ctx.base + "/members/" + encodeURIComponent(m.id), { briefing: value.trim() ? value : null });
          m.briefing = updated && "briefing" in updated ? updated.briefing : (value.trim() ? value : null);
          ["briefing_by", "briefing_version", "briefing_updated_at"].forEach((k) => { if (updated && k in updated) m[k] = updated[k]; });
          status.done();
          show();
        } catch (err) {
          status.fail("Not saved: ", err);
        } finally {
          saveButton.disabled = false;
        }
      };
      M.dom.clear(box);
      append(box, h("form", { class: "briefing-form", onsubmit: save },
        h("label", { for: id }, "Briefing (Markdown, at most 16,384 characters; " + M.dom.SEND_KEYS + " saves)"), text,
        h("p", { class: "hint" }, "The agent reads it at its next resume."),
        h("div", { class: "row" },
          h("button", { type: "button", onclick: show }, "Cancel"),
          saveButton),
        status.el));
      text.focus();
    };
    show();
    return box;
  }

  function pauseControl(ctx, m) {
    const status = M.statusLine();
    const save = async (paused) => {
      status.busy("Saving…");
      try {
        await M.api.patch(ctx.base + "/members/" + encodeURIComponent(m.id), { paused });
        ctx.refresh();
      } catch (err) {
        status.fail("Not saved: ", err);
      }
    };
    if (m.paused) {
      return h("div", { class: "pause" },
        h("button", { type: "button", onclick: () => save(null) }, "Clear pause"), status.el);
    }
    const id = "pause-" + m.id;
    const reason = h("input", { id, placeholder: "Why it stopped" });
    // Folded until Pause… in the card's Actions menu opens it (the
    // designer's pass part 3): an open form on every card made each one twice
    // as long.
    const form = h("form", {
      class: "pause",
      onsubmit: (e) => {
        e.preventDefault();
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ reason: reason.value.trim() });
      },
    },
    h("label", { for: id }, "Pause"), reason, h("button", { type: "submit" }, "Pause"),
    h("button", { type: "button", onclick: () => { form.hidden = true; reason.value = ""; } }, "Cancel"),
    h("p", { class: "hint" }, PAUSE_EFFECT), status.el);
    form.hidden = true;
    form.openPause = () => { form.hidden = false; reason.focus(); };
    return form;
  }

  // The card's Actions menu (the designer's pass part 3): what an admin
  // does to the agent, folded into one control in the card's header.
  function actionsMenu(pause, briefing) {
    const items = () => [
      pause && pause.openPause ? { label: "Pause…", onSelect: pause.openPause } : null,
      briefing && briefing.edit ? { label: briefing.hasText() ? "Edit briefing" : "Write a briefing", onSelect: briefing.edit } : null,
    ].filter(Boolean);
    if (!items().length) return null;
    return M.menuButton({ label: "Actions", class: "agent-actions", face: ["Actions ", h("span", { "aria-hidden": "true" }, "▾")], items }).el;
  }

  // One failing credentials call costs that card its credentials section,
  // not the view.
  function loadCredentials(ctx, m) {
    return M.api.getAll(ctx.base + "/members/" + encodeURIComponent(m.id) + "/credentials")
      .then((list) => ({ list }), (error) => ({ error }));
  }

  // Shared with the Members view.
  M.pauseWords = { effect: PAUSE_EFFECT, paused: PAUSED_EFFECT };

  M.views.agents = async function (ctx, root, args) {
    const agents = ctx.members.filter((m) => m.kind === "agent");
    const creds = await Promise.all(agents.map((m) => loadCredentials(ctx, m)));
    const online = agents.filter((m) => m.presence === "online").length;

    // Joining lives here (docs/api.md §3.1, js/join.js): the panel under the
    // title, the open joins as seats at the front of the grid, the others
    // folded at the end. Only for those who may create joins.
    const grid = h("div", { class: "profiles" });
    const earlierBox = h("div", { class: "earlier-box" });
    const countLine = h("p", { class: "muted agents-count" });
    const joinButton = h("button", { type: "button", class: "primary join-open" }, "+ Join an agent");
    let J = null;
    const drawCount = () => {
      const open = J ? J.openCount() : 0;
      countLine.textContent = agents.length + (agents.length === 1 ? " agent" : " agents") + " · " + online + " online"
        + (J ? " · " + open + (open === 1 ? " open join" : " open joins") : "");
    };
    let cards = [];
    const drawGrid = () => {
      append(clear(grid), J ? J.seats() : null, cards);
      append(clear(earlierBox), J ? J.earlier() : null);
      drawCount();
    };
    if (ctx.canAdmin && M.join) {
      J = await M.join.mount(ctx, {
        changed: drawGrid,
        opened: (yes) => { joinButton.hidden = yes; if (!yes) joinButton.focus(); },
      });
      joinButton.addEventListener("click", () => J.open(joinButton));
    }

    // An agent running its line takes its seat: the view redraws with its
    // card, unless the panel is open; then only the seats move and the app's
    // reload flag stands.
    if (J) {
      ctx.onEvents((events) => {
        if (!events.some((e) => e.kind === "member_joined")) return;
        if (J.busy()) J.reread();
        else ctx.refresh();
      });
    }

    append(root, h("div", { class: "toolbar agents-head" }, h("h2", null, "Agents"), J ? joinButton : null),
      countLine, J ? [J.panel, J.listStatus.el] : null);
    // Where they run (js/placements.js), where the hub has placements: after
    // the grid, before the record of earlier joins — also with no agent
    // yet, when a placement that creates its profile is all there is.
    // Not awaited: the view shows at once and the section joins it when
    // read, so neither the grid nor the join panel waits for the runners.
    const placements = () => {
      if (!M.placements) return;
      const credsOf = Object.fromEntries(agents.map((m, i) => [m.id, (creds[i].list && creds[i].list.items) || []]));
      M.placements.section(ctx, credsOf).then((placed) => { if (placed && earlierBox.parentNode === root) root.insertBefore(placed, earlierBox); });
    };
    // No agents yet: the panel opens, and the way in is said.
    if (!agents.length) {
      append(root, h("p", { class: "muted" }, "No agents in this project yet.", J ? " Join one: its line is made here." : ""), grid, earlierBox);
      drawGrid();
      if (J) J.open(joinButton);
      placements();
      return;
    }

    const live = {};
    const presenceStatus = M.statusLine();
    ctx.every(PRESENCE_MS, async () => {
      try {
        const fresh = await M.api.get(ctx.base + "/members");
        fresh.items.forEach((f) => {
          const n = live[f.id];
          if (!n) return;
          n.dot.className = "dot " + f.presence;
          n.label.className = "presence " + f.presence;
          n.label.textContent = PRESENCE_LABELS[f.presence] || f.presence;
          n.seen.textContent = formatAgo(f.last_seen_at);
        });
        presenceStatus.done();
      } catch (err) {
        presenceStatus.fail("Presence could not be refreshed: ", err);
      }
    });

    cards = agents.map((m, i) => {
        const mine = m.owner_id === ctx.me.id;
        const s = m.session;
        const p = presenceNodes(m);
        live[m.id] = p;
        const pause = ctx.canAdmin ? pauseControl(ctx, m) : null;
        // A hub that does not know briefings yet has no such key.
        const briefing = ctx.canAdmin && m.kind === "agent" && "briefing" in m ? briefingControl(ctx, m) : null;
        return h("article", { class: "profile", "aria-label": m.display_name },
          h("header", null,
            M.avatar(m, 28),
            p.dot,
            h("h3", null, M.dom.memberRef(ctx, m.id)),
            h("span", { class: "handle" }, "@" + M.dom.handleOf(ctx, m)),
            p.label,
            actionsMenu(pause, briefing)),
          h("dl", { class: "facts" },
            h("dt", null, "Owner"), h("dd", null, M.dom.memberRef(ctx, m.owner_id)),
            h("dt", null, "Role"), h("dd", null, m.role),
            h("dt", null, "Reports to"), h("dd", null, m.reports_to ? M.dom.memberRef(ctx, m.reports_to) : "—"),
            h("dt", null, "Areas"), h("dd", null, m.areas.length ? m.areas.join(", ") : "—"),
            m.capabilities && m.capabilities.length
              ? [h("dt", null, "Capabilities"), h("dd", null, m.capabilities.join(", "))]
              : null,
            h("dt", null, "Harness"), h("dd", null, (m.harness || "—") + (m.model ? " · " + m.model : "")),
            h("dt", null, "Session"), h("dd", null, s
              ? s.id + " since " + formatTime(s.started_at) + (s.client ? " · " + s.client : "")
                + (s.listening ? " · listening" : "")
              : "none"),
            h("dt", null, "Last seen"), p.seen,
            h("dt", null, "Joined"), h("dd", null, formatTime(m.joined_at))),
          m.paused
            ? h("p", { class: "flag" }, "Paused " + formatAgo(m.paused.since),
              m.paused.by && m.paused.by !== m.id ? [" by ", M.dom.memberRef(ctx, m.paused.by)] : null, ": " + m.paused.reason,
              m.paused.by && m.paused.by !== m.id ? h("span", { class: "hint" }, " " + PAUSED_EFFECT) : null)
            : null,
          pause,
          briefing,
          // Its owner gives it their preferences (§19.4); a hub without them has no key.
          M.preferences && m.owner_id === ctx.me.id && "owner_preferences" in m ? M.preferences.ownerToggle(ctx, m) : null,
          creds[i].error
            ? h("div", { class: "credentials" }, h("h4", null, "Credentials"), M.errorBox(creds[i].error))
            : credentials(ctx, m, creds[i].list),
          mine ? h("p", { class: "chat-link" }, h("a", { href: ctx.link("chat", m.id) }, "Chat")) : null);
      });
    append(root, presenceStatus.el, grid, earlierBox);
    drawGrid();
    // #/<owner>/<slug>/agents/join (and the old #/join): the panel open at once.
    if (J && args && args[0] === "join") J.open(joinButton);
    placements();
  };
})(window.Maity);
