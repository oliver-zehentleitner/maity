// Shell: sign-in, project switcher, header with project state and the
// owner's absence, navigation, the router on paths (js/route.js, §16.11).
// Each view is a function
// (ctx, root, args) registered in Maity.views; see views.md in context/
// for the order.
//
// Routes:
//   /all                         everything waiting for the human, all projects
//   /new                         create a project
//   /<owner>/<slug>/<view>[/<arg>...]  a view inside one project (§6.25)
//   (empty)                       /all with several projects, else the inbox
//                                 (no project yet: /all shows the empty state)
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;

  // watch: the event kinds that change what the view shows; one arriving
  // from someone else offers a reload. The inbox follows the open counts,
  // the chat reads its own messages.
  const NAV = [
    { route: "inbox", label: "Inbox" },
    // Redrawn in place on task_*, request_*, probe_observed and member_* (js/overview.js).
    { route: "overview", label: "Overview" },
    { route: "board", label: "Board", watch: /^task_/, changed: "The board changed." },
    // One card (/<owner>/<slug>/tasks/<id>, an id's link, js/ids.js): the board
    // with that card marked; its tab is the board's.
    { route: "tasks", view: "board", label: "Board", tab: false, current: "board", watch: /^task_/, changed: "The board changed." },
    { route: "members", label: "Members", watch: /^(member_|session_|credential_)/, changed: "The members changed." },
    { route: "chat", label: "Chat" },
    // Redrawn in place from the feed (js/messages.js).
    { route: "messages", label: "Messages" },
    // The change feed (js/ticker.js); new items from the feed, in place.
    { route: "ticker", label: "Ticker" },
    // The team at work (js/swarm.js, docs/api.md §6.22).
    { route: "swarm", label: "Swarm" },
    // No tab: opened from the Chat tab, the Messages view and a chat (js/project-message.js).
    { route: "message", label: "Message the project", tab: false },
    // One's own agents in the project (js/agents-page.js), the component of
    // /agents; before Runners and Why (the maintainer, 2026-10-29).
    { route: "agents", view: "projectAgents", label: "Agents", when: (ctx) => ctx.me.kind === "human", watch: /^(member_|credential_)/, changed: "Your agents changed." },
    // The account-level view is views.runners; this one is the project's.
    { route: "runners", view: "projectRunners", label: "Runners", admin: true, watch: /^runner_/, changed: "The runners changed." },
    // Where the hub knows the Keep the Why export (docs/api.md §6.1, §11.3).
    { route: "why", label: "Why", when: (ctx) => "keep_the_why_export" in ctx.project },
    // The project's own settings, its last tab (the maintainer's request,
    // 2026-10-25); a save stays here.
    { route: "settings", label: "Settings" },
  ];
  const offered = (ctx, item) => (!item.admin || ctx.canAdmin) && (!item.when || item.when(ctx));

  // docs/api.md §6.1; moving to launch is the owner's go.
  const STATES = ["plan", "build", "review", "launch", "archived"];
  const STATE_LABELS = {
    plan: "Plan",
    build: "Build",
    review: "Review",
    launch: "Launch",
    archived: "Archived",
  };

  M.views = M.views || {};

  // Counts and the open list are re-read on this interval (docs/api.md
  // §5.1: /me after an answer and on an interval), only while the tab is
  // shown; a tab shown again catches up within BACK_MS (context/refresh.md).
  const POLL_MS = 60000;
  const BACK_MS = 5000;
  const hidden = () => document.visibilityState === "hidden";

  // The open project's events are read on this interval, with wait=0, while
  // the tab is shown; see context/refresh.md for why not the long-poll.
  const EVENTS_MS = 15000;
  const EVENTS_PAGE = 200;

  // Events that change the header of every project view.
  const PROJECT_KINDS = /^(state_changed|absence_changed|policy_changed|rules_changed|project_updated)$/;
  const REQUEST_KINDS = /^request_/;

  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

  // A project's address is its full name (§6.25, §16.11): /<owner>/<slug>/<view>.
  function projectLink(full, view, ...rest) {
    return "/" + M.api.projectPath(full) + "/" + [view].concat(rest).map(encodeURIComponent).join("/");
  }
  // The dashboard's own first words and the hub's (§16.11, "Reserved first
  // segments"): never a namespace, a handle may not be one of them.
  const OWN_WORDS = ["account", "admin", "agents", "all", "api", "assets", "badge", "chats", "components", "explore", "health",
    "impressum", "imprint", "inbox", "invite", "join", "login", "mail", "new", "notifications", "observe", "privacy", "register",
    "requests", "runners", "settings", "sign-in", "terms"];

  // Throws URIError on a malformed escape; called inside render's try.
  function parseRoute() {
    // A route's own query (/login?next=…) is the page's to read (M.route.current).
    const parts = M.route.current().path.split("/").filter(Boolean).map(decodeURIComponent);
    if (!parts.length) return { scope: null };
    // Signed out as much as signed in: an invitation (§3.4) and registration (§2.7).
    if (parts[0] === "invite" && parts[1]) return { scope: "invite", token: parts[1] };
    if (parts[0] === "register") return { scope: "register" };
    if (parts[0] === "notifications") return { scope: "notifications" };
    if (parts[0] === "chats") return { scope: "chats", args: parts.slice(1) };
    // The login page, always reachable (docs/api.md §16.7); signed in, the root.
    if (parts[0] === "login") return { scope: "login" };
    if (parts[0] === "all") return { scope: "all" };
    if (parts[0] === "new") return { scope: "new" };
    // /account/orgs[/<handle>]: organisations (§6.26), under the account (views.md).
    if (parts[0] === "account" && parts[1] === "orgs") return { scope: "orgs", args: parts.slice(2) };
    if (parts[0] === "account") return { scope: "account", args: parts.slice(1) };
    if (parts[0] === "runners") return { scope: "runners" };
    // /agents[/<id>]: one's agent profiles across projects (js/agents-page.js).
    if (parts[0] === "agents") return { scope: "agents", args: parts.slice(1) };
    if (parts[0] === "observe" && parts[2]) return { scope: "observe", slug: parts[1] + "/" + parts[2], args: parts.slice(3) };
    if (parts[0] === "admin" && !parts[1]) return { scope: "instance-admin" };
    if (parts[1] && !OWN_WORDS.includes(parts[0])) {
      return { scope: "project", slug: parts[0] + "/" + parts[1], route: parts[2] || "inbox", args: parts.slice(3) };
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
      // An ambiguous mention is said with the long forms to write (§8.6).
      fail: (prefix, err) => { el.textContent = prefix + (M.dom.ambiguousMention(err) || err).message; el.className = "send-status failed"; },
    };
  }

  // The header lockup (web/brand/BRAND.md: 28 px, the small mark), one file
  // per theme; app.css shows the one the page's theme asks for, so a theme
  // picked in the menu switches it too.
  function brandTitle() {
    return h("h1", { class: "brand" },
      h("img", { class: "brand-lockup brand-light", src: "brand/maity-lockup.svg", alt: "Maity", width: "94", height: "28" }),
      h("img", { class: "brand-lockup brand-dark", src: "brand/maity-lockup-dark.svg", alt: "Maity", width: "94", height: "28" }));
  }

  // Light, dark, or as the system has it; per browser (js/theme.js). The
  // header's menu is for pages without a session (the maintainer's
  // instruction): signed in, the theme is chosen in Your account.
  const THEME_WORDS = { system: "System", light: "Light", dark: "Dark" };
  function themeMenu() {
    if (!M.theme) return null;
    const theme = M.menuButton({
      label: "Theme: " + THEME_WORDS[M.theme.get()],
      listLabel: "Theme",
      class: "theme-menu",
      face: M.icons.theme(M.theme.get(), 18),
      items: () => M.theme.THEMES.map((t) => ({
        label: THEME_WORDS[t],
        checked: t === M.theme.get(),
        onSelect: () => {
          M.theme.set(t);
          clear(theme.button);
          append(theme.button, M.icons.theme(t, 18));
          theme.button.setAttribute("aria-label", "Theme: " + THEME_WORDS[t]);
          theme.button.setAttribute("title", "Theme: " + THEME_WORDS[t]);
        },
      })),
    });
    return h("span", { class: "me" }, theme.el);
  }
  M.themeMenu = themeMenu;
  M.THEME_WORDS = THEME_WORDS;

  function stateBadge(state, note) {
    return h("span", { class: "state state-" + state, title: note || "" }, STATE_LABELS[state] || state);
  }

  // The released mark (docs/api.md §6.1): set once with the first release
  // tag, never cleared; shown beside the state wherever the state is.
  const RELEASED_RULES = "interfaces change only with versioning and a stated transition period, "
    + "migrations stay backward compatible, and the release checklist is required";
  function releasedDay(project) {
    const d = new Date(project.released_at);
    return Number.isNaN(d.getTime()) ? project.released_at
      : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
  function releasedMark(project) {
    if (!project || !project.released_at) return null;
    return h("span", { class: "state released", title: "Released since " + releasedDay(project) + ": " + RELEASED_RULES + "." }, "Released");
  }

  // ---- sign-in ------------------------------------------------------------

  // Where a sign-in goes on (/login?next=…, docs/api.md §2.6.5, §16.11): a
  // path of the dashboard only, as the hub checks it (no "#", no "//", not a
  // hub path); anything else is no next.
  function safeNext(v) {
    return typeof v === "string" && v.length <= 512 && M.route.isRoute(v) ? v : null;
  }
  function routeNext() {
    return safeNext(M.route.current().query.get("next"));
  }
  function goNext(next) {
    const n = safeNext(next);
    // Replacing the login page's entry: Back does not lead to it again. The
    // root is no place of its own: a sign-in shown in place of a view stays there.
    if (n && n !== "/" && M.route.current().path !== n) M.route.go(n, { replace: true });
    else render();
  }
  // The sign-in calls of js/device-sign-in.js send it too.
  M.signInNext = routeNext;
  M.safeNext = safeNext;
  // A page's link to sign in or register and come back to it.
  M.withNext = (route, back) => route + "?next=" + encodeURIComponent(back);

  // The session ended while the page was signed in (a 401 on a call that
  // needs it, js/api.js): everything in the background stops, and the
  // sign-in page comes with a note; nothing more is asked until a sign-in.
  // Signing in again returns to the same route.
  let sessionEnded = false;
  M.onSessionEnded = (path, epoch) => {
    if (sessionEnded || (epoch !== undefined && epoch !== (M.sessionEpoch || 0))) return;
    sessionEnded = true;
    M.api.endSession();
    renderSeq++;
    M.notify.halt();
    stopTimers();
    if (M.clearChatDrafts) M.clearChatDrafts();
    // As a sign-out does: the next human in this tab starts with their own settings.
    M.notify.stopBrowser();
    M.notify.state.settings = null;
    renderLogin(document.getElementById("main"), "Your session has ended. Sign in again to go on where you were.");
  };

  function renderLogin(main, note) {
    document.title = "Sign in · Maity";
    append(clear(document.getElementById("header")), h("div", { class: "bar" },
      brandTitle(),
      M.api.source === "fixtures" ? h("span", { class: "source" }, "Fixtures") : null,
      themeMenu()));
    const handle = h("input", { id: "login-handle", name: "handle", autocomplete: "username", required: true });
    const password = h("input", { id: "login-password", name: "password", type: "password", autocomplete: "current-password", required: true });
    const status = statusLine();
    const form = h("form", {
      class: "login door",
      onsubmit: async (e) => {
        e.preventDefault();
        status.busy("Signing in…");
        try {
          const next = routeNext();
          const answer = await M.api.post("/auth/login", Object.assign({ handle: handle.value.trim(), password: password.value }, next ? { next } : {}));
          password.value = "";
          goNext(answer && answer.next);
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
    // A code from another device or a link by mail, as the hub offers them
    // (js/device-sign-in.js), on this page's own timers.
    append(clear(main), note ? h("p", { class: "flag session-ended", role: "status" }, note) : null, form,
      M.deviceSignIn ? M.deviceSignIn.loginOptions((ms, fn) => { timers.push(window.setInterval(fn, ms)); }, () => render()) : null,
      M.legal ? M.legal.links() : null);
  }

  // The one page of a pending account (§2.7.5): it may sign out, nothing else.
  function renderPending(main) {
    document.title = "Waiting for approval · Maity";
    append(clear(document.getElementById("header")), h("div", { class: "bar" }, brandTitle(), themeMenu()));
    append(clear(main), h("section", { class: "pending-account" },
      h("h2", null, "Your account waits for the operator's approval"),
      h("p", null, "Once it is approved you get a mail, and this page becomes your dashboard. An invitation you followed waits for you meanwhile."),
      h("button", { type: "button", onclick: logout }, "Sign out")));
  }

  // back: a dashboard path (checked as a sign-in's next is) to
  // show once signed out, e.g. the invitation that offered Not you? Sign
  // out (H on #461); anything else, and none, is the root.
  async function logout(back) {
    const after = safeNext(back);
    // The held long-poll goes before the session does (§18.2).
    M.notify.halt();
    // Signing out on purpose is no session that ended under the page.
    sessionEnded = true;
    try {
      // Build the request while the fallback CSRF token is still available.
      const ending = M.api.post("/auth/logout");
      M.api.endSession();
      await ending;
    } finally {
      if (M.clearChatDrafts) M.clearChatDrafts();
      M.notify.stopBrowser();
      M.notify.state.settings = null;
      // Signed out at the same address: nothing changes there, so draw it.
      if (!M.route.go(after || "/", { replace: true })) render();
    }
  }

  // ---- project state and absence ----------------------------------------

  // State (owner and admin, with a reason) and absence (owner only), as
  // PATCH /projects/{owner}/{slug}.
  // The hub's rule for a repository URL (§6.1), as the create view says it too.
  const FORGE_RULE = "Must be https://<forge host>/<owner>/<name> on a forge this hub is configured for.";
  M.FORGE_RULE = FORGE_RULE;

  // The repository (§6.1, project:admin, humans only): where the probe, the
  // Keep the Why dashboard and the runners' clones look. https only here;
  // the hub checks the forge host. Changing or removing it asks first.
  function repositoryForm(ctx) {
    const current = ctx.project.repository && ctx.project.repository.url;
    const status = statusLine();
    const input = h("input", { id: "repo-url", type: "url", placeholder: "https://github.com/owner/name",
      autocomplete: "off", spellcheck: "false", "aria-describedby": "repo-url-hint repo-url-error" });
    input.value = current || "";
    const error = h("p", { class: "field-error", id: "repo-url-error", role: "alert" });
    const fail = (text) => { error.textContent = text; input.setAttribute("aria-invalid", "true"); input.focus(); };
    return h("form", {
      class: "inline-form repository-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        error.textContent = "";
        input.removeAttribute("aria-invalid");
        const url = input.value.trim().replace(/\/+$/, "");
        if (url === (current || "")) { status.done(); append(status.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
        if (url && !/^https:\/\/[^\s/]+\/[^\s/]+\/[^\s/]+$/.test(url)) { fail(FORGE_RULE); return; }
        if (current && !window.confirm(url
          ? "Change the repository to " + url + "? The probe, the Keep the Why dashboard and new clones of runners follow it."
          : "Remove the repository? The probe and the Keep the Why dashboard stop, and runners cannot clone for this project.")) return;
        status.busy("Saving…");
        try {
          await M.api.patch(ctx.base, { repository: url ? { url } : null });
          render();
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields;
          const why = fields && (fields["repository.url"] || fields.repository);
          if (why) { status.done(); fail(why === "not_a_configured_forge" ? FORGE_RULE : String(why)); }
          else status.fail("Repository not saved: ", err);
        }
      },
    },
    h("h2", { class: "panel-title", id: "repo-heading" }, "Repository"),
    h("label", { for: "repo-url" }, "URL"), input,
    h("p", { class: "hint", id: "repo-url-hint" }, "Leave it empty to remove it. The hub reads the forge's state and the Keep the Why dashboard from it."),
    error,
    h("button", { type: "submit" }, "Save repository"),
    status.el);
  }

  // §8.5's blind removal: an owner or admin removes a reported message of a
  // closed group chat by its number, without reading it; the hub answers
  // {seq, redacted} only, never the message.
  function blindRemoveForm(ctx) {
    const status = statusLine();
    const seq = h("input", { id: "remove-seq", inputmode: "numeric", autocomplete: "off", "aria-describedby": "remove-seq-hint" });
    const reason = h("input", { id: "remove-reason", autocomplete: "off", placeholder: "What was reported" });
    return h("form", {
      class: "inline-form remove-reported",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const n = seq.value.trim();
        if (!/^\d+$/.test(n)) { status.fail("Not removed: ", { message: "the message number is a whole number" }); seq.focus(); return; }
        if (!reason.value.trim()) { status.fail("Not removed: ", { message: "a reason is needed" }); reason.focus(); return; }
        if (!window.confirm("Remove the closed group chat's message with number " + n + " for everyone who can read it? Its text is replaced by a note.")) return;
        status.busy("Removing…");
        try {
          // expect: the hub removes only a message of a closed group chat, so
          // a mistyped number never takes out another event (§8.5, #206).
          await M.api.post(ctx.base + "/events/" + encodeURIComponent(n) + "/redact", { reason: reason.value.trim(), expect: "closed_chat_message" });
          seq.value = "";
          reason.value = "";
          status.done();
          append(status.el, h("span", { class: "ok" }, "Message " + n + " is removed."));
        } catch (err) {
          const mismatch = err.code === "invalid" && err.details && err.details.fields && err.details.fields.expect === "mismatch";
          status.fail("Not removed: ", mismatch || err.code === "not_found"
            ? { message: "number " + n + " is no message of a closed group chat in this project; nothing was removed" } : err);
        }
      },
    },
    h("h2", { class: "panel-title" }, "Remove a reported message"),
    h("label", { for: "remove-seq" }, "Message number"), seq,
    h("label", { for: "remove-reason" }, "Reason"), reason,
    h("button", { type: "submit" }, "Remove"),
    h("p", { class: "hint", id: "remove-seq-hint" }, "For a message of a closed group chat, which no human is in any more: "
      + "you remove it by its number without reading it. The chat's former participants see your reason."),
    status.el);
  }

  function onboardingForm(ctx) {
    const current = ctx.project.settings.onboarding || { check_in_with: "coordinator" };
    const status = statusLine();
    const briefing = h("textarea", { id: "onboarding-briefing", rows: "6", "aria-describedby": "onboarding-hint" }, current.briefing || "");
    const choices = [{ value: "", label: "No check-in" }, { value: "coordinator", label: "Coordinator" }]
      // §6.1: trust:owner, trust:admin or a role; never a guest (§2.3).
      .concat(["owner", "admin"].map((trust) => ({ value: "trust:" + trust, label: "Trust: every " + trust })))
      .concat(M.trust.ROLES.map((role) => ({ value: "role:" + role, label: "Role: every " + role })))
      .concat(ctx.members.filter((m) => !m.removed_at && !M.trust.guest(m)).map((m) => ({ value: m.id, label: "Member: @" + M.dom.handleOf(ctx, m) + " (" + m.kind + ")" })));
    if (current.check_in_with && !choices.some((c) => c.value === current.check_in_with)) {
      choices.push({ value: current.check_in_with, label: "Unavailable member: " + current.check_in_with });
    }
    const target = h("select", { id: "onboarding-target" }, choices.map((c) => h("option", {
      value: c.value, selected: c.value === (current.check_in_with || ""),
    }, c.label)));
    const button = h("button", { type: "submit" }, "Save onboarding");
    const metadata = h("p", { class: "muted onboarding-metadata" },
      current.version != null ? "Version " + current.version : "Project default",
      current.by ? [" · set by ", M.dom.memberRef(ctx, current.by, { text: "handle" })] : null,
      current.updated_at ? " · updated " + formatTime(current.updated_at) : null);
    return h("form", { class: "inline-form project-onboarding", onsubmit: async (e) => {
      e.preventDefault();
      if ([...briefing.value].length > 16 * 1024) {
        status.fail("Not saved: ", { message: "The briefing may contain at most 16,384 characters." }); briefing.focus(); return;
      }
      const onboarding = {};
      if (briefing.value) onboarding.briefing = briefing.value;
      if (target.value) onboarding.check_in_with = target.value;
      button.disabled = true; status.busy("Saving…");
      try {
        const saved = await M.api.patch(ctx.base, { settings: { onboarding } });
        ctx.project = saved;
        const value = saved.settings && saved.settings.onboarding;
        clear(metadata);
        append(metadata, value && value.version != null ? "Version " + value.version : "Project default",
          value && value.by ? [" · set by ", M.dom.memberRef(ctx, value.by, { text: "handle" })] : null,
          value && value.updated_at ? " · updated " + formatTime(value.updated_at) : null);
        status.done(); append(status.el, h("span", { class: "ok" }, "Onboarding saved."));
      } catch (err) { status.fail("Onboarding not saved: ", err); }
      finally { button.disabled = false; }
    } },
    h("h2", { class: "panel-title" }, "Onboarding"), metadata,
    h("label", { for: "onboarding-briefing" }, "Default briefing (Markdown)"), briefing,
    h("p", { class: "hint", id: "onboarding-hint" }, "Up to 16,384 characters. Agents with their own briefing keep it; others receive this text on their next resume. Leave empty to remove the default text."),
    h("label", { for: "onboarding-target" }, "Check in with"), target,
    h("p", { class: "hint" }, "The coordinator or role is resolved when the agent resumes. No check-in disables the hint."), button, status.el);
  }

  function projectPanel(ctx) {
    const status = statusLine();
    const save = async (body, label) => {
      status.busy("Saving…");
      try {
        await M.api.patch(ctx.base, body);
        settingsSaved = label + " saved.";
        render();
      } catch (err) {
        status.fail(label + " not saved: ", err);
      }
    };

    const panel = h("div", { class: "panel", id: "project-panel" });
    const language = (ctx.project.settings || {}).language || "en";
    const humanAdmin = ctx.me.kind === "human" && ctx.canAdmin;
    if (humanAdmin) {
      const select = h("select", { id: "project-language" },
        h("option", { value: "en" }, "English"), h("option", { value: "de" }, "Deutsch"));
      select.value = language;
      append(panel, h("form", { class: "inline-form project-language", onsubmit: (e) => {
        e.preventDefault(); save({ settings: { language: select.value } }, "Language");
      } }, h("h2", { class: "panel-title" }, "Project language"),
      h("label", { for: "project-language" }, "Language"), select,
      h("button", { type: "submit" }, "Save language")));
    } else {
      append(panel, h("p", { class: "project-language" }, "Project language: " + (language === "de" ? "Deutsch" : "English")));
    }

    if (ctx.canAdmin) {
      const state = h("select", { id: "state-select" },
        STATES.map((s) => h("option", {
          value: s,
          selected: s === ctx.project.state,
          // Only the owner moves the project to launch; an admin may leave it.
          disabled: s === "launch" && !ctx.isOwner && ctx.project.state !== "launch",
        }, STATE_LABELS[s])));
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
      h("h2", { class: "panel-title" }, "Project state"),
      ctx.project.released_at
        ? h("p", { class: "released-note" }, "Released since " + releasedDay(ctx.project) + ", for good: " + RELEASED_RULES + ".")
        : null,
      h("label", { for: "state-select" }, "State"), state,
      h("label", { for: "state-note" }, "Note"), note,
      h("label", { for: "state-reason" }, "Reason"), reason,
      h("button", { type: "submit" }, "Change state")));
    }
    if (ctx.canAdmin && ctx.project.settings && "onboarding" in ctx.project.settings) append(panel, onboardingForm(ctx));
    if (ctx.canAdmin && "repository" in ctx.project) append(panel, repositoryForm(ctx));
    // Its name: rename and transfer, for a human owner where the hub has them (§6.25).
    const names = M.projectNames && M.projectNames.section(ctx);
    if (names) append(panel, names);
    // A policy field, humans only (§2.3 ʰ); where the hub knows it (§6.22).
    if (humanAdmin && M.swarm && ctx.project.policy && "swarm_public" in ctx.project.policy) append(panel, M.swarm.settingsForm(ctx, save));
    if ("memory" in ctx.project && M.projectSetup) append(panel, memoryPanel(ctx));
    // Humans only, as every policy field (§2.3 ʰ); where the hub knows it.
    if (humanAdmin && ctx.project.policy && "badge" in ctx.project.policy) append(panel, badgeForm(ctx, save));
    if (humanAdmin && ctx.project.policy && "keep_the_why" in ctx.project.policy) append(panel, keepTheWhyForm(ctx, save));
    // The change ticker (§17.3) where the hub has one, read by every member,
    // changed by a human admin; the forge webhook (§17.4) for that human only.
    if (M.tickerSettings) {
      const tickerSlot = h("div", { class: "ticker-settings-slot" });
      append(panel, tickerSlot);
      M.api.hubHas("GET", "/projects/{owner}/{slug}/ticker").catch(() => false).then((yes) => {
        if (yes) append(tickerSlot, M.tickerSettings.tickerForm(ctx, save));
      });
      if (humanAdmin) {
        const webhookSlot = h("div", { class: "webhook-slot" });
        append(panel, webhookSlot);
        M.api.hubHas("GET", "/projects/{owner}/{slug}/forge/webhook").catch(() => false).then((yes) => {
          if (yes) append(webhookSlot, M.tickerSettings.webhookPanel(ctx));
        });
      }
    }
    if (humanAdmin && ctx.project.policy && "member_agents" in ctx.project.policy) append(panel, memberAgentsForm(ctx, save));
    // Only on a hub with group chats: without them there is no closed one.
    if (ctx.canAdmin && M.groupChat) {
      const slot = h("div", { class: "remove-reported-slot" });
      append(panel, slot);
      M.groupChat.served().then((yes) => { if (yes) append(slot, blindRemoveForm(ctx)); });
    }
    // §8.7: everyone's pending uploads, for freeing the quota.
    if (ctx.canAdmin && M.attachments) append(panel, M.attachments.pendingPanel(ctx));
    // Offered where the hub knows the field (docs/api.md §6.1).
    if (ctx.canAdmin && ctx.project.policy && "signing" in ctx.project.policy) append(panel, signingForm(ctx, save));
    if (ctx.canAdmin && "logo" in ctx.project) append(panel, imagesForm(ctx));
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
      h("h2", { class: "panel-title" }, "Your absence"),
      h("label", { for: "absence-until" }, "Away until"), until,
      h("label", { for: "absence-scope" }, "Meanwhile"), scope,
      h("div", { class: "actions" },
        a ? h("button", { type: "button", onclick: () => save({ absence: null }, "Absence") }, "I am back") : null,
        h("button", { type: "submit" }, a ? "Update absence" : "Set absence"))));
    }
    append(panel, status.el);
    return panel;
  }

  // The project's own logo and banner (docs/api.md §11.2), for project:admin
  // humans: what shows now and where it comes from, upload, and removing an
  // upload (the forge's image then applies again). The type is read from the
  // file's first bytes, as the hub reads it; at most 1 MiB.
  const { sniffImage, IMAGE_MAX } = M.dom;
  const SOURCES = { uploaded: "uploaded here", forge: "from the repository's forge" };
  const IMAGE_REASONS = {
    unsupported_type: "not a PNG, JPEG or WebP image",
    too_large: "larger than 1 MiB",
  };

  // Set by an upload or a removal; the next header opens the panel with it.
  let imagesNote = null;

  function imagesForm(ctx) {
    const status = statusLine();
    if (imagesNote) {
      append(status.el, h("span", { class: "ok" }, imagesNote));
      imagesNote = null;
    }
    const box = h("div", { class: "images" }, h("h2", { class: "panel-title" }, "Logo and banner"));
    [["logo", "Logo", "Square; shown next to the project's name everywhere."],
      ["banner", "Banner", "2:1, like a forge's social preview (ideally 1280×640); shown at the top of the project's inbox."]].forEach(([kind, label, hint]) => {
      const view = ctx.project[kind] || { available: false, source: null };
      const url = M.api.imageUrl(ctx.slug, kind, view);
      const id = "upload-" + kind;
      const input = h("input", { id, type: "file", accept: "image/png,image/jpeg,image/webp" });
      input.addEventListener("change", async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        if (file.size > IMAGE_MAX) { status.fail(label + " not uploaded: ", { message: "larger than 1 MiB" }); input.value = ""; return; }
        const type = await sniffImage(file);
        if (!type) { status.fail(label + " not uploaded: ", { message: "not a PNG, JPEG or WebP image" }); input.value = ""; return; }
        status.busy("Uploading the " + kind + "…");
        try {
          await M.api.putImage(ctx.base + "/" + kind, file, type);
          imagesNote = label + " uploaded.";
          render();
        } catch (err) {
          const why = err.code === "invalid" && err.details && err.details.fields && err.details.fields.body;
          status.fail(label + " not uploaded: ", why ? { message: IMAGE_REASONS[why] || why } : err);
          input.value = "";
        }
      });
      append(box, h("div", { class: "image-row" },
        h("h3", { class: "panel-sub" }, label),
        url
          ? h("img", { class: "image-preview image-preview-" + kind, src: url, alt: "The project's current " + kind })
          : h("p", { class: "muted" }, kind === "logo" ? "None: a monogram is shown." : "None."),
        view.source ? h("p", { class: "muted" }, SOURCES[view.source] || view.source) : null,
        h("label", { for: id }, "Upload a " + kind + " (PNG, JPEG or WebP, at most 1 MiB)"), input,
        h("p", { class: "hint" }, hint),
        view.source === "uploaded"
          ? h("button", {
            type: "button",
            onclick: async () => {
              status.busy("Removing the " + kind + "…");
              try {
                await M.api.del(ctx.base + "/" + kind);
                imagesNote = "Uploaded " + kind + " removed" + (kind === "logo" ? "; the forge's logo, or a monogram, shows again." : ".");
                render();
              } catch (err) {
                status.fail(label + " not removed: ", err);
              }
            },
          }, "Remove the uploaded " + kind)
          : null));
    });
    append(box, status.el);
    return box;
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
          h("ul", null, bearer.map(({ m, c }) => h("li", null, M.dom.memberRef(ctx, m.id), " · ",
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
    h("h2", { class: "panel-title" }, "Agent signing"),
    h("p", { class: "hint" }, "Required refuses every agent call made with the bare bearer credential (curl, the join page's plain path); "
      + "the maity CLI signs its calls. Humans in the dashboard are not affected."),
    h("label", { for: "signing-select" }, "Signing"), select,
    impact,
    h("label", { for: "signing-reason" }, "Reason"), reason,
    h("button", { type: "submit" }, "Change signing"));
    return form;
  }

  // Project memory (docs/api.md §6.1, §6.21), read here and not changed:
  // the hub would set nothing up and remove nothing on a change, so a change
  // is an agent's work in the repository, on a card. The setup chosen at
  // creation, and its cards once the hub made them.
  function memoryPanel(ctx) {
    const { PROVIDERS, OPTIONS } = M.projectSetup;
    const provider = ctx.project.memory && ctx.project.memory.provider;
    const s = ctx.project.setup;
    const named = (PROVIDERS.find(([v]) => v === provider) || [provider, provider])[1];
    const chosen = s ? OPTIONS.filter(([k]) => s[k]).map(([, title]) => title) : [];
    let setup;
    if (!s) setup = h("p", { class: "muted" }, "The project predates setup cards: none were chosen.");
    else if (Array.isArray(s.cards) && s.cards.length) {
      setup = h("p", null, "Setup cards: ", s.cards.map((id, i) => [i ? ", " : null, h("a", { class: "id-ref", href: ctx.link("tasks", id) }, id)]));
    } else if (!chosen.length || Array.isArray(s.cards)) setup = h("p", { class: "muted" }, "No setup option was chosen.");
    else setup = [h("p", null, "Chosen: " + chosen.join("; ") + "."), h("p", { class: "muted" }, "The cards are made when the project gets a repository.")];
    return h("section", { class: "inline-form memory-panel", "aria-labelledby": "memory-heading" },
      h("h2", { class: "panel-title", id: "memory-heading" }, "Project memory"),
      h("p", null, h("strong", null, named || "—"),
        provider === "keep-the-why" ? ": joining agents load the Keep the Why skill and keep the project's reasons in the repository's context/."
          : provider === "none" ? ": the project works without a memory provider." : null),
      h("p", { class: "hint" }, "Chosen when the project was created. A change is work in the repository: write a card for an agent; "
        + "the hub sets nothing up and removes nothing."),
      setup);
  }

  // policy.badge (docs/api.md §6.20): off unless an admin switches it on, a
  // policy change with its reason. The README snippet and, while it is on,
  // the badge as the hub serves it.
  const BADGES = [["off", "Off: no badge is served"], ["members", "Members: how many humans and agents"],
    ["agents_online", "Agents online: how many agents are online now"]];
  // The Keep the Why commitment (docs/api.md §6.23): required, the hub
  // makes every agent confirm it and every code report name its why;
  // optional, nobody is held to it. Without the memory provider it can
  // only be optional, and the form says why instead of offering it.
  function keepTheWhyForm(ctx, save) {
    const current = ctx.project.policy.keep_the_why;
    const provider = ctx.project.memory && ctx.project.memory.provider;
    const off = provider === "none";
    const select = h("select", { id: "ktw-policy-select", disabled: off ? true : null },
      [["required", "Required: every agent confirms it, every code report names its why"], ["optional", "Optional: nobody is reminded"]]
        .map(([v, l]) => h("option", { value: v, selected: v === current }, l)));
    select.value = current;
    const reason = h("input", { id: "ktw-policy-reason", required: true, placeholder: "Why it changes (logged)", disabled: off ? true : null });
    return h("form", {
      class: "inline-form ktw-policy-form",
      onsubmit: (e) => {
        e.preventDefault();
        if (off || select.value === current) return;
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ policy: { keep_the_why: select.value }, reason: reason.value.trim() }, "Keep the Why commitment");
      },
    },
    h("h2", { class: "panel-title" }, "Keep the Why commitment"),
    h("p", { class: "hint" }, off
      ? "This project has no memory provider, so Keep the Why stays optional. Choose Keep the Why as the memory to require it."
      : "Required: each agent instance confirms at its resume that it uses Keep the Why, is reminded once after 30 minutes, "
        + "and its owner is told 30 minutes later; a code report names the entry that keeps its why, or says why there is none."),
    h("label", { for: "ktw-policy-select" }, "Keep the Why"), select,
    h("label", { for: "ktw-policy-reason" }, "Reason"), reason,
    h("button", { type: "submit", disabled: off ? true : null }, "Change"));
  }

  // §3.1 "Bringing your own agent", §6.1: whether members add agents of
  // their own, and how many each may hold here; a human with project:admin,
  // with a reason, as every policy field.
  function memberAgentsForm(ctx, save) {
    const pol = ctx.project.policy;
    const on = h("select", { id: "member-agents-select" }, [["on", "On: members add agents of their own"], ["off", "Off: only admins add agents"]]
      .map(([v, l]) => h("option", { value: v }, l)));
    on.value = pol.member_agents || "on";
    const max = h("input", { id: "member-agents-max", type: "number", min: "0", max: "20", step: "1" });
    max.value = String(pol.member_agents_max === undefined ? 3 : pol.member_agents_max);
    const reason = h("input", { id: "member-agents-reason", required: true, placeholder: "Why it changes (logged)" });
    const error = h("p", { class: "field-error", id: "member-agents-error", role: "alert" });
    return h("form", {
      class: "inline-form member-agents-form",
      onsubmit: (e) => {
        e.preventDefault();
        const n = Number(max.value);
        if (!Number.isInteger(n) || n < 0 || n > 20) { error.textContent = "Agents per member: a whole number from 0 to 20."; max.focus(); return; }
        const policy = {};
        if (on.value !== (pol.member_agents || "on")) policy.member_agents = on.value;
        if (n !== (pol.member_agents_max === undefined ? 3 : pol.member_agents_max)) policy.member_agents_max = n;
        if (!Object.keys(policy).length) return;
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ policy, reason: reason.value.trim() }, "Members' own agents");
      },
    },
    h("h2", { class: "panel-title" }, "Members' own agents"),
    h("p", { class: "hint" }, "A member may add agents of their own: as member or guest, as coder, reviewer, tester or designer, reporting to them. "
      + "Turning it off stops new ones; joins already handed out stay usable."),
    h("label", { for: "member-agents-select" }, "Members add agents"), on,
    h("label", { for: "member-agents-max" }, "Agents per member (active and open joins)"), max, error,
    h("label", { for: "member-agents-reason" }, "Reason"), reason,
    h("button", { type: "submit" }, "Save"));
  }

  function badgeForm(ctx, save) {
    const current = ctx.project.policy.badge;
    const select = h("select", { id: "badge-select" }, BADGES.map(([v, l]) => h("option", { value: v, selected: v === current }, l)));
    select.value = current;
    // As reached in this tab; a file:// page has no origin to name.
    const raw = window.location && window.location.origin;
    const origin = raw && raw !== "null" ? raw : "https://<hub>";
    const url = origin + "/badge/" + M.api.projectPath(ctx.slug) + ".svg";
    const snippet = "[![maity](" + url + ")](" + origin + projectLink(ctx.slug, "overview") + ")";
    const copy = h("button", {
      type: "button",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(snippet);
          copy.textContent = "Copied";
        } catch (err) {
          copy.textContent = "Copy failed — select the line";
        }
      },
    }, "Copy");
    return h("form", {
      class: "inline-form badge-form",
      onsubmit: (e) => {
        e.preventDefault();
        if (select.value === current) return;
        // The badge alone needs no reason (docs/api.md §6.20).
        save({ policy: { badge: select.value } }, "Badge");
      },
    },
    h("h2", { class: "panel-title" }, "README badge"),
    h("p", { class: "hint" }, "Public: anyone with the address sees the count, never a name. The hub serves it while the badge is on. "
      + "The address is this hub's as reached in this tab."),
    h("label", { for: "badge-select" }, "Badge"), select,
    // Shown from the hub itself; fixture mode has no hub to serve it.
    current !== "off" && M.api.source === "api"
      // Versioned by the rules: a policy change bumps it, so a cached
      // badge of the old variant is not shown (§6.20: max-age=60).
      ? h("img", { class: "badge-preview", src: "/badge/" + M.api.projectPath(ctx.slug) + ".svg?v=" + encodeURIComponent(ctx.project.rules_version || 0),
        alt: "The project's badge as the hub serves it" }) : null,
    h("div", { class: "paste-row" }, h("code", { class: "paste-line" }, snippet), copy),
    current === "off" ? h("p", { class: "muted" }, "While the badge is off, its address answers not found.") : null,
    h("button", { type: "submit" }, "Change badge"));
  }

  // ---- project logo -------------------------------------------------------

  // Dark enough for white initials: each at least 5.2:1 against #fff (WCAG AA).
  const MONOGRAM_COLOURS = ["#1a66d9", "#7a3fc4", "#b02a6b", "#b3361d", "#8a5a00", "#2f7a1f",
    "#0f7a6b", "#1f6f99", "#5b4cc4", "#9a3412", "#4d6b1f", "#6b4f3a"];

  const initials = (name) => {
    const words = String(name || "?").trim().split(/[\s_-]+/).filter(Boolean);
    const letters = words.length > 1 ? [words[0], words[1]].map((w) => [...w][0]) : [...(words[0] || "?")].slice(0, 1);
    return letters.join("").toUpperCase();
  };

  const colourOf = (slug) => {
    let n = 0;
    for (const ch of String(slug)) n = (n * 31 + ch.codePointAt(0)) % 9973;
    return MONOGRAM_COLOURS[n % MONOGRAM_COLOURS.length];
  };

  // A project's logo (§11.2) as the hub serves it, else a monogram from its
  // initials in a colour from its slug. The mark stands next to the
  // project's name, which is its accessible name, so the mark itself is
  // left out of the accessibility tree (alt="", aria-hidden).
  function projectMark(slug, name, view, size) {
    const url = view && M.api.imageUrl(slug, "logo", view.logo);
    if (url) return h("img", { class: "project-mark " + (size || ""), src: url, alt: "", width: "20", height: "20" });
    const mark = h("span", { class: "project-mark monogram " + (size || ""), "aria-hidden": "true" }, initials(name));
    mark.style.background = colourOf(slug);
    return mark;
  }
  M.projectMark = projectMark;

  // The tab's icon: the project's logo where it has one, else the browser's default.
  function setFavicon(slug, view) {
    const url = slug && view && M.api.imageUrl(slug, "logo", view.logo);
    let link = document.head && document.head.querySelectorAll
      ? Array.from(document.head.querySelectorAll("link")).find((l) => l.getAttribute("rel") === "icon") || null
      : null;
    if (!url) {
      if (link) link.remove();
      return;
    }
    if (!link) {
      link = h("link", { rel: "icon" });
      document.head.appendChild(link);
    }
    link.setAttribute("href", url);
  }

  // ---- header -------------------------------------------------------------

  // Always visible: every project of this human with what waits there, and
  // the cross-project view with the total.
  function switcher(ctx) {
    const N = M.notify.state;
    // With the hub's notifications: what asks for the human, requests,
    // unread chats and mentions (docs/api.md §18.2); else the open requests.
    const total = N.available ? N.counts.total : ctx.projects.reduce((n, p) => n + (p.open_requests || 0), 0);
    const count = (n) => (n ? h("span", { class: "count", "aria-label": n + " open" }, String(n)) : null);
    // The same words on every pill: what the number is made of.
    const counted = (c) => (c.total ? h("span", { class: "count", "aria-label": [c.requests ? c.requests + " open" : null,
      c.chat ? c.chat + " unread in chats" : null, c.mention ? c.mention + (c.mention === 1 ? " mention" : " mentions") : null].filter(Boolean).join(", ") },
    String(c.total)) : null);
    const pill = (p) => (N.available ? counted(M.notify.projectCount(p)) : count(p.open_requests));
    const all = N.available ? counted({ requests: N.counts.inbox, chat: N.counts.chat, mention: N.counts.mention, total }) : count(total);
    return h("nav", { class: "switcher", "aria-label": "Projects" },
      h("a", { href: "/all", "aria-current": ctx.scope === "all" ? "page" : null }, "All projects", all),
      ctx.projects.map((p) => h("a", {
        href: projectLink(p.full_name, "inbox"),
        "aria-current": ctx.scope === "project" && p.full_name === ctx.slug ? "page" : null,
      },
      projectMark(p.full_name, p.name, (ctx.projectViews || {})[p.full_name], "small"),
      p.name,
      h("span", { class: "dot state-dot-" + p.state, title: STATE_LABELS[p.state] || p.state, "aria-label": STATE_LABELS[p.state] || p.state }),
      pill(p))),
    // Runners belong to the person, not to a project (the maintainer's
    // wish, tsk-cb6myw32def0): they are in the gear menu, not this row.
    h("a", { href: "/new", class: "new-project", "aria-current": ctx.scope === "new" ? "page" : null }, "+ New project"));
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

  // The inbox tab says the project's open requests, the chat tab its unread
  // chats (docs/api.md §18.2), where the hub has notifications.
  function tabCount(ctx, route) {
    if (!M.notify.state.available || (route !== "inbox" && route !== "chat")) return null;
    const c = M.notify.projectCount(ctx.projects.find((p) => p.full_name === ctx.slug) || { full_name: ctx.slug });
    const n = route === "inbox" ? c.requests : c.chat;
    return n ? h("span", { class: "count", "aria-label": n + (route === "inbox" ? " open" : " unread") }, String(n)) : null;
  }

  function renderTabCounts(ctx) {
    const nav = document.getElementById("header").querySelector("nav.views");
    if (!nav) return;
    nav.querySelectorAll("a").forEach((a) => {
      const route = NAV.find((n) => a.getAttribute("href") === projectLink(ctx.slug, n.route));
      if (!route) return;
      const old = a.querySelector(".count");
      if (old) old.remove();
      const fresh = tabCount(ctx, route.route);
      if (fresh) a.appendChild(fresh);
    });
  }

  // The bell follows the counts; an open one stays as it is until closed.
  function renderBell(ctx) {
    const header = document.getElementById("header");
    const old = header.querySelector(".bell-box");
    if (old && old.querySelector("[aria-expanded=\"true\"]")) return;
    const fresh = M.notify.bell(ctx, () => ctx.refreshCounts());
    if (old && fresh) { old.parentNode.insertBefore(fresh, old); old.remove(); }
    else if (old) old.remove();
    else if (fresh) { const me = header.querySelector(".me"); if (me) me.insertBefore(fresh, me.firstChild); }
  }

  // The Chat button follows the counts too, keeping the focus if it had it.
  function renderChat(ctx) {
    const old = document.getElementById("header").querySelector("a.chat-button");
    if (!old) return;
    const focused = document.activeElement === old;
    const fresh = M.notify.chatButton(ctx);
    old.parentNode.insertBefore(fresh, old);
    old.remove();
    if (focused) fresh.focus();
  }

  // The Lead button beside Chat, once whom it reaches is known
  // (js/lead-chat.js); none where it reaches no one.
  function renderLead(ctx) {
    const me = document.getElementById("header").querySelector(".me");
    const chat = me && me.querySelector("a.chat-button");
    if (!chat || !ctx.chatFound || !M.leadChat) return;
    const lead = M.leadChat.leadControl(ctx, ctx.chatFound);
    if (lead) me.insertBefore(lead, chat.nextSibling);
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
    const mayConfigure = ctx.scope === "project" && (ctx.canAdmin || ctx.isOwner);
    // Views lead to the project's Settings tab too (the overview's Set the
    // repository), at the repository field.
    ctx.openSettings = mayConfigure ? () => {
      settingsFocus = "repo-url";
      M.route.go(projectLink(ctx.slug, "settings"));
    } : null;
    // Settings: the hub's and one's own; the project's are its tab.
    const settings = M.menuButton({
      label: "Settings",
      class: "settings-menu",
      face: M.icons.gear(18),
      items: () => [
        // Agents belong to their owner and span projects (the maintainer, 2026-10-29).
        ctx.me.kind === "human" ? { label: "Agents", href: "/agents", current: ctx.scope === "agents" } : null,
        { label: "Runners", href: "/runners", current: ctx.scope === "runners" },
        ctx.me.instance_admin ? { label: "Instance administration", href: "/admin", current: ctx.scope === "instance-admin" } : null,
      ].filter(Boolean),
    });
    // Sign in another device (§2.6.2) where the hub's machine form has it.
    let deviceCodes = false;
    M.api.hubHas("POST", "/auth/device-codes").then((yes) => { deviceCodes = yes; }, () => {});
    // Organisations (§6.26) where the hub has them; humans only.
    let orgs = false;
    // A machine form that cannot be read keeps the entry (views.md).
    if (ctx.me.kind === "human") M.api.hubHas("GET", "/orgs").then((yes) => { orgs = yes; }, () => { orgs = true; });
    // The human: their picture, the account, signing out.
    const profile = M.menuButton({
      label: "Your profile: " + ctx.me.display_name,
      class: "profile-menu",
      face: [M.avatar(ctx.me, 24), h("span", { class: "me-name" }, ctx.me.display_name)],
      items: () => [
        { label: "Profile", href: "/account" },
        { label: "Picture", href: "/account/picture" },
        { label: "Preferences", href: "/account/preferences" },
        { label: "Theme", href: "/account/theme" },
        orgs ? { label: "Organisations", href: "/account/orgs", current: ctx.scope === "orgs" } : null,
        deviceCodes ? { label: "Sign in another device", href: "/account/sign-in-device" } : null,
        { label: "Change password", href: "/account" },
        { label: "Linked accounts", disabled: true, why: "later" },
        { separator: true },
        { label: "Sign out", onSelect: logout },
      ].filter(Boolean),
    });
    append(header,
      h("div", { class: "bar" },
        brandTitle(),
        ctx.scope === "project"
          ? [projectMark(ctx.slug, ctx.project.name, ctx.project), h("span", { class: "project" }, ctx.project.name)]
          : h("span", { class: "project" }, { new: "New project", account: "Your account", orgs: "Organisations", agents: "Your agents", runners: "Runners", "instance-admin": "Instance administration", observe: "Read along", chats: "Chats" }[ctx.scope] || "Everything waiting for you"),
        M.api.source === "fixtures"
          ? h("span", { class: "source", title: "Data from web/fixtures/, not from the hub. Changes are kept in this tab only." }, "Fixtures")
          : null,
        // Chat, Notifications, the gear, the profile: in one row on a phone too.
        h("span", { class: "me" }, M.notify.chatButton(ctx), M.notify.bell(ctx, () => ctx.refreshCounts()), settings.el, profile.el)),
      // The projects, and at their right, apart, this project's state and
      // the owner's absence with the settings that change them.
      h("div", { class: "switcher-row" },
        switcher(ctx),
        ctx.scope === "project"
          ? h("div", { class: "project-state", role: "group", "aria-label": "State and absence" },
            stateBadge(ctx.project.state, ctx.project.state_note),
            releasedMark(ctx.project),
            absence ? h("span", { class: "state away", title: absence.scope }, "Away until " + formatTime(absence.until)) : null)
          : null),
      ctx.scope === "project" && ctx.project.state_note ? h("p", { class: "state-note" }, ctx.project.state_note) : null,
      // The time is in the block above; what holds meanwhile, here.
      absence
        ? h("p", { class: "flag absence" }, "While away: " + absence.scope)
        : null,
      ctx.scope === "project"
        ? h("nav", { class: "views", "aria-label": "Views" },
          NAV.filter((item) => offered(ctx, item) && item.tab !== false).map((item) => h("a", {
            href: projectLink(ctx.slug, item.route),
            "aria-current": item.route === current ? "page" : null,
          }, item.label, tabCount(ctx, item.route))))
        : null);
    header.querySelectorAll("nav").forEach((nav) => { showCurrent(nav); scrollCue(nav); });
    // Whom the Lead button reaches: known at once in a project, read for every project outside one.
    header.chatCtx = ctx;
    if (M.leadChat) {
      M.leadChat.found(ctx).then((f) => {
        if (document.getElementById("header").chatCtx !== ctx) return;
        ctx.chatFound = f;
        renderLead(ctx);
      }, () => {});
    }
  }

  // The field a link into Settings asked for (the overview's Set the
  // repository); taken once the view is drawn.
  let settingsFocus = null;
  // What the last save on Settings did, said once on the redrawn tab.
  let settingsSaved = null;
  M.views.settings = async function (ctx, root) {
    append(root, h("h2", null, "Settings"),
      h("p", { class: "muted" }, "This project's settings. Yours and the hub's are in the gear menu."),
      settingsSaved ? h("p", { class: "ok", role: "status" }, settingsSaved) : null,
      projectPanel(ctx));
    settingsSaved = null;
    const wanted = settingsFocus ? Array.from(root.querySelectorAll("input")).find((el) => el.id === settingsFocus) : null;
    settingsFocus = null;
    if (wanted) window.setTimeout(() => wanted.focus(), 0);
  };

  // ---- context ------------------------------------------------------------

  // The project's members as read: the list, the index by id and the names
  // set together, so no view reads one fresher than the others. Every view
  // that reads the members again sets them through this (M.withMembers).
  function withMembers(ctx, members) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    ctx.members = members;
    ctx.memberById = byId;
    ctx.nameOf = (id) => (byId[id] ? byId[id].display_name : id || "—");
    return ctx;
  }

  // Each project's logo for the switcher: from /me's projects where the hub
  // puts it there (docs/api.md §5.1), else from the full project views
  // (GET /projects, §6.1); without either the switcher draws monograms.
  async function projectViews(me) {
    if (me.projects.every((p) => "logo" in p)) {
      const bySlug = {};
      me.projects.forEach((p) => { bySlug[p.full_name] = p; });
      return bySlug;
    }
    try {
      const list = await M.api.get("/projects");
      const bySlug = {};
      (list.items || []).forEach((p) => { bySlug[p.full_name] = p; });
      return bySlug;
    } catch (err) {
      return {};
    }
  }

  // §6.25: a full name that is no project of one's own may be an alias (a
  // rename, a transfer), which the hub answers with the current full name.
  // Null where nothing moved: the view says what it says.
  async function movedTo(where, me) {
    if (where.scope !== "project" || me.projects.some((p) => p.full_name === where.slug)) return null;
    const view = await M.api.get("/projects/" + M.api.projectPath(where.slug)).catch(() => null);
    return view && view.full_name && view.full_name !== where.slug && me.projects.some((p) => p.full_name === view.full_name)
      ? projectLink(view.full_name, where.route, ...where.args) : null;
  }

  async function loadContext(where, me) {
    const ctx = {
      me: me.member,
      projects: me.projects,
      serverTime: me.server_time,
      scope: where.scope,
      projectLink,
      stateLabel: (state) => STATE_LABELS[state] || state,
      stateBadge,
      releasedMark,
      refresh: render,
      markSeen: () => {},
      // Once the session ended, a view still drawing starts nothing more.
      every: (ms, fn) => { if (!sessionEnded) timers.push(window.setInterval(fn, ms)); },
      onDispose: (fn) => { disposers.push(fn); },
      listeners: [],
      onEvents: (fn) => { ctx.listeners.push(fn); },
      // Re-reads /me for the switcher's counts. What counts as seen stays;
      // the inbox marks it after an answer of its own.
      refreshCounts: async () => {
        // A failed notifications read keeps the last counts and leaves /me's
        // refresh standing; the next round reads them again.
        const [fresh] = await Promise.all([M.api.get("/me"), M.notify.read().catch(() => null)]);
        ctx.projects = fresh.projects;
        renderSwitcher(ctx);
        renderChat(ctx);
        renderBell(ctx);
        renderTabCounts(ctx);
        document.title = M.notify.title(baseTitle);
        // While a sign-in alert is unread, or when the last one went: the
        // banner is built again each round, so a swap of alerts or an
        // approved session ending elsewhere shows at once (§2.6.5).
        if (securityCount() || bannerFor) renderBanner(ctx);
      },
    };
    if (where.scope !== "project") return ctx;
    const mine = me.projects.find((p) => p.full_name === where.slug);
    if (!mine) {
      throw new M.api.ApiError("You are not a member of the project " + where.slug, 404, "/me", "not_found");
    }
    ctx.slug = where.slug;
    // Trust × role (docs/api.md §2.3): owner and admin hold project:admin and
    // members:admin for a human; absence is the owner's alone.
    ctx.trust = mine.trust;
    ctx.role = mine.role;
    ctx.canAdmin = M.trust.governs(mine);
    ctx.isOwner = M.trust.owner(mine);
    ctx.base = "/projects/" + M.api.projectPath(where.slug);
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

  // One project's context inside a view that is not the project's (the
  // global chat, js/chats.js): its project, members and role, its own
  // listeners and no events feed of its own. chatLink builds the links of
  // its chats, so that they stay in that view.
  M.withMembers = (ctx, members) => withMembers(ctx, members);
  M.projectContext = async (ctx, slug, chatLink) => {
    const mine = ctx.projects.find((p) => p.full_name === slug);
    if (!mine) throw new M.api.ApiError("You are not a member of the project " + slug, 404, "/me", "not_found");
    const pctx = Object.assign({}, ctx, {
      slug, trust: mine.trust, role: mine.role, canAdmin: M.trust.governs(mine), isOwner: M.trust.owner(mine),
      base: "/projects/" + M.api.projectPath(slug), listeners: [], outsider: false,
    });
    pctx.onEvents = (fn) => { pctx.listeners.push(fn); };
    pctx.link = (view, ...rest) => (view === "chat" ? chatLink(slug, rest[0]) : projectLink(slug, view, ...rest));
    const [project, members] = await Promise.all([M.api.get(pctx.base), M.api.getAll(pctx.base + "/members")]);
    pctx.project = project;
    return withMembers(pctx, members.items);
  };

  // Timers belong to one render; the next render stops them.
  let timers = [];
  let disposers = [];
  function stopTimers() {
    disposers.forEach((fn) => fn());
    disposers = [];
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
    // The inbox count as §18.2 keeps it (counts.inbox, by_project's inbox),
    // which counts the personal requests the list holds; /me's open_requests
    // does not. A hub without notifications: open_requests.
    const notified = () => M.notify.state.available && M.notify.state.counts;
    const openNow = () => (where.scope === "all"
      ? (notified() ? M.notify.state.counts.inbox || 0 : ctx.projects.reduce((n, p) => n + (p.open_requests || 0), 0))
      : (() => { const p = ctx.projects.find((x) => x.full_name === ctx.slug); return p ? (notified() ? M.notify.projectCount(p).requests : p.open_requests) : undefined; })());
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
    if (notifyError) { append(failLine, h("p", { class: "send-status failed" }, "Could not read your notifications: " + notifyError.message)); notifyError = null; }
    // A hidden tab asks nothing; shown again, it reads what it missed.
    let missed = false;
    const poll = () => { missed = false; return counts().then(() => clear(failLine), failed); };
    ctx.every(POLL_MS, () => { if (hidden()) { missed = true; return null; } return poll(); });
    ctx.every(BACK_MS, () => (missed && !hidden() ? poll() : null));
    // A changed count is answered by reloading; an answer given here
    // updates what counts as seen.
    ctx.markSeen = () => { seen = openNow(); };

    if (where.scope !== "project") return;
    ctx.onEvents((events) => {
      const theirs = events.filter((e) => !(e.actor && e.actor.member_id === ctx.me.id));
      const texts = [];
      if (theirs.some((e) => PROJECT_KINDS.test(e.kind))) texts.push("The project changed.");
      if (item && item.watch && theirs.some((e) => item.watch.test(e.kind))) texts.push(item.changed);
      texts.forEach((t) => changed.add(t));
      if (texts.length) append(clear(changeLine), h("p", { class: "flag" }, Array.from(changed).join(" ") + " ", reload));
      if (events.some((e) => REQUEST_KINDS.test(e.kind))) counts().catch(failed);
    });
    let reading = false;
    let eventsMissed = false;
    const read = async () => {
      if (reading) return;
      eventsMissed = false;
      reading = true;
      try {
        await readEvents(ctx);
        clear(failLine);
      } catch (err) {
        failed(err);
      } finally {
        reading = false;
      }
    };
    // A hidden tab reads no events; shown again, it reads what it missed
    // within BACK_MS, from the cursor.
    ctx.every(EVENTS_MS, () => { if (hidden()) { eventsMissed = true; return null; } return read(); });
    ctx.every(BACK_MS, () => (eventsMissed && !hidden() ? read() : null));
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
  // The mail sign-in banner (§2.6.5) at the top of the page: built when the
  // page renders and again when the count of unread sign-in alerts changes.
  let bannerFor = 0;
  let bannerSeq = 0;
  const securityCount = () => (M.notify.state.available && M.notify.state.counts ? M.notify.state.counts.security || 0 : 0);
  function renderBanner(ctx) {
    if (!M.sessions) return;
    const main = document.getElementById("main");
    const seq = ++bannerSeq;
    bannerFor = securityCount();
    const drop = () => { const old = main.querySelector(".signin-banner"); if (old) main.removeChild(old); };
    if (!bannerFor) { drop(); return; }
    M.sessions.banner(ctx, () => render()).then((b) => {
      if (seq !== bannerSeq) return;
      drop();
      if (b) main.insertBefore(b, main.firstChild);
    });
  }

  // The tab title without its count, and a failed notifications read to say.
  let baseTitle = "Maity";
  let notifyError = null;

  // Browser notifications run across renders, once per page; the account's
  // wish is read once and again when the account view changes it.
  async function startBrowserNotifications(ctx) {
    if (M.notify.running() || M.notify.state.available === false || !("Notification" in window) || window.Notification.permission !== "granted") return;
    try {
      const settings = M.notify.state.settings || (M.notify.state.settings = await M.api.get("/me/notification-settings"));
      M.notify.startBrowser(ctx, settings);
    } catch (err) {
      notifyError = err;
    }
  }

  async function render() {
    const seq = ++renderSeq;
    stopTimers();
    // A route noted as not on this hub holds within one view only: after a
    // deploy, the next navigation asks it again.
    M.api.absent.clear();
    const main = document.getElementById("main");
    // The view being left stays on screen until the next one is drawn, but
    // takes no click or key any more: an action there (a Revoke) would be
    // answered into a view that is gone, while the new one shows what it read
    // before. Every way out of render() replaces main or renders again.
    Array.from(main.childNodes).forEach((n) => { if (n.setAttribute) n.setAttribute("inert", ""); });
    let where = { scope: "unknown" };
    let ctx;
    try {
      where = parseRoute();
      if (where.scope === "invite" && M.invite) { await M.invite.page(main, document.getElementById("header"), where.token); return; }
      if (where.scope === "register" && M.register) { await M.register.page(main, document.getElementById("header"), routeNext()); return; }
      // A project's swarm (§6.22): the public page for a visitor, for anyone
      // who is not a member and with ?as=public; a member gets the tab.
      const swarmHere = where.scope === "project" && where.route === "swarm" && M.swarm;
      const publicSwarm = () => M.swarm.publicPage(main, document.getElementById("header"), where.slug);
      if (swarmHere && M.route.current().query.get("as") === "public") { await publicSwarm(); return; }
      try {
        await M.api.get("/auth/session");
      } catch (err) {
        if (err.status === 401 && swarmHere) { await publicSwarm(); return; }
        // Without a session the login page; the landing page at the root
        // is the hub's own static page (§16.7), never drawn here.
        if (err.status === 401) { renderLogin(main); return; }
        throw err;
      }
      const me = await M.api.get("/me");
      if (seq !== renderSeq) return;
      // Signed in again after signing out here: the stream may run again.
      M.notify.resume();
      // A new session: what the old one still gets back (a late 401) ends nothing.
      if (sessionEnded) { sessionEnded = false; M.sessionEpoch = (M.sessionEpoch || 0) + 1; }
      // An account that waits for approval (§2.7.5) sees that, and nothing else.
      if (me.member && me.member.account_status === "pending") {
        // Its one page has its own address (§16.11): /account/pending.
        if (M.route.current().path !== "/account/pending") M.route.go("/account/pending", { replace: true });
        renderPending(main);
        return;
      }
      if (where.scope === null || where.scope === "login") {
        const next = where.scope === "login" ? routeNext() : null;
        M.route.go(next || (me.projects.length === 1 ? projectLink(me.projects[0].full_name, "inbox") : "/all"), { replace: true });
        return;
      }
      // An earlier address of a project (a rename, a transfer) leads to its current one.
      const moved = await movedTo(where, me);
      if (seq !== renderSeq) return;
      if (moved) { M.route.go(moved, { replace: true }); return; }
      // Not a member: a project's swarm is its public page.
      if (swarmHere && !me.projects.some((p) => p.full_name === where.slug)) { await publicSwarm(); return; }
      // Notifications never stop the page: a failed read is said in the
      // notice (watch), and a hub without them leaves the counts as /me has them.
      const [loaded, views] = await Promise.all([loadContext(where, me), projectViews(me),
        M.notify.read().catch((err) => { notifyError = err; })]);
      ctx = loaded;
      ctx.projectViews = views;
      if (seq !== renderSeq) return;
    } catch (err) {
      if (seq !== renderSeq) return;
      // The page could not load: the header with the lockup stays, the
      // failure stands where the loader stood, with a way to try again.
      append(clear(document.getElementById("header")), h("div", { class: "bar" }, brandTitle()));
      append(clear(main), pageFailed(err));
      return;
    }
    if (seq !== renderSeq) return;
    const item = where.scope === "project" ? NAV.find((n) => n.route === where.route) : null;
    renderHeader(ctx, (item && item.current) || where.route);
    const empty = where.scope === "all" && !ctx.projects.length;
    const known = ["all", "new", "account", "orgs", "agents", "runners", "instance-admin", "observe", "notifications", "chats"].includes(where.scope)
      || (item && own(M.views, item.view || item.route) && offered(ctx, item));
    let viewName = "unknown";
    if (["all", "new", "account", "orgs", "agents", "runners", "instance-admin", "observe", "notifications", "chats"].includes(where.scope)) viewName = where.scope;
    else if (known) viewName = (item && item.current) || where.route;
    const root = h("section", { class: "view view-" + viewName });
    try {
      if (empty) {
        // A personal request (§7) reaches its human without a membership:
        // what waits comes first, the way to a project of one's own after it.
        const waiting = (await M.api.getAll("/requests")).items;
        if (seq !== renderSeq) return;
        if (waiting.length) await M.views.inbox(ctx, root, []);
        const start = h("div", { class: "no-projects" });
        M.views.noProjects(ctx, start);
        append(root, start);
        // Without a project of one's own, one's agents may still be in others'.
        const elsewhere0 = M.observe ? await M.observe.note(ctx) : null;
        if (elsewhere0) append(root, elsewhere0);
      } else if (where.scope === "all") {
        await M.views.inbox(ctx, root, []);
        // Where one's agents are in projects one is not: read along there.
        const elsewhere = M.observe ? await M.observe.note(ctx) : null;
        if (elsewhere) append(root, elsewhere);
      } else if (where.scope === "notifications") {
        await M.waiting.full(ctx, root);
      } else if (where.scope === "chats") {
        await M.views.chats(ctx, root, where.args || []);
      } else if (where.scope === "observe") {
        await M.views.observe(ctx, root, where);
      } else if (where.scope === "new") {
        await M.views.newProject(ctx, root);
      } else if (where.scope === "account") {
        await M.views.account(ctx, root, where.args);
      } else if (where.scope === "orgs") {
        await M.views.orgs(ctx, root, where.args);
      } else if (where.scope === "instance-admin") {
        await M.views.instanceAdmin(ctx, root);
      } else if (where.scope === "runners") {
        await M.views.runners(ctx, root);
      } else if (where.scope === "agents") {
        await M.views.agentsPage(ctx, root, where.args);
      } else if (known) {
        await M.views[item.view || item.route](ctx, root, where.args);
      } else {
        append(root, h("p", null, "No such view. ", h("a", { href: "/all" }, "Go to everything waiting for you.")));
      }
    } catch (err) {
      if (seq !== renderSeq) return;
      append(clear(root), errorBox(err));
    }
    if (seq !== renderSeq) return;
    append(clear(main), root);
    renderBanner(ctx);
    watch(ctx, where, known ? item : null, main);
    let label = "No such view";
    if (empty) label = "No projects yet";
    else if (where.scope === "all") label = "All projects";
    else if (where.scope === "notifications") label = "Notifications";
    else if (where.scope === "chats") label = "Chats";
    else if (where.scope === "new") label = "New project";
    else if (where.scope === "account") label = "Your account";
    else if (where.scope === "orgs") label = where.args && where.args[0] ? "@" + M.orgs.handleOf(where.args[0]) + " · Organisations" : "Organisations";
    else if (where.scope === "runners") label = "Runners";
    else if (where.scope === "agents") label = "Your agents";
    else if (where.scope === "instance-admin") label = "Instance administration";
    else if (where.scope === "observe") label = "Read along · " + where.slug;
    else if (known) label = item.label + " · " + ctx.project.name;
    baseTitle = label + " · Maity";
    document.title = M.notify.title(baseTitle);
    if (M.notify.state.available) startBrowserNotifications(ctx);
    setFavicon(where.scope === "project" ? ctx.slug : null, where.scope === "project" ? ctx.project : null);
  }

  // The loader as web/index.html has it, for a page that loads again.
  const SVG = "http://www.w3.org/2000/svg";
  function loading() {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "maity-loader");
    svg.setAttribute("viewBox", "0 0 64 64");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Loading");
    const seats = [[32, 10], [51, 21], [51, 43], [32, 54], [13, 43], [13, 21]];
    seats.forEach(([cx, cy]) => {
      const c = document.createElementNS(SVG, "circle");
      c.setAttribute("cx", String(cx)); c.setAttribute("cy", String(cy)); c.setAttribute("r", "6");
      svg.appendChild(c);
    });
    seats.forEach(([cx, cy]) => {
      const r = document.createElementNS(SVG, "rect");
      r.setAttribute("class", "maity-loader-t");
      r.setAttribute("x", String(cx - 6)); r.setAttribute("y", String(cy - 6));
      r.setAttribute("width", "12"); r.setAttribute("height", "12"); r.setAttribute("rx", "3");
      svg.appendChild(r);
    });
    return h("p", { class: "page-loading", role: "status" }, svg, " Loading Maity…");
  }

  // A page that could not load, in plain words for the person (the
  // designer's pass on #433): the mark at rest, what does not work, what to
  // do, the technical reason folded away, and Try again; Sign in again
  // where the session is gone.
  function pageFailed(err) {
    const fixtures = M.api.source === "fixtures";
    const unreachable = !err.status;
    const title = fixtures ? "The sample data didn't load"
      : unreachable ? "Maity can't reach its hub" : "Maity couldn't load this page";
    const advice = fixtures ? "Reload the page. If it keeps happening, the fixtures are missing from this copy."
      : unreachable ? "Check your connection, then try again. If it keeps happening, the hub may be down."
        : "Try again. If it keeps happening, the hub may have a problem; the details say which.";
    const again = h("button", { type: "button", class: "primary", onclick: () => { append(clear(document.getElementById("main")), loading()); render(); } }, "Try again");
    const signIn = err.status === 401
      ? h("button", { type: "button", onclick: () => { M.route.go("/login"); } }, "Sign in again") : null;
    const mark = (file, theme) => h("img", { class: "page-failed-mark brand-mark " + theme, src: "brand/" + file, alt: "", width: "40", height: "40" });
    return h("div", { class: "page-failed", role: "alert" },
      mark("maity-mark-small.svg", "brand-light"), mark("maity-mark-small-dark.svg", "brand-dark"),
      h("h2", { class: "page-failed-title" }, title),
      h("p", { class: "muted" }, advice),
      h("details", null, h("summary", null, "Details"), h("p", { class: "page-failed-reason" },
        [err.status ? "HTTP " + err.status + (err.code ? " " + err.code : "") : "No answer", err.message, err.path || null].filter(Boolean).join(" · "))),
      h("div", { class: "page-failed-actions" }, signIn, again));
  }

  M.errorBox = errorBox;
  M.withMembers = withMembers;
  M.logout = logout;
  M.brandTitle = brandTitle;
  M.statusLine = statusLine;
  M.STATE_LABELS = STATE_LABELS;

  // Back, forward, a link of the dashboard, M.route.go: the view follows.
  M.route.listen(render);
  window.addEventListener("resize", () => {
    document.getElementById("header").querySelectorAll("nav").forEach(updateCue);
  });
  document.addEventListener("DOMContentLoaded", render);
})(window.Maity);
