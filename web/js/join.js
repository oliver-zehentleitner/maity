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
// A first join may name the agent member whose work the new one continues
// and where the hand-over is written; neither moves anything (§3.1).
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
  // Getters: the words are the catalog's when said.
  const LIMIT_WORDS = {
    get agent() { return M.t("join.limit.agent"); },
    get trust() { return M.t("join.limit.trust"); },
    get role() { return M.t("join.limit.role"); },
    get reports_to() { return M.t("join.limit.reports_to"); },
    get areas() { return M.t("join.limit.areas"); },
    get capabilities() { return M.t("join.limit.capabilities"); },
    get takes_over() { return M.t("join.limit.takes_over"); },
  };
  // The hub's refusals of takes_over and handover (§3.1), in words.
  const TAKEOVER_REFUSALS = {
    "takes_over:first_join_only": () => M.t("join.failed.takes_over_first_join"),
    "takes_over:not_an_agent_member": () => M.t("join.failed.takes_over_not_member"),
    "handover:not_found": () => M.t("join.failed.handover_not_found"),
    "handover:not_readable": () => M.t("join.failed.handover_not_readable"),
  };

  // Where a hand-over is written (§3.1, §5.2: {kind, id}), as a link: the
  // card, or the project's messages for a message, which have no page each.
  function handoverRef(ctx, ho) {
    if (!ho) return null;
    if (ho.kind === "task") return h("a", { href: ctx.link("tasks", String(ho.id)) }, String(ho.id));
    // A seq is an id, not a quantity: written as the hub gives it.
    return h("a", { href: ctx.link("messages") }, M.t("join.handover.message", { seq: String(ho.id) }));
  }

  // Whose work a join or a membership continues and where its hand-over is
  // (§3.1, §6.2): `takes_over` an id (a join) or {member_id, handle} (a member).
  function takeOverWords(ctx, x) {
    const who = x.takes_over ? M.dom.memberRef(ctx, x.takes_over, { text: "handle" }) : null;
    if (who && x.handover) return M.tn("join.takes_over.both", { who, handover: handoverRef(ctx, x.handover) });
    return who ? M.tn("join.takes_over.who", { who }) : M.tn("join.takes_over.handover_only", { handover: handoverRef(ctx, x.handover) });
  }

  // A card id as typed, or a message's seq as a number (§3.1).
  const handoverValue = (v) => (/^[0-9]+$/.test(v) ? Number(v) : v);
  const BRIEFING_CHARS = 16 * 1024; // docs/api.md §3: 16 KiB, in characters as the hub counts

  // A join's state from GET /joins (docs/api.md §3.1), in the hub's order:
  // revoked, used, burned, then the clock.
  function joinState(j, now) {
    if (j.revoked_at) return { key: "revoked", label: M.t("join.state.revoked"), text: M.t("join.state.revoked_at", { time: formatTime(j.revoked_at) }) };
    if (j.used_at) return { key: "used", label: M.t("join.state.used"), text: M.t("join.state.used_at", { time: formatTime(j.used_at) }) };
    if (j.burned) return { key: "burned", label: M.t("join.state.burned"), text: M.t("join.state.burned_text") };
    if (Date.parse(j.expires_at) <= now) return { key: "expired", label: M.t("join.state.expired"), text: M.t("join.state.expired_at", { time: formatTime(j.expires_at) }) };
    return { key: "open", label: M.t("join.state.open"), text: M.t("join.state.open_until", { time: formatTime(j.expires_at) }) };
  }

  // All the human's profiles, since a handle is taken whichever project they are in, and
  // `offered`, the ones this project is allowed for (§6.3): only those are offered.
  async function readProfiles(ctx) {
    const [all, allowed] = await Promise.all([M.api.getAll("/agents"),
      M.api.getAll("/agents?allowed_in=" + encodeURIComponent(ctx.project.full_name))]);
    const ok = new Set(allowed.items.map((p) => p.id));
    return Object.assign({}, all, { offered: all.items.filter((p) => ok.has(p.id)) });
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
      profiles.offered.map((p) => h("option", { value: p.id }, p.memberships.some((x) => x.project === ctx.slug)
        ? M.t("join.agent.option_member", { name: p.display_name, handle: profileHandle(p) })
        : M.t("join.agent.option", { name: p.display_name, handle: profileHandle(p) }))),
      h("option", { value: "" }, M.t("join.agent.new")));
    profileOptions();
    const HANDLE = M.dom.NAME_RULES.handle;
    const handle = h("input", { id: "join-handle", placeholder: M.t("join.handle.placeholder"), pattern: HANDLE.pattern,
      maxlength: "31", autocomplete: "off", spellcheck: "false", "aria-describedby": "join-handle-rule join-handle-state" });
    const display = h("input", { id: "join-display", placeholder: M.t("join.display.placeholder") });
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
        : bad ? M.t("join.handle.bad", { rule: HANDLE.text })
        : taken ? M.t("join.handle.taken", { name: taken.display_name, handle: v })
        : refused.has(v) ? M.t("join.handle.refused", { handle: v })
        : M.t("join.handle.free", { handle: v });
    };
    handle.addEventListener("input", checkHandle);
    const newFields = h("div", { class: "new-agent", hidden: true },
      h("label", { for: "join-handle" }, M.t("join.handle.label")), handle, h("p", { class: "hint", id: "join-handle-rule" }, HANDLE.text),
      handleState,
      h("label", { for: "join-display" }, M.t("join.display.label")), display);
    if (!profiles.offered.length) newFields.hidden = false;

    // An agent that is already a member: the new line starts another
    // instance of it or replaces one of its instances (docs/api.md §6.17).
    // Role, reports to, areas and briefing stay the membership's; the join
    // leaves them out, as a change there goes through its card.
    const replaceOne = h("input", { type: "radio", name: "join-instance", id: "join-replace", value: "replace" });
    const another = h("input", { type: "radio", name: "join-instance", id: "join-new-instance", value: "new" });
    const replaced = h("select", { id: "join-replaces", "aria-label": M.t("join.instance.replaces_label") });
    const quota = h("p", { class: "hint", id: "join-quota" });
    const instanceBox = h("fieldset", { class: "join-instance wide", hidden: true },
      h("legend", null, M.t("join.instance.legend")),
      h("p", { class: "hint" }, M.t("join.instance.hint")),
      h("div", { class: "instance-choice" }, replaceOne, h("label", { for: "join-replace" }, M.t("join.instance.replace")), replaced),
      h("p", { class: "hint" }, M.t("join.instance.replace_hint")),
      h("div", { class: "instance-choice" }, another, h("label", { for: "join-new-instance" }, M.t("join.instance.another"))),
      quota);
    const activeOf = (m) => (m.instances || []).filter((i) => !i.revoked_at);
    const instanceText = (i) => {
      const cards = M.t("join.instance.cards", { count: i.claims || 0 });
      return i.presence === "online" ? M.t("join.instance.online", { label: i.label || i.id, cards })
        : M.t("join.instance.seen", { label: i.label || i.id, ago: formatAgo(i.last_seen_at, M.api.now()), cards });
    };
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
      takeOverOptions();
      if (!m) return;
      const active = activeOf(m);
      const kept = replaced.value;
      append(clear(replaced), active.map((i) => h("option", { value: i.id }, instanceText(i))));
      replaced.value = active.some((i) => i.id === kept) ? kept : active.length ? active[0].id : "";
      replaceOne.disabled = replaced.disabled = !active.length;
      if (fresh || !active.length) { replaceOne.checked = active.length > 0; another.checked = !active.length; }
      const max = m.team && m.team.max_instances;
      quota.textContent = max ? (active.length >= max ? M.t("join.quota.full", { active: active.length, max }) : M.t("join.quota.active", { active: active.length, max }))
        : m.instances ? "" : M.t("join.quota.unlisted");
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
      M.trust.fillRoles(role, offered, wanted, "coder");
    };
    const roleHelp = M.trust.roleHint(role);
    trust.addEventListener("change", fillRoles);
    fillRoles();
    const reportsTo = h("select", { id: "join-reports" },
      h("option", { value: "" }, M.t("join.reports.nobody")),
      // A guest is never reported to (§2.3).
      ctx.members.filter((m) => !M.trust.guest(m)).map((m) => h("option", { value: m.id }, m.display_name)));
    const areas = h("input", { id: "join-areas", placeholder: "hub/, docs/" });
    // docs/api.md §3: the briefing reaches the agent in its resume packet
    // after the exchange, never on the join page.
    const briefing = M.dom.sendOnCtrlEnter(h("textarea", {
      id: "join-briefing",
      rows: "5",
      placeholder: M.t("join.briefing.placeholder"),
    }));
    // A first join only: the agent member whose work this one continues
    // (one's own agents for a member's join, §3.1), and its hand-over.
    const takesOver = h("select", { id: "join-takes-over", "aria-describedby": "join-takes-over-hint" });
    const takeable = () => ctx.members.filter((m) => m.kind === "agent" && !m.removed_at && m.id !== agentSelect.value
      && (!own || m.owner_id === ctx.me.id));
    const takeOverOptions = () => {
      const kept = takesOver.value;
      const list = takeable();
      append(clear(takesOver), h("option", { value: "" }, M.t("join.takes_over.nobody")),
        list.map((m) => h("option", { value: m.id }, M.t("join.takes_over.option", { name: m.display_name, handle: M.dom.handleOf(ctx, m) }))));
      takesOver.value = list.some((m) => m.id === kept) ? kept : "";
      takeOverField.hidden = !list.length || !!(agentSelect.value && memberOf(agentSelect.value));
    };
    const handover = h("input", { id: "join-handover", maxlength: "200", autocomplete: "off", spellcheck: "false",
      placeholder: M.t("join.handover.placeholder"), "aria-describedby": "join-handover-hint" });
    const takeOverField = h("div", { class: "field" }, h("label", { for: "join-takes-over" }, M.t("join.field.takes_over")), takesOver,
      h("p", { class: "hint", id: "join-takes-over-hint" }, M.t("join.takes_over.hint")));
    const handoverField = membershipField(h("div", { class: "field" }, h("label", { for: "join-handover" }, M.t("join.field.handover")), handover,
      h("p", { class: "hint", id: "join-handover-hint" }, M.t("join.handover.hint"))));
    const ttl = h("select", { id: "join-ttl" },
      [900, 1800, 3600].map((v) => h("option", { value: String(v) },
        v < 3600 ? M.t("join.ttl.minutes", { count: v / 60 }) : M.t("join.ttl.hours", { count: v / 3600 }))));

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
        h("p", null, h("strong", null, M.t("join.state_dir.title"))),
        h("p", null, M.t("join.state_dir.where", { handle: member.handle })),
        h("code", { class: "paste-line state-dir-line" }, dir),
        h("p", null, M.t("join.state_dir.no_resume")));
    }

    function showLine(j, member) {
      const line = h("code", { class: "paste-line" }, j.paste_line);
      const copy = h("button", {
        type: "button",
        onclick: async () => {
          try {
            await navigator.clipboard.writeText(j.paste_line);
            copy.textContent = M.t("join.copy.done");
          } catch (err) {
            copy.textContent = M.t("join.copy.failed");
          }
        },
      }, M.t("join.copy.label"));
      const again = h("button", { type: "button", onclick: () => { showForm(); agentSelect.focus(); } }, M.t("join.line.again"));
      append(clear(body), h("div", { class: "join-result" },
        h("p", null, h("strong", null, M.t("join.line.paste", { time: formatTime(j.expires_at) }))),
        member ? instanceNote(member) : null,
        h("div", { class: "paste-row" }, line, copy),
        h("p", { class: "first-hint" }, M.t("join.line.hint")),
        h("div", { class: "actions" }, again, h("button", { type: "button", class: "primary", onclick: () => close(true) }, M.t("join.line.done")))));
      copy.focus();
    }

    // Held while a join is being created: one join per submission, by click or Ctrl+Enter.
    const create = h("button", { type: "submit", class: "primary" }, M.t("join.create"));
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
            status.fail(M.t("join.failed"), { message: M.t("join.failed.handle", { rule: HANDLE.text }) });
            handle.focus();
            return;
          }
          agent = { handle: handle.value.trim(), display_name: display.value.trim() || handle.value.trim() };
        }
        const member = agent.id ? memberOf(agent.id) : null;
        // At the member's limit (§3.1) only an instance of an agent already
        // in the project is made: that counts nothing.
        if (!member && hooks.full && hooks.full()) {
          status.fail(M.t("join.failed"), { message: M.t("join.failed.full") });
          agentSelect.focus();
          return;
        }
        const text = member ? "" : briefing.value.trim();
        if ([...text].length > BRIEFING_CHARS) {
          status.fail(M.t("join.failed"), { message: M.t("join.failed.briefing", { max: BRIEFING_CHARS }) });
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
        if (!member && takesOver.value && !takeOverField.hidden) req.takes_over = takesOver.value;
        if (!member && handover.value.trim()) req.handover = handoverValue(handover.value.trim());
        status.busy(M.t("join.creating"));
        create.disabled = true;
        let j;
        try {
          j = await M.api.post(ctx.base + "/joins", req);
        } catch (err) {
          const fields = (err.code === "invalid" && err.details && err.details.fields) || {};
          const why = fields.handle;
          const d = err.details || {};
          const takeover = ["takes_over", "handover"].find((f) => Object.hasOwn(TAKEOVER_REFUSALS, f + ":" + fields[f]));
          status.fail(M.t("join.failed"), why === "taken" ? { message: M.t("join.failed.taken", { handle: agent.handle }) }
            : takeover ? { message: TAKEOVER_REFUSALS[takeover + ":" + fields[takeover]]() }
            // §3.1's limits for a member, in words, the field named.
            : d.reason === "project_not_allowed" ? { message: M.t("join.failed.project_not_allowed") }
            : d.reason === "member_join_limit" ? { message: M.t("join.failed.member_limit", {
              field: Object.hasOwn(LIMIT_WORDS, d.field) ? LIMIT_WORDS[d.field] : d.field || M.t("join.limit.a_field") }) }
            : d.reason === "member_agents_max" ? { message: M.t("join.failed.member_max", { max: d.max }) }
            : err);
          // The limit is the agent owner's rulebook, on its card on Agents (§6.18).
          if (takeover || d.field === "takes_over") (takeover === "handover" ? handover : takesOver).focus();
          if (err.code === "instance_quota" && agent.id) {
            append(status.el, " ", h("a", { class: "join-quota-link", href: ctx.link("agents", agent.id, "rulebook") },
              M.t("join.quota.raise")));
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
            if (saysMember) status.fail(M.t("join.failed"), { message: M.t("join.failed.is_member") });
            (replaceOne.checked && !replaceOne.disabled ? replaced : another).focus();
          }
          if (why) {
            // The hub knows better than the list on screen: read it again, and say so at the field.
            if (why === "taken") refused.add(agent.handle);
            try { profiles = await readProfiles(ctx); } catch (ignored) { /* the refusal above says enough */ }
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
          [profiles, joins] = await Promise.all([readProfiles(ctx), M.api.getAll(ctx.base + "/joins")]);
        } catch (err) {
          listStatus.fail(M.t("join.created_unread"), err);
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
        h("div", { class: "field wide" }, h("label", { for: "join-agent" }, M.t("join.field.agent")), agentSelect),
        newFields,
        instanceBox,
        membershipField(h("div", { class: "field" }, h("label", { for: "join-trust" }, M.t("join.field.trust")), trust)),
        membershipField(h("div", { class: "field" }, h("label", { for: "join-role" }, M.t("join.field.role")), role, roleHelp)),
        own ? membershipField(h("p", { class: "hint field wide" }, M.t("join.field.own_hint")))
          : [membershipField(h("div", { class: "field" }, h("label", { for: "join-reports" }, M.t("join.field.reports_to")), reportsTo)),
            membershipField(h("div", { class: "field" }, h("label", { for: "join-areas" }, M.t("join.field.areas")), areas))],
        membershipField(takeOverField),
        handoverField,
        h("div", { class: "field" }, h("label", { for: "join-ttl" }, M.t("join.field.ttl")), ttl)),
      membershipField(h("div", { class: "join-briefing" },
        h("label", { for: "join-briefing" }, M.t("join.briefing.label", { keys: M.dom.SEND_KEYS })), briefing,
        h("p", { class: "hint" }, M.t("join.briefing.hint"))))),
    h("div", { class: "actions" }, h("button", { type: "button", onclick: () => close(true) }, M.t("join.cancel")), create),
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
        listStatus.fail(M.t("join.read_failed"), err);
        return;
      }
      changed();
    }
    const profileOf = (id) => profiles.items.find((x) => x.id === id) || null;
    function revoke(j) {
      return h("button", {
        type: "button",
        class: "danger",
        "aria-label": M.t("join.revoke.label", { name: profileName(j.agent_id) }),
        onclick: async () => {
          listStatus.busy(M.t("join.revoke.busy"));
          try {
            await M.api.del(ctx.base + "/joins/" + encodeURIComponent(j.id));
            listStatus.done();
            await reread();
          } catch (err) {
            listStatus.fail(M.t("join.revoke.failed"), err);
            // Used, burned or expired meanwhile: show it as the hub has it.
            if (err.code === "invalid_transition") await reread();
          }
        },
      }, M.t("join.revoke"));
    }
    // An open join is a member who has not arrived yet: a seat in the grid.
    function seats() {
      const now = M.api.now();
      return joins.items.map((j) => ({ j, state: joinState(j, now) }))
        .filter(({ j, state }) => revocable(j, state, now))
        .map(({ j, state }) => {
          const p = profileOf(j.agent_id);
          return h("article", { class: "profile seat join-" + state.key, "aria-label": M.t("join.seat.label", { name: profileName(j.agent_id) }), "data-join": j.id },
            h("header", null,
              h("span", { class: "seat-mark", "aria-hidden": "true" }),
              h("h3", null, profileName(j.agent_id)),
              p ? h("span", { class: "handle" }, "@" + profileHandle(p)) : null,
              h("span", { class: "seat-label" }, state.key === "open" ? M.t("join.seat.open") : M.t("join.state.expired"))),
            h("dl", { class: "facts" },
              h("dt", null, M.t("join.seat.trust_role")), h("dd", null, M.trust.words(j), j.reports_to ? " · " + M.t("join.seat.reports_to", { name: ctx.nameOf(j.reports_to) }) : null),
              h("dt", null, M.t("join.seat.join")), h("dd", null, state.text + " · ", h("code", null, j.id)),
              takeOverFacts(j)),
            h("p", { class: "muted" }, M.t("join.seat.waiting")),
            h("div", { class: "seat-actions" }, revoke(j)));
        });
    }
    // The record: used, burned, revoked, expired past the grace minute.
    function earlier() {
      const now = M.api.now();
      const rows = joins.items.map((j) => ({ j, state: joinState(j, now) })).filter(({ j, state }) => !revocable(j, state, now));
      if (!rows.length) return null;
      return h("details", { class: "earlier-joins" },
        h("summary", null, M.t("join.earlier", { count: rows.length })),
        h("ul", { class: "joins closed-joins" }, rows.map(({ j, state }) => h("li", { class: "join-" + state.key },
          h("span", { class: "badge join-state" }, state.label), " ",
          h("code", null, j.id), " " + M.t("join.earlier.row", { name: profileName(j.agent_id), words: M.trust.words(j), state: state.text }),
          takeOverLine(j)))));
    }
    // A join's takes_over and handover (§3.1): whose work it continues, where the hand-over is.
    function takeOverFacts(j) {
      if (!j.takes_over && !j.handover) return null;
      return [h("dt", null, M.t("join.seat.takes_over")), h("dd", { class: "join-takes-over" }, takeOverWords(ctx, j))];
    }
    function takeOverLine(j) {
      if (!j.takes_over && !j.handover) return null;
      return [" · ", h("span", { class: "muted join-takes-over" }, takeOverWords(ctx, j))];
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
    // A profile made beside the panel (the Agents view's Add an agent): offered from now on.
    const reprofile = async () => { profiles = await readProfiles(ctx); profileOptions(); };
    return { open, close, seats, earlier, openCount, openAgents, reread, refresh, reprofile };
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
        h("h3", { id: "join-title" }, own ? M.t("join.title.own") : M.t("join.title")),
        h("button", { type: "button", class: "icon-button join-close", "aria-label": M.t("join.close"), title: M.t("join.close"), onclick: onClose }, "×")),
      h("p", { class: "muted" }, M.t("join.intro")),
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
        const [profiles, joins] = await Promise.all([readProfiles(ctx), M.api.getAll(ctx.base + "/joins")]);
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
        }, M.t("join.retry"));
        append(clear(panel), panelHead(failedClose, !!hooks.member),
          h("p", { class: "error", role: "alert" }, M.t("join.read_failed_text", { reason: err.message || err.code || M.t("join.an_error") })), retry);
        listStatus.fail(M.t("join.read_failed"), err);
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
        const retry = panel.querySelector ? Array.from(panel.querySelectorAll("button")).find((b) => b.textContent === M.t("join.retry")) : null;
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
      reprofile: () => (impl ? impl.reprofile() : Promise.resolve()),
      // An open panel holds a form being filled in or a line shown once: a
      // redraw of the view would lose either.
      busy: () => !panel.hidden,
    };
  }

  M.join = { mount, takeOverWords };
})(window.Maity);
