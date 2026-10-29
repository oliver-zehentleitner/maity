// All notifications (/notifications, docs/api.md §18.2, §18.3): the bell's
// More, paged by the hub's cursor, unread ones in bold with a dot, and Mark
// all read. The inbox shows the requests alone (the maintainer, 2026-10-29):
// conversations, mentions and the account's alerts are here, on the bell
// and on the Chat button.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append, clear, formatAgo } = M.dom;

  function rowLink(ctx, x, status) {
    return h("li", { class: "waiting-item " + (x.read ? "read" : "unread"), "data-notification": x.id },
      h("a", { href: M.notify.linkOf(x), onclick: () => {
        if (x.read || M.notify.keepsUnread(x)) return; // Read with This was me, or once the matter is closed.
        M.api.post("/me/notifications/read", { ids: [x.id] }).then(() => {
          M.notify.changed();
          return ctx.refreshCounts();
        }).catch((err) => status.fail("Could not mark the item read: ", err));
      } }, x.redacted ? "Removed" : x.title || M.notify.KIND_WORDS[x.kind] || "Notification"),
      x.read ? null : h("span", { class: "visually-hidden" }, " (unread)"),
      h("span", { class: "muted" }, (x.project ? x.project.name + " · " : "") + formatAgo(x.at)));
  }

  async function full(ctx, root) {
    const list = h("ul", { class: "waiting-items" }), status = M.statusLine();
    const older = h("button", { type: "button" }, "Older");
    // Mark all read marks up to the head of the first page (§18.3, as the
    // bell does); a sign-in or address alert stays unread (§2.6.5).
    const markAll = h("button", { type: "button", class: "small" }, "Mark all read");
    markAll.hidden = true;
    let cursor = null, top = null, disposed = false;
    ctx.onDispose(() => { disposed = true; });
    async function load() {
      older.disabled = true;
      try {
        const answer = await M.api.get("/me/notifications?limit=50" + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
        if (disposed) return;
        if (cursor === null) top = answer.next_after || null;
        (answer.items || []).filter(M.notify.known).forEach((x) => append(list, rowLink(ctx, x, status)));
        cursor = answer.next_cursor; older.hidden = !cursor; status.done();
        markAll.hidden = top === null || !list.querySelectorAll(".waiting-item.unread").length;
        if (!list.children.length) append(list, h("li", { class: "empty" }, "No notifications."));
      } catch (err) {
        if (!disposed) status.fail("Could not read notifications: ", err);
      } finally { older.disabled = false; }
    }
    markAll.addEventListener("click", async () => {
      markAll.disabled = true;
      status.busy("Marking…");
      try {
        await M.api.post("/me/notifications/read", { up_to: top });
        M.notify.changed();
        await ctx.refreshCounts();
        clear(list); cursor = null;
        await load();
      } catch (err) {
        status.fail("Not marked: ", err);
      } finally { markAll.disabled = false; }
    });
    older.addEventListener("click", load);
    append(root, h("div", { class: "toolbar" }, h("h2", null, "Notifications"), markAll), list, older, status.el);
    await load();
  }
  M.waiting = { full };
})(window.Maity);
