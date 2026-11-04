// All notifications (/notifications, docs/api.md §18.2, §18.3): the bell's
// More, paged by the hub's cursor, unread ones in bold with a dot, Mark read
// per item and Mark all read. The inbox shows the requests alone (the maintainer, 2026-10-29):
// conversations, mentions and the account's alerts are here, on the bell
// and on the Chat button.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append, clear, formatAgo } = M.dom;

  // One item: its link, and Mark read where a read mark can be set from
  // here (§18.3): not on an open matter, which reads as read once it is
  // closed, and on a security alert only where this session may mark it
  // (M.sessions.mayMark, as the bell does): an address change from a
  // confirmed session older than it, every other kind from any session. A
  // sign-in is no item (§2.6.5); the box above shows the sessions.
  function row(ctx, x, mark, sessions) {
    let li = null;
    const title = x.redacted ? M.t("waiting.removed") : x.title || M.notify.KIND_WORDS[x.kind] || M.t("waiting.untitled");
    const security = x.kind === "security";
    const markable = !x.read && (security ? !!(sessions && M.sessions && M.sessions.mayMark(sessions.current, x, null)) : !M.notify.keepsUnread(x));
    const link = h("a", { href: M.notify.linkOf(x), onclick: () => {
      if (x.read || M.notify.keepsUnread(x)) return; // Read once the matter is closed.
      mark({ ids: [x.id] });
    } }, title);
    const unread = x.read ? null : h("span", { class: "visually-hidden" }, " ", M.t("waiting.unread"));
    // Marked read in place: the row, its words and its button change, the
    // focus goes to its link, the pages read so far stay.
    const markButton = markable ? h("button", { type: "button", class: "small mark-read", "aria-label": M.t("waiting.mark_read.label", { title }) }, M.t("waiting.mark_read")) : null;
    if (markButton) {
      markButton.addEventListener("click", async () => {
        markButton.disabled = true;
        if (!(await mark({ ids: [x.id] }))) { markButton.disabled = false; return; }
        x.read = true;
        li.className = "waiting-item read";
        if (unread && unread.parentNode) unread.parentNode.removeChild(unread);
        if (markButton.parentNode) markButton.parentNode.removeChild(markButton);
        link.focus();
      });
    }
    li = h("li", { class: "waiting-item " + (x.read ? "read" : "unread"), "data-notification": x.id },
      link, unread,
      h("span", { class: "muted" }, (x.project ? x.project.name + " · " : "") + formatAgo(x.at)),
      markButton);
    return li;
  }

  // "Current sessions" (§18.8): the human's active sessions, compact, newest
  // first, at most five and "and N more", with a link to Profile → Sessions,
  // where sessions are ended and confirmed. No buttons, no unread state. Read
  // when the page opens and again whenever `sessions_rev` moves (§18.2).
  const SESSIONS_SHOWN = 5;
  function sessionsBox(ctx) {
    const list = h("ul", { class: "current-sessions-items" }), status = M.statusLine();
    const box = h("section", { class: "panel current-sessions", "aria-labelledby": "current-sessions-title" },
      h("h3", { id: "current-sessions-title", class: "panel-subtitle" }, M.t("waiting.sessions.title")),
      list, status.el,
      h("p", { class: "hint" }, h("a", { href: "/account/sessions" }, M.t("waiting.sessions.manage"))));
    let seen, disposed = false, seq = 0;
    async function read() {
      const mine = ++seq;
      seen = M.notify.state.sessionsRev;
      let items;
      try {
        items = (await M.api.get("/auth/sessions")).items.filter((s) => !s.ended_at);
      } catch (err) {
        if (!disposed && mine === seq) status.fail(M.t("waiting.sessions.read_failed"), err);
        return;
      }
      if (disposed || mine !== seq) return;
      status.done();
      items.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
      const rows = items.slice(0, SESSIONS_SHOWN).map((s) => h("li", null,
        h("span", null, M.sessions.device(s)),
        h("span", { class: "muted" }, " · " + M.sessions.methodOf(s) + " · " + M.t("waiting.sessions.signed_in", { when: formatAgo(s.created_at) })),
        s.current ? h("span", { class: "badge" }, " " + M.t("waiting.sessions.this_session")) : null,
        s.good_standing ? null : h("span", { class: "badge" }, " " + M.t("sessions.unconfirmed_badge"))));
      const more = items.length - SESSIONS_SHOWN;
      append(clear(list), rows, more > 0 ? h("li", { class: "muted" }, M.t("waiting.sessions.more", { count: more })) : null);
    }
    const unsubscribe = M.notify.subscribe(() => { if (!disposed && M.notify.state.sessionsRev !== seen) read(); });
    ctx.onDispose(() => { disposed = true; unsubscribe(); });
    read();
    return box;
  }

  async function full(ctx, root) {
    const list = h("ul", { class: "waiting-items" }), status = M.statusLine();
    const older = h("button", { type: "button" }, M.t("waiting.older"));
    // Mark all read marks up to the head of the first page (§18.3, as the
    // bell does); a sign-in or address alert stays unread (§2.6.5). Always
    // there, off while nothing it would mark is unread.
    const markAll = h("button", { type: "button", class: "small" }, M.t("waiting.mark_all"));
    // A filter from the address (?kind=mention&project=<owner>/<slug>, the
    // project's mention link beside its tabs, tsk-xb7bf1x0h3cy): one kind of
    // §18.2 and one project of the human's, sent to the hub as they are, and
    // Mark all read marks that kind and project only (§18.3). Anything else
    // is no filter.
    const asked = M.route.current().query;
    const kind = Object.hasOwn(M.notify.KIND_WORDS, asked.get("kind") || "") ? asked.get("kind") : null;
    const project = ctx.projects.find((p) => p.full_name === asked.get("project")) || null;
    const filter = (kind ? "&kind=" + kind : "") + (project ? "&project=" + encodeURIComponent(project.full_name) : "");
    const scoped = Object.assign({}, kind ? { kind } : null, project ? { project: project.full_name } : null);
    const heading = kind && project ? M.t("waiting.title.kind_in", { kind: M.notify.KIND_WORDS[kind], project: project.name })
      : kind ? M.notify.KIND_WORDS[kind] : project ? M.t("waiting.title.in", { project: project.name }) : M.t("waiting.title");
    let cursor = null, top = null, disposed = false, items = [];
    // The sessions, read only when the page shows an unread security item.
    let sessions = null;
    ctx.onDispose(() => { disposed = true; });
    const markAllOff = () => { markAll.disabled = top === null || !items.some((x) => !x.read && !M.notify.keepsUnread(x)); };
    // True once the hub took it; the counts follow. Mark all read reads
    // the list again, since it reaches items on pages not shown.
    async function mark(body) {
      let answer;
      try {
        answer = await M.api.post("/me/notifications/read", body);
      } catch (err) {
        status.fail(M.t("waiting.not_marked"), err);
        return false;
      }
      // An id the hub left unread (§18.3 `skipped`, e.g. an address change made
      // from this session, which the page cannot see) is said, not shown read.
      const left = body.ids ? ((answer && answer.skipped) || []).find((y) => body.ids.includes(y.id)) : null;
      if (left) {
        status.fail(M.t("waiting.not_marked"), Object.assign(new Error(M.notify.skippedWhy(left.reason)), { details: {} }));
        return false;
      }
      M.notify.changed();
      await ctx.refreshCounts().catch(() => null);
      if (body.up_to) { clear(list); cursor = null; items = []; await load(); } else markAllOff();
      return true;
    }
    async function load() {
      older.disabled = true;
      try {
        const answer = await M.api.get("/me/notifications?limit=50" + filter + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
        if (disposed) return;
        if (cursor === null) top = answer.next_after || null;
        const page = (answer.items || []).filter(M.notify.known);
        if (!sessions && page.some((x) => x.kind === "security" && !x.read)) {
          const listed = await M.api.get("/auth/sessions?ended=true").then((r) => r.items, () => null);
          sessions = listed ? { list: listed, current: listed.find((x) => x.current) || null } : null;
        }
        if (disposed) return;
        items = items.concat(page);
        page.forEach((x) => append(list, row(ctx, x, mark, sessions)));
        cursor = answer.next_cursor; older.hidden = !cursor; status.done();
        markAllOff();
        if (!list.children.length) append(list, h("li", { class: "empty" }, M.t("waiting.none")));
      } catch (err) {
        if (!disposed) status.fail(M.t("waiting.read_failed"), err);
      } finally { older.disabled = false; }
    }
    markAll.addEventListener("click", async () => {
      markAll.disabled = true;
      status.busy(M.t("waiting.marking"));
      await mark(Object.assign({ up_to: top }, scoped));
      markAllOff();
    });
    older.addEventListener("click", load);
    append(root, h("div", { class: "toolbar" }, h("h2", null, heading), markAll),
      filter ? h("p", { class: "hint" }, h("a", { href: "/notifications" }, M.t("bell.all"))) : null,
      M.sessions ? sessionsBox(ctx) : null,
      h("p", { class: "hint" }, M.t("waiting.mark_all.hint")),
      list, older, status.el);
    markAllOff();
    await load();
  }
  M.waiting = { full };
})(window.Maity);
