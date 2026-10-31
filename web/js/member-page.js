// A member's page (/<owner>/<slug>/members/<id>[/<tab>], the designer's
// handover #6484, the read-only cut of the coordinator, 2026-10-30): a
// breadcrumb back to Members, a header — the 64 px avatar with its presence,
// the name and @handle, pills for trust and role, whose agent it is, whom it
// reports to and its areas, one line of presence, harness, model and the
// cards it holds, Chat where one may — and tabs: Activity, Cards, Briefing,
// Sessions & credentials (Briefing only for an admin and the agent's owner, §6.2).
// Every action stays where it is done (#643): the
// Actions menu only leads there, Manage on Members for an admin, Manage on
// Agents for the agent's owner.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;
  const TABS = [["activity", "Activity"], ["cards", "Cards"], ["briefing", "Briefing"], ["sessions", "Sessions & credentials"]];
  const PRESENCE = { online: "Online", away: "Away", offline: "Offline", paused: "Paused" };
  // The Activity tab lists at most this many of the member's events, newest
  // first, from the window the project's messages read (js/messages.js).
  const ACTIVITY_SHOWN = 50;
  // An event in words: its kind, and the card or message it is about.
  const KIND_WORDS = { task_created: "created a card", task_claimed: "claimed a card", task_released: "released a card", task_updated: "changed a card",
    task_reported: "reported on a card", request_created: "asked", request_answered: "answered", message: "wrote", member_joined: "joined", member_updated: "changed a membership" };

  const ownAgentOf = (ctx, m) => m.kind === "agent" && ctx.me.kind === "human" && m.owner_id === ctx.me.id;

  // The instance that speaks for the member now: the online one, else the newest.
  function currentInstance(m) {
    const live = (m.instances || []).filter((i) => !i.revoked_at);
    return live.find((i) => i.presence === "online") || live.slice().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0] || null;
  }

  function pill(text, cls) { return h("span", { class: "pill member-pill" + (cls ? " " + cls : "") }, text); }

  function header(ctx, m, held) {
    const inst = currentInstance(m);
    // A human has a presence too (§5.3); an agent's pause shows instead of it.
    const presence = m.paused ? "paused" : m.presence || null;
    const line = [presence ? PRESENCE[presence] || presence : null,
      m.kind === "agent" ? (inst && inst.harness) || m.harness : null,
      m.kind === "agent" ? (inst && inst.model) || m.model : null,
      held === null ? null : "holds " + held + (held === 1 ? " card" : " cards")].filter(Boolean).join(" · ");
    const owner = m.kind === "agent" && m.owner_id ? M.dom.memberRef(ctx, m.owner ? Object.assign({ member_id: m.owner_id }, m.owner) : m.owner_id) : null;
    const pills = [pill(M.trust.words(m)),
      owner ? h("span", { class: "pill member-pill" }, "agent of ", owner) : null,
      m.reports_to ? h("span", { class: "pill member-pill" }, "reports to ", M.dom.memberRef(ctx, m.reports_to)) : null,
      (m.areas || []).length ? pill("areas " + m.areas.join(", ")) : null,
      m.paused ? pill("paused", "member-pill-paused") : null];
    // Chat: one's own agent's direct chat, anyone else a group chat with them chosen (§9.2).
    const groupOk = !M.trust.guest(ctx) && !["accepted", "archived"].includes(ctx.project.state);
    const chat = m.id === ctx.me.id || m.removed_at || ctx.me.kind !== "human" ? null
      : ownAgentOf(ctx, m) ? ctx.link("chat", m.id) : groupOk ? ctx.link("chat", "new") + "?with=" + encodeURIComponent(m.id) : null;
    // Actions lead to where each one is done (#643): nothing is done here.
    const actions = [];
    if (ctx.canAdmin && m.id !== ctx.me.id) actions.push({ label: "Manage on Members", href: ctx.link("members") + "?manage=" + encodeURIComponent(m.id) });
    if (ownAgentOf(ctx, m)) actions.push({ label: "Manage on Agents", href: ctx.link("agents", m.id) });
    const menu = actions.length ? M.menuButton({
      label: "Actions for " + m.display_name,
      face: ["Actions", h("span", { "aria-hidden": "true" }, " ▾")],
      items: () => actions,
    }) : null;
    if (menu) menu.el.className = "menu-box member-actions-menu";
    const heading = h("h2", { id: "member-heading", tabindex: "-1" }, m.display_name, " ", h("span", { class: "mono muted" }, "@" + M.dom.handleOf(ctx, m)));
    const el = h("div", { class: "member-head" },
      h("div", { class: "member-head-face" }, M.avatar(m, 64),
        presence ? h("span", { class: "dot member-head-dot " + presence, "aria-hidden": "true" }) : null),
      h("div", { class: "member-head-text" },
        heading,
        h("p", { class: "member-pills" }, pills),
        line ? h("p", { class: "muted member-line" }, line) : null),
      h("div", { class: "member-head-actions" },
        chat ? h("a", { class: "button primary member-chat", href: chat }, "Chat") : null,
        menu ? menu.el : null));
    return { el, heading };
  }

  // Activity: what the member did among the project's latest events.
  async function activity(ctx, m, box) {
    append(box, h("p", { class: "muted" }, "Reading…"));
    let items, cut;
    try {
      // The hub has no filter by actor (§8.3): the window is read and filtered here.
      const here = M.route.current().path;
      const read = await M.recentEvents(ctx, (e) => e.actor && e.actor.member_id === m.id && !e.redacted, () => M.route.current().path === here);
      if (!read) return;
      items = read.kept.slice(-ACTIVITY_SHOWN).reverse();
      cut = read.cut;
    } catch (err) {
      append(clear(box), h("p", { class: "send-status failed" }, "Could not read the activity: " + err.message));
      return;
    }
    append(clear(box), h("p", { class: "hint" }, "What they did in this project, newest first"
      + (cut ? ", within the hub's latest " + M.recentEvents.WINDOW + " events (all projects counted)." : ".")),
      items.length
        ? h("ul", { class: "member-activity" }, items.map((e) => {
          const subject = e.subject && e.subject.type === "task" ? h("a", { href: ctx.link("tasks", e.subject.id) }, h("span", { class: "mono" }, e.subject.id)) : null;
          const body = e.kind === "message" && e.payload && e.payload.type !== "chat" && e.payload.body ? String(e.payload.body).slice(0, 280) : null;
          return h("li", { "data-seq": String(e.seq) },
            h("span", null, KIND_WORDS[e.kind] || e.kind.replace(/_/g, " ")), subject ? [" ", subject] : null,
            h("span", { class: "muted" }, " · " + formatAgo(e.at)), body ? h("p", { class: "pre muted" }, body) : null);
        }))
        : h("p", { class: "muted" }, "Nothing of theirs among them."));
  }

  // Cards: those they hold, then those assigned to them; each opens on the board.
  async function cards(ctx, m, box) {
    append(box, h("p", { class: "muted" }, "Reading…"));
    let held, assigned;
    try {
      [held, assigned] = await Promise.all([
        M.api.getAll(ctx.base + "/tasks?holder=" + encodeURIComponent(m.id)),
        M.api.getAll(ctx.base + "/tasks?assigned_to=" + encodeURIComponent(m.id)),
      ]);
    } catch (err) {
      append(clear(box), h("p", { class: "send-status failed" }, "Could not read the cards: " + err.message));
      return;
    }
    const seen = new Set();
    const list = (items, title) => {
      const rows = items.filter((c) => !seen.has(c.id) && seen.add(c.id));
      return [h("h3", null, title + " (" + rows.length + ")"), rows.length
        ? h("ul", { class: "member-cards" }, rows.map((c) => h("li", null,
          h("a", { href: ctx.link("tasks", c.id) }, h("span", { class: "mono" }, c.id), " ", c.title),
          h("span", { class: "muted" }, " · " + String(c.status).replace("_", " ")))))
        : h("p", { class: "muted" }, "None.")];
    };
    append(clear(box), list(held.items || [], "Holds"), list(assigned.items || [], "Assigned"));
  }

  // Who reads an agent's briefing (§6.2): an admin in the member view, its
  // owner through the versions; nobody else, so nobody else gets the tab.
  const readsBriefing = (ctx, m) => m.kind === "agent" && (ctx.canAdmin || ownAgentOf(ctx, m));

  // Briefing: read here; it is edited in the agent's Manage row.
  async function briefing(ctx, m, box) {
    let text = m.briefing, by = m.briefing_by, version = m.briefing_version;
    if (!ctx.canAdmin) {
      // The owner without members:admin: the newest version (GET …/briefings).
      try {
        const latest = ((await M.api.get(ctx.base + "/members/" + encodeURIComponent(m.id) + "/briefings")).items || [])[0] || null;
        text = latest ? latest.text : null; by = latest ? latest.by : null; version = latest ? latest.version : null;
      } catch (err) {
        append(box, h("p", { class: "send-status failed" }, "Could not read the briefing: " + err.message));
        return;
      }
    }
    append(box, text
      ? h("div", { class: "md member-briefing" }, M.markdown(text, M.ids.where(ctx)))
      : h("p", { class: "muted" }, "No briefing; the project's onboarding applies."),
    by ? h("p", { class: "muted" }, "Set by @" + (by.handle || by.id) + (version ? " · version " + version : "")) : null);
  }

  // Sessions & credentials: the instances with their sessions; the
  // credentials where the hub shows them to the viewer (an admin, the owner).
  // `chosen`: the instance an address's #id leads to (tsk-bczgjkfpw1wg),
  // marked as the current one and given the focus.
  function focusWhenShown(el, tries) {
    if (el.isConnected === false) { if (tries > 0) window.setTimeout(() => focusWhenShown(el, tries - 1), 100); return; }
    el.focus();
  }

  async function sessions(ctx, m, box, chosen) {
    const live = (m.instances || []);
    const picked = live.some((i) => i.id === chosen) ? chosen : null;
    let pickedLine = null;
    append(box, h("h3", null, "Instances"), live.length
      ? h("ul", { class: "member-instances" }, live.map((i) => { const line = h("li", {
        id: "member-instance-" + i.id,
        class: [i.revoked_at ? "revoked" : null, i.id === picked ? "chosen" : null].filter(Boolean).join(" ") || null,
        "aria-current": i.id === picked ? "true" : null,
        tabindex: i.id === picked ? "-1" : null,
      },
        h("span", { class: "mono" }, i.label || i.id), " ",
        h("span", { class: "muted" }, [i.revoked_at ? "revoked " + formatAgo(i.revoked_at) : PRESENCE[i.presence] || i.presence,
          i.harness, i.model, i.last_seen_at ? "seen " + formatAgo(i.last_seen_at) : null,
          i.claims ? i.claims + (i.claims === 1 ? " claim" : " claims") : null].filter(Boolean).join(" · ")),
        // Its open session (§6.17): id, since when, and since when it has not been listening.
        i.session ? h("p", { class: "muted member-session" }, "Session ", h("span", { class: "mono" }, i.session.id),
          i.session.started_at ? " · since " + formatTime(i.session.started_at) : "",
          i.session.not_listening_since ? [" · ", h("span", { class: "flag-inline" }, "not listening since " + formatAgo(i.session.not_listening_since))] : "") : null);
        if (i.id === picked) pickedLine = line;
        return line;
      }))
      : h("p", { class: "muted" }, m.kind === "agent" ? "No instance yet." : "A human has no instances."));
    // The view is put into the page once it is drawn: the chosen line takes
    // the focus as soon as it is there (tried for a few seconds at most).
    if (pickedLine) focusWhenShown(pickedLine, 40);
    if (m.kind !== "agent" || !(ctx.canAdmin || ownAgentOf(ctx, m)) || !M.agentParts) return;
    const slot = h("div", { class: "member-credentials" }, h("p", { class: "muted" }, "Reading the credentials…"));
    append(box, slot);
    const got = await M.agentParts.loadCredentials(ctx, m);
    // Read only here: Revoke is in the Manage row (#643).
    append(clear(slot), got.error ? M.errorBox(got.error) : h("div", null, h("h3", null, "Credentials"),
      h("ul", { class: "member-creds" }, ((got.list && got.list.items) || []).map((c) => h("li", { class: c.revoked_at ? "revoked" : null },
        h("span", { class: "mono" }, c.id), " ",
        h("span", { class: "muted" }, [c.client || null, "created " + formatTime(c.created_at),
          c.revoked_at ? "revoked " + formatAgo(c.revoked_at) : c.last_used_at ? "used " + formatAgo(c.last_used_at) : "never used"].filter(Boolean).join(" · ")))))));
  }

  async function page(ctx, root, id, tab, instanceId) {
    const m = (ctx.members || []).find((x) => x.id === id);
    const crumb = h("nav", { class: "breadcrumb", "aria-label": "Breadcrumb" }, h("a", { href: ctx.link("members") }, "Members"), " / ",
      h("span", { "aria-current": "page" }, m ? "@" + M.dom.handleOf(ctx, m) : id));
    if (!m) {
      append(root, crumb, h("p", { class: "error", role: "alert" }, "No member with the id " + id + " in this project."));
      return;
    }
    const offered = TABS.filter(([k]) => k !== "briefing" || readsBriefing(ctx, m));
    const chosen = offered.some(([k]) => k === tab) ? tab : "activity";
    // The cards held, for the header's line, from the instances' claims where the hub counts them.
    const claims = (m.instances || []).some((i) => typeof i.claims === "number")
      ? (m.instances || []).filter((i) => !i.revoked_at).reduce((n, i) => n + (i.claims || 0), 0) : null;
    const tabs = h("nav", { class: "member-tabs", "aria-label": "Sections" }, offered.map(([k, label]) =>
      h("a", { href: ctx.link("members", m.id, k), class: "member-tab", "aria-current": k === chosen ? "page" : null }, label)));
    const body = h("section", { class: "member-section", "aria-label": TABS.find(([k]) => k === chosen)[1] });
    const head = header(ctx, m, claims);
    append(root, crumb, head.el, tabs, body);
    // Opened by a member's link: the heading takes the focus; a tab's own link keeps it on the tabs.
    if (!tab) window.setTimeout(() => head.heading.focus(), 0);
    if (chosen === "activity") await activity(ctx, m, body);
    else if (chosen === "cards") await cards(ctx, m, body);
    else if (chosen === "briefing") await briefing(ctx, m, body);
    else await sessions(ctx, m, body, instanceId);
  }

  M.memberPage = { page, TABS };
})(window.Maity);
