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
    { route: "inbox", get label() { return M.t("nav.inbox"); } },
    // Redrawn in place on task_*, request_*, probe_observed and member_* (js/overview.js).
    { route: "overview", get label() { return M.t("nav.overview"); } },
    { route: "board", get label() { return M.t("nav.board"); }, watch: /^task_/, get changed() { return M.t("nav.board.changed"); } },
    // One card (/<owner>/<slug>/tasks/<id>, an id's link, js/ids.js): the board
    // with that card marked; its tab is the board's.
    { route: "tasks", view: "board", get label() { return M.t("nav.board"); }, tab: false, current: "board", watch: /^task_/, get changed() { return M.t("nav.board.changed"); } },
    { route: "members", get label() { return M.t("nav.members"); }, watch: /^(member_|session_|credential_)/, get changed() { return M.t("nav.members.changed"); } },
    // The Team page's Organisation tab (js/org.js); its tab in the row is Members'.
    { route: "organisation", get label() { return M.t("nav.organisation"); }, tab: false, current: "members" },
    // One's own agents in the project (js/agents-page.js), the component of
    // /agents; right after Members (the maintainer, 2026-10-31; before Why since 2026-10-29).
    { route: "agents", view: "projectAgents", get label() { return M.t("nav.agents"); }, when: (ctx) => ctx.me.kind === "human", watch: /^(member_|credential_)/, get changed() { return M.t("nav.agents.changed"); } },
    { route: "chat", get label() { return M.t("nav.chat"); } },
    // Redrawn in place from the feed (js/messages.js).
    { route: "messages", get label() { return M.t("nav.messages"); } },
    // The change feed (js/ticker.js); new items from the feed, in place.
    { route: "ticker", get label() { return M.t("nav.ticker"); } },
    // No tab: opened from the Chat tab, the Messages view and a chat (js/project-message.js).
    { route: "message", get label() { return M.t("nav.message"); }, tab: false },
    // The account-level view is views.runners; this one is the project's,
    // linked from the project's Settings, no tab of its own (the maintainer, 2026-10-31).
    { route: "runners", view: "projectRunners", get label() { return M.t("nav.runners"); }, tab: false, current: "settings", section: "runners", admin: true, watch: /^runner_/, get changed() { return M.t("nav.runners.changed"); } },
    // Where the hub knows the Keep the Why export (docs/api.md §6.1, §11.3).
    { route: "why", get label() { return M.t("nav.why"); } },
    // The jour fixe (js/jour-fixe.js, §20): its rounds, one round at jour-fixe/<id>;
    // between Why and Settings (the maintainer, 2026-10-31).
    { route: "jour-fixe", view: "jourFixe", get label() { return M.t("nav.jour_fixe"); } },
    // The project's own settings, its last tab (the maintainer's request,
    // 2026-10-25); a save stays here.
    // One view with two tabs (§16.11): the project's for its admins, one's
    // own at settings/mine for every human member.
    { route: "settings", get label() { return M.t("nav.settings"); }, when: (ctx) => ctx.canAdmin || ctx.me.kind === "human" },
  ];
  const offered = (ctx, item) => (!item.admin || ctx.canAdmin) && (!item.when || item.when(ctx));

  // docs/api.md §6.1; moving to launch is the owner's go.
  const STATES = ["plan", "build", "review", "launch", "archived"];
  const STATE_LABELS = {
    get plan() { return M.t("state.plan"); },
    get build() { return M.t("state.build"); },
    get review() { return M.t("state.review"); },
    get launch() { return M.t("state.launch"); },
    get archived() { return M.t("state.archived"); },
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
  const OWN_WORDS = ["account", "admin", "agents", "all", "api", "assets", "badge", "chats", "components", "explore", "for", "health",
    "impressum", "imprint", "inbox", "invite", "join", "login", "mail", "new", "notifications", "observe", "privacy", "register",
    "requests", "runners", "settings", "sign-in", "terms"];
  // Read by js/ids.js: an id after one of them names no project. The hub's
  // own first words are also js/route.js's HUB list, so a word missing here
  // is still caught there: ids.js links only what M.route.isRoute accepts.
  M.reservedFirst = OWN_WORDS;

  // Throws URIError on a malformed escape; called inside render's try.
  function parseRoute() {
    // A route's own query (/login?next=…) is the page's to read (M.route.current).
    const parts = M.route.current().path.split("/").filter(Boolean).map(decodeURIComponent);
    if (!parts.length) return { scope: null };
    // Signed out as much as signed in: an invitation (§3.4) and registration (§2.7).
    if (parts[0] === "invite" && parts[1]) return { scope: "invite", token: parts[1] };
    // /invite alone: the person invitations of one's projects (§16.11, js/invitations.js).
    if (parts[0] === "invite") return { scope: "invitations" };
    if (parts[0] === "register") return { scope: "register" };
    if (parts[0] === "notifications") return { scope: "notifications" };
    if (parts[0] === "chats") return { scope: "chats", args: parts.slice(1) };
    // The login page, always reachable (docs/api.md §16.7); signed in, the root.
    if (parts[0] === "login") return { scope: "login" };
    if (parts[0] === "all") return { scope: "all" };
    if (parts[0] === "new") return { scope: "new" };
    // /account/orgs[/<handle>]: organisations (§6.26), under the account (views.md).
    if (parts[0] === "account" && parts[1] === "orgs") return { scope: "orgs", args: parts.slice(2) };
    // /settings/forge: the account's forge access (§11.4, §16.11), where the hub's setup redirect lands.
    if (parts[0] === "settings" && parts[1] === "forge" && !parts[2]) return { scope: "account", args: ["forge"] };
    if (parts[0] === "account") return { scope: "account", args: parts.slice(1) };
    if (parts[0] === "runners") return { scope: "runners" };
    // /agents[/<id>]: one's agent profiles across projects (js/agents-page.js).
    if (parts[0] === "agents") return { scope: "agents", args: parts.slice(1) };
    if (parts[0] === "observe" && parts[2]) return { scope: "observe", slug: parts[1] + "/" + parts[2], args: parts.slice(3) };
    if (parts[0] === "admin" && !parts[1]) return { scope: "instance-admin" };
    // The two sections a notification links into (§18.2): Registration, and Reports with one report opened;
    // and Import or export everything, at /admin/site (tsk-xw8a2hd84x3a).
    if (parts[0] === "admin" && ((parts[1] === "registration" || parts[1] === "site") && !parts[2] || parts[1] === "reports" && !parts[3])) {
      return { scope: "instance-admin", section: parts[1], args: parts.slice(2) };
    }
    if (parts[1] && !OWN_WORDS.includes(parts[0])) {
      return { scope: "project", slug: parts[0] + "/" + parts[1], route: parts[2] || "inbox", args: parts.slice(3) };
    }
    // /<handle>: a person or an organisation, the dashboard's own view of them (§6.27, §16.11).
    if (!OWN_WORDS.includes(parts[0])) return { scope: "person", handle: parts[0] };
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
  // picked in the menu switches it too. It is the way home: signed in to
  // everything waiting (/all), without a session to the instance's start
  // page (/); the link carries the name, the pictures none of their own.
  function brandTitle(signedIn) {
    const home = signedIn === undefined ? !!M.api.session() : signedIn;
    const label = home ? "Maity: everything waiting for you" : "Maity: home";
    return h("h1", { class: "brand" },
      h("a", { class: "brand-home", href: home ? "/all" : "/", "aria-label": label, title: label },
        h("img", { class: "brand-lockup brand-light", src: "brand/maity-lockup.svg", alt: "", width: "94", height: "28" }),
        h("img", { class: "brand-lockup brand-dark", src: "brand/maity-lockup-dark.svg", alt: "", width: "94", height: "28" })));
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
  // The selected project's two places one goes to often, beside its state
  // (the maintainer, tsk-n161gf6h8feb): its repository, with its forge's
  // mark, and the Keep the Why dashboard of the family's root. Each only
  // where the project has it, as plain https, in a tab of its own.
  const FORGES = { github: "GitHub", gitlab: "GitLab", gitea: "Gitea" };
  // 16 × 16 marks: GitHub's (Octicons, MIT), GitLab's simplified, and a
  // branch (Octicons) for any other forge.
  const FORGE_MARKS = {
    github: "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z",
    gitlab: "M8 15L1 9.8 2.6 2 5 6h6l2.4-4L15 9.8z",
    other: "M9.5 3.25a2.25 2.25 0 113 2.12V6A2.5 2.5 0 0110 8.5H6a1 1 0 00-1 1v1.13a2.25 2.25 0 11-1.5 0V5.37a2.25 2.25 0 111.5 0v1.84A2.49 2.49 0 016 7h4a1 1 0 001-1v-.63A2.25 2.25 0 019.5 3.25z",
  };
  const BOOK = "M2 2.5A1.5 1.5 0 013.5 1H13v11H3.5a.5.5 0 000 1H13v1.5H3.5A1.5 1.5 0 012 13V2.5zM5 4v1h5V4H5z";
  // The project's own links (§6.11), in this order, each with its word and a 16 × 16 mark
  // (Octicons, MIT): an issue, a book, a speech bubble, a chat bubble.
  const OWN_LINKS = [
    ["issues", () => M.t("project.link.issues"), "M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm9 3a1 1 0 11-2 0 1 1 0 012 0zm-.25-6.25a.75.75 0 00-1.5 0v3.5a.75.75 0 001.5 0v-3.5z"],
    ["wiki", () => M.t("project.link.wiki"), BOOK],
    ["discussions", () => M.t("project.link.discussions"), "M1.75 1A1.75 1.75 0 000 2.75v6.5C0 10.216.784 11 1.75 11H3v3.25a.75.75 0 001.28.53L7.56 11H11.25A1.75 1.75 0 0013 9.25v-6.5A1.75 1.75 0 0011.25 1H1.75z"],
    ["chat", () => M.t("project.link.chat"), "M2.75 2h10.5c.966 0 1.75.784 1.75 1.75v7A1.75 1.75 0 0113.25 12.5H6.06L3.28 14.78A.75.75 0 012 14.25V12.5h-.25A1.75 1.75 0 010 10.75v-7C0 2.784.784 2 1.75 2h1z"],
  ];
  // The links that are set, as plain https only: what the header and the overview show.
  const ownLinks = (project) => OWN_LINKS.map(([key, label, d]) => ({ key, label: label(), d, url: M.dom.safeUrl(((project && project.links) || {})[key]) }))
    .filter((x) => x.url);
  function mark(d) {
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 16 16"], ["width", "16"], ["height", "16"], ["aria-hidden", "true"], ["focusable", "false"], ["class", "header-link-mark"]]
      .forEach(([k, v]) => svg.setAttribute(k, v));
    const p = document.createElementNS(SVG, "path");
    p.setAttribute("d", d);
    p.setAttribute("fill", "currentColor");
    svg.appendChild(p);
    return svg;
  }
  function projectLinks(project) {
    const repo = project.repository && M.dom.safeUrl(project.repository.url);
    const forge = project.repository && project.repository.forge;
    const exp = project.keep_the_why_export;
    const root = exp && (exp.members || []).find((m) => m.path === "");
    const why = root && M.dom.safeUrl(root.dashboard_url);
    // "Repository" whatever the forge (the maintainer, 11b7e786): its mark says which forge,
    // and the project's own links stand beside it.
    const name = M.t("project.link.repository");
    return [
      repo ? h("a", { class: "header-link", href: repo, target: "_blank", rel: "noopener noreferrer",
        "aria-label": M.t("project.link.opens", { what: FORGES[forge] ? M.t("project.link.repository_on", { forge: FORGES[forge] }) : name }), title: repo },
      mark(FORGE_MARKS[forge] || FORGE_MARKS.other), h("span", { class: "header-link-text" }, name)) : null,
      ownLinks(project).map((x) => h("a", { class: "header-link", href: x.url, target: "_blank", rel: "noopener noreferrer",
        "aria-label": M.t("project.link.opens", { what: x.label }), title: x.url },
      mark(x.d), h("span", { class: "header-link-text" }, x.label))),
      why ? h("a", { class: "header-link", href: why, target: "_blank", rel: "noopener noreferrer",
        "aria-label": "Keep the Why dashboard (opens in a new tab)", title: why },
      mark(BOOK), h("span", { class: "header-link-text" }, "Why")) : null,
    ];
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
      brandTitle(false),
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

  // The second step of a sign-in (js/second-factor.js, §2.8.2): the session reaches
  // nothing else, so the page is the step with the brand and the theme around it.
  function renderStep(main, session) {
    append(clear(document.getElementById("header")), h("div", { class: "bar" }, brandTitle(false), themeMenu()));
    // The hub answers next "/" without a stored one (§2.8.2): from a /sign-in/ address that is the
    // dashboard's start, not that address again (goNext stays put for "/").
    const done = (next) => {
      const n = safeNext(next);
      if ((!n || n === "/") && M.route.current().path.startsWith("/sign-in/")) M.route.go("/", { replace: true });
      else goNext(next);
    };
    M.secondFactor.page(main, session, done, logout);
  }
  function renderStepElsewhere(main, signedIn) {
    append(clear(document.getElementById("header")), h("div", { class: "bar" }, brandTitle(false), themeMenu()));
    M.secondFactor.elsewhere(main, signedIn);
  }

  // The one page of a pending account (§2.7.5): it may sign out, nothing else.
  function renderPending(main) {
    document.title = "Waiting for approval · Maity";
    append(clear(document.getElementById("header")), h("div", { class: "bar" }, brandTitle(false), themeMenu()));
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

  // The project's own links (§6.11), for project:admin: four fields, only
  // the changed ones sent (the hub merges by key, so another admin's change
  // to another link meanwhile stays), each refusal said at its field.
  function linksForm(ctx) {
    const current = ctx.project.links || {};
    const status = statusLine();
    const WORDS = { format: () => M.t("settings.links.format"), too_long: () => M.t("settings.links.too_long"), unknown: () => M.t("settings.links.unknown") };
    const fields = OWN_LINKS.map(([key, label]) => {
      const id = "link-" + key;
      const input = h("input", { id, type: "url", inputmode: "url", autocomplete: "off", spellcheck: "false", maxlength: "500",
        "aria-describedby": ["links-hint", id + "-error"].join(" ") });
      input.value = current[key] || "";
      const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
      return { key, input, error, nodes: [h("label", { for: id }, label()), input, error] };
    });
    return h("form", {
      class: "inline-form links-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        fields.forEach((f) => { f.error.textContent = ""; f.input.removeAttribute("aria-invalid"); });
        const links = {};
        fields.forEach((f) => {
          const value = f.input.value.trim();
          if (value !== (current[f.key] || "")) links[f.key] = value || null;
        });
        if (!Object.keys(links).length) { status.done(); append(status.el, h("span", null, M.t("settings.links.unchanged"))); return; }
        status.busy(M.t("settings.links.saving"));
        try {
          await M.api.patch(ctx.base, { links });
          settingsSaved = M.t("settings.links.saved");
          render();
        } catch (err) {
          const refused = err.code === "invalid" && err.details && err.details.fields;
          const hits = refused ? fields.filter((f) => refused["links." + f.key]) : [];
          if (!hits.length) { status.fail(M.t("settings.links.not_saved"), err); return; }
          status.done();
          hits.forEach((f) => {
            const why = refused["links." + f.key];
            f.error.textContent = Object.hasOwn(WORDS, why) ? WORDS[why]() : why;
            f.input.setAttribute("aria-invalid", "true");
          });
          hits[0].input.focus();
        }
      },
    },
    h("h2", { class: "panel-title" }, M.t("settings.links.title")),
    h("p", { class: "hint", id: "links-hint" }, M.t("settings.links.hint")),
    fields.map((f) => f.nodes),
    h("button", { type: "submit" }, M.t("settings.links.save")),
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
      .concat(M.trust.ROLES.map((role) => ({ value: "role:" + role, label: "Role: every " + M.trust.roleLabel(role).toLowerCase() })))
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
    // atFields: a form's own handler of the hub's field refusals; when it says
    // them at its fields, the status line only says that nothing was saved.
    const save = async (body, label, atFields) => {
      status.busy("Saving…");
      try {
        await M.api.patch(ctx.base, body);
        settingsSaved = label + " saved.";
        render();
      } catch (err) {
        // true: said at the fields; a text: what the status line says besides them.
        const atField = atFields && atFields(err);
        if (atField) { status.fail(label + " not saved: ", { message: atField === true ? M.t("settings.see_fields") : atField }); return; }
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
    if (ctx.canAdmin) append(panel, onboardingForm(ctx), repositoryForm(ctx), M.forge ? M.forge.repositoryPart(ctx) : null, linksForm(ctx));
    // Its name: rename and transfer, for a human owner (§6.25).
    const names = M.projectNames && M.projectNames.section(ctx);
    if (names) append(panel, names);
    if (M.projectSetup) append(panel, memoryPanel(ctx, save, humanAdmin));
    // Humans only, as every policy field (§2.3 ʰ); the commitment above the badge (the maintainer, 2026-11-01).
    if (humanAdmin) append(panel, keepTheWhyForm(ctx, save), keepTheWhyDefaultsForm(ctx, save), badgeForm(ctx, save));
    // The jour fixe's series and their moderators (§20.1, §20.2), kept by humans.
    if (humanAdmin && M.jourFixeSeries) append(panel, M.jourFixeSeries.settingsPart(ctx));
    // The change ticker (§17.3), read by every member, changed by a human
    // admin; the forge webhook (§17.4) for that human only.
    if (M.tickerSettings) {
      append(panel, h("div", { class: "ticker-settings-slot" }, M.tickerSettings.tickerForm(ctx, save)));
      if (humanAdmin) append(panel, h("div", { class: "webhook-slot" }, M.tickerSettings.webhookPanel(ctx)));
    }
    if (humanAdmin) {
      append(panel, memberAgentsForm(ctx, save), h("div", { class: "agent-owners-slot" }, agentOwnersForm(ctx, save)));
    }
    if (ctx.canAdmin && M.groupChat) append(panel, h("div", { class: "remove-reported-slot" }, blindRemoveForm(ctx)));
    // §8.7: everyone's pending uploads, for freeing the quota.
    if (ctx.canAdmin && M.attachments) append(panel, M.attachments.pendingPanel(ctx));
    // docs/api.md §6.1.
    if (ctx.canAdmin) append(panel, signingForm(ctx, save), imagesForm(ctx));
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

  // The memory provider (docs/api.md §6.1, §6.21): shown to every member;
  // a human with project:admin changes it, with a reason for the rules
  // change it makes. A change makes and cancels no setup card, and a switch
  // to Keep the Why lets the commitment below be required.
  function memoryPanel(ctx, save, humanAdmin) {
    const { PROVIDERS, OPTIONS } = M.projectSetup;
    const provider = ctx.project.memory && ctx.project.memory.provider;
    const s = ctx.project.setup;
    const named = (PROVIDERS.find(([v]) => v === provider) || [provider, provider])[1];
    // The dashboard's option names its path (§6.1 setup.dashboard_path).
    const chosen = s ? OPTIONS.filter(([k]) => s[k]).map(([k, title]) => (k === "keep_the_why_dashboard" && s.dashboard_path
      ? M.t("memory.setup.dashboard_under", { title, path: s.dashboard_path }) : title)) : [];
    let setup;
    if (!s) setup = h("p", { class: "muted" }, M.t("memory.setup.predates"));
    else if (Array.isArray(s.cards) && s.cards.length) {
      setup = [h("p", null, M.tn("memory.setup.cards", { cards: s.cards.map((id, i) => [i ? ", " : null, h("a", { class: "id-ref", href: ctx.link("tasks", id) }, id)]) })),
        s.keep_the_why_dashboard && s.dashboard_path ? h("p", { class: "muted" }, M.t("memory.setup.published", { path: s.dashboard_path })) : null];
    } else if (!chosen.length || Array.isArray(s.cards)) setup = h("p", { class: "muted" }, M.t("memory.setup.none"));
    else setup = [h("p", null, M.t("memory.setup.chosen", { options: chosen.join("; ") })), h("p", { class: "muted" }, M.t("memory.setup.later"))];
    const what = provider === "keep-the-why" ? M.t("memory.keep_the_why") : provider === "none" ? M.t("memory.none") : null;
    const shown = h("p", null, h("strong", null, named || "—"), what ? [": ", what] : null);
    if (!humanAdmin) {
      return h("section", { class: "inline-form memory-panel", "aria-labelledby": "memory-heading" },
        h("h2", { class: "panel-title", id: "memory-heading" }, M.t("memory.title")), shown,
        h("p", { class: "hint" }, M.t("memory.hint.read")), setup);
    }
    const select = h("select", { id: "memory-provider" },
      PROVIDERS.map(([value, label]) => h("option", { value, selected: value === provider }, label)));
    select.value = provider || "keep-the-why";
    const reason = h("input", { id: "memory-reason", required: true, placeholder: M.t("memory.reason.placeholder") });
    return h("form", {
      class: "inline-form memory-panel",
      "aria-labelledby": "memory-heading",
      onsubmit: (e) => {
        e.preventDefault();
        if (select.value === provider) return;
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ memory: { provider: select.value }, reason: reason.value.trim() }, M.t("memory.saved_label"));
      },
    },
    h("h2", { class: "panel-title", id: "memory-heading" }, M.t("memory.title")), shown,
    h("p", { class: "hint" }, M.t("memory.hint.change")),
    h("label", { for: "memory-provider" }, M.t("memory.label")), select,
    h("label", { for: "memory-reason" }, M.t("memory.reason")), reason,
    h("button", { type: "submit" }, M.t("memory.change")),
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

  // §6.1 agent_owners and outside_roles, §6.2 "An agent whose owner is no
  // member". Unset, the setting follows the public page; the form says what it
  // reads now, and once set it has no way back to unset, as in the hub.
  const OUTSIDE_BASES = ["coder", "designer", "writer", "blue-team"];
  function agentOwnersForm(ctx, save) {
    const pol = ctx.project.policy;
    const stored = pol.agent_owners || null;
    const served = ctx.project.public_page === "on" && ctx.project.state !== "archived" && !ctx.project.moderation;
    const effective = stored || (served ? "anyone" : "members");
    const words = { members: M.t("settings.agent_owners.members"), anyone: M.t("settings.agent_owners.anyone") };
    const select = h("select", { id: "agent-owners-select" },
      stored ? null : h("option", { value: "" }, M.t("settings.agent_owners.unset", { value: words[effective] })),
      ["members", "anyone"].map((v) => h("option", { value: v }, words[v])));
    select.value = stored || "";
    const current = pol.outside_roles || ["coder"];
    // A role already on the list stays offered, so that saving never drops it unseen.
    const offered = [...new Set([...OUTSIDE_BASES, ...current])];
    const boxes = offered.map((r) => {
      const box = h("input", { type: "checkbox", id: "outside-role-" + r, value: r });
      box.checked = current.includes(r);
      return box;
    });
    const roleRow = (r, i) => h("label", { class: "check", for: "outside-role-" + r }, boxes[i], " ", M.trust.roleLabel(r));
    const roleRows = offered.map(roleRow);
    const rolesHint = h("p", { class: "hint" }, M.t("settings.outside_roles.hint"));
    // The project's own roles on a base that works may be offered too (§2.3, §6.1); without them the built-in ones stay.
    // Added beside the others, so that what was ticked or typed meanwhile stays.
    M.api.get(ctx.base + "/roles").then((r) => {
      ((r && r.custom) || []).filter((x) => OUTSIDE_BASES.includes(x.base)).map((x) => x.name)
        .filter((name) => !offered.includes(name)).forEach((name) => {
          offered.push(name);
          boxes.push(h("input", { type: "checkbox", id: "outside-role-" + name, value: name }));
          rolesHint.parentNode.insertBefore(roleRow(name, offered.length - 1), rolesHint);
        });
    }).catch(() => {});
    const reason = h("input", { id: "agent-owners-reason", required: true, placeholder: M.t("settings.agent_owners.reason_hint") });
    const error = h("p", { class: "field-error", id: "agent-owners-error", role: "alert" });
    return h("form", {
      class: "inline-form agent-owners-form",
      onsubmit: (e) => {
        e.preventDefault();
        error.textContent = "";
        const roles = offered.filter((r, i) => boxes[i].checked);
        const policy = {};
        if (select.value && select.value !== stored) policy.agent_owners = select.value;
        if (roles.length !== current.length || roles.some((r) => !current.includes(r))) policy.outside_roles = roles;
        if (!Object.keys(policy).length) return;
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ policy, reason: reason.value.trim() }, M.t("settings.agent_owners.title"), (err) => {
          if (((err.details || {}).fields || {}).outside_roles !== "outside_owner") return false;
          error.textContent = M.t("settings.agent_owners.role_in_use");
          return true;
        });
      },
    },
    h("h2", { class: "panel-title" }, M.t("settings.agent_owners.title")),
    h("p", { class: "hint" }, M.t("settings.agent_owners.hint")),
    h("label", { for: "agent-owners-select" }, M.t("settings.agent_owners.label")), select,
    h("fieldset", { class: "outside-roles" },
      h("legend", null, M.t("settings.outside_roles.label")),
      roleRows,
      rolesHint),
    error,
    h("label", { for: "agent-owners-reason" }, M.t("settings.agent_owners.reason")), reason,
    h("button", { type: "submit" }, M.t("settings.agent_owners.save")));
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
    h("p", { class: "hint" }, "A member may add agents of their own: as member or guest, in every role but ops and proxy, reporting to them. "
      + "Turning it off stops new ones; joins already handed out stay usable."),
    h("label", { for: "member-agents-select" }, "Members add agents"), on,
    h("label", { for: "member-agents-max" }, "Agents per member (active and open joins)"), max, error,
    h("label", { for: "member-agents-reason" }, "Reason"), reason,
    h("button", { type: "submit" }, "Save"));
  }

  // Where a joining agent's personal Keep the Why settings come from (§6.23). The values stay
  // in the repository's .keep-the-why: the hub does not read that file, so this names it.
  function keepTheWhyDefaultsForm(ctx, save) {
    if ((ctx.project.memory || {}).provider === "none") return null;
    const current = ctx.project.policy.keep_the_why_defaults || "adopt";
    const select = h("select", { id: "ktw-defaults-select" },
      [["adopt", M.t("settings.ktw_defaults.adopt")], ["ask", M.t("settings.ktw_defaults.ask")]]
        .map(([v, l]) => h("option", { value: v, selected: v === current }, l)));
    select.value = current;
    const reason = h("input", { id: "ktw-defaults-reason", required: true, placeholder: M.t("settings.ktw_defaults.reason_placeholder") });
    return h("form", {
      class: "inline-form ktw-defaults-form",
      onsubmit: (e) => {
        e.preventDefault();
        if (select.value === current) return;
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ policy: { keep_the_why_defaults: select.value }, reason: reason.value.trim() }, M.t("settings.ktw_defaults.title"));
      },
    },
    h("h2", { class: "panel-title" }, M.t("settings.ktw_defaults.title")),
    h("p", { class: "hint" }, M.t("settings.ktw_defaults.hint")),
    h("label", { for: "ktw-defaults-select" }, M.t("settings.ktw_defaults.label")), select,
    h("label", { for: "ktw-defaults-reason" }, M.t("settings.ktw_defaults.reason")), reason,
    h("button", { type: "submit" }, M.t("settings.ktw_defaults.save")));
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
    // What asks for the human, requests, unread chats and mentions
    // (docs/api.md §18.2); until the counts are read, the open requests.
    const total = N.counts ? N.counts.total : ctx.projects.reduce((n, p) => n + (p.open_requests || 0), 0);
    const count = (n) => (n ? h("span", { class: "count", "aria-label": n + " open" }, String(n)) : null);
    // The same words on every pill: what the number is made of.
    const counted = (c) => (c.total ? h("span", { class: "count", "aria-label": [c.requests ? c.requests + " open" : null,
      c.chat ? c.chat + " unread in chats" : null, c.mention ? c.mention + (c.mention === 1 ? " mention" : " mentions") : null].filter(Boolean).join(", ") },
    String(c.total)) : null);
    const pill = (p) => (N.counts ? counted(M.notify.projectCount(p)) : count(p.open_requests));
    const all = N.counts ? counted({ requests: N.counts.inbox, chat: N.counts.chat, mention: N.counts.mention, total }) : count(total);
    return h("nav", { class: "switcher", "aria-label": "Projects" },
      h("a", { href: "/all", "aria-current": ctx.scope === "all" || ctx.scope === "chats" || ctx.scope === "agents" ? "page" : null }, "All projects", all),
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
  // chats (docs/api.md §18.2), once the counts are read.
  function tabCount(ctx, route) {
    if (!M.notify.state.counts || (route !== "inbox" && route !== "chat")) return null;
    const c = M.notify.projectCount(ctx.projects.find((p) => p.full_name === ctx.slug) || { full_name: ctx.slug });
    const n = route === "inbox" ? c.requests : c.chat;
    return n ? h("span", { class: "count", "aria-label": n + (route === "inbox" ? " open" : " unread") }, String(n)) : null;
  }

  // All projects has two pages (the maintainer, tsk-gw59z3w3fenf): the
  // requests across projects and every chat across them, each with what
  // the hub counts for it (§18.2).
  const ALL_PAGES = [
    { scope: "all", href: "/all", label: () => M.t("all.page.inbox"),
      count: (c) => c.inbox || 0, said: (count) => M.t("all.page.inbox.count", { count }) },
    { scope: "chats", href: "/chats", label: () => M.t("all.page.chats"),
      count: (c) => c.chat || 0, said: (count) => M.t("all.page.chats.count", { count }) },
    // One's own agent profiles (/agents): a human's page, and nothing counted on it.
    { scope: "agents", href: "/agents", label: () => M.t("all.page.agents"), when: (ctx) => ctx.me.kind === "human", count: () => 0 },
  ];
  function allCount(page) {
    const n = M.notify.state.counts ? page.count(M.notify.state.counts) : 0;
    return n ? h("span", { class: "count", "aria-label": page.said(n) }, String(n)) : null;
  }

  function renderTabCounts(ctx) {
    const nav = document.getElementById("header").querySelector("nav.views");
    if (!nav) return;
    if (ctx.scope !== "project") {
      nav.querySelectorAll("a").forEach((a) => {
        const page = ALL_PAGES.find((x) => a.getAttribute("href") === M.route.href(x.href));
        if (!page) return;
        const old = a.querySelector(".count");
        if (old) old.remove();
        const fresh = allCount(page);
        if (fresh) a.appendChild(fresh);
      });
      return;
    }
    nav.querySelectorAll("a").forEach((a) => {
      // dom.h writes a route through M.route.href (a fragment in the fixture), so compare with that.
      const route = NAV.find((n) => a.getAttribute("href") === M.route.href(projectLink(ctx.slug, n.route)));
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
    // A bell that was not there goes where it stands: before the profile.
    else if (fresh) {
      const me = header.querySelector(".me");
      const profileBox = me ? Array.from(me.children).find((c) => c.querySelector && c.querySelector(".profile-menu")) : null;
      if (me) me.insertBefore(fresh, profileBox || null);
    }
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
      label: M.t("menu.settings"),
      class: "settings-menu",
      face: M.icons.gear(18),
      items: () => [
        // Agents belong to their owner and span projects (the maintainer, 2026-10-29).
        ctx.me.kind === "human" ? { label: M.t("menu.agents"), href: "/agents", current: ctx.scope === "agents" } : null,
        { label: M.t("menu.runners"), href: "/runners", current: ctx.scope === "runners" },
        ctx.me.instance_admin ? { label: M.t("menu.instance_admin"), href: "/admin", current: ctx.scope === "instance-admin" } : null,
      ].filter(Boolean),
    });
    // "+": bring someone in, an agent or a person (the maintainer, 2026-10-31):
    // the agents page with its join, the invitations page. Humans only.
    const add = ctx.me.kind === "human" ? M.menuButton({
      label: M.t("menu.add.label"),
      class: "add-menu",
      face: h("span", { class: "add-face", "aria-hidden": "true" }, "+"),
      items: () => [
        { label: M.t("menu.add.agent"), href: "/agents", current: ctx.scope === "agents" },
        { label: M.t("menu.add.user"), href: "/invite", current: ctx.scope === "invitations" },
      ],
    }) : null;
    // The human: their picture, the account, signing out.
    const profile = M.menuButton({
      label: M.t("menu.profile.label", { name: ctx.me.display_name }),
      class: "profile-menu",
      face: [M.avatar(ctx.me, 24), h("span", { class: "me-name" }, ctx.me.display_name)],
      items: () => [
        { label: M.t("menu.profile"), href: "/account" },
        { label: M.t("menu.picture"), href: "/account/picture" },
        { label: M.t("menu.preferences"), href: "/account/preferences" },
        { label: M.t("menu.theme"), href: "/account/theme" },
        ctx.me.kind === "human" ? { label: M.t("menu.orgs"), href: "/account/orgs", current: ctx.scope === "orgs" } : null,
        { label: M.t("menu.sign_in_device"), href: "/account/sign-in-device" },
        { label: M.t("menu.change_password"), href: "/account" },
        { label: M.t("menu.linked_accounts"), disabled: true, why: M.t("menu.later") },
        { separator: true },
        { label: M.t("menu.sign_out"), onSelect: logout },
      ].filter(Boolean),
    });
    append(header,
      h("div", { class: "bar" },
        brandTitle(true),
        ctx.scope === "project"
          ? [projectMark(ctx.slug, ctx.project.name, ctx.project), h("span", { class: "project" }, ctx.project.name)]
          : h("span", { class: "project" }, ({ new: M.t("header.new"), account: M.t("header.account"), orgs: M.t("header.orgs"), agents: M.t("header.agents"), runners: M.t("header.runners"), invitations: M.t("header.invitations"),
            "instance-admin": M.t("header.instance_admin"), observe: M.t("header.observe"), person: M.t("header.person") })[ctx.scope] || M.t("header.all")),
        M.api.source === "fixtures"
          ? h("span", { class: "source", title: M.t("header.fixtures.title") }, M.t("header.fixtures"))
          : null,
        // Chat, (Lead,) "+", the gear, Notifications, the profile: in one row on a phone too.
        // The Lead button goes in right after Chat once known (renderLead), so "+" stays to its right.
        h("span", { class: "me" }, M.notify.chatButton(ctx), add ? add.el : null, settings.el, M.notify.bell(ctx, () => ctx.refreshCounts()), profile.el)),
      // The projects, and at their right, apart, this project's state and
      // the owner's absence with the settings that change them.
      h("div", { class: "switcher-row" },
        switcher(ctx),
        ctx.scope === "project"
          ? h("div", { class: "project-state", role: "group", "aria-label": M.t("header.state_group") },
            stateBadge(ctx.project.state, ctx.project.state_note),
            releasedMark(ctx.project),
            absence ? h("span", { class: "state away", title: absence.scope }, M.t("header.away_until", { time: formatTime(absence.until) })) : null,
            projectLinks(ctx.project))
          : null),
      ctx.scope === "project" && ctx.project.state_note ? h("p", { class: "state-note" }, ctx.project.state_note) : null,
      // The time is in the block above; what holds meanwhile, here.
      absence
        ? h("p", { class: "flag absence" }, M.t("header.while_away", { scope: absence.scope }))
        : null,
      ctx.scope === "project"
        ? h("nav", { class: "views", "aria-label": M.t("header.views") },
          NAV.filter((item) => offered(ctx, item) && item.tab !== false).map((item) => h("a", {
            href: projectLink(ctx.slug, item.route),
            "aria-current": item.route === current ? "page" : null,
          }, item.label, tabCount(ctx, item.route))))
        : ctx.scope === "all" || ctx.scope === "chats" || ctx.scope === "agents"
          ? h("nav", { class: "views", "aria-label": M.t("all.pages") },
            ALL_PAGES.filter((page) => !page.when || page.when(ctx)).map((page) => h("a", { href: page.href, "aria-current": ctx.scope === page.scope ? "page" : null }, page.label(), allCount(page))))
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
  // Settings (§16.11): the project's tab at settings for those with
  // project:admin, one's own at settings/mine for every human member; a
  // member without the right who opens settings gets settings/mine.
  M.views.settings = async function (ctx, root, args) {
    const mine = (args || [])[0] === "mine";
    const human = ctx.me.kind === "human";
    if (!mine && !ctx.canAdmin) { M.route.go(projectLink(ctx.slug, "settings", "mine"), { replace: true }); return; }
    const tabs = [ctx.canAdmin ? ["Project", projectLink(ctx.slug, "settings"), !mine] : null,
      human ? ["Mine", projectLink(ctx.slug, "settings", "mine"), mine] : null].filter(Boolean);
    append(root, h("h2", null, "Settings"),
      tabs.length > 1 ? h("nav", { class: "settings-tabs", "aria-label": "Settings" },
        tabs.map(([label, href, on]) => h("a", { href, "aria-current": on ? "page" : null }, label))) : null);
    if (mine) { await M.mySettings(ctx, root); return; }
    append(root,
      h("p", { class: "muted" }, "This project's settings. Yours for this project are under Mine; the hub's are in the gear menu."),
      // The project's runners, no tab of their own any more.
      h("p", { class: "settings-runners" }, h("a", { href: projectLink(ctx.slug, "runners") }, M.t("settings.runners_link"))),
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

  // Each project's logo for the switcher, from /me's projects (docs/api.md §5.1).
  async function projectViews(me) {
    const bySlug = {};
    me.projects.forEach((p) => { bySlug[p.full_name] = p; });
    return bySlug;
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
      ownLinks,
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
    // does not. Until the counts are read: open_requests.
    const notified = () => M.notify.state.counts;
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
  const securityCount = () => (M.notify.state.counts ? M.notify.state.counts.security || 0 : 0);
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
    if (M.notify.running() || !("Notification" in window) || window.Notification.permission !== "granted") return;
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
      let session;
      try {
        session = await M.api.get("/auth/session");
      } catch (err) {
        // The mail's second-factor link in a browser without the session it was sent for (§2.8.8).
        if (err.status === 401 && M.secondFactor && M.secondFactor.isMailLink()) { renderStepElsewhere(main, false); return; }
        // Without a session the login page; the landing page at the root
        // is the hub's own static page (§16.7), never drawn here.
        if (err.status === 401) { renderLogin(main); return; }
        throw err;
      }
      // A new session after a sign-out or an ended one: what the old one still gets back (a late
      // 401) ends nothing, and one that ends now is told again — the second step included.
      if (sessionEnded) { sessionEnded = false; M.sessionEpoch = (M.sessionEpoch || 0) + 1; }
      // A session that owes the second factor reaches nothing else (§2.8.2): its step.
      if (session && session.second_factor === "required" && M.secondFactor) { renderStep(main, session); return; }
      // The link opened where the sign-in is already complete: nothing to post here.
      if (M.secondFactor && M.secondFactor.isMailLink()) { renderStepElsewhere(main, true); return; }
      // The step's own address (where a sign-in link's 303 lands) with the sign-in complete: the start.
      if (M.route.current().path === "/sign-in/second-factor") { M.route.go("/", { replace: true }); return; }
      const me = await M.api.get("/me");
      if (seq !== renderSeq) return;
      // Signed in again after signing out here: the stream may run again.
      M.notify.resume();
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
      // Notifications never stop the page: a failed read is said in the
      // notice (watch), and the counts stay as /me has them.
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
    const known = ["all", "new", "account", "orgs", "agents", "runners", "instance-admin", "observe", "notifications", "chats", "person"].includes(where.scope)
      || (item && own(M.views, item.view || item.route) && offered(ctx, item));
    let viewName = "unknown";
    if (["all", "new", "account", "orgs", "agents", "runners", "instance-admin", "observe", "notifications", "chats", "person", "invitations"].includes(where.scope)) viewName = where.scope;
    // `section`: a view whose tab stands for another (`current`) keeps its own name here.
    else if (known) viewName = (item && (item.section || item.current)) || where.route;
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
        await M.views.instanceAdmin(ctx, root, where);
      } else if (where.scope === "runners") {
        await M.views.runners(ctx, root);
      } else if (where.scope === "invitations") {
        await M.views.invitations(ctx, root);
      } else if (where.scope === "agents") {
        await M.views.agentsPage(ctx, root, where.args);
      } else if (where.scope === "person") {
        await M.views.person(ctx, root, where.handle);
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
    else if (where.scope === "invitations") label = M.t("header.invitations");
    else if (where.scope === "agents") label = "Your agents";
    else if (where.scope === "person") label = "@" + where.handle;
    else if (where.scope === "instance-admin") label = "Instance administration";
    else if (where.scope === "observe") label = "Read along · " + where.slug;
    else if (known) label = item.label + " · " + ctx.project.name;
    baseTitle = label + " · Maity";
    document.title = M.notify.title(baseTitle);
    if (M.notify.state.counts) startBrowserNotifications(ctx);
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
