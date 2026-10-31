// Your agents (/agents, docs/api.md §6.3, §16.11): every agent profile of the
// human, across projects, from the gear menu beside Runners. Each profile
// with its picture, its memberships (project, trust and role, the instances
// against the team's limit), Add to a project, its name, git identity and
// handle, and its deletion; a new profile at the top. Adding to a project is
// the join panel on that project's Members (js/join.js), opened with the
// profile chosen: one component, in the project and from here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const HANDLE = M.dom.NAME_RULES.handle;

  // The hub's refusals of a profile's fields (§6.3, §6.24), in words.
  // Getters: the words are the catalog's when said.
  const FIELD_WORDS = {
    get taken() { return M.t("agents.field.taken"); },
    get reserved() { return M.t("agents.field.reserved"); },
    get string_pattern_mismatch() { return HANDLE.text; },
    get string_too_short() { return M.t("agents.field.required"); },
    get invalid() { return M.t("agents.field.git"); },
  };
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) {
      return { message: Object.entries(fields).map(([k, v]) => M.t("agents.refused.field", { field: k.replace("_", " "),
        why: Object.hasOwn(FIELD_WORDS, v) ? FIELD_WORDS[v] : v })).join("; ") };
    }
    if (err.code === "alias_limit") return { message: M.t("agents.refused.aliases") };
    if (err.code === "rate_limited") return { message: M.t("agents.refused.rate") };
    return err;
  }

  // A project one may bring an agent into: one's trust there is owner or
  // admin, or member where the project lets members bring their own (§3.1);
  // the join panel there says the rest.
  const mayBring = (p) => ["owner", "admin", "member"].includes(p.trust);

  function newProfile(done) {
    const status = M.statusLine();
    const handle = h("input", { id: "agent-new-handle", required: true, autocomplete: "off", spellcheck: "false", pattern: HANDLE.pattern, maxlength: "31" });
    const name = h("input", { id: "agent-new-name", required: true, maxlength: "100", autocomplete: "off" });
    const go = h("button", { type: "submit" }, M.t("agents.new.create"));
    return h("form", {
      class: "agent-new project-form",
      onsubmit: async (e) => {
        e.preventDefault();
        go.disabled = true;
        status.busy(M.t("agents.new.creating"));
        try {
          const made = await M.api.post("/agents", { handle: handle.value.trim().replace(/^@/, ""), display_name: name.value.trim() });
          done(made, M.t("agents.new.done", { handle: made.handle }));
        } catch (err) {
          status.fail(M.t("agents.new.failed"), said(err));
          go.disabled = false;
        }
      },
    },
    h("h3", null, M.t("agents.new.title")),
    h("label", { for: "agent-new-handle" }, M.t("agents.handle")), handle, h("p", { class: "hint" }, HANDLE.text),
    h("label", { for: "agent-new-name" }, M.t("agents.display_name")), name,
    go, status.el);
  }

  // A membership's line: the project, trust and role, the instances against
  // the team's limit as that project's member view has them.
  function membershipLine(ctx, a, m, view) {
    const active = view ? (view.instances || []).filter((i) => !i.revoked_at).length : null;
    const max = view && view.team ? view.team.max_instances : null;
    return h("li", { class: "agent-membership" },
      h("a", { href: "/" + M.api.projectPath(m.project) + "/agents/" + encodeURIComponent(a.id) }, m.project),
      h("span", { class: "muted" }, " · " + M.trust.words(m)),
      active === null ? null : h("span", { class: "muted" }, " · " + (max ? M.t("agents.instances_max", { active, count: max }) : M.t("agents.instances", { count: active }))),
      " ", h("a", { class: "small", href: "/" + M.api.projectPath(m.project) + "/agents/" + encodeURIComponent(a.id) + "/rulebook" }, M.t("agents.rulebook")));
  }

  function addToProject(ctx, a) {
    const projects = (ctx.projects || []).filter(mayBring);
    if (!projects.length) return h("p", { class: "muted" }, M.t("agents.add.none"));
    const id = "agent-add-" + a.id;
    const pick = h("select", { id }, projects.map((p) => h("option", { value: p.full_name }, M.t("agents.add.option", { name: p.name, full: p.full_name }))));
    pick.value = projects[0].full_name;
    const go = h("button", { type: "submit" }, M.t("agents.add.submit"));
    return h("form", {
      class: "agent-add inline-form",
      onsubmit: (e) => {
        e.preventDefault();
        // The project's own join panel, this profile chosen: there its rules apply.
        M.route.go("/" + M.api.projectPath(pick.value) + "/agents/join?agent=" + encodeURIComponent(a.id));
      },
    }, h("label", { for: id }, M.t("agents.add.label")), pick, go,
    h("p", { class: "hint" }, M.t("agents.add.hint")));
  }

  function editForm(a, done) {
    const status = M.statusLine();
    const key = (k) => "agent-" + k + "-" + a.id;
    const name = h("input", { id: key("name"), required: true, maxlength: "100" });
    name.value = a.display_name;
    const handle = h("input", { id: key("handle"), required: true, autocomplete: "off", spellcheck: "false", pattern: HANDLE.pattern, maxlength: "31" });
    handle.value = a.handle;
    const gitName = h("input", { id: key("git-name"), autocomplete: "off" });
    gitName.value = (a.git_identity && a.git_identity.name) || "";
    const gitMail = h("input", { id: key("git-email"), type: "email", autocomplete: "off" });
    gitMail.value = (a.git_identity && a.git_identity.email) || "";
    const go = h("button", { type: "submit" }, M.t("agents.edit.save"));
    return h("form", {
      class: "agent-edit project-form",
      onsubmit: async (e) => {
        e.preventDefault();
        const body = {};
        if (name.value.trim() !== a.display_name) body.display_name = name.value.trim();
        const wanted = handle.value.trim().replace(/^@/, "");
        if (wanted !== a.handle) body.handle = wanted;
        const git = gitName.value.trim() || gitMail.value.trim() ? { name: gitName.value.trim(), email: gitMail.value.trim() } : null;
        if (JSON.stringify(git) !== JSON.stringify(a.git_identity || null)) body.git_identity = git;
        if (!Object.keys(body).length) { status.busy(M.t("agents.edit.unchanged")); return; }
        go.disabled = true;
        status.busy(M.t("agents.edit.saving"));
        try {
          const now = await M.api.patch("/agents/" + encodeURIComponent(a.id), body);
          done(now, "handle" in body ? M.t("agents.edit.saved_renamed", { handle: a.handle }) : M.t("agents.edit.saved"));
        } catch (err) {
          go.disabled = false;
          status.fail(M.t("agents.edit.failed"), said(err));
        }
      },
    },
    h("label", { for: key("name") }, M.t("agents.display_name")), name,
    h("label", { for: key("handle") }, M.t("agents.handle")), handle,
    h("p", { class: "hint" }, HANDLE.text + " " + M.t("agents.edit.handle_hint")),
    h("label", { for: key("git-name") }, M.t("agents.edit.git_name")), gitName,
    h("label", { for: key("git-email") }, M.t("agents.edit.git_email")), gitMail,
    h("p", { class: "hint" }, M.t("agents.edit.git_hint")),
    go, status.el);
  }

  // The members of each project a profile is in, read once per project.
  async function memberViews(profiles) {
    const projects = [...new Set(profiles.flatMap((a) => (a.memberships || []).map((m) => m.project)))];
    const lists = await Promise.all(projects.map((full) => M.api.getAll("/projects/" + M.api.projectPath(full) + "/members")
      .then((r) => r.items, () => null)));
    const views = {};
    projects.forEach((full, i) => { (lists[i] || []).forEach((x) => { views[full + " " + x.id] = x; }); });
    return views;
  }

  // One profile's card, on /agents and on a project's Agents: one component.
  // o: {wanted, views, changed (after a save), add (Add to a
  // project), here (what belongs to this project's membership, or none)}.
  function profileCard(ctx, a, o) {
    const marked = o.wanted === a.id;
    return h("li", { class: "agent-card" + (marked ? " wanted" : ""), "data-agent": a.id },
      h("div", { class: "agent-card-head" }, M.avatar(a, 48),
        h("h3", { class: "agent-card-title", tabindex: marked ? "-1" : null }, a.display_name, h("span", { class: "muted" }, " @" + (a.name || a.handle)))),
      (a.memberships || []).length
        ? h("ul", { class: "agent-memberships" }, a.memberships.map((m) => membershipLine(ctx, a, m, o.views[m.project + " " + a.id])))
        : h("p", { class: "muted" }, M.t("agents.card.no_project")),
      o.here || null,
      o.add ? addToProject(ctx, a) : null,
      h("details", { class: "agent-settings", open: marked && !o.here ? true : null },
        h("summary", null, M.t("agents.card.settings")),
        editForm(a, o.changed),
        M.pictureEditor ? M.pictureEditor(a, "/agents/" + encodeURIComponent(a.id) + "/avatar", false, o.changed) : null,
        M.profileDelete ? M.profileDelete(a, o.changed) : null));
  }

  M.views.agentsPage = async function (ctx, root, args) {
    if (ctx.me.kind !== "human") {
      append(root, h("h2", null, M.t("agents.title")), h("p", null, M.t("agents.humans_only")));
      return;
    }
    const wanted = args && args[0] ? args[0] : null;
    const note = h("div");
    const body = h("div", { class: "agents-page" });
    const heading = h("h2", { id: "agents-heading", tabindex: "-1" }, M.t("agents.title"));
    append(root, heading, h("p", { class: "hint" }, M.t("agents.intro")), note, body);
    const draw = async (words) => {
      const profiles = (await M.api.getAll("/agents")).items.filter((a) => a.owner_id === ctx.me.id && !a.deleted_at);
      const views = await memberViews(profiles);
      const redraw = (answer, said) => draw(said).catch((err) => append(clear(body), h("p", { class: "send-status failed" }, M.t("agents.reread_failed", { reason: err.message }))));
      clear(note);
      if (words) append(note, h("p", { class: "ok", role: "status" }, words));
      append(clear(body),
        profiles.length ? h("ul", { class: "agent-cards" }, profiles.map((a) => profileCard(ctx, a, { wanted, views, changed: redraw, add: true })))
          : h("p", { class: "muted" }, M.t("agents.none")),
        newProfile(redraw));
      // /agents/<id> (a link to one profile): that card's title focused, once.
      const title = wanted && !words ? Array.from(body.querySelectorAll("li.agent-card.wanted .agent-card-title"))[0] : null;
      if (title) title.focus();
    };
    await draw();
  };

  // A project's Agents (/<owner>/<slug>/agents, the maintainer, 2026-10-29):
  // the caller's own agents in this project, each the card of /agents with
  // what belongs to its membership here under it (js/members.js's parts):
  // the team's rulebook, the instances and their credentials, whether it gets
  // the owner's preferences, and with members:admin its pause and removal.
  // Add an agent is the join panel (js/join.js); the open joins stand under
  // the cards, where the agents run (js/placements.js) after them.
  // args: ["join"] (the panel open, ?agent=<id> choosing the profile), [<id>]
  // (that card marked), [<id>, "rulebook"] (at its rulebook, a join's quota refusal).
  M.views.projectAgents = async function (ctx, root, args) {
    if (ctx.me.kind !== "human") {
      append(root, h("h2", null, M.t("agents.project.title")), h("p", null, M.t("agents.project.humans_only")));
      return;
    }
    const joinAsked = !!(args && args[0] === "join");
    const wanted = joinAsked ? null : (args && args[0]) || null;
    const rulebookAsked = !!(wanted && args[1] === "rulebook");
    const status = M.statusLine();
    const note = h("div");
    const cards = h("div", { class: "agents-page project-agents" });
    // focus key -> the element drawn for it, so focus survives a redraw.
    const focusables = new Map();
    const keyed = (key, el) => { focusables.set(key, el); el.setAttribute("data-focus", key); return el; };
    const edits = new Map(), open = new Set();
    let items = ctx.members, profiles = [], views = {}, words = null, unread = null;
    async function readProfiles() {
      profiles = (await M.api.getAll("/agents")).items.filter((a) => a.owner_id === ctx.me.id && !a.deleted_at);
      views = await memberViews(profiles);
      unread = null;
    }
    async function reload() {
      items = (await M.api.getAll(ctx.base + "/members")).items;
      // The join panel offers instances from ctx.members: a save shows there too.
      M.withMembers(ctx, items);
      await readProfiles();
    }
    function redraw(focusKey) {
      const active = document.activeElement;
      const key = focusKey || (active && active.getAttribute ? active.getAttribute("data-focus") : null);
      draw();
      const again = key && focusables.get(key);
      if (again) again.focus();
    }
    const P = M.memberParts(ctx, { status, keyed, edits, open, reload, redraw });
    const memberOf = (a) => items.find((m) => m.id === a.id && !m.removed_at);
    // A profile's own save (name, picture, deletion): read again, said once.
    const changed = (answer, said) => reload().then(() => { words = said; redraw(); }, (err) => status.fail(M.t("agents.project.reread_failed"), err));

    function here(m) {
      const memberPath = ctx.base + "/members/" + encodeURIComponent(m.id);
      const inHere = M.t("agents.project.in", { name: ctx.project.name || ctx.slug });
      return h("section", { class: "agent-here", "aria-label": inHere },
        h("h4", null, inHere),
        h("p", { class: "muted" }, M.trust.words(m), " · ", M.presenceNodes(m, ctx.canAdmin, ctx),
          m.paused && !ctx.canAdmin ? [" · ", P.pausedText(m)] : null),
        M.preferences && "owner_preferences" in m ? M.preferences.ownerToggle(ctx, m) : null,
        // Whom it reports to, as its owner sets it (§2.3); an admin also on Members.
        P.reportsToPart(m, memberPath),
        P.teamForm(m, memberPath),
        P.credentialsPart(m),
        // Its owner puts an instance to rest or wakes it (§6.17).
        P.dormantPart(m, memberPath),
        // The pause and the removal need members:admin (§6.2).
        ctx.canAdmin ? [P.pausePart(m, memberPath), P.removePart(m, memberPath, false, null)] : null);
    }

    function draw() {
      focusables.clear();
      clear(note);
      if (words) append(note, h("p", { class: "ok", role: "status" }, words));
      words = null;
      const list = profiles.filter(memberOf);
      // Profiles not read are no "none": the failure is said where the cards go.
      append(clear(cards), unread
        ? h("p", { class: "send-status failed" }, M.t("agents.project.read_failed", { reason: unread.message }))
        : list.length
          ? h("ul", { class: "agent-cards" }, list.map((a) => profileCard(ctx, a, { wanted, views, changed, here: here(memberOf(a)) })))
          : h("p", { class: "muted" }, J || mayAdd ? M.t("agents.project.none_add") : M.t("agents.project.none")));
      drawJoins();
    }

    // Joining (docs/api.md §3.1, js/join.js), for whom may create joins: Add
    // opens the panel at the head; the open joins stand as seats under the
    // cards, the others folded at the end. The panel, its form and a line
    // shown once live outside the redrawn cards, so a redraw loses neither.
    const addButton = h("button", { type: "button", class: "primary join-open" }, !ctx.canAdmin ? M.t("agents.project.add_mine") : M.t("agents.project.add"));
    const seatsBox = h("div", { class: "profiles join-seats" });
    const earlierBox = h("div", { class: "earlier-box" });
    let J = null;
    // Bringing one's own agent (§3.1, tsk-zd2ch05rk7s1): a human member
    // without members:admin adds agents of their own while the project
    // allows it, up to member_agents_max.
    const policy = ctx.project.policy || {};
    const memberAdds = !ctx.canAdmin && !M.trust.guest(ctx) && policy.member_agents !== "off";
    const mayAdd = (ctx.canAdmin || memberAdds) && !!M.join;
    const maxOwn = policy.member_agents_max === undefined ? 3 : policy.member_agents_max;
    // What §3.1 counts: one's distinct agents with an active membership or
    // an open join; an instance of one already counted adds nothing.
    const ownMembers = () => items.filter((m) => P.ownAgent(m) && !m.removed_at);
    const ownCount = () => new Set(ownMembers().map((m) => m.id).concat(J ? J.openAgents() : [])).size;
    const limitNote = h("span", { class: "muted member-agents-limit", id: "member-agents-limit" });
    // How many of one's agents are here, online, and the joins open.
    const countLine = h("p", { class: "muted agents-count" });
    function drawCount() {
      const own = ownMembers();
      const joins = J ? J.openCount() : 0;
      // Facts with a middle dot between them, each one whole.
      const facts = [M.t("agents.count.own", { count: own.length }), M.t("agents.count.online", { count: own.filter((m) => m.presence === "online").length })];
      if (J) facts.push(memberAdds ? M.t("agents.count.joins_mine", { count: joins }) : M.t("agents.count.joins", { count: joins }));
      countLine.textContent = facts.join(" · ");
      if (memberAdds) {
        const n = ownCount();
        const full = n >= maxOwn;
        // At the limit the panel still makes an instance of one of them.
        const limit = [M.t("agents.limit", { n, count: maxOwn })];
        if (full) limit.push(own.length ? M.t("agents.limit.instances_only") : M.t("agents.limit.no_more"));
        limitNote.textContent = limit.join(" · ");
        addButton.disabled = full && !own.length;
        addButton.setAttribute("aria-describedby", "member-agents-limit");
      }
    }
    function drawJoins() {
      drawCount();
      if (!J) return;
      append(clear(seatsBox), J.seats());
      append(clear(earlierBox), J.earlier());
      // An open panel's choice follows the members just read (a saved rulebook).
      J.refresh();
    }

    const panelSlot = h("div", { class: "join-panel-slot" });
    addButton.hidden = true;
    const placementsSlot = h("div", { class: "placements-slot" });
    append(root, h("div", { class: "toolbar agents-head" }, h("h2", { id: "project-agents-heading" }, M.t("agents.project.title")), memberAdds ? limitNote : null, mayAdd ? addButton : null),
      h("p", { class: "hint" }, (() => {
        const values = { name: ctx.project.name || ctx.slug, link: h("a", { href: "/agents" }, M.t("agents.title")) };
        return ctx.canAdmin ? M.tn("agents.project.hint_admin", values) : M.tn("agents.project.hint", values);
      })()),
      countLine, status.el, panelSlot, note, cards, seatsBox, placementsSlot, earlierBox);
    try {
      await readProfiles();
    } catch (err) {
      unread = err;
    }
    draw();
    if (mayAdd) {
      M.join.mount(ctx, {
        member: memberAdds,
        full: () => memberAdds && ownCount() >= maxOwn,
        changed: drawJoins,
        opened: (yes) => { addButton.hidden = yes; if (!yes) addButton.focus(); },
      }).then((mounted) => {
        J = mounted;
        addButton.hidden = false;
        addButton.addEventListener("click", () => { if (!addButton.disabled) J.open(addButton); });
        append(panelSlot, J.panel, J.listStatus.el);
        drawJoins();
        // Asked for, or no agent of one's own here yet: the panel is the way
        // in, open at once. ?agent=<id> (Your agents' Add to a project): that profile chosen.
        if (joinAsked || !ownMembers().length) J.open(addButton, joinAsked ? M.route.current().query.get("agent") : null);
      }, (err) => append(panelSlot, h("p", { class: "send-status failed" }, M.t("agents.project.joins_failed", { reason: err.message }))));
      // An agent running its line takes its seat: the list is read again,
      // unless the panel is open; then only the seats move.
      ctx.onEvents((events) => {
        if (!J || !events.some((e) => e.kind === "member_joined")) return;
        if (J.busy()) J.reread();
        else reload().then(() => redraw(), () => {});
      });
    }
    // Where the agents run (js/placements.js);
    // the credentials (for a restart's new join) are read for one's own only.
    if (M.placements && M.agentParts) {
      const agentsNow = items.filter((m) => P.ownAgent(m) && !m.removed_at);
      Promise.all(agentsNow.map((m) => M.agentParts.loadCredentials(ctx, m)))
        .then((creds) => M.placements.section(ctx, Object.fromEntries(agentsNow.map((m, i) => [m.id, (creds[i].list && creds[i].list.items) || []]))))
        .then((placed) => { if (placed) append(placementsSlot, placed); }, () => {});
    }
    // A card asked for by the URL: its title, or its rulebook, takes the
    // focus; a profile of the caller's that is not here is said.
    if (wanted) {
      const at = rulebookAsked ? focusables.get("team-max:" + wanted) : Array.from(cards.querySelectorAll("li.agent-card.wanted .agent-card-title"))[0];
      if (at) window.setTimeout(() => at.focus(), 0);
      else append(status.el, h("span", null, M.t("agents.project.not_here", { id: wanted })));
    }
  };
})(window.Maity);
