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
  // closed, and on a sign-in or address alert only where this session may
  // confirm it (§2.6.5, M.sessions.mayConfirm), else the hub would skip it.
  function row(ctx, x, mark, sessions) {
    const title = x.redacted ? "Removed" : x.title || M.notify.KIND_WORDS[x.kind] || "Notification";
    const security = x.kind === "security";
    const reported = security && sessions && (x.target || {}).type === "session" ? sessions.list.find((s) => s.id === x.target.id) || null : null;
    const markable = !x.read && (security ? !!(sessions && M.sessions && M.sessions.mayConfirm(sessions.current, x, reported)) : !M.notify.keepsUnread(x));
    const markButton = markable ? h("button", { type: "button", class: "small mark-read", "aria-label": "Mark read: " + title }, "Mark read") : null;
    if (markButton) markButton.addEventListener("click", () => mark({ ids: [x.id] }, markButton));
    return h("li", { class: "waiting-item " + (x.read ? "read" : "unread"), "data-notification": x.id },
      h("a", { href: M.notify.linkOf(x), onclick: () => {
        if (x.read || M.notify.keepsUnread(x)) return; // Read with This was me, or once the matter is closed.
        mark({ ids: [x.id] }, null);
      } }, title),
      x.read ? null : h("span", { class: "visually-hidden" }, " (unread)"),
      h("span", { class: "muted" }, (x.project ? x.project.name + " · " : "") + formatAgo(x.at)),
      markButton);
  }

  async function full(ctx, root) {
    const list = h("ul", { class: "waiting-items" }), status = M.statusLine();
    const older = h("button", { type: "button" }, "Older");
    // Mark all read marks up to the head of the first page (§18.3, as the
    // bell does); a sign-in or address alert stays unread (§2.6.5). Always
    // there, off while nothing it would mark is unread.
    const markAll = h("button", { type: "button", class: "small" }, "Mark all read");
    let cursor = null, top = null, disposed = false, items = [];
    // The sessions, read only when the page shows an unread security item.
    let sessions = null;
    ctx.onDispose(() => { disposed = true; });
    const markAllOff = () => { markAll.disabled = top === null || !items.some((x) => !x.read && !M.notify.keepsUnread(x)); };
    async function mark(body, button) {
      if (button) button.disabled = true;
      try {
        await M.api.post("/me/notifications/read", body);
        M.notify.changed();
        await ctx.refreshCounts();
        if (button || body.up_to) { clear(list); cursor = null; items = []; await load(); }
      } catch (err) {
        status.fail("Not marked: ", err);
        if (button) button.disabled = false;
      }
    }
    async function load() {
      older.disabled = true;
      try {
        const answer = await M.api.get("/me/notifications?limit=50" + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
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
        if (!list.children.length) append(list, h("li", { class: "empty" }, "No notifications."));
      } catch (err) {
        if (!disposed) status.fail("Could not read notifications: ", err);
      } finally { older.disabled = false; }
    }
    markAll.addEventListener("click", async () => {
      markAll.disabled = true;
      status.busy("Marking…");
      await mark({ up_to: top }, null);
      markAllOff();
    });
    older.addEventListener("click", load);
    append(root, h("div", { class: "toolbar" }, h("h2", null, "Notifications"), markAll),
      h("p", { class: "hint" }, "Mark all read leaves sign-in and address alerts unread: confirm them with This was me under Sessions in your account."),
      list, older, status.el);
    markAllOff();
    await load();
  }
  M.waiting = { full };
})(window.Maity);
