// Your agents (/agents, docs/api.md §6.3, §16.11): every agent profile of the
// human, across projects, from the header's "+" → Agent and the gear menu.
// Join an agent at the top (a project's join panel, js/join.js); then the
// profiles as a list like Members, each with Manage: its memberships (project,
// trust and role, the instances against the team's limit), Add to a project,
// its name, git identity and handle, its deletion, and per membership its
// instances with their credentials; a new profile below the list.
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

  // The instances of one membership (§6.17), with their credentials and
  // revocation as Members' Manage has them (js/members.js credentialsPart),
  // read in that project's context once the row is opened.
  // onRevoked(): an instance was revoked here, so a count shown elsewhere is stale.
  function instancesPart(ctx, full, view, pctxs, onRevoked) {
    const slot = h("div", { class: "agent-instances", "data-project": full });
    const name = (ctx.projects.find((p) => p.full_name === full) || {}).name || full;
    append(slot, h("h4", null, M.t("agents.instances.in", { project: name })),
      h("p", { class: "muted" }, M.t("agents.instances.reading")));
    (pctxs[full] = pctxs[full] || M.projectContext(ctx, full, (slug, id) => "/chats/" + M.api.projectPath(slug) + (id ? "/" + encodeURIComponent(id) : "")))
      .then((pctx) => {
        const status = M.statusLine();
        const P = M.memberParts(pctx, { status, keyed: (k, el) => el, edits: new Map(), open: new Set(),
          reload: () => Promise.resolve(), redraw: () => {}, revoked: () => { if (onRevoked) onRevoked(full); } });
        append(clear(slot), h("h4", null, M.t("agents.instances.in", { project: name })), P.credentialsPart(view), status.el);
      }, (err) => append(clear(slot), h("p", { class: "send-status failed" }, M.t("agents.instances.failed", { project: name, reason: err.message }))));
    return slot;
  }

  // Joining an agent from here (§3.1, js/join.js): the project chosen
  // (?project=<owner>/<slug>, as Members' Join agent links it), then that
  // project's join panel. Owners and admins join for the project; a member
  // brings their own agent within its limits, which the hub checks.
  function joinPart(ctx, onJoined) {
    const able = ctx.projects.filter((p) => p.state !== "archived" && p.trust !== "guest");
    const box = h("section", { class: "agents-join", "aria-labelledby": "agents-join-heading" },
      h("h3", { id: "agents-join-heading" }, M.t("agents.join.title")));
    if (!able.length) { append(box, h("p", { class: "muted" }, M.t("agents.join.none"))); return box; }
    const asked = M.route.current().query.get("project");
    const pick = h("select", { id: "agents-join-project" }, able.map((p) => h("option", { value: p.full_name }, p.name || p.full_name)));
    pick.value = able.some((p) => p.full_name === asked) ? asked : able[0].full_name;
    const open = h("button", { type: "button", class: "primary agents-join-open" }, M.t("agents.join.open"));
    const slot = h("div", { class: "join-panel-slot" });
    const status = M.statusLine();
    let mounted = null, mountedFor = null, seq = 0;
    async function mount(andOpen) {
      const full = pick.value;
      if (mounted && mountedFor === full) { if (andOpen) mounted.open(open); return; }
      const mine = ++seq;
      open.disabled = true;
      status.busy(M.t("agents.join.reading"));
      try {
        const pctx = await M.projectContext(ctx, full, (slug, id) => "/chats/" + M.api.projectPath(slug) + (id ? "/" + encodeURIComponent(id) : ""));
        const p = able.find((x) => x.full_name === full);
        const J = await M.join.mount(pctx, {
          member: !M.trust.governs(p),
          changed: () => onJoined(),
          opened: (yes) => { open.hidden = yes; if (!yes) open.focus(); },
        });
        if (mine !== seq) return;
        mounted = J; mountedFor = full;
        append(clear(slot), J.panel, J.listStatus.el);
        status.done();
        if (andOpen) J.open(open);
      } catch (err) {
        if (mine === seq) status.fail(M.t("agents.join.failed"), err);
      } finally {
        if (mine === seq) open.disabled = false;
      }
    }
    // Another project chosen: a mount still reading for the old one is dropped.
    pick.addEventListener("change", () => { seq += 1; mounted = null; mountedFor = null; clear(slot); open.hidden = false; open.disabled = false; status.done(); });
    open.addEventListener("click", () => mount(true));
    append(box, h("div", { class: "inline-form" }, h("label", { for: "agents-join-project" }, M.t("agents.join.project")), pick, open), status.el, slot);
    // Asked for from Members' Join agent: the panel open at once.
    if (asked) mount(true);
    return box;
  }

  // Your agents (/agents, the maintainer's card tsk-05meme59sq1x): Join an
  // agent at the top, then one's own agents as a list like Members, each
  // with Manage, which opens under its row what the profile card holds and
  // the instances of each membership; a new profile under the list.
  M.views.agentsPage = async function (ctx, root, args) {
    if (ctx.me.kind !== "human") {
      append(root, h("h2", null, M.t("agents.title")), h("p", null, M.t("agents.humans_only")));
      return;
    }
    const wanted = args && args[0] ? args[0] : null;
    const note = h("div");
    const body = h("div", { class: "agents-page" });
    const heading = h("h2", { id: "agents-heading", tabindex: "-1" }, M.t("agents.title"));
    // Rows opened stay open across a redraw; a profile asked for opens.
    const opened = new Set(wanted ? [wanted] : []);
    const pctxs = {};
    let redrawing = null;
    // What was read last: opening or closing a row draws from it, without reading again.
    let read = null;
    const draw = async (words) => {
      const profiles = (await M.api.getAll("/agents")).items.filter((a) => a.owner_id === ctx.me.id && !a.deleted_at);
      const views = await memberViews(profiles);
      read = { profiles, views };
      render(words);
    };
    const redraw = (answer, said) => draw(said).catch((err) => append(clear(body), h("p", { class: "send-status failed" }, M.t("agents.reread_failed", { reason: err.message }))));
    redrawing = redraw;
    function render(words) {
      const { profiles, views } = read;
      clear(note);
      if (words) append(note, h("p", { class: "ok", role: "status" }, words));
      const instancesOf = (a) => (a.memberships || []).reduce((n, m) => {
        const v = views[m.project + " " + a.id];
        return n + (v && v.instances ? v.instances.filter((i) => !i.revoked_at).length : 0);
      }, 0);
      const online = (a) => (a.memberships || []).some((m) => { const v = views[m.project + " " + a.id]; return v && v.presence === "online"; });
      const rows = profiles.map((a) => {
        const rowId = "agent-manage-" + a.id;
        const isOpen = opened.has(a.id);
        // aria-controls only while the row it names exists (as on Members).
        const manage = h("button", { type: "button", class: "small agent-manage", "aria-expanded": String(isOpen), "aria-controls": isOpen ? rowId : null,
          "aria-label": M.t("agents.list.manage_label", { name: a.display_name }) }, M.t("agents.list.manage"));
        // Opening or closing touches this row alone: nothing is read again, and
        // what is typed in another open row stays.
        manage.addEventListener("click", () => {
          const shown = Array.from(body.querySelectorAll("tr.agent-manage")).find((tr) => tr.getAttribute("id") === rowId);
          if (shown) {
            opened.delete(a.id);
            shown.parentNode.removeChild(shown);
            manage.setAttribute("aria-expanded", "false");
            manage.removeAttribute("aria-controls");
          } else {
            opened.add(a.id);
            head.parentNode.insertBefore(detail(), head.nextSibling);
            manage.setAttribute("aria-expanded", "true");
            manage.setAttribute("aria-controls", rowId);
          }
        });
        const names = (a.memberships || []).map((m) => (ctx.projects.find((p) => p.full_name === m.project) || {}).name || m.project);
        const countCell = h("td", { "data-label": M.t("agents.list.instances") }, M.t("agents.list.instances_count", { count: instancesOf(a) }));
        // A revocation in the open row: that project's member list read again, this row's count with it.
        const recount = (full) => M.api.getAll("/projects/" + M.api.projectPath(full) + "/members").then((r) => {
          const fresh = r.items.find((x) => x.id === a.id);
          if (fresh) views[full + " " + a.id] = fresh;
          countCell.textContent = M.t("agents.list.instances_count", { count: instancesOf(a) });
        }, () => {});
        const head = h("tr", { class: "agent-row" + (wanted === a.id ? " wanted" : ""), "data-agent": a.id },
          h("th", { scope: "row" }, M.avatar(a, 24), " ", h("span", { class: "agent-row-name" }, a.display_name), h("span", { class: "muted" }, " @" + (a.name || a.handle))),
          h("td", { "data-label": M.t("agents.list.projects") }, names.length ? M.fmt.list(names) : h("span", { class: "muted" }, M.t("agents.card.no_project"))),
          countCell,
          h("td", { "data-label": M.t("agents.list.presence") }, online(a) ? M.t("agents.list.online") : h("span", { class: "muted" }, M.t("agents.list.offline"))),
          h("td", { class: "agent-actions" }, manage));
        const detail = () => h("tr", { class: "agent-manage", id: rowId }, h("td", { colspan: "5" }, h("div", { class: "agent-manage-body" },
          h("ul", { class: "agent-cards" }, profileCard(ctx, a, { wanted, views, changed: redraw, add: true })),
          (a.memberships || []).filter((m) => views[m.project + " " + a.id]).map((m) => instancesPart(ctx, m.project, views[m.project + " " + a.id], pctxs, recount)))));
        return isOpen ? [head, detail()] : [head];
      });
      append(clear(body),
        profiles.length
          ? h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-labelledby": "agents-list-heading" },
            h("h3", { id: "agents-list-heading" }, M.t("agents.list.title", { count: profiles.length })),
            h("table", { class: "members agents-list" },
              h("thead", null, h("tr", null, h("th", { scope: "col" }, M.t("agents.list.name")), h("th", { scope: "col" }, M.t("agents.list.projects")),
                h("th", { scope: "col" }, M.t("agents.list.instances")), h("th", { scope: "col" }, M.t("agents.list.presence")),
                h("th", { scope: "col" }, M.t("agents.list.actions")))),
              h("tbody", null, rows.flat())))
          : h("p", { class: "muted" }, M.t("agents.none")),
        // A profile just made opens its row: its card is where it is named and placed.
        newProfile((made, said) => { if (made && made.id) opened.add(made.id); return redraw(made, said); }));
    }
    let titled = false;
    append(root, heading, h("p", { class: "hint" }, M.t("agents.intro")),
      M.join ? joinPart(ctx, () => { if (redrawing) redrawing(); }) : null, note, body);
    await draw();
    // /agents/<id> (a link to one profile): its card's title focused, once.
    const title = wanted && !titled ? Array.from(body.querySelectorAll("li.agent-card.wanted .agent-card-title"))[0] : null;
    if (title) { titled = true; title.focus(); }
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
    // The rows whose card is open; the one asked for (agents/<id>, its rulebook) opens.
    const cardsOpen = new Set(wanted ? [wanted] : []);
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
        h("p", { class: "muted" }, M.trust.words(m), " · ", M.presenceNodes(m, ctx.canAdmin),
          m.paused && !ctx.canAdmin ? [" · ", P.pausedText(m)] : null),
        M.preferences && "owner_preferences" in m ? M.preferences.ownerToggle(ctx, m) : null,
        // Whom it reports to, as its owner sets it (§2.3); an admin also on Members.
        P.reportsToPart(m, memberPath),
        P.teamForm(m, memberPath),
        P.credentialsPart(m),
        // The pause and the removal need members:admin (§6.2).
        ctx.canAdmin ? [P.pausePart(m, memberPath), P.removePart(m, memberPath, false, null)] : null);
    }

    function draw() {
      focusables.clear();
      clear(note);
      if (words) append(note, h("p", { class: "ok", role: "status" }, words));
      words = null;
      const list = profiles.filter(memberOf);
      // As Your agents, limited to this project (the maintainer's card tsk-05meme59sq1x): one row
      // per agent of one's own here, Manage opening its card and what belongs to its membership here.
      const rows = list.map((a) => {
        const m = memberOf(a);
        const rowId = "agent-here-" + a.id;
        const isOpen = cardsOpen.has(a.id);
        const manage = keyed("card:" + a.id, h("button", { type: "button", class: "small agent-manage", "aria-expanded": String(isOpen),
          "aria-controls": isOpen ? rowId : null, "aria-label": M.t("agents.list.manage_label", { name: a.display_name }),
          onclick: () => { if (cardsOpen.has(a.id)) cardsOpen.delete(a.id); else cardsOpen.add(a.id); redraw("card:" + a.id); } }, M.t("agents.list.manage")));
        const active = (m.instances || []).filter((i) => !i.revoked_at).length;
        const head = h("tr", { class: "agent-row" + (wanted === a.id ? " wanted" : ""), "data-agent": a.id },
          h("th", { scope: "row" }, M.avatar(a, 24), " ", h("span", { class: "agent-row-name" }, a.display_name), h("span", { class: "muted" }, " @" + (a.name || a.handle))),
          h("td", { "data-label": M.t("members.col.role") }, M.trust.words(m)),
          h("td", { "data-label": M.t("agents.list.presence") }, M.presenceNodes(m, ctx.canAdmin)),
          h("td", { "data-label": M.t("agents.list.instances") }, M.t("agents.list.instances_count", { count: active })),
          h("td", { class: "agent-actions" }, manage));
        return isOpen ? [head, h("tr", { class: "agent-manage", id: rowId }, h("td", { colspan: "5" },
          h("ul", { class: "agent-cards" }, profileCard(ctx, a, { wanted, views, changed, here: here(m) }))))] : [head];
      });
      // Profiles not read are no "none": the failure is said where the cards go.
      append(clear(cards), unread
        ? h("p", { class: "send-status failed" }, M.t("agents.project.read_failed", { reason: unread.message }))
        : list.length
          ? h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-labelledby": "project-agents-heading" },
            h("table", { class: "members agents-list" },
              h("thead", null, h("tr", null, h("th", { scope: "col" }, M.t("agents.list.name")), h("th", { scope: "col" }, M.t("members.col.role")),
                h("th", { scope: "col" }, M.t("agents.list.presence")), h("th", { scope: "col" }, M.t("agents.list.instances")),
                h("th", { scope: "col" }, M.t("agents.list.actions")))),
              h("tbody", null, rows.flat())))
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
