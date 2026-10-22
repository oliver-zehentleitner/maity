// Shell: sign-in, project switcher, header with project state and the
// owner's absence, navigation, hash router. Each view is a function
// (ctx, root, args) registered in Maity.views; see views.md in context/
// for the order.
//
// Routes:
//   #/all                         everything waiting for the human, all projects
//   #/new                         create a project
//   #/p/<slug>/<view>[/<arg>...]  a view inside one project
//   (empty)                       #/all with several projects, else the inbox
//                                 (no project yet: #/all shows the empty state)
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;

  // watch: the event kinds that change what the view shows; one arriving
  // from someone else offers a reload. The inbox follows the open counts,
  // the chat reads its own messages.
  const NAV = [
    { route: "inbox", label: "Inbox" },
    { route: "board", label: "Board", watch: /^task_/, changed: "The board changed." },
    { route: "agents", label: "Agents", watch: /^(member_|session_|credential_)/, changed: "The agents changed." },
    { route: "org", label: "Organisation", watch: /^member_/, changed: "The organisation changed." },
    { route: "chat", label: "Chat" },
    { route: "join", label: "Join an agent", admin: true },
  ];

  const STATES = ["build", "freeze", "fixes-only", "accepted", "archived"];
  const STATE_LABELS = {
    build: "Build",
    freeze: "Freeze",
    "fixes-only": "Fixes only",
    accepted: "Accepted",
    archived: "Archived",
  };

  M.views = M.views || {};

  // Counts and the open list are re-read on this interval (docs/api.md
  // §5.1: /me after an answer and on an interval).
  const POLL_MS = 15000;

  // The open project's events are read on this interval, with wait=0; see
  // context/refresh.md for why not the long-poll.
  const EVENTS_MS = 5000;
  const EVENTS_PAGE = 200;

  // Events that change the header of every project view.
  const PROJECT_KINDS = /^(state_changed|absence_changed|policy_changed|rules_changed)$/;
  const REQUEST_KINDS = /^request_/;

  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

  function projectLink(slug, view, ...rest) {
    return "#/p/" + [slug, view].concat(rest).map(encodeURIComponent).join("/");
  }

  // Throws URIError on a malformed escape; called inside render's try.
  function parseHash() {
    const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
    if (!parts.length) return { scope: null };
    if (parts[0] === "all") return { scope: "all" };
    if (parts[0] === "new") return { scope: "new" };
    if (parts[0] === "account") return { scope: "account" };
    if (parts[0] === "p" && parts[1]) {
      return { scope: "project", slug: parts[1], route: parts[2] || "inbox", args: parts.slice(3) };
    }
    return { scope: "unknown" };
  }

  function errorBox(err) {
    const where = err.path ? " (" + err.path + ")" : "";
    const status = err.status ? "HTTP " + err.status + (err.code ? " " + err.code : "") + ": " : "";
    return h("div", { class: "error", role: "alert" },
      h("strong", null, "Could not load" + where),
      h("p", null, status + err.message));
  }

  // The status line of a form: "Saving…", then nothing or the error.
  function statusLine() {
    const el = h("p", { class: "send-status", role: "status" });
    return {
      el,
      busy: (text) => { el.textContent = text; el.className = "send-status"; },
      done: () => { el.textContent = ""; el.className = "send-status"; },
      fail: (prefix, err) => { el.textContent = prefix + err.message; el.className = "send-status failed"; },
    };
  }

  function stateBadge(state, note) {
    return h("span", { class: "state state-" + state, title: note || "" }, STATE_LABELS[state] || state);
  }

  // ---- sign-in ------------------------------------------------------------

  function renderLogin(main) {
    append(clear(document.getElementById("header")), h("div", { class: "bar" },
      h("h1", { class: "brand" }, "Maity"),
      M.api.source === "fixtures" ? h("span", { class: "source" }, "Fixtures") : null));
    const handle = h("input", { id: "login-handle", name: "handle", autocomplete: "username", required: true });
    const password = h("input", { id: "login-password", name: "password", type: "password", autocomplete: "current-password", required: true });
    const status = statusLine();
    const form = h("form", {
      class: "login",
      onsubmit: async (e) => {
        e.preventDefault();
        status.busy("Signing in…");
        try {
          await M.api.post("/auth/login", { handle: handle.value.trim(), password: password.value });
          password.value = "";
          render();
        } catch (err) {
          password.value = "";
          status.fail("Not signed in: ", err);
        }
      },
    },
    h("h2", null, "Sign in"),
    h("label", { for: "login-handle" }, "Handle"), handle,
    h("label", { for: "login-password" }, "Password"), password,
    h("button", { type: "submit" }, "Sign in"),
    status.el);
    append(clear(main), form);
  }

  async function logout() {
    try {
      await M.api.post("/auth/logout");
    } finally {
      window.location.hash = "";
      render();
    }
  }

  // ---- project state and absence ----------------------------------------

  // State (owner and admin, with a reason) and absence (owner only), as
  // PATCH /projects/{slug}.
  function projectPanel(ctx) {
    const status = statusLine();
    const save = async (body, label) => {
      status.busy("Saving…");
      try {
        await M.api.patch(ctx.base, body);
        render();
      } catch (err) {
        status.fail(label + " not saved: ", err);
      }
    };

    const panel = h("div", { class: "panel", id: "project-panel" });
    if (ctx.canAdmin) {
      const state = h("select", { id: "state-select" },
        STATES.map((s) => h("option", { value: s, selected: s === ctx.project.state }, STATE_LABELS[s])));
      const note = h("input", { id: "state-note", value: ctx.project.state_note || "", placeholder: "What this state means right now" });
      const reason = h("input", { id: "state-reason", required: true, placeholder: "Why it changes (logged)" });
      append(panel, h("form", {
        class: "inline-form",
        onsubmit: (e) => {
          e.preventDefault();
          if (!reason.value.trim()) { reason.focus(); return; }
          save({ state: state.value, state_note: note.value.trim() || null, reason: reason.value.trim() }, "State");
        },
      },
      h("h3", null, "Project state"),
      h("label", { for: "state-select" }, "State"), state,
      h("label", { for: "state-note" }, "Note"), note,
      h("label", { for: "state-reason" }, "Reason"), reason,
      h("button", { type: "submit" }, "Change state")));
    }
    // Offered where the hub knows the field (docs/api.md §6.1).
    if (ctx.canAdmin && ctx.project.policy && "signing" in ctx.project.policy) append(panel, signingForm(ctx, save));
    if (ctx.isOwner) {
      const a = ctx.project.absence;
      const until = h("input", { id: "absence-until", type: "datetime-local", required: true });
      const scope = h("input", { id: "absence-scope", required: true, placeholder: "What the admin roles may decide meanwhile", value: a ? a.scope : "" });
      append(panel, h("form", {
        class: "inline-form",
        onsubmit: (e) => {
          e.preventDefault();
          const when = new Date(until.value);
          if (!until.value || Number.isNaN(when.getTime())) { until.focus(); return; }
          if (!scope.value.trim()) { scope.focus(); return; }
          save({ absence: { until: when.toISOString().replace(/\.\d{3}Z$/, "Z"), scope: scope.value.trim() } }, "Absence");
        },
      },
      h("h3", null, "Your absence"),
      h("label", { for: "absence-until" }, "Away until"), until,
      h("label", { for: "absence-scope" }, "Meanwhile"), scope,
      h("button", { type: "submit" }, a ? "Update absence" : "Set absence"),
      a ? h("button", { type: "button", onclick: () => save({ absence: null }, "Absence") }, "I am back") : null));
    }
    append(panel, status.el);
    return panel;
  }

  // policy.signing (docs/api.md §2.2, §6.1, §10). Before it becomes
  // required, the form lists the agents whose credentials were last used
  // as a bearer token: they would be refused until they sign, and the
  // switch then needs an explicit confirmation.
  function signingForm(ctx, save) {
    const current = ctx.project.policy.signing;
    const select = h("select", { id: "signing-select" },
      [["optional", "Optional: bearer or signed"], ["required", "Required: signed calls only"]].map(([v, l]) =>
        h("option", { value: v, selected: v === current }, l)));
    select.value = current;
    const reason = h("input", { id: "signing-reason", required: true, placeholder: "Why it changes (logged)" });
    const impact = h("div", { class: "signing-impact", "aria-live": "polite" });
    const confirmBox = h("input", { id: "signing-confirm", type: "checkbox" });
    let needsConfirm = false;
    let check = 0;

    async function showImpact() {
      const seq = ++check;
      clear(impact);
      needsConfirm = false;
      if (select.value !== "required" || current === "required") return;
      append(impact, h("p", { class: "muted" }, "Checking which agents still call with a bearer token…"));
      const agents = ctx.members.filter((m) => m.kind === "agent");
      let rows;
      try {
        rows = await Promise.all(agents.map(async (m) => {
          const creds = await M.api.getAll(ctx.base + "/members/" + encodeURIComponent(m.id) + "/credentials");
          return { m, creds: creds.items.filter((c) => !c.revoked_at) };
        }));
      } catch (err) {
        if (seq !== check) return;
        clear(impact);
        needsConfirm = true;
        append(impact, M.errorBox(err),
          h("p", { class: "flag" }, "Which agents would be cut off could not be read."),
          h("label", { class: "check", for: "signing-confirm" }, confirmBox, " Require signing anyway"));
        return;
      }
      if (seq !== check) return;
      clear(impact);
      const bearer = [];
      const unused = [];
      rows.forEach(({ m, creds }) => creds.forEach((c) => {
        if (c.last_used_via === "bearer") bearer.push({ m, c });
        else if (!c.last_used_via) unused.push({ m, c });
      }));
      if (!bearer.length) {
        append(impact, h("p", { class: "muted" }, "No agent's credential was last used as a bearer token; none is cut off."));
      } else {
        needsConfirm = true;
        append(impact, h("div", { class: "flag" },
          h("p", null, bearer.length === 1 ? "This agent calls with a bearer token and would be refused (signature_required) until it signs:"
            : "These agents call with a bearer token and would be refused (signature_required) until they sign:"),
          h("ul", null, bearer.map(({ m, c }) => h("li", null, m.display_name + " · ",
            h("code", null, c.id), " · last used " + formatAgo(c.last_used_at) + " as a bearer token"))),
          h("p", null, "Signing is what the maity CLI does; an agent without it installs it and runs maity resume."),
          h("label", { class: "check", for: "signing-confirm" }, confirmBox, " Cut them off until they sign")));
      }
      if (unused.length) {
        append(impact, h("p", { class: "muted" }, unused.length + " credential" + (unused.length === 1 ? " has" : "s have")
          + " not been used yet (" + unused.map(({ m }) => m.display_name).join(", ") + "); from the switch on, it must sign from its first call."));
      }
    }
    select.addEventListener("change", showImpact);

    const form = h("form", {
      class: "inline-form",
      onsubmit: (e) => {
        e.preventDefault();
        if (select.value === current) return;
        if (!reason.value.trim()) { reason.focus(); return; }
        if (select.value === "required" && needsConfirm && !confirmBox.checked) { confirmBox.focus(); return; }
        save({ policy: { signing: select.value }, reason: reason.value.trim() }, "Signing");
      },
    },
    h("h3", null, "Agent signing"),
    h("p", { class: "hint" }, "Required refuses every agent call made with the bare bearer credential (curl, the join page's plain path); "
      + "the maity CLI signs its calls. Humans in the dashboard are not affected."),
    h("label", { for: "signing-select" }, "Signing"), select,
    impact,
    h("label", { for: "signing-reason" }, "Reason"), reason,
    h("button", { type: "submit" }, "Change signing"));
    return form;
  }

  // ---- header -------------------------------------------------------------

  // Always visible: every project of this human with what waits there, and
  // the cross-project view with the total.
  function switcher(ctx) {
    const total = ctx.projects.reduce((n, p) => n + (p.open_requests || 0), 0);
    const count = (n) => (n ? h("span", { class: "count", "aria-label": n + " open" }, String(n)) : null);
    return h("nav", { class: "switcher", "aria-label": "Projects" },
      h("a", { href: "#/all", "aria-current": ctx.scope === "all" ? "page" : null }, "All projects", count(total)),
      ctx.projects.map((p) => h("a", {
        href: projectLink(p.slug, "inbox"),
        "aria-current": ctx.scope === "project" && p.slug === ctx.slug ? "page" : null,
      },
      p.name,
      h("span", { class: "dot state-dot-" + p.state, title: STATE_LABELS[p.state] || p.state, "aria-label": STATE_LABELS[p.state] || p.state }),
      count(p.open_requests))),
    h("a", { href: "#/new", class: "new-project", "aria-current": ctx.scope === "new" ? "page" : null }, "+ New project"));
  }

  // A row that scrolls shows it: a fade on the side with more entries. Set
  // on render, on the row's scroll and on a resize or rotation.
  function updateCue(nav) {
    const more = nav.scrollWidth - nav.clientWidth;
    nav.classList.toggle("more-before", more > 1 && nav.scrollLeft > 1);
    nav.classList.toggle("more-after", more > 1 && nav.scrollLeft < more - 1);
  }
  function scrollCue(nav) {
    nav.addEventListener("scroll", () => updateCue(nav), { passive: true });
    updateCue(nav);
  }

  // A tab row scrolls sideways on its own when it is wider than the screen;
  // the current tab is scrolled into it, without moving the page.
  function showCurrent(nav) {
    const cur = nav && nav.querySelector('[aria-current="page"]');
    if (!cur || !nav.clientWidth) return;
    const left = cur.offsetLeft - nav.offsetLeft;
    const right = left + cur.offsetWidth;
    if (left < nav.scrollLeft) nav.scrollLeft = Math.max(0, left - 8);
    else if (right > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = right - nav.clientWidth + 8;
  }

  // The counts changed: only the switcher is replaced, so an open State &
  // absence panel and the tab row's scroll position stay as they are.
  function renderSwitcher(ctx) {
    const old = document.getElementById("header").querySelector("nav.switcher");
    if (!old) return;
    const fresh = switcher(ctx);
    const scrolled = old.scrollLeft;
    old.parentNode.insertBefore(fresh, old);
    old.remove();
    fresh.scrollLeft = scrolled;
    scrollCue(fresh);
  }

  function renderHeader(ctx, current) {
    const header = clear(document.getElementById("header"));
    const absence = ctx.scope === "project" ? ctx.project.absence : null;
    let panelOpen = false;
    const panelSlot = h("div");
    const toggle = ctx.scope === "project" && (ctx.canAdmin || ctx.isOwner)
      ? h("button", {
        type: "button",
        class: "small",
        "aria-expanded": "false",
        "aria-controls": "project-panel",
        onclick: (e) => {
          panelOpen = !panelOpen;
          e.target.setAttribute("aria-expanded", String(panelOpen));
          clear(panelSlot);
          if (panelOpen) append(panelSlot, projectPanel(ctx));
        },
      }, "State & absence")
      : null;
    append(header,
      h("div", { class: "bar" },
        h("h1", { class: "brand" }, "Maity"),
        ctx.scope === "project"
          ? [h("span", { class: "project" }, ctx.project.name), stateBadge(ctx.project.state, ctx.project.state_note), toggle]
          : h("span", { class: "project" }, { new: "New project", account: "Your account" }[ctx.scope] || "Everything waiting for you"),
        M.api.source === "fixtures"
          ? h("span", { class: "source", title: "Data from web/fixtures/, not from the hub. Changes are kept in this tab only." }, "Fixtures")
          : null,
        h("span", { class: "me" }, ctx.me.display_name,
          h("a", { href: "#/account", class: "small-link", "aria-current": ctx.scope === "account" ? "page" : null }, "Account"),
          h("button", { type: "button", class: "small", onclick: logout }, "Sign out"))),
      switcher(ctx),
      ctx.scope === "project" && ctx.project.state_note ? h("p", { class: "state-note" }, ctx.project.state_note) : null,
      absence
        ? h("p", { class: "flag absence" }, "Away until " + formatTime(absence.until) + " — " + absence.scope)
        : null,
      panelSlot,
      ctx.scope === "project"
        ? h("nav", { class: "views", "aria-label": "Views" },
          NAV.filter((item) => !item.admin || ctx.canAdmin).map((item) => h("a", {
            href: projectLink(ctx.slug, item.route),
            "aria-current": item.route === current ? "page" : null,
          }, item.label)))
        : null);
    header.querySelectorAll("nav").forEach((nav) => { showCurrent(nav); scrollCue(nav); });
  }

  // ---- context ------------------------------------------------------------

  function withMembers(ctx, members) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    ctx.members = members;
    ctx.memberById = byId;
    ctx.nameOf = (id) => (byId[id] ? byId[id].display_name : id || "—");
    return ctx;
  }

  async function loadContext(where, me) {
    const ctx = {
      me: me.member,
      projects: me.projects,
      serverTime: me.server_time,
      scope: where.scope,
      projectLink,
      stateLabel: (state) => STATE_LABELS[state] || state,
      refresh: render,
      markSeen: () => {},
      every: (ms, fn) => { timers.push(window.setInterval(fn, ms)); },
      listeners: [],
      onEvents: (fn) => { ctx.listeners.push(fn); },
      // Re-reads /me for the switcher's counts. What counts as seen stays;
      // the inbox marks it after an answer of its own.
      refreshCounts: async () => {
        const fresh = await M.api.get("/me");
        ctx.projects = fresh.projects;
        renderSwitcher(ctx);
      },
    };
    if (where.scope !== "project") return ctx;
    const mine = me.projects.find((p) => p.slug === where.slug);
    if (!mine) {
      throw new M.api.ApiError("You are not a member of the project " + where.slug, 404, "/me", "not_found");
    }
    ctx.slug = where.slug;
    ctx.role = mine.role;
    // A human's owner and admin memberships hold project:admin and
    // members:admin (docs/api.md §2.3); absence is the owner's alone.
    ctx.canAdmin = mine.role === "owner" || mine.role === "admin";
    ctx.isOwner = mine.role === "owner";
    ctx.base = "/projects/" + encodeURIComponent(where.slug);
    ctx.link = (view, ...rest) => projectLink(where.slug, view, ...rest);
    // The event head is read before the view's data, so that nothing that
    // happens while the view loads is missed (it is offered as a reload).
    const [project, members, head] = await Promise.all([
      M.api.get(ctx.base),
      M.api.get(ctx.base + "/members"),
      M.api.get(ctx.base + "/events?after=latest&wait=0"),
    ]);
    ctx.project = project;
    ctx.eventCursor = head.cursor;
    return withMembers(ctx, members.items);
  }

  // Timers belong to one render; the next render stops them.
  let timers = [];
  function stopTimers() {
    timers.forEach((t) => window.clearInterval(t));
    timers = [];
  }

  // Polls /me; when the open count of what is on screen changes, offers to
  // reload the list instead of replacing it under the human's hands. In a
  // project it also reads the project's events (docs/api.md §8.3) from the
  // head on: requests re-read the counts at once, and an event of a kind
  // the view watches, from someone else, offers a reload. Listeners added
  // with ctx.onEvents get every event, the human's own included.
  // Set by a quiet reload of the inbox, shown once by the next watch().
  let quietNote = null;

  function watch(ctx, where, item, main) {
    const openNow = () => (where.scope === "all"
      ? ctx.projects.reduce((n, p) => n + (p.open_requests || 0), 0)
      : (ctx.projects.find((p) => p.slug === ctx.slug) || {}).open_requests);
    let seen = openNow();
    const countLine = h("div");
    const changeLine = h("div");
    const failLine = h("div");
    const notice = h("div", { class: "notice", role: "status" }, countLine, changeLine, failLine);
    main.insertBefore(notice, main.firstChild);
    if (quietNote) {
      append(countLine, h("p", { class: "muted" }, quietNote));
      quietNote = null;
    }
    const reload = h("button", { type: "button", class: "small", onclick: () => render() }, "Reload");
    const changed = new Set();

    async function counts() {
      await ctx.refreshCounts();
      clear(countLine);
      const now = openNow();
      if (now !== seen && (where.scope === "all" || where.route === "inbox")) {
        // Nothing open on screen and nobody busy in the header (the State &
        // absence panel, a focused control): the list reloads on its own,
        // and says so to a screen reader in the next render's notice.
        const header = document.getElementById("header");
        const busy = header.querySelector(".panel") || (document.activeElement && header.contains(document.activeElement));
        if (ctx.quietReload && ctx.quietReload() && !busy) {
          const n = now - seen;
          quietNote = n > 0 ? n + (n === 1 ? " new request." : " new requests.") : "The list was updated (" + now + " open).";
          render();
          return;
        }
        append(countLine, h("p", { class: "flag" }, "What waits for you changed (" + now + " open). ",
          h("button", { type: "button", class: "small", onclick: () => render() }, "Reload the list")));
      }
    }
    const failed = (err) => append(clear(failLine), h("p", { class: "send-status failed" }, "Could not refresh: " + err.message));
    ctx.every(POLL_MS, () => counts().then(() => clear(failLine), failed));
    // A changed count is answered by reloading; an answer given here
    // updates what counts as seen.
    ctx.markSeen = () => { seen = openNow(); };

    if (where.scope !== "project") return;
    ctx.onEvents((events) => {
      const theirs = events.filter((e) => !(e.actor && e.actor.member_id === ctx.me.id));
      const texts = [];
      if (theirs.some((e) => PROJECT_KINDS.test(e.kind))) texts.push("The project's state, absence or policy changed.");
      if (item && item.watch && theirs.some((e) => item.watch.test(e.kind))) texts.push(item.changed);
      texts.forEach((t) => changed.add(t));
      if (texts.length) append(clear(changeLine), h("p", { class: "flag" }, Array.from(changed).join(" ") + " ", reload));
      if (events.some((e) => REQUEST_KINDS.test(e.kind))) counts().catch(failed);
    });
    let reading = false;
    ctx.every(EVENTS_MS, async () => {
      if (reading) return;
      reading = true;
      try {
        await readEvents(ctx);
        clear(failLine);
      } catch (err) {
        failed(err);
      } finally {
        reading = false;
      }
    });
  }

  // Reads every event after the cursor, page by page, and hands them on.
  async function readEvents(ctx) {
    for (;;) {
      const page = await M.api.get(ctx.base + "/events?after=" + encodeURIComponent(ctx.eventCursor)
        + "&wait=0&limit=" + EVENTS_PAGE);
      if (page.cursor !== null && page.cursor !== undefined) ctx.eventCursor = page.cursor;
      if (page.items.length) ctx.listeners.forEach((fn) => fn(page.items));
      if (page.items.length < EVENTS_PAGE) return;
    }
  }

  let renderSeq = 0;

  async function render() {
    const seq = ++renderSeq;
    stopTimers();
    const main = document.getElementById("main");
    let where = { scope: "unknown" };
    let ctx;
    try {
      where = parseHash();
      try {
        await M.api.get("/auth/session");
      } catch (err) {
        if (err.status === 401) {
          if (seq === renderSeq) renderLogin(main);
          return;
        }
        throw err;
      }
      const me = await M.api.get("/me");
      if (seq !== renderSeq) return;
      if (where.scope === null) {
        window.location.replace(me.projects.length === 1 ? projectLink(me.projects[0].slug, "inbox") : "#/all");
        return;
      }
      ctx = await loadContext(where, me);
    } catch (err) {
      if (seq !== renderSeq) return;
      append(clear(document.getElementById("header")), h("div", { class: "bar" }, h("h1", { class: "brand" }, "Maity")));
      append(clear(main), errorBox(err));
      return;
    }
    if (seq !== renderSeq) return;
    renderHeader(ctx, where.route);
    const item = where.scope === "project" ? NAV.find((n) => n.route === where.route) : null;
    const empty = where.scope === "all" && !ctx.projects.length;
    const known = where.scope === "all" || where.scope === "new" || where.scope === "account"
      || (item && own(M.views, item.route) && !(item.admin && !ctx.canAdmin));
    let viewName = "unknown";
    if (where.scope === "all" || where.scope === "new" || where.scope === "account") viewName = where.scope;
    else if (known) viewName = where.route;
    const root = h("section", { class: "view view-" + viewName });
    try {
      if (empty) {
        M.views.noProjects(ctx, root);
      } else if (where.scope === "all") {
        await M.views.inbox(ctx, root, []);
      } else if (where.scope === "new") {
        await M.views.newProject(ctx, root);
      } else if (where.scope === "account") {
        await M.views.account(ctx, root);
      } else if (known) {
        await M.views[item.route](ctx, root, where.args);
      } else {
        append(root, h("p", null, "No such view. ", h("a", { href: "#/all" }, "Go to everything waiting for you.")));
      }
    } catch (err) {
      if (seq !== renderSeq) return;
      append(clear(root), errorBox(err));
    }
    if (seq !== renderSeq) return;
    append(clear(main), root);
    watch(ctx, where, known ? item : null, main);
    let label = "No such view";
    if (empty) label = "No projects yet";
    else if (where.scope === "all") label = "All projects";
    else if (where.scope === "new") label = "New project";
    else if (where.scope === "account") label = "Your account";
    else if (known) label = item.label + " · " + ctx.project.name;
    document.title = label + " · Maity";
  }

  M.errorBox = errorBox;
  M.statusLine = statusLine;
  M.STATE_LABELS = STATE_LABELS;

  window.addEventListener("hashchange", render);
  window.addEventListener("resize", () => {
    document.getElementById("header").querySelectorAll("nav").forEach(updateCue);
  });
  document.addEventListener("DOMContentLoaded", render);
})(window.Maity);
