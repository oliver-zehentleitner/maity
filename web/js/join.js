// Joining an agent, inside a project's Agents view (js/agents-page.js): a panel that
// creates a join for one of the human's agent profiles (or a new one) and
// shows the paste line once (docs/api.md §3.1); the open joins as seats under
// the cards; the others folded at the view's end. The
// line carries a single-use code; it is held in the view only, never
// stored, and gone when the view is left. Each join's state is derived from
// its fields, expiry against the clock while the view is open; only an open
// join (or one expired within the grace minute) can be revoked. A join
// for an agent that is already a member says which instance it makes:
// another one, or one in place of an instance (docs/api.md §3.1, §6.17).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;

  // Expiry emits no event; the list re-judges it on this interval, by the
  // hub's clock (M.api.now). A join expired less than GRACE_MS ago keeps
  // Revoke: what the hub still accepts must stay revocable, and the hub
  // decides.
  const EXPIRY_MS = 10000;
  const GRACE_MS = 60000;

  // A member bringing their own agent (§3.1): M.trust.MEMBER_TRUSTS and
  // MEMBER_ROLES and nothing else; an admin assigns areas and capabilities
  // later, and the agent reports to them.
  const LIMIT_WORDS = { agent: "the agent (only one of your own, or a new one; or its membership was raised by an admin)", trust: "the trust",
    role: "the role", reports_to: "whom it reports to", areas: "its areas", capabilities: "its capabilities" };
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

  // The panel, the seats and the record, from the profiles and joins read;
  // drawn into the panel the Agents view already holds.
  function build(ctx, hooks, panel, listStatus, profilesRead, joinsRead) {
    let profiles = profilesRead;
    let joins = joinsRead;
    // The project's members as last read (ctx.members, which Agents keeps
    // current after each save): an agent among them joins as an instance.
    // Agents the hub said are members count as such even when the list on
    // screen does not show them yet.
    const saidMember = new Set();
    const memberOf = (id) => ctx.members.find((m) => m.id === id)
      || (saidMember.has(id) ? { id, instances: null, team: null } : null);
    const profileName = (id) => {
      const p = profiles.items.find((x) => x.id === id);
      return p ? p.display_name : id;
    };

    // A profile by its short handle, or its global name where a member of
    // this project shares the short one (§6.3), as members are named here.
    const profileHandle = (p) => M.dom.handleIn(ctx.members, { kind: "agent", handle: p.handle, name: p.name });
    const agentSelect = h("select", { id: "join-agent" });
    const profileOptions = () => append(clear(agentSelect),
      profiles.items.map((p) => h("option", { value: p.id }, p.display_name + " (@" + profileHandle(p) + ")"
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
    if (!profiles.items.length) newFields.hidden = false;

    // An agent that is already a member: the new line starts another
    // instance of it or replaces one of its instances (docs/api.md §6.17).
    // Role, reports to, areas and briefing stay the membership's; the join
    // leaves them out, as a change there goes through its card.
    const replaceOne = h("input", { type: "radio", name: "join-instance", id: "join-replace", value: "replace" });
    const another = h("input", { type: "radio", name: "join-instance", id: "join-new-instance", value: "new" });
    const replaced = h("select", { id: "join-replaces", "aria-label": "The instance it replaces" });
    const quota = h("p", { class: "hint", id: "join-quota" });
    const instanceBox = h("fieldset", { class: "join-instance wide", hidden: true },
      h("legend", null, "This agent is already a member of the project"),
      h("p", { class: "hint" }, "The new line makes an instance of it: the same role, areas and briefing, "
        + "which you change on its card. A different job is a different agent."),
      h("div", { class: "instance-choice" }, replaceOne, h("label", { for: "join-replace" }, "Replace instance"), replaced),
      h("p", { class: "hint" }, "When the new line is used, the replaced instance's credential is revoked and its cards move to the new one."),
      h("div", { class: "instance-choice" }, another, h("label", { for: "join-new-instance" }, "Start another instance")),
      quota);
    const activeOf = (m) => (m.instances || []).filter((i) => !i.revoked_at);
    const instanceText = (i) => (i.label || i.id) + " · " + (i.presence === "online" ? "online" : "last seen " + formatAgo(i.last_seen_at, M.api.now()))
      + " · " + (i.claims === 1 ? "1 card" : (i.claims || 0) + " cards");
    // The fields a member's join leaves out.
    const membershipFields = [];
    const membershipField = (el) => { membershipFields.push(el); return el; };
    // The choice starts from its default for each agent shown as a member.
    let shownFor = "";
    function showAgent() {
      const m = agentSelect.value ? memberOf(agentSelect.value) : null;
      const fresh = (m ? m.id : "") !== shownFor;
      shownFor = m ? m.id : "";
      newFields.hidden = agentSelect.value !== "";
      instanceBox.hidden = !m;
      membershipFields.forEach((f) => { f.hidden = !!m; });
      if (!m) return;
      const active = activeOf(m);
      const kept = replaced.value;
      append(clear(replaced), active.map((i) => h("option", { value: i.id }, instanceText(i))));
      replaced.value = active.some((i) => i.id === kept) ? kept : active.length ? active[0].id : "";
      replaceOne.disabled = replaced.disabled = !active.length;
      if (fresh || !active.length) { replaceOne.checked = active.length > 0; another.checked = !active.length; }
      const max = m.team && m.team.max_instances;
      quota.textContent = max ? active.length + " of " + max + " instances active" + (active.length >= max ? "; another one is over the team's limit." : ".")
        : m.instances ? "" : "The hub has not listed its instances here.";
    }
    agentSelect.addEventListener("change", showAgent);
    // Choosing an instance is choosing to replace it.
    replaced.addEventListener("change", () => { replaceOne.checked = true; another.checked = false; });
    // The project's members read again, for the instances a choice offers.
    async function rereadMembers() {
      try { M.withMembers(ctx, (await M.api.getAll(ctx.base + "/members")).items); } catch (ignored) { /* the refusal shown says enough */ }
    }

    const own = !!hooks.member;
    // An agent never holds trust owner; admin and the role proxy only from an
    // owner, proxy only with trust admin (§3.1, owner_only §2.3).
    const trusts = own ? M.trust.MEMBER_TRUSTS : ctx.isOwner ? ["member", "guest", "admin"] : ["member", "guest"];
    const trust = h("select", { id: "join-trust" }, trusts.map((r) => h("option", { value: r }, r)));
    trust.value = "member";
    const role = h("select", { id: "join-role" });
    const fillRoles = () => {
      const wanted = role.value || "coder";
      const offered = own ? M.trust.MEMBER_ROLES : M.trust.ROLES.filter((r) => r !== "proxy" || (ctx.isOwner && trust.value === "admin"));
      append(clear(role), offered.map((r) => h("option", { value: r }, r)));
      role.value = offered.includes(wanted) ? wanted : "coder";
    };
    trust.addEventListener("change", fillRoles);
    fillRoles();
    const reportsTo = h("select", { id: "join-reports" },
      h("option", { value: "" }, "nobody"),
      // A guest is never reported to (§2.3).
      ctx.members.filter((m) => !M.trust.guest(m)).map((m) => h("option", { value: m.id }, m.display_name)));
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

    // Another instance, or one that replaces an instance, runs with a state
    // directory of its own (docs/agents.md, "For the human"): said before
    // the line, since the line in a directory that holds a credential is
    // refused, and a resume there would take over that instance instead.
    // The CLI's side: see cli/context/credentials.md bb201120.
    function instanceNote(member) {
      const dir = "export MAITY_STATE_DIR=\"$HOME/.local/state/maity/" + member.handle + "-<name>\"";
      return h("div", { class: "instance-note", role: "note" },
        h("p", null, h("strong", null, "Every instance needs a state directory of its own.")),
        h("p", null, "Outside a clone of the repository, maity join puts this one next to the first by itself. "
          + "In a clone where @" + member.handle + " already joined, set this first, with a name for the instance:"),
        h("code", { class: "paste-line state-dir-line" }, dir),
        h("p", null, "Do not run maity resume there to start it: in a directory that already holds a credential, "
          + "resume takes over that instance, and two sessions then run as one."));
    }

    function showLine(j, member) {
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
        member ? instanceNote(member) : null,
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
        const member = agent.id ? memberOf(agent.id) : null;
        // At the member's limit (§3.1) only an instance of an agent already
        // in the project is made: that counts nothing.
        if (!member && hooks.full && hooks.full()) {
          status.fail("No join created: ", { message: "you hold as many agents in this project as it allows; "
            + "choose one of yours that is a member to start another instance or replace one" });
          agentSelect.focus();
          return;
        }
        const text = member ? "" : briefing.value.trim();
        if ([...text].length > BRIEFING_CHARS) {
          status.fail("No join created: ", { message: "the briefing is longer than 16,384 characters" });
          briefing.focus();
          return;
        }
        const req = member
          ? Object.assign({ agent, ttl_seconds: Number(ttl.value) },
            replaceOne.checked && replaced.value ? { replaces: replaced.value } : { new_instance: true })
          // One's own agent (§3.1): it reports to its owner by default, no field.
          : own ? { agent, trust: trust.value, role: role.value, ttl_seconds: Number(ttl.value) }
          : {
            agent,
            trust: trust.value,
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
          const fields = (err.code === "invalid" && err.details && err.details.fields) || {};
          const why = fields.handle;
          const d = err.details || {};
          status.fail("No join created: ", why === "taken" ? { message: "you already have an agent with the handle @" + agent.handle }
            // §3.1's limits for a member, in words, the field named.
            : d.reason === "member_join_limit" ? { message: "a member may not set this for their own agent: " + (LIMIT_WORDS[d.field] || d.field || "a field") }
            : d.reason === "member_agents_max" ? { message: "you hold as many agents in this project as it allows (" + d.max + ")" }
            : err);
          // The limit is the agent owner's rulebook, on its card on Agents (§6.18).
          if (err.code === "instance_quota" && agent.id) {
            append(status.el, " ", h("a", { class: "join-quota-link", href: ctx.link("agents", agent.id, "rulebook") },
              "Raise it in the team's rulebook"));
          }
          // A member the list on screen did not show, a first join the list
          // took for a member's, or an instance revoked meanwhile: read the
          // members again and offer what the hub has.
          const notMember = fields.new_instance === "not_a_member" || fields.replaces === "not_a_member";
          // The hub checks the membership's fields before the instance
          // (routes/joins.py): a differing role, area or briefing says
          // "member" as surely as instance: required does.
          const saysMember = fields.instance === "required" || Object.values(fields).includes("differs_from_membership");
          if (agent.id && (saysMember || fields.replaces || notMember || err.code === "instance_quota")) {
            if (saysMember) saidMember.add(agent.id);
            if (notMember) saidMember.delete(agent.id);
            await rereadMembers();
            if (notMember) M.withMembers(ctx, ctx.members.filter((m) => m.id !== agent.id));
            showAgent();
            if (saysMember) status.fail("No join created: ", { message: "this agent is already a member of the project. "
              + "Choose whether the line starts another instance or replaces one, then create it." });
            (replaceOne.checked && !replaceOne.disabled ? replaced : another).focus();
          }
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
        showLine(j, member);
        // A new profile is named in the select, the new join is a seat.
        try {
          [profiles, joins] = await Promise.all([M.api.getAll("/agents"), M.api.getAll(ctx.base + "/joins")]);
        } catch (err) {
          listStatus.fail("Join created; the list could not be re-read: ", err);
          return;
        }
        profileOptions();
        agentSelect.value = j.agent_id;
        showAgent();
        // The handle just created is one's own now: the hint says so.
        checkHandle();
        changed();
      },
    },
    h("div", { class: "join-columns" },
      h("div", { class: "join-fields" },
        h("div", { class: "field wide" }, h("label", { for: "join-agent" }, "Agent"), agentSelect),
        newFields,
        instanceBox,
        membershipField(h("div", { class: "field" }, h("label", { for: "join-trust" }, "Trust"), trust)),
        membershipField(h("div", { class: "field" }, h("label", { for: "join-role" }, "Role"), role)),
        own ? membershipField(h("p", { class: "hint field wide" }, "It reports to you. An admin gives it areas and capabilities later."))
          : [membershipField(h("div", { class: "field" }, h("label", { for: "join-reports" }, "Reports to"), reportsTo)),
            membershipField(h("div", { class: "field" }, h("label", { for: "join-areas" }, "Areas (comma separated)"), areas))],
        h("div", { class: "field" }, h("label", { for: "join-ttl" }, "Valid for"), ttl)),
      // Offered when the hub knows briefings: its member view then has the key.
      ctx.members.some((x) => "briefing" in x)
        ? membershipField(h("div", { class: "join-briefing" },
          h("label", { for: "join-briefing" }, "Briefing (optional, Markdown; " + M.dom.SEND_KEYS + " creates the link)"), briefing,
          h("p", { class: "hint" }, "The agent reads it in its resume packet once it has joined, and on every resume "
            + "after; it is never on the join page. You can change it later on the agent's card.")))
        : null),
    h("div", { class: "actions" }, h("button", { type: "button", onclick: () => close(true) }, "Cancel"), create),
    status.el);

    function showForm() { append(clear(body), form); }
    showForm();
    showAgent();
    append(clear(panel), panelHead(() => close(true), own), body);

    let opener = null;
    // Opened, it reads the members again: an agent's instances and its team's
    // limit may have changed since the view was drawn (a rulebook saved, an
    // instance revoked), and the choice must offer what the hub has now.
    // agentId: a profile to start from (the Agents page's Add to a project).
    function open(from, agentId) {
      opener = from || null;
      panel.hidden = false;
      if (hooks.opened) hooks.opened(true);
      if (agentId && Array.from(agentSelect.querySelectorAll("option")).some((o) => o.getAttribute("value") === agentId)) {
        agentSelect.value = agentId;
        showAgent();
      }
      focusSoon(agentSelect);
      rereadMembers().then(() => { if (!panel.hidden) showAgent(); });
    }
    function close(refocus) {
      panel.hidden = true;
      showForm();
      if (hooks.opened) hooks.opened(false);
      if (refocus && opener && opener.focus) opener.focus();
    }

    // Seats and earlier joins, drawn by the Agents view where they stand.
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
              p ? h("span", { class: "handle" }, "@" + profileHandle(p)) : null,
              h("span", { class: "seat-label" }, state.key === "open" ? "open seat" : "expired")),
            h("dl", { class: "facts" },
              h("dt", null, "Trust and role"), h("dd", null, M.trust.words(j), j.reports_to ? " · reports to " + ctx.nameOf(j.reports_to) : null),
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
          h("code", null, j.id), " " + profileName(j.agent_id) + " as " + M.trust.words(j) + " · " + state.text))));
    }
    const openCount = () => { const now = M.api.now(); return joins.items.filter((j) => joinState(j, now).key === "open").length; };
    // The agents open joins are for: with the active memberships, what §3.1 counts per profile.
    const openAgents = () => { const now = M.api.now(); return joins.items.filter((j) => joinState(j, now).key === "open").map((j) => j.agent_id); };

    shownKey = keyOf(joins, M.api.now());
    // A join that expires while the view is open moves on without a reload.
    ctx.every(EXPIRY_MS, () => { if (keyOf(joins, M.api.now()) !== shownKey) changed(); });

    // The members changed under an open panel (a rulebook saved on Agents):
    // the choice drawn again from them, the chosen agent and instance kept.
    const refresh = () => { if (!panel.hidden) showAgent(); };
    return { open, close, seats, earlier, openCount, openAgents, reread, refresh };
  }

  // On a page the router has not attached yet (a direct /<owner>/<slug>/agents/join), the
  // focus waits until it is in the document.
  function focusSoon(el) {
    if (el.isConnected === false) window.setTimeout(() => { if (el.isConnected !== false) el.focus(); }, 0);
    else el.focus();
  }

  function panelHead(onClose, own) {
    return [
      h("div", { class: "join-head" },
        h("h3", { id: "join-title" }, own ? "Add my agent" : "Add an agent"),
        h("button", { type: "button", class: "icon-button join-close", "aria-label": "Close", title: "Close", onclick: onClose }, "×")),
      h("p", { class: "muted" }, "The agent's session runs wherever you run it; it joins by the line you paste into it."),
    ];
  }

  // hooks.changed(): the seats and the earlier joins changed (a join made,
  // revoked, expired, or read at last); the Agents view draws them again.
  // A failed read of the profiles or the joins stays in the panel and the
  // seats, with a retry: the agents' cards never depend on it.
  async function mount(ctx, hooks) {
    const panel = h("section", { class: "join-panel", "aria-labelledby": "join-title" });
    panel.hidden = true;
    const listStatus = M.statusLine();
    let impl = null;
    let opener = null;
    // The profile asked for (?agent=<id>), kept for a Try again after a failed first read.
    let asked = null;
    const failedClose = () => {
      panel.hidden = true;
      if (hooks.opened) hooks.opened(false);
      if (opener && opener.focus) opener.focus();
    };
    async function load() {
      try {
        const [profiles, joins] = await Promise.all([M.api.getAll("/agents"), M.api.getAll(ctx.base + "/joins")]);
        // A member sees their own joins only, the ones they may revoke (§3.1).
        if (hooks.member) joins.items = joins.items.filter((j) => j.created_by === ctx.me.id);
        impl = build(ctx, hooks, panel, listStatus, profiles, joins);
        listStatus.done();
        return true;
      } catch (err) {
        impl = null;
        const retry = h("button", {
          type: "button",
          onclick: async () => {
            retry.disabled = true;
            if (await load()) {
              hooks.changed();
              if (!panel.hidden) impl.open(opener, asked);
            } else retry.disabled = false;
          },
        }, "Try again");
        append(clear(panel), panelHead(failedClose, !!hooks.member),
          h("p", { class: "error", role: "alert" }, "The joins could not be read: " + (err.message || err.code || "an error")), retry);
        listStatus.fail("The joins could not be read: ", err);
        return false;
      }
    }
    await load();
    return {
      panel,
      listStatus,
      open: (from, agentId) => {
        opener = from || null;
        asked = agentId || null;
        if (impl) { impl.open(from, agentId); return; }
        panel.hidden = false;
        if (hooks.opened) hooks.opened(true);
        const retry = panel.querySelector ? Array.from(panel.querySelectorAll("button")).find((b) => b.textContent === "Try again") : null;
        if (retry) focusSoon(retry);
      },
      close: (refocus) => (impl ? impl.close(refocus) : failedClose()),
      seats: () => (impl ? impl.seats() : []),
      earlier: () => (impl ? impl.earlier() : null),
      openCount: () => (impl ? impl.openCount() : 0),
      openAgents: () => (impl ? impl.openAgents() : []),
      // A failed first read keeps its Try again.
      reread: () => (impl ? impl.reread() : Promise.resolve()),
      refresh: () => { if (impl) impl.refresh(); },
      // An open panel holds a form being filled in or a line shown once: a
      // redraw of the view would lose either.
      busy: () => !panel.hidden,
    };
  }

  M.join = { mount };
})(window.Maity);
