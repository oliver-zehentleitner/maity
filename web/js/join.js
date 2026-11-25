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
// For a human with members:admin, and for a member bringing an agent of
// their own that is not in the project yet (tsk-at3gnzqd8svy), the form's
// last part starts the agent on one of their runners instead of a line
// (§15.6, js/placements.js `runnerPart`, tsk-hdczmsq2r431): one form for
// both ways, the profile first. An outsider of a public project whose admins opted in brings
// an agent of their own the same way (hooks.outsider, from js/outsider-actions.js; §3.1 "An
// outsider's agent"): trust `outside`, a role of the project's `outside_roles`, no runner.
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

  // The hub's refusals of a member's own agent beyond "Bringing your own agent" (§3.1), for a join
  // and for a placement that admits the agent (§15.6), in words, the field named; else null.
  function memberRefusal(err) {
    const d = err.details || {};
    return d.reason === "project_not_allowed" ? { message: M.t("join.failed.project_not_allowed") }
      : d.reason === "member_join_limit" ? { message: M.t("join.failed.member_limit", {
        field: Object.hasOwn(LIMIT_WORDS, d.field) ? LIMIT_WORDS[d.field] : d.field || M.t("join.limit.a_field") }) }
      : d.reason === "member_agents_max" ? { message: M.t("join.failed.member_max", { max: d.max }) }
      // No members:admin and the member's way closed (§3.1): say which right is missing.
      : err.code === "forbidden" && !d.reason && d.scope === "members:admin" ? { message: M.t("join.failed.no_admin") }
      : null;
  }

  // The hub's refusals of an outsider's join (§3.1 "An outsider's agent"), in words; else null
  // (the quota is memberRefusal's member_agents_max). `not_found` is the opt-in gone meanwhile; a
  // role refused is one the policy took off its list since the form was drawn, so no list is named.
  function outsiderRefusal(err) {
    const d = err.details || {};
    return err.code === "not_found" ? { message: M.t("outsider.join.closed") }
      : d.reason === "blocked" ? { message: M.t("outsider.reason.blocked") }
      : d.reason === "member_join_limit" && d.field === "role" ? { message: M.t("outsider.join.role") }
      : null;
  }

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

  // A card id as typed, or a message's seq as a number (§3.1), also written as the page
  // shows it ("message #6001").
  const handoverValue = (v) => (/^#?[0-9]+$/.test(v) ? Number(v.startsWith("#") ? v.slice(1) : v) : v);
  const BRIEFING_CHARS = 16 * 1024; // docs/api.md §3: 16 KiB, in characters as the hub counts
  // A control is described by the hints shown now only: a screen reader reads a hidden element
  // named in aria-describedby too (as js/placements.js does).
  function describe(control, ids) {
    const shown = ids.filter(Boolean).join(" ");
    if (shown) control.setAttribute("aria-describedby", shown);
    else control.removeAttribute("aria-describedby");
  }

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
    // For a join line, agents the hub said are members (instance: required) count as such even
    // when the list on screen does not show them yet: the next line is an instance's, which the
    // hub refuses (not_a_member) should the membership be gone, so nothing is made on that word.
    // A start on a runner never takes it: its id alone would be admitted with the hub's
    // defaults, so it is a member's only once the members read show it (`recheckMember`).
    const saidMember = new Set();
    const memberOf = (id) => ctx.members.find((m) => m.id === id)
      || (saidMember.has(id) && !(viaRunner && viaRunner.on()) ? { id, instances: null, team: null } : null);
    const profileName = (id) => {
      const p = profiles.items.find((x) => x.id === id);
      return p ? p.display_name : id;
    };

    // A profile by its short handle, or its global name where a member of
    // this project shares the short one (§6.3), as members are named here.
    const profileHandle = (p) => M.dom.handleIn(ctx.members, { kind: "agent", handle: p.handle, name: p.name });
    const agentSelect = h("select", { id: "join-agent" });
    // A member bringing their own agent (hooks.member) who starts it on a runner: the placement
    // admits only a profile of their own that is not in the project yet (§15.6): the others stay
    // listed, off, with the reason; one chosen stays chosen and is refused at Start (tsk-6w4qckma672q).
    let admitting = false;
    const agentWhy = h("p", { class: "hint join-agent-runner", id: "join-agent-runner" }, M.t("join.runner.own_agents"));
    agentWhy.hidden = true;
    const runnerTakes = (id) => !!id && !memberOf(id);
    const markAdmitting = () => {
      Array.from(agentSelect.querySelectorAll("option")).forEach((o) => { o.disabled = admitting && !runnerTakes(o.getAttribute("value")); });
      agentWhy.hidden = !admitting;
      describe(agentSelect, [admitting ? agentWhy.id : null]);
    };
    const profileOptions = () => {
      append(clear(agentSelect),
        profiles.offered.map((p) => h("option", { value: p.id }, p.memberships.some((x) => x.project === ctx.slug)
          ? M.t("join.agent.option_member", { name: p.display_name, handle: profileHandle(p) })
          : M.t("join.agent.option", { name: p.display_name, handle: profileHandle(p) }))),
        h("option", { value: "" }, M.t("join.agent.new")));
      markAdmitting();
    };
    profileOptions();
    const HANDLE = M.dom.NAME_RULES.handle;
    const handle = h("input", { id: "join-handle", placeholder: M.t("join.handle.placeholder"), pattern: HANDLE.pattern, required: true,
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
        : bad && /[A-Z]/.test(v) ? M.handles.problem(v)
        : bad ? M.t("join.handle.bad", { rule: HANDLE.text })
        : taken ? M.t("join.handle.taken", { name: taken.display_name, handle: v })
        : refused.has(v) ? M.t("join.handle.refused", { handle: v })
        : M.t("join.handle.free", { handle: v });
    };
    handle.addEventListener("input", checkHandle);
    // A member's start on a runner takes no new profile (§15.6): the fields stay, off, with why.
    const newWhy = h("p", { class: "hint join-new-runner", id: "join-new-runner" }, M.t("join.runner.own_agents"));
    newWhy.hidden = true;
    const newFields = h("div", { class: "new-agent", hidden: true },
      h("label", { for: "join-handle" }, M.t("join.handle.label")), handle,
      M.handles.explain("agent", handle), h("p", { class: "hint", id: "join-handle-rule" }, HANDLE.text),
      handleState,
      h("label", { for: "join-display" }, M.t("join.display.label")), display, newWhy);
    if (!profiles.offered.length) newFields.hidden = false;
    // An outsider's own agent (§3.1 "An outsider's agent", js/outsider-actions.js): a member's
    // own join with trust `outside`, a role of `outside.roles` (the policy's `outside_roles`),
    // reports_to sent as the caller, which the contract allows; the hub stores nobody, the owner
    // being no member (§6.2). No trust or boss to choose, no runner, no restricted texts.
    const outside = hooks.outsider || null;
    const own = !!hooks.member || !!outside;
    // Or on a runner instead of a join line (§15.6, js/placements.js `runnerPart`,
    // tsk-hdczmsq2r431): the part at the form's end, for a human with members:admin, and for a
    // member bringing their own agent one of theirs not in the project yet (tsk-at3gnzqd8svy).
    const viaRunner = M.placements && !outside ? M.placements.runnerPart(ctx, { changed: () => showAgent(), member: own }) : null;
    // The handle a start's clone defaults to: the chosen profile's, or the new one's typed.
    const followRunner = () => {
      if (!viaRunner) return;
      const p = agentSelect.value ? profiles.offered.find((x) => x.id === agentSelect.value) : null;
      viaRunner.follow(agentSelect.value, agentSelect.value ? memberOf(agentSelect.value) : null, p ? p.handle : handle.value.trim());
    };
    handle.addEventListener("input", followRunner);

    // An agent that is already a member: the new line starts another
    // instance of it or replaces one of its instances (docs/api.md §6.17).
    // Role, reports to, areas and briefing stay the membership's; the join
    // leaves them out, as a change there goes through its card.
    const replaceOne = h("input", { type: "radio", name: "join-instance", id: "join-replace", value: "replace" });
    const another = h("input", { type: "radio", name: "join-instance", id: "join-new-instance", value: "new" });
    const replaced = h("select", { id: "join-replaces", "aria-label": M.t("join.instance.replaces_label") });
    const quota = h("p", { class: "hint", id: "join-quota" });
    // A start on a runner makes another instance; replacing one that way is not built yet.
    const noReplace = h("p", { class: "hint join-runner-only", id: "join-replace-runner" }, M.t("join.runner.no_replace"));
    noReplace.hidden = true;
    const instanceBox = h("fieldset", { class: "join-instance wide", hidden: true },
      h("legend", null, M.t("join.instance.legend")),
      h("p", { class: "hint" }, M.t("join.instance.hint")),
      h("div", { class: "instance-choice" }, replaceOne, h("label", { for: "join-replace" }, M.t("join.instance.replace")), replaced),
      h("p", { class: "hint" }, M.t("join.instance.replace_hint")), noReplace,
      h("div", { class: "instance-choice" }, another, h("label", { for: "join-new-instance" }, M.t("join.instance.another"))),
      quota);
    const activeOf = (m) => (m.instances || []).filter((i) => !i.revoked_at);
    const instanceText = (i) => {
      const cards = M.t("join.instance.cards", { count: i.claims || 0 });
      return i.presence === "online" ? M.t("join.instance.online", { label: i.label || i.id, cards })
        : M.t("join.instance.seen", { label: i.label || i.id, ago: formatAgo(i.last_seen_at, M.api.now()), cards });
    };
    // An agent already here: the membership's fields, which its join and its start on a runner
    // leave out, are shown as they are, off, where they always stand, with the way to Manage
    // (tsk-6w4qckma672q). What was typed for another agent comes back when one is chosen again.
    const membershipNote = h("p", { class: "hint field wide join-membership-note" });
    membershipNote.hidden = true;
    let shownMember = null; // the membership whose fields are shown, else null
    let draft = null;       // the form's own values while a membership's are shown
    // A value the form would not offer: its option added until the list is filled again.
    const showValue = (select, value, label) => {
      if (!Array.from(select.querySelectorAll("option")).some((o) => o.getAttribute("value") === value)) append(select, h("option", { value }, label));
      select.value = value;
    };
    function showMembership(m) {
      if (m && !shownMember) {
        draft = { trust: trust.value, role: role.value, areas: areas.value, briefing: briefing.value, subagents: subagents.checked,
          english: english.checked, touched: subagentsTouched, takesOver: takesOver.value, handover: handover.value };
      }
      const was = shownMember;
      shownMember = m;
      if (m) {
        fillTrust();
        fillRoles();
        areas.value = (m.areas || []).join(", ");
        briefing.value = m.briefing || "";
        // A membership that predates the field has its role's default (§6.2).
        subagents.checked = typeof m.subagents === "boolean" ? m.subagents : SUBAGENT_ROLES.includes(m.role);
        english.checked = m.subagents_language === "en";
        const over = m.takes_over && (m.takes_over.member_id || m.takes_over);
        if (over) showValue(takesOver, over, M.t("join.takes_over.option", { name: ctx.nameOf(over), handle: m.takes_over.handle || over }));
        else takesOver.value = "";
        handover.value = !m.handover ? "" : m.handover.kind === "task" ? String(m.handover.id) : "#" + m.handover.id;
        clear(membershipNote);
        // An outsider has no Manage of its own agent's membership here: the sentence alone.
        append(membershipNote, M.t("join.membership.readonly"), outside ? null : [" ", M.tn("join.membership.manage", { link: ctx.canAdmin
          ? h("a", { class: "join-manage-link", href: ctx.link("team") + "?manage=" + encodeURIComponent(m.id) }, M.t("memberpage.manage_members"))
          : h("a", { class: "join-manage-link", href: ctx.link("agents", m.id) }, M.t("memberpage.manage_agents")) })]);
      } else if (was && draft) {
        trust.value = draft.trust;
        fillTrust();
        role.value = draft.role;
        fillRoles();
        areas.value = draft.areas;
        briefing.value = draft.briefing;
        subagents.checked = draft.subagents;
        english.checked = draft.english;
        subagentsTouched = draft.touched;
        takeOverOptions();
        takesOver.value = Array.from(takesOver.querySelectorAll("option")).some((o) => o.getAttribute("value") === draft.takesOver) ? draft.takesOver : "";
        handover.value = draft.handover;
        draft = null;
      }
      membershipNote.hidden = !m;
    }
    // A membership's fields are off, and a join line's own while on a runner (§15.6: takes_over,
    // handover and ttl_seconds stay join-only), each with its reason.
    function settle(m, on) {
      [trust, role, areas, briefing, subagents].forEach((c) => { c.disabled = !!m; });
      english.disabled = !!m || !subagents.checked;
      takesOver.disabled = handover.disabled = !!m || on;
      ttl.disabled = on;
      [takeOverWhy, handoverWhy, ttlWhy].forEach((p) => { p.hidden = !on; });
      describe(takesOver, ["join-takes-over-hint", on ? takeOverWhy.id : null]);
      describe(handover, ["join-handover-hint", on ? handoverWhy.id : null]);
      describe(ttl, [on ? ttlWhy.id : null]);
    }
    // One click to what the form cannot change (tsk-svqsdp6qf0f3): the chosen agent's profile
    // and, where it is a member here, the rulebook with its instance limit.
    const profileLinks = h("p", { class: "hint join-profile-links" });
    function profileLinksFor(id, member) {
      clear(profileLinks);
      profileLinks.hidden = !id;
      if (!id) return;
      append(profileLinks, h("a", { href: "/agents/" + encodeURIComponent(id) }, M.t("join.profile_link")),
        member && !outside ? [" · ", h("a", { href: ctx.link("agents", id, "rulebook") }, M.t("join.rulebook_link"))] : null);
    }
    // The choice starts from its default for each agent shown as a member.
    let shownFor = "";
    let drawAhead = null; // set with the restricted-access line below
    // The instance choice before the runner part was turned on, given back when it is turned off.
    let instanceKept = null;
    // The fields as the agent chosen asks; the runner part hides and changes nothing above it.
    function showAgent() {
      admitting = own && !!viaRunner && viaRunner.on();
      markAdmitting();
      showJoinFields();
      if (!viaRunner) return;
      followRunner();
      create.textContent = viaRunner.on() ? M.t("placements.new.submit") : M.t("join.create");
    }
    function showJoinFields() {
      const m = agentSelect.value ? memberOf(agentSelect.value) : null;
      const on = !!viaRunner && viaRunner.on();
      const fresh = (m ? m.id : "") !== shownFor;
      shownFor = m ? m.id : "";
      newFields.hidden = agentSelect.value !== "";
      // Hidden, the new profile's fields are off too: a handle typed for one and refused by its
      // pattern no longer blocks the form once an agent is chosen (review of #1558, #1919). A
      // member's start on a runner takes no new profile: shown, off, with the reason.
      handle.disabled = display.disabled = newFields.hidden || admitting;
      newWhy.hidden = newFields.hidden || !admitting;
      instanceBox.hidden = !m;
      reportsOptions();
      takeOverOptions();
      showMembership(m);
      // Reports to stands in one place: the new membership's boss, or the boss of the agent
      // already here, which its owner changes here (a PATCH before the join or the start).
      if (reportsField) reportsField.hidden = !!m;
      memberReportsField.hidden = !m || !!outside;
      if (m && fresh) memberReportsOptions(m);
      settle(m, on);
      profileLinksFor(agentSelect.value, m);
      // The line before the join follows the profile chosen, also when `open()` chooses it
      // (no `change` event) or the members are read again.
      if (drawAhead) drawAhead();
      if (fresh) instanceKept = null;
      if (!m) return;
      const active = activeOf(m);
      const kept = replaced.value;
      append(clear(replaced), active.map((i) => h("option", { value: i.id }, instanceText(i))));
      replaced.value = active.some((i) => i.id === kept) ? kept : active.length ? active[0].id : "";
      replaceOne.disabled = replaced.disabled = !active.length;
      if (fresh || !active.length) { replaceOne.checked = active.length > 0; another.checked = !active.length; }
      // On a runner the start is another instance (§15.5); Replace is off with why, and the
      // choice made before comes back when the part is turned off.
      if (on) {
        if (instanceKept === null) instanceKept = replaceOne.checked;
        replaceOne.checked = false;
        another.checked = true;
        replaceOne.disabled = replaced.disabled = true;
      } else if (instanceKept !== null) {
        if (!replaceOne.disabled) { replaceOne.checked = instanceKept; another.checked = !instanceKept; }
        instanceKept = null;
      }
      noReplace.hidden = !on;
      describe(replaceOne, [on ? noReplace.id : null]);
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

    // An agent never holds trust owner; admin and the role proxy only from an
    // owner, proxy only with trust admin (§3.1, owner_only §2.3).
    const trusts = outside ? ["outside"] : own ? M.trust.MEMBER_TRUSTS : ctx.isOwner ? ["member", "guest", "admin"] : ["member", "guest"];
    const trust = h("select", { id: "join-trust" });
    // The trusts offered, and a membership's own where it is shown (showMembership).
    const fillTrust = () => {
      const wanted = shownMember ? shownMember.trust : trust.value;
      const list = shownMember && wanted && !trusts.includes(wanted) ? trusts.concat([wanted]) : trusts;
      append(clear(trust), list.map((r) => h("option", { value: r }, M.trust.trustWord(r))));
      trust.value = list.includes(wanted) ? wanted : trusts[0];
    };
    fillTrust();
    const role = h("select", { id: "join-role" });
    // The project's own roles follow the built-in ones (§2.3): for one's own agent only those on
    // a base a member join may give (not ops), as the hub's member limits check it. A start on a
    // runner takes this role too: with members:admin every base, as validate_assignment takes it
    // for a placement, and a member's own profile admitted the member join's bases (§15.6).
    const takeOwn = (list) => (own ? list.filter((x) => M.trust.MEMBER_ROLES.includes(x.base)) : list);
    // An outsider's roles are the policy's list as `…/contribution` gives it; the project's roles
    // are a member's read (§2.3), so a project role there reads by its name.
    let ownRoles = outside ? [] : takeOwn(M.trust.projectRoles(ctx, (list) => { ownRoles = takeOwn(list); if (ownRoles.length) fillRoles(); }));
    const fallback = outside ? outside.roles[0] : "coder";
    const fillRoles = () => {
      const wanted = shownMember ? shownMember.role : role.value || fallback;
      const offered = outside ? outside.roles.slice()
        : (own ? M.trust.MEMBER_ROLES : M.trust.ROLES.filter((r) => r !== "proxy" || (ctx.isOwner && trust.value === "admin")))
          .concat(ownRoles.map((x) => x.name));
      // A membership's role shown although this form would not give it.
      if (shownMember && wanted && !offered.includes(wanted)) offered.push(wanted);
      M.trust.fillRoles(role, offered, wanted, fallback, ownRoles);
    };
    const roleHelp = M.trust.roleHint(role);
    // The owner's instruction to work in subagents (docs/api.md §3.1): on by default for
    // coder and reviewer, following the role until the box is touched. It is written in the
    // language this dashboard shows, or in English when asked: sent as `subagents_language`, so
    // it never falls to a language the hub would pick without the human seeing it.
    const subagents = h("input", { type: "checkbox", id: "join-subagents", "aria-describedby": "join-subagents-hint" });
    const english = h("input", { type: "checkbox", id: "join-subagents-english" });
    let subagentsTouched = false;
    const SUBAGENT_ROLES = ["coder", "reviewer"];
    const followRole = () => {
      if (!subagentsTouched) subagents.checked = SUBAGENT_ROLES.includes(role.value);
      english.disabled = !subagents.checked;
    };
    subagents.addEventListener("change", () => { subagentsTouched = true; followRole(); });
    role.addEventListener("change", followRole);
    trust.addEventListener("change", fillRoles);
    trust.addEventListener("change", followRole);
    fillRoles();
    followRole();
    const subagentsField = h("div", { class: "field wide join-subagents" },
      h("div", { class: "join-offer" }, subagents, " ", h("label", { for: "join-subagents" }, M.t("join.subagents.label"))),
      h("p", { class: "hint", id: "join-subagents-hint" }, M.t("join.subagents.hint")),
      M.i18n.language === "en" ? null
        : h("div", { class: "join-offer" }, english, " ", h("label", { for: "join-subagents-english" }, M.t("join.subagents.english"))));
    // Before the join: whether the agent will read the project's restricted texts (§6.1
    // "Every way into the set"). It is the creator's agent, as every agent a join makes.
    const ahead = M.restricted && !outside ? M.restricted.aheadLine() : null;
    drawAhead = () => {
      if (!ahead) return;
      const id = agentSelect.value;
      if (id && memberOf(id)) { ahead.show(null); return; } // a new instance enters nothing
      const fresh = id || "join:new-agent";
      const profile = id ? profiles.offered.find((p) => p.id === id) : null;
      const name = profile ? profile.display_name : display.value.trim() || handle.value.trim() || M.t("join.ahead.the_agent");
      ahead.show(M.restricted.ahead(ctx, (members) => members.concat([{ id: fresh, kind: "agent", owner_id: ctx.me.id,
        trust: trust.value, display_name: name, handle: profile ? profile.handle : handle.value.trim() || null, isolated: null }]),
      id ? [] : [fresh]));
    };
    [agentSelect, trust].forEach((f) => f.addEventListener("change", drawAhead));
    [handle, display].forEach((f) => f.addEventListener("input", drawAhead));
    // Whom the agent reports to (§3.1, §2.3, §6.2). Every profile offered here is the caller's
    // own, so the caller is the subordinate's owner: oneself and one's own agents apply at once,
    // anyone else is a cross-owner edge, said so in its option, that waits for consent (filed at
    // the exchange for a first join, at once by the PATCH below for an agent already here).
    const ownBoss = (x) => x.id === ctx.me.id || (x.kind === "agent" && x.owner_id === ctx.me.id);
    const bossLabel = (x) => (x.id === ctx.me.id ? M.t("members.reports.you", { name: x.display_name })
      : ownBoss(x) ? M.t("members.reports.agent", { name: x.display_name, handle: M.dom.handleOf(ctx, x) })
      : M.t("members.reports.cross", { name: x.display_name, handle: M.dom.handleOf(ctx, x) }));
    // A guest is never reported to (§2.3). A member's own join offers oneself and one's own
    // managers here only (§3.1), oneself first and chosen; an admin's, every other member too.
    // A manager by the literal role, as the hub checks it: not a project role based on manager.
    const bosses = () => {
      const list = ctx.members.filter((x) => !x.removed_at && !M.trust.guest(x)
        && (!own || x.id === ctx.me.id || (x.kind === "agent" && x.owner_id === ctx.me.id && x.role === "manager")));
      return own && !list.some((x) => x.id === ctx.me.id) ? [ctx.me].concat(list) : list;
    };
    const reportsTo = h("select", { id: "join-reports" });
    const reportsOptions = () => {
      const kept = reportsTo.value;
      const list = bosses();
      append(clear(reportsTo), own ? null : h("option", { value: "" }, M.t("join.reports.nobody")),
        list.map((x) => h("option", { value: x.id }, bossLabel(x))));
      reportsTo.value = list.some((x) => x.id === kept) ? kept : own ? ctx.me.id : "";
    };
    // An agent already here keeps its membership's boss unless it is changed here: its owner's
    // own PATCH (§2.3), sent before the join, so the join page and the first resume show it where
    // it applies at once (200). Waiting for the other side's consent (202), the join page keeps the
    // boss it was issued with (the hub copies it into the join); the resume after the consent shows the new one.
    const memberReports = h("select", { id: "join-member-reports", "aria-describedby": "join-member-reports-hint" });
    // The boss asked for while a consent is open, per member: chosen again, it is not asked twice.
    const asked = new Map();
    const bossNow = (m) => (asked.has(m.id) ? asked.get(m.id) : m.reports_to || "");
    const closesCircle = (m, boss) => {
      const byId = Object.fromEntries(ctx.members.map((x) => [x.id, x]));
      for (let at = boss, seen = new Set(); at && !seen.has(at); at = byId[at] && byId[at].reports_to) {
        if (at === m.id) return true;
        seen.add(at);
      }
      return false;
    };
    function memberReportsOptions(m) {
      const list = ctx.members.filter((x) => !x.removed_at && !M.trust.guest(x) && x.id !== m.id && !closesCircle(m, x.id));
      const now = bossNow(m);
      append(clear(memberReports), h("option", { value: "" }, M.t("join.reports.nobody")),
        list.map((x) => h("option", { value: x.id }, bossLabel(x))),
        now && !list.some((x) => x.id === now) ? h("option", { value: now }, M.t("members.reports.unlisted", { name: ctx.nameOf(now) })) : null);
      memberReports.value = now;
    }
    const memberReportsField = h("div", { class: "field join-member-reports", hidden: true },
      h("label", { for: "join-member-reports" }, M.t("members.edit.reports")), memberReports,
      h("p", { class: "hint", id: "join-member-reports-hint" }, M.t("join.reports.member_hint")));
    // An outsider's agent reports to the caller, never chosen (§3.1 "An outsider's agent").
    const reportsField = outside ? null : h("div", { class: "field join-reports" }, h("label", { for: "join-reports" }, M.t("members.edit.reports")), reportsTo);
    // Areas as the members' Manage calls and explains them (js/members.js).
    const areas = h("input", { id: "join-areas", placeholder: M.t("members.edit.areas.placeholder"), "aria-describedby": "join-areas-hint" });
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
      // Nobody to take over from: no choice to show, unless a membership shown names one.
      const m = agentSelect.value ? memberOf(agentSelect.value) : null;
      takeOverField.hidden = !list.length && !(m && m.takes_over);
    };
    const handover = h("input", { id: "join-handover", maxlength: "200", autocomplete: "off", spellcheck: "false",
      placeholder: M.t("join.handover.placeholder"), "aria-describedby": "join-handover-hint" });
    // Join-only (§15.6): off while the agent starts on a runner, each saying why (settle).
    const runnerWhy = (id, text) => { const p = h("p", { class: "hint join-runner-only", id }, text); p.hidden = true; return p; };
    const takeOverWhy = runnerWhy("join-takes-over-runner", M.t("join.runner.join_only"));
    const handoverWhy = runnerWhy("join-handover-runner", M.t("join.runner.join_only"));
    const ttlWhy = runnerWhy("join-ttl-runner", M.t("join.runner.no_line"));
    const takeOverField = h("div", { class: "field" }, h("label", { for: "join-takes-over" }, M.t("join.field.takes_over")), takesOver,
      h("p", { class: "hint", id: "join-takes-over-hint" }, M.t("join.takes_over.hint")), takeOverWhy);
    const handoverField = h("div", { class: "field" }, h("label", { for: "join-handover" }, M.t("join.field.handover")), handover,
      h("p", { class: "hint", id: "join-handover-hint" }, M.t("join.handover.hint")), handoverWhy);
    const ttl = h("select", { id: "join-ttl" },
      [900, 1800, 3600].map((v) => h("option", { value: String(v) },
        v < 3600 ? M.t("join.ttl.minutes", { count: v / 60 }) : M.t("join.ttl.hours", { count: v / 3600 }))));

    const ttlField = h("div", { class: "field" }, h("label", { for: "join-ttl" }, M.t("join.field.ttl")), ttl, ttlWhy);

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

    // §3.1: all lines come in the one answer, as the code appears nowhere else. The browser's
    // system is only a first guess, since the agent may run elsewhere; the choice is remembered
    // per browser. Which shell runs a line is the agent's business, so there is no choice of shell.
    const PLATFORM_KEY = "maity.join.platform";
    function initialPlatform(lines) {
      try {
        const kept = window.localStorage.getItem(PLATFORM_KEY);
        if (kept && lines[kept]) return kept;
      } catch (err) { /* this browser keeps nothing */ }
      if (!/^win/i.test(navigator.platform || "")) return "posix";
      // windows is null where the instance's install line cannot run in PowerShell (§3.2).
      return lines.windows ? "windows" : "join";
    }

    function showLine(j, member, bossSaid) {
      const lines = j.paste_lines;
      let platform = initialPlatform(lines);
      const line = h("code", { class: "paste-line" }, lines[platform]);
      const offer = (value, label) => {
        if (!lines[value]) return null;
        const id = "join-line-" + value;
        const radio = h("input", {
          type: "radio", name: "join-line", id, value,
          onchange: () => {
            platform = value;
            line.textContent = lines[value];
            copy.textContent = M.t("join.copy.label");
            try { window.localStorage.setItem(PLATFORM_KEY, value); } catch (err) { /* as above */ }
          },
        });
        radio.checked = value === platform;
        return h("div", { class: "join-offer" }, radio, " ", h("label", { for: id }, label));
      };
      const offers = h("fieldset", { class: "join-offers" },
        h("legend", null, M.t("join.platform.label")),
        offer("join", M.t("join.platform.join")),
        offer("posix", M.t("join.platform.posix")),
        offer("windows", M.t("join.platform.windows")));
      const copy = h("button", {
        type: "button",
        onclick: async () => {
          try {
            // The instruction first, a blank line, then the line (§3.1): one message.
            await navigator.clipboard.writeText(j.instruction ? j.instruction + "\n\n" + j.paste_lines[platform] : j.paste_lines[platform]);
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
        bossSaid ? h("p", { class: "join-reports-said" }, bossSaid) : null,
        offers,
        j.instruction ? h("div", { class: "join-instruction" },
          h("p", null, M.t("join.line.instruction")),
          h("blockquote", { class: "join-instruction-text" }, j.instruction)) : null,
        h("div", { class: "paste-row" }, line, copy),
        h("p", { class: "first-hint" }, M.t("join.line.hint")),
        h("div", { class: "actions" }, again, h("button", { type: "button", class: "primary", onclick: () => close(true) }, M.t("join.line.done")))));
      copy.focus();
    }

    // On a runner instead of a join line (§15.6): the agent and its place in the team from the
    // form (an agent here by its id alone, a new profile or one's own not here yet with its join
    // fields), the rest from the runner part; one POST, no line. Made, the panel closes and the
    // line under it says so, with the way to where it runs; refused, the hub's message and the
    // fields it names stay here.
    // Whether the runner part can start the chosen agent now: said and true when it cannot, before
    // anything is sent (a boss changed on the form is not saved for a start that cannot be made).
    function placeRefused() {
      const no = viaRunner.blocked() || (!viaRunner.ready() ? M.t("placements.new.not_ready") : null);
      if (no) { status.fail(M.t("placements.new.failed"), { message: no }); viaRunner.first().focus(); return true; }
      // A tool that starts only on a named model (opencode) is never sent without one.
      const unnamed = viaRunner.unnamed();
      if (unnamed) { status.fail(M.t("placements.new.failed"), { message: unnamed }); viaRunner.model().focus(); return true; }
      return false;
    }
    // bossSaid: a boss of the agent already here saved by its PATCH just before; a refused start
    // says that it stays saved.
    async function place(agent, member, text, mine, bossSaid) {
      // A profile of one's own not in the project yet: the placement admits it with the fields of
      // a first join, as the join would carry them (§15.6, §3.1). A member's (`admitting`): trust,
      // role, oneself or one's own manager as the boss, the briefing, subagents; no areas or
      // capabilities. An admin's: an admin's join fields, as for a new profile
      // (`first_join_fields`). An agent already here: its id alone, as a placement never changes
      // a membership (not_with_agent_id).
      const admits = !!agent.id && !member;
      const req = admits && admitting ? { agent: { id: agent.id }, trust: trust.value, role: role.value, reports_to: reportsTo.value || ctx.me.id }
        : agent.id && !admits ? { agent: { id: agent.id } } : {
          agent,
          trust: trust.value,
          role: role.value,
          reports_to: reportsTo.value || null,
          areas: areas.value.split(",").map((a) => a.trim()).filter(Boolean),
          capabilities: [],
        };
      if ((admits || !agent.id) && text) req.briefing = text;
      // The owner's subagent instruction, as the join sends it (§15.6 takes it as in a join).
      if (admits || !agent.id) {
        followRole();
        req.subagents = subagents.checked;
        if (subagents.checked) req.subagents_language = english.checked ? "en" : M.i18n.language;
      }
      Object.assign(req, viaRunner.body());
      status.busy(M.t("placements.new.busy"));
      create.disabled = true;
      let made;
      try {
        made = await M.api.post(ctx.base + "/placements", req);
      } catch (err) {
        // Closed meanwhile: close() freed the form, and a form opened since is not this
        // submission's to touch (review of #1919).
        if (mine !== submission) return;
        const say = () => {
          const limit = own ? memberRefusal(err) : null;
          if (limit) status.fail(M.t("placements.new.failed"), limit);
          else viaRunner.refuse(status, err);
          // The boss changed just before stays changed: said plainly, not undone.
          if (bossSaid) append(status.el, " ", h("span", { class: "flag join-reports-said" }, M.t("join.reports.kept", { said: bossSaid })));
        };
        say();
        const fields = (err.code === "invalid" && err.details && err.details.fields) || {};
        if (fields.handle === "taken" && agent.handle) { refused.add(agent.handle); checkHandle(); handle.focus(); }
        // Join fields for a profile the list on screen took for one not here yet: the members
        // are read again, the button held until then.
        if (admits && Object.values(fields).includes("not_with_agent_id")) { await recheckMember(mine, say); return; }
        create.disabled = false;
        return;
      }
      // Made even when the panel was closed meanwhile: the line says so all the same, and a form
      // opened since keeps its draft, its button and the focus.
      if (mine === submission) {
        create.disabled = false;
        status.done();
        close(true);
      }
      // The agent placed now is placed: the part reads again before it is offered next; in a
      // form opened meanwhile, at its next opening, not under the fields being typed.
      if (panel.hidden) viaRunner.reread();
      append(clear(listStatus.el), h("span", { class: "ok" }, M.t("placements.new.done",
        { name: made.agent.display_name || made.agent.handle, runner: made.runner.name })), " ",
      h("a", { href: ctx.link("placements") }, M.t("placements.title")),
      bossSaid ? [" ", h("span", { class: "join-reports-said" }, bossSaid)] : null);
      listStatus.el.className = "send-status";
      if (hooks.started) await hooks.started(made);
      // A new profile is one's own now: offered by name, its handle taken.
      // The choice shown stays (a form opened meanwhile keeps its draft).
      try {
        profiles = await readProfiles(ctx);
        const kept = agentSelect.value;
        profileOptions();
        agentSelect.value = kept;
        showAgent();
        checkHandle();
      } catch (ignored) { /* the placement is made; the list catches up when read again */ }
    }

    // "Already a member" (not_with_agent_id) for a profile a start sent to be admitted: the
    // members are read again, and only a list that shows it as a member makes the next start its
    // id alone. A list without it keeps the admission draft as filled in, and the refusal; a read
    // that fails keeps both too and offers to read again. On the hub's word alone, a membership
    // gone before the next start would be admitted again with the hub's defaults, and the role,
    // boss, areas and briefing shown here dropped unseen. The button is held until the read is
    // done; a panel closed meanwhile (`submission` counted on) is not touched.
    async function recheckMember(mine, say) {
      let failed = null;
      try { M.withMembers(ctx, (await M.api.getAll(ctx.base + "/members")).items); } catch (err) { failed = err; }
      if (mine !== submission) return;
      create.disabled = false;
      showAgent();
      say();
      if (!failed) return;
      const again = h("button", { type: "button", class: "join-members-again", onclick: () => {
        if (again.disabled) return;
        again.disabled = create.disabled = true;
        recheckMember(submission, say);
      } }, M.t("join.retry"));
      append(status.el, " ", h("span", { class: "join-members-unread" },
        M.t("placements.new.members_unread", { reason: failed.message || failed.code || M.t("join.an_error") })), " ", again);
    }

    // Held while a join is being created: one join per submission, by click or Ctrl+Enter.
    const create = h("button", { type: "submit", class: "primary" }, M.t("join.create"));
    // Where the second factor is asked for when the hub wants it for the join.
    const stepSlot = h("div", { class: "step-up-slot" });
    stepSlot.hidden = true;
    // Counts the submissions: closing the panel starts a new count, so a submission
    // still waiting for its code is not sent once the panel was closed.
    let submission = 0;
    const form = h("form", {
      class: "join-form",
      onsubmit: async (e) => {
        e.preventDefault();
        if (create.disabled) return;
        let agent;
        // A member's start on a runner of an agent it does not take (one already here, or a new
        // profile), chosen before the part was turned on: refused here with the reason.
        if (admitting && !runnerTakes(agentSelect.value)) {
          status.fail(M.t("placements.new.failed"), { message: M.t("join.runner.own_agents") });
          agentSelect.focus();
          return;
        }
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
        // A start on a runner is left to the hub's member_agents_max: a profile that a placement
        // admits already holds its slot there, which this count does not see (§3.1, §15.6).
        // A profile already held (an open first join of one's own) takes no new slot either.
        if (!member && !(viaRunner && viaRunner.on()) && hooks.full && hooks.full(agent.id)) {
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
        const placing = !!viaRunner && viaRunner.on();
        if (placing && placeRefused()) return;
        const req = placing ? null : member
          ? Object.assign({ agent, ttl_seconds: Number(ttl.value) },
            replaceOne.checked && replaced.value ? { replaces: replaced.value } : { new_instance: true })
          // One's own agent (§3.1): oneself (the default) or one of one's own managers here.
          // An outsider's: the caller, never another boss (§3.1 "An outsider's agent"); stored as nobody.
          : own ? { agent, trust: trust.value, role: role.value, reports_to: outside ? ctx.me.id : reportsTo.value || ctx.me.id, ttl_seconds: Number(ttl.value) }
          : {
            agent,
            trust: trust.value,
            role: role.value,
            reports_to: reportsTo.value || null,
            areas: areas.value.split(",").map((a) => a.trim()).filter(Boolean),
            capabilities: [],
            ttl_seconds: Number(ttl.value),
          };
        if (req && text) req.briefing = text;
        if (req && !member) {
          followRole();  // an untouched box takes the role chosen now
          req.subagents = subagents.checked;
          if (subagents.checked) req.subagents_language = english.checked ? "en" : M.i18n.language;
        }
        if (req && !member && takesOver.value && !takeOverField.hidden) req.takes_over = takesOver.value;
        if (req && !member && handover.value.trim()) req.handover = handoverValue(handover.value.trim());
        // An agent already here whose boss was changed in the panel: that PATCH first (§2.3),
        // then the join or the start on a runner. Refused, nothing is sent after it; taken, it
        // stays whatever the join or the start does, and the panel says so beside its outcome.
        // This submission's number, taken before the first wait: a panel closed meanwhile
        // (close() counts on) ends it, so neither the PATCH's outcome nor a join follows.
        const mine = ++submission;
        let bossSaid = null;
        if (member && memberReports.value !== bossNow(member)) {
          const to = memberReports.value || null;
          status.busy(M.t("join.reports.saving"));
          create.disabled = true;
          let answer;
          try {
            answer = await M.api.patch(ctx.base + "/members/" + encodeURIComponent(member.id), { reports_to: to });
          } catch (err) {
            // Closed meanwhile: close() freed the form, and a form opened since is not this
            // submission's to touch (review of #1919).
            if (mine !== submission) return;
            create.disabled = false;
            status.fail(placing ? M.t("join.reports.failed_start") : M.t("join.reports.failed"), err);
            memberReports.focus();
            return;
          }
          const name = profileName(member.id);
          // 202: the edge waits for the other side's consent (§6.2), the membership as it was.
          if (answer && answer.class === "consent" && /^req-/.test(answer.id || "")) {
            asked.set(member.id, to || "");
            bossSaid = M.t("join.reports.waiting", { name, boss: ctx.nameOf(to), id: answer.id });
          } else {
            asked.delete(member.id);
            member.reports_to = to;
            bossSaid = to ? M.t("join.reports.saved", { name, boss: ctx.nameOf(to) }) : M.t("join.reports.saved_nobody", { name });
          }
          // Taken, the boss stays (kept above for the next submission); closed meanwhile, no join.
          if (mine !== submission) return;
        }
        if (placing) { await place(agent, member, text, mine, bossSaid); return; }
        const sayBoss = () => { if (bossSaid) append(status.el, " ", h("span", { class: "flag join-reports-said" }, bossSaid)); };
        status.busy(M.t("join.creating"));
        create.disabled = true;
        let j;
        try {
          // Creating a join is a sensitive call (§2.8.4): the hub asks for the
          // second factor first, by app or by mail, and the join is sent again.
          j = await M.stepUp.run(() => (mine === submission ? M.api.post(ctx.base + "/joins", req)
            : Promise.reject(new M.api.ApiError(M.t("stepup.cancelled"), 0, "", "cancelled"))), stepSlot, M.t("join.step_up"));
        } catch (err) {
          // Closed meanwhile: its refusal is not the newer form's to say.
          if (mine !== submission) return;
          if (err.code === "cancelled") { status.done(); sayBoss(); return; }
          const fields = (err.code === "invalid" && err.details && err.details.fields) || {};
          const why = fields.handle;
          const d = err.details || {};
          const takeover = ["takes_over", "handover"].find((f) => Object.hasOwn(TAKEOVER_REFUSALS, f + ":" + fields[f]));
          status.fail(M.t("join.failed"), why === "taken" ? { message: M.t("join.failed.taken", { handle: agent.handle }) }
            : takeover ? { message: TAKEOVER_REFUSALS[takeover + ":" + fields[takeover]]() }
            : (outside && outsiderRefusal(err)) || memberRefusal(err) || err);
          sayBoss();
          // The limit is the agent owner's rulebook, on its card on Agents (§6.18).
          if (takeover || d.field === "takes_over") (takeover === "handover" ? handover : takesOver).focus();
          // An outsider has no Agents view: no link that would be not found.
          if (err.code === "instance_quota" && agent.id && !outside) {
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
            // Closed while the members were read: the members are taken, the form opened since
            // keeps its choice, its status and the focus (A1265 at #1919).
            if (mine !== submission) return;
            showAgent();
            if (saysMember) { status.fail(M.t("join.failed"), { message: M.t("join.failed.is_member") }); sayBoss(); }
            (replaceOne.checked && !replaceOne.disabled ? replaced : another).focus();
          }
          if (why) {
            // The hub knows better than the list on screen: read it again, and say so at the field.
            if (why === "taken") refused.add(agent.handle);
            try { profiles = await readProfiles(ctx); } catch (ignored) { /* the refusal above says enough */ }
            // Closed while the profiles were read: the agent chosen since stays chosen (A1265 at #1919).
            if (mine !== submission) return;
            profileOptions();
            agentSelect.value = "";
            checkHandle();
            handle.focus();
          }
          return;
        } finally {
          // Only this submission's own button: a form opened since keeps its own state.
          if (mine === submission) create.disabled = false;
        }
        // Created after the panel was closed: the join is made, the lists catch up, and the form
        // opened since stays as it is (review of #1919).
        if (mine !== submission) { reread(); return; }
        status.done();
        showLine(j, member, bossSaid);
        // A new profile is named in the select, the new join is a seat.
        try {
          [profiles, joins] = await Promise.all([readProfiles(ctx), M.api.getAll(ctx.base + "/joins")]);
        } catch (err) {
          listStatus.fail(M.t("join.created_unread"), err);
          return;
        }
        // Done while the lists were read: the new profile is offered and the new seat listed,
        // as after a placement; the form opened since keeps its choice (A1265 at #1919).
        if (mine !== submission) {
          const kept = agentSelect.value;
          profileOptions();
          agentSelect.value = kept;
          showAgent();
          checkHandle();
          changed();
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
        // One shape whichever way the agent comes in (tsk-6w4qckma672q): the agent, a new
        // profile, the instance, then the membership in the order and words of the members'
        // Manage (js/members.js), then what only a join line takes; the briefing beside them,
        // the runner part at the end.
        h("div", { class: "field wide" }, h("label", { for: "join-agent" }, M.t("join.field.agent")), agentSelect, agentWhy, profileLinks),
        newFields,
        instanceBox,
        membershipNote,
        outside ? null : h("div", { class: "field" }, h("label", { for: "join-trust" }, M.t("members.edit.trust")), trust),
        h("div", { class: "field" }, h("label", { for: "join-role" }, M.t("members.edit.role")), role, roleHelp),
        reportsField,
        memberReportsField,
        outside ? h("p", { class: "hint field wide join-outside-hint" }, M.t("join.field.outsider_hint"))
          : own ? h("p", { class: "hint field wide" }, M.t("join.field.own_hint"))
          : h("div", { class: "field" }, h("label", { for: "join-areas" }, M.t("members.edit.areas")), areas,
            h("p", { class: "hint", id: "join-areas-hint" }, M.t("members.edit.areas.hint"))),
        subagentsField,
        takeOverField,
        // An outsider's join hands over a card it reads only, never a message (§3.1, H1 at
        // 39497bfb): the field, which takes both, is left out for it.
        outside ? null : handoverField,
        ttlField),
      h("div", { class: "join-briefing" },
        h("label", { for: "join-briefing" }, M.t("join.briefing.label", { keys: M.dom.SEND_KEYS })), briefing,
        h("p", { class: "hint" }, M.t("join.briefing.hint")))),
    viaRunner ? viaRunner.el : null,
    ahead ? ahead.el : null,
    stepSlot,
    h("div", { class: "actions" }, h("button", { type: "button", onclick: () => close(true) }, M.t("join.cancel")), create),
    status.el);

    function showForm() { append(clear(body), form); drawAhead(); }
    showForm();
    showAgent();
    append(clear(panel), panelHead(ctx, () => close(true), own, !!outside), body);

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
      // The runners and placements as they are now, when the part is on.
      if (viaRunner) viaRunner.reread();
      rereadMembers().then(() => { if (!panel.hidden) showAgent(); });
    }
    function close(refocus) {
      // A code question still open belongs to the submission being closed: it ends
      // with it, and the next submission sends the fields then shown.
      submission++;
      // A submission still waiting ends with it: the form opens again free (review of #1919).
      create.disabled = false;
      status.done();
      M.stepUp.cancel(stepSlot);
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

  // The project the join is for, by name and full name: with several
  // projects open it must not be guessed from the tab.
  function panelHead(ctx, onClose, own, outside) {
    const project = ctx.project || {};
    const full = project.full_name || ctx.slug || "";
    return [
      h("div", { class: "join-head" },
        h("h3", { id: "join-title" }, outside ? M.t("outsider.add_agent") : own ? M.t("join.title.own") : M.t("join.title")),
        h("button", { type: "button", class: "icon-button join-close", "aria-label": M.t("join.close"), title: M.t("join.close"), onclick: onClose }, M.icons.close(16))),
      h("p", { class: "join-project" }, M.t("join.project", { name: project.name || ctx.slug || full, full })),
      h("p", { class: "muted" }, M.t("join.intro")),
    ];
  }

  // hooks.started(placement): after a start on a runner, for a page that lists placements.
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
        // A member, or an outsider, sees their own joins only, the ones they may revoke (§3.1).
        if (hooks.member || hooks.outsider) joins.items = joins.items.filter((j) => j.created_by === ctx.me.id);
        impl = build(ctx, hooks, panel, listStatus, profiles, joins);
        listStatus.done();
        return true;
      } catch (failed) {
        impl = null;
        // An outsider's joins read answers not_found once the opt-in closed: said in words.
        const err = (hooks.outsider && outsiderRefusal(failed)) || failed;
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
        append(clear(panel), panelHead(ctx, failedClose, !!hooks.member || !!hooks.outsider, !!hooks.outsider),
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
