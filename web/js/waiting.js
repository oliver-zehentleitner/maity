// Unread activity beside the requests, sharing the tab's notifications stream.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append, clear, formatAgo } = M.dom;
  // §18.8: requests (and what asks like one), conversations, mentions, the
  // account's alerts. Cards, the ticker and jour fixe steps are not here.
  const GROUPS = [["inbox", "Request updates"], ["chat", "Conversations"], ["mention", "Mentions"], ["account", "Account"]];
  const projectOf = (x) => x.project && x.project.slug || "";
  // The view shows 200 rows: 4 pages of the hub's most (50, §18.2) are all it
  // reads; the rest is behind More notifications. Stream events within a
  // short while are one refresh.
  const SHOWN = 200, PAGES = SHOWN / 50, SETTLE_MS = 400;
  const requestKey = (slug, id) => slug + "/" + id;
  function rows(items, requests, project) {
    const open = new Set(requests.filter((r) => r.status === "open").map((r) => requestKey(r.slug, r.id)));
    const chats = new Map(), groups = Object.fromEntries(GROUPS.map(([key]) => [key, []]));
    const seen = new Set();
    items.filter((x) => !x.read && (!project || projectOf(x) === project)).forEach((x) => {
      if (seen.has(x.id)) return;
      seen.add(x.id);
      const target = x.target || {};
      if (x.kind === "inbox" && target.type === "request" && open.has(requestKey(projectOf(x), target.id))) return;
      const kind = x.kind === "security" ? "account" : x.kind;
      if (!groups[kind]) return;
      if (kind === "chat" && target.type === "conversation") {
        const key = projectOf(x) + "/" + target.id;
        const row = chats.get(key);
        if (row) {
          row.count++;
          if (String(x.at) > String(row.item.at)) row.item = x;
        } else {
          const entry = { item: x, count: 1 };
          chats.set(key, entry); groups.chat.push(entry);
        }
      } else groups[kind].push({ item: x, count: 1 });
    });
    GROUPS.forEach(([key]) => groups[key].sort((a, b) => String(b.item.at).localeCompare(String(a.item.at))));
    return groups;
  }

  // more: the list stopped at its 200 rows, so a conversation's count may
  // be short of the hub's.
  function rowLink(ctx, row, afterRead, status, more) {
    const x = row.item;
    return h("li", { class: "waiting-item", "data-notification": x.id },
      h("a", { href: M.notify.linkOf(x), onclick: () => {
        if (M.notify.keepsUnread(x)) return; // Read with This was me, or once the matter is closed.
        M.api.post("/me/notifications/read", { ids: [x.id] }).then(() => {
          if (afterRead) afterRead(x);
          M.notify.changed();
          return ctx.refreshCounts();
        }).catch((err) => status.fail("Could not mark the item read: ", err));
      } }, x.redacted ? "Removed" : x.title || M.notify.KIND_WORDS[x.kind] || "Notification"),
      x.kind === "chat" && !x.read ? h("span", { class: "count" }, row.count + (more ? "+" : "") + " unread") : null,
      h("span", { class: "muted" }, (x.project ? x.project.name + " · " : "") + formatAgo(x.at)));
  }

  // Mounted without being awaited: the inbox is drawn at once, this list
  // reads in its own time and says so meanwhile.
  function mount(ctx, root, requests, project) {
    const box = h("div", { class: "waiting-activity" }), status = M.statusLine();
    append(root, box, status.el);
    let items = [], more = false, disposed = false, loading = false, again = false, last = null, settle = null;
    // The project the last read was for: the 200 are read per project, so a
    // filter changed to another one reads again instead of filtering the 200.
    let readFor;
    const draw = () => {
      if (!M.notify.state.available) { clear(box); last = null; return; }
      if (readFor !== undefined && project() !== readFor) { refresh(); return; }
      const groups = rows(items, requests, project());
      const signature = JSON.stringify(groups) + more;
      if (signature === last) return;
      last = signature;
      const focused = Array.from(box.querySelectorAll(".waiting-item")).find((el) => el.contains(document.activeElement));
      const focusId = focused && focused.getAttribute("data-notification");
      clear(box);
      let left = SHOWN, total = 0;
      GROUPS.forEach(([key, title]) => {
        const all = groups[key]; total += all.length;
        const visible = all.slice(0, left); left -= visible.length;
        if (visible.length) append(box, h("section", { class: "waiting-group", "aria-label": title },
          h("h3", null, title), h("ul", { class: "waiting-items" }, visible.map((row) => rowLink(ctx, row, null, status, more)))));
      });
      if (total > SHOWN || more) append(box, h("p", { class: "hint" }, "Showing " + Math.min(total, SHOWN) + " activity rows. ", h("a", { href: "#/notifications" }, "More notifications")));
      if (focusId) {
        const replacement = Array.from(box.querySelectorAll(".waiting-item")).find((el) => el.getAttribute("data-notification") === focusId);
        if (replacement) replacement.querySelector("a").focus();
      }
    };
    async function refresh() {
      if (disposed || M.notify.state.available === false) { if (!disposed) draw(); return; }
      if (loading) { again = true; return; }
      loading = true;
      try {
        readFor = project();
        const path = "/me/notifications?unread=true&limit=50" + (readFor ? "&project=" + encodeURIComponent(readFor) : "");
        const all = [], cursors = new Set();
        let cursor = null, pages = 0;
        do {
          const answer = await M.api.get(path + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
          if (disposed) return;
          all.push(...(answer.items || []));
          cursor = answer.next_cursor;
          pages++;
          if (cursor && cursors.has(cursor)) throw new Error("The hub repeated a notification page.");
          cursors.add(cursor);
        } while (cursor && pages < PAGES);
        items = all; more = !!cursor; status.done(); draw();
      } catch (err) {
        if (disposed) return;
        if (await M.api.missingRoute(err, "GET", "/me/notifications")) {
          M.api.absent.note("GET", "/me/notifications"); M.notify.state.available = false; items = []; status.done(); draw();
        } else status.fail("Could not read waiting activity: ", err);
      } finally {
        loading = false;
        if (again && !disposed) { again = false; refresh(); }
      }
    }
    // A busy stream is one refresh once it settles, never a new read per event.
    const soon = () => { window.clearTimeout(settle); settle = window.setTimeout(refresh, SETTLE_MS); };
    const unsubscribe = M.notify.state.available ? M.notify.subscribe(soon) : () => {};
    ctx.onDispose(() => { disposed = true; window.clearTimeout(settle); unsubscribe(); });
    if (M.notify.state.available) status.busy("Reading what else is new…");
    const ready = refresh();
    return { draw, ready, refresh };
  }

  // The overflow destination is paginated, so the 200-row landing page
  // never hides the remainder or turns its More link into settings.
  async function full(ctx, root) {
    const list = h("ul", { class: "waiting-items" }), status = M.statusLine();
    const older = h("button", { type: "button" }, "Older");
    let cursor = null, disposed = false;
    ctx.onDispose(() => { disposed = true; });
    async function load() {
      older.disabled = true;
      try {
        const answer = await M.api.get("/me/notifications?limit=50" + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
        if (disposed) return;
        (answer.items || []).filter(M.notify.known).forEach((x) => append(list, rowLink(ctx, { item: x, count: 1 }, null, status)));
        cursor = answer.next_cursor; older.hidden = !cursor; status.done();
        if (!list.children.length) append(list, h("li", { class: "empty" }, "No notifications."));
      } catch (err) {
        if (!disposed) status.fail("Could not read notifications: ", err);
      } finally { older.disabled = false; }
    }
    older.addEventListener("click", load);
    append(root, h("h2", null, "Notifications"), list, older, status.el);
    await load();
  }
  M.waiting = { mount, rows, full };
})(window.Maity);
