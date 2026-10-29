// Notifications for the human (docs/api.md §18, stage 1 and the browser
// part): the counts behind the badges and the tab title, the bell with the
// latest items, and browser notifications while a tab is open. Everything
// comes from GET /me/notifications; a hub without it leaves the page as it
// was (counts summed from /me, no bell). Links are built from an item's
// target, never from its url: the dashboard owns its routes.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo } = M.dom;

  const KIND_WORDS = {
    // Only what the human has to react to (docs/api.md §18.1, 2026-10-26): what
    // only informs is on the board, the ticker and the project's feed.
    inbox: "Requests", chat: "Chats", mention: "Mentions", security: "Sign-ins and address",
  };
  // How long a browser long-poll may hold, and how long to stay away after
  // another tab took the long-poll over (§18.2: one per session).
  const WAIT_S = 55;
  const SUPERSEDED_MS = 5 * 60 * 1000;
  // An answer back faster than this with nothing in it (a hub or mock that
  // does not hold) is not asked again at once.
  const QUICK_MS = 1000;
  const PAUSE_MS = 30 * 1000;

  // available: null until read, false when the hub has no notifications.
  const state = { available: null, counts: null, byProject: {}, settings: null };

  // The page's address for an item, from its target. Account records lead
  // to the account: a sign-in to its sessions, the settings to the
  // notification settings; a personal request of a project one is no
  // member of, to everything waiting, until the page has the personal
  // inbox (§18.2 names /requests/<id>). A security item of another target
  // goes to the sessions too, where it is confirmed.
  // Of the kinds since 2026-10-26 (§18.1): an older hub's other items are no notification here.
  const known = (x) => Object.prototype.hasOwnProperty.call(KIND_WORDS, x.kind);
  // Read only on purpose: a sign-in alert by This was me (§2.6.5), and an
  // item that asks for an action (a registration to decide, an address to
  // set again) closes with the matter, not by opening it (§18.1).
  const keepsUnread = (x) => x.kind === "security" || ["registration", "settings"].includes((x.target || {}).type);

  function linkOf(item) {
    const t0 = item.target || {};
    if (t0.type === "session" || item.kind === "security") return "/account/sessions";
    if (t0.type === "settings") return "/account/notifications";
    // A registration waiting for the instance admin (§16.4): Admin.
    if (t0.type === "registration") return "/admin";
    const full = item.project && item.project.full_name;
    if (!full || item.project.member === false) return "/all";
    const base = "/" + M.api.projectPath(full) + "/";
    const t = item.target || {};
    if (t.type === "conversation") return base + "chat/" + encodeURIComponent(t.id);
    if (t.type === "task") return base + "tasks/" + encodeURIComponent(t.id);
    if (t.type === "request") return base + "inbox/" + encodeURIComponent(t.id);
    return base + "inbox";
  }

  // The counts, per project too (by_project, computed by the hub over
  // every unread item, §18.2), and the head for the long-poll; no items.
  // A hub without them (404 or 405) is asked once: the counts' timer then
  // stops knocking for the rest of the page's life.
  async function read() {
    if (M.api.absent.has("GET", "/me/notifications")) { state.available = false; return state; }
    try {
      const answer = await M.api.get("/me/notifications?limit=0");
      state.available = true;
      state.counts = answer.counts;
      state.byProject = answer.by_project || {};
    } catch (err) {
      if (!M.api.notOnHub(err)) throw err;
      if (await M.api.missingRoute(err, "GET", "/me/notifications")) M.api.absent.note("GET", "/me/notifications");
      state.available = false;
    }
    changed();
    return state;
  }

  // What asks for the human in one project of theirs, as the hub counts it.
  function projectCount(p) {
    const c = state.byProject[p.full_name];
    if (!c || c.member === false) return { requests: p.open_requests || 0, chat: 0, mention: 0, total: p.open_requests || 0 };
    return { requests: c.inbox || 0, chat: c.chat || 0, mention: c.mention || 0, total: c.total || 0 };
  }

  // The tab title: "(6) " before it while anything asks for the human.
  function title(base) {
    const n = state.available && state.counts ? state.counts.total : 0;
    return (n ? "(" + n + ") " : "") + base;
  }

  // The Chat button: every chat across the projects (/chats), with the
  // unread chat messages the hub counts (counts.chat, §18.2) on it.
  function chatButton(ctx) {
    const n = state.available && state.counts ? state.counts.chat || 0 : 0;
    const label = n ? n + (n === 1 ? " unread chat message" : " unread chat messages") : "Chats";
    return h("a", { class: "bell chat-button", href: "/chats", "aria-label": label, title: label, "aria-current": ctx && ctx.scope === "chats" ? "page" : null },
      M.icons.chat(18), n ? h("span", { class: "count", "aria-hidden": "true" }, String(n)) : null);
  }

  // The bell: the unread count on it, the latest items under it, each a
  // link to where it happened, unread ones marked, and Mark all read.
  function bell(ctx, onChange) {
    // A hub without notifications: the bell still stands, a link to
    // everything waiting, without a count; in the same box as the full
    // bell, so that a refresh replaces it in place.
    if (!state.available) {
      return h("div", { class: "bell-box" },
        h("a", { class: "bell", href: "/all", "aria-label": "Notifications", title: "Notifications" }, M.icons.bell(18)));
    }
    // What is unread on the bell: every kind but the open requests, which
    // the inbox and the switcher show. Sign-in and address alerts count,
    // but "mark all read" never reaches them (§18.3).
    const counts = state.counts || {};
    const unread = Object.keys(KIND_WORDS).filter((k) => k !== "inbox").reduce((n, k) => n + (counts[k] || 0), 0);
    const markable = unread - (counts.security || 0);
    const box = h("div", { class: "bell-box" });
    const list = h("div", { class: "bell-panel", id: "bell-panel", role: "region", "aria-label": "Notifications" });
    list.hidden = true;
    const label = unread ? unread + (unread === 1 ? " new notification" : " new notifications") : "Notifications";
    const button = h("button", {
      type: "button", class: "bell", "aria-expanded": "false", "aria-controls": "bell-panel", "aria-label": label, title: label,
    }, M.icons.bell(18), unread ? h("span", { class: "count", "aria-hidden": "true" }, String(unread)) : null);
    const status = M.statusLine();
    const close = (refocus) => {
      list.hidden = true;
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", outside, true);
      if (refocus) button.focus();
    };
    function outside(e) { if (!box.contains(e.target)) close(false); }
    let items = [];
    let top = null;
    function draw() {
      append(clear(list),
        h("div", { class: "bell-head" }, h("h2", { class: "panel-title" }, "Notifications"),
          top !== null && markable ? h("button", {
            type: "button", class: "small",
            onclick: async () => {
              status.busy("Marking…");
              try {
                await M.api.post("/me/notifications/read", { up_to: top });
              } catch (err) {
                status.fail("Not marked: ", err);
                return;
              }
              // The bell is drawn again with the new counts; the focus goes to it.
              close(false);
              await onChange();
              const again = document.getElementById("header").querySelector("button.bell");
              if (again) again.focus();
            },
          }, "Mark all read") : null),
        h("p", { class: "muted bell-counts" }, Object.keys(KIND_WORDS).filter((k) => counts[k]).map((k) => KIND_WORDS[k] + " " + counts[k]).join(" · ") || "Nothing new."),
        counts.security ? h("p", { class: "hint" }, "A sign-in or address alert stays unread: opening it here does not confirm it, and Mark all read leaves it. Confirm it with This was me under Sessions in your account.") : null,
        items.length
          ? h("ul", { class: "bell-items" }, items.map((x) => h("li", { class: x.read ? "read" : "unread" },
            h("a", {
              href: linkOf(x),
              onclick: () => {
                close(false);
                // A sign-in or address alert is confirmed only explicitly (§2.6.5,
                // §18.3): opening it to look must not give that session good standing.
                if (!x.read && !keepsUnread(x)) M.api.post("/me/notifications/read", { ids: [x.id] }).then(onChange, () => {});
              },
            }, x.redacted ? "Removed" : x.title),
            h("span", { class: "muted" }, " · " + (x.project ? x.project.name + " · " : "") + formatAgo(x.at)),
            x.read ? null : h("span", { class: "visually-hidden" }, " (unread)"))))
          : h("p", { class: "muted" }, "No notifications in the last 30 days."),
        h("p", { class: "hint" }, h("a", { href: "/notifications", onclick: () => close(false) }, "All notifications"), " · ",
          h("a", { href: "/account/notifications", onclick: () => close(false) }, "Notification settings")),
        status.el);
    }
    // The latest 20 are read when the bell opens; "mark all read" marks up to
    // that answer's position.
    button.addEventListener("click", async () => {
      if (!list.hidden) { close(true); return; }
      try {
        const answer = await M.api.get("/me/notifications?limit=20");
        items = (answer.items || []).filter(known);
        top = answer.next_after || null;
      } catch (err) {
        items = [];
        top = null;
        status.fail("Could not read your notifications: ", err);
      }
      draw();
      list.hidden = false;
      button.setAttribute("aria-expanded", "true");
      document.addEventListener("click", outside, true);
    });
    // Escape closes it wherever the focus is: on the bell or in the panel.
    const onEscape = (e) => { if (e.key === "Escape" && !list.hidden) { e.preventDefault(); close(true); } };
    button.addEventListener("keydown", onEscape);
    list.addEventListener("keydown", onEscape);
    append(box, button, list);
    return box;
  }

  // ---- browser notifications (§18.8 stage 2) ---------------------------

  let browserLoop = null;
  let browserConfig = null;
  // Held while the page ends its own session on purpose (a password
  // change, signing out): no request of the stream goes out, the held one
  // is cancelled, and a 401 that still comes back is that end, not a fault.
  let halted = false;
  // A resume() while the cancelled loop has not ended yet: that loop starts
  // the next one when it ends. A 401 the hub sends on its own sets nothing.
  let restartWanted = false;
  const watchers = new Set();
  const shown = new Set();
  const changed = () => watchers.forEach((fn) => fn());
  const wanted = () => browserConfig || watchers.size;

  // The waiting view and browser pop-ups share one request, even while a
  // navigation or a settings change happens during an outstanding long-poll.
  function ensureLoop() {
    if (halted || browserLoop || !wanted() || state.available === false) return;
    const loop = { timer: null, wake: null, reset: false, abort: null };
    browserLoop = loop;
    let after = null;
    const pause = (ms) => new Promise((done) => {
      loop.wake = done;
      loop.timer = window.setTimeout(() => { loop.wake = null; done(); }, ms);
    });
    (async () => {
      while (!halted && wanted() && state.available !== false) {
        // A resume() that came while this loop was only pausing: it serves it.
        restartWanted = false;
        const asked = Date.now();
        let answer;
        try {
          if (loop.reset) { after = null; loop.reset = false; }
          if (after === null) {
            const head = await M.api.get("/me/notifications?limit=0");
            after = head.next_after;
            state.counts = head.counts || state.counts;
            state.byProject = head.by_project || state.byProject;
          }
          if (!wanted() || halted) break;
          const cancel = typeof AbortController === "function" ? new AbortController() : null;
          loop.abort = cancel ? () => cancel.abort() : null;
          answer = await M.api.get("/me/notifications?after=" + encodeURIComponent(after) + "&wait=" + WAIT_S + "&limit=50",
            cancel ? { signal: cancel.signal } : undefined);
          loop.abort = null;
        } catch (err) {
          loop.abort = null;
          // Cancelled on purpose, or the session this page ended itself: the stream stops.
          if (halted || err.code === "aborted") break;
          // The session is gone (signed out elsewhere, revoked): the next render
          // shows sign-in; knocking on would only collect more 401s.
          if (err.status === 401) break;
          if (await M.api.missingRoute(err, "GET", "/me/notifications")) {
            M.api.absent.note("GET", "/me/notifications");
            state.available = false;
            changed();
            break;
          }
          if (err.code === "invalid" && err.details && err.details.fields && err.details.fields.after === "position") {
            after = null;
            changed();
          }
          if (wanted()) await pause(PAUSE_MS);
          continue;
        }
        if (!wanted()) break;
        if (loop.reset) continue; // A settings/session change discarded this answer.
        if (answer.superseded) { await pause(SUPERSEDED_MS); after = null; continue; }
        const items = answer.items || [];
        if (answer.next_after) after = answer.next_after;
        state.counts = answer.counts || state.counts;
        state.byProject = answer.by_project || state.byProject;
        // Refresh the snapshot, including removals/read flags; never insert a
        // long-poll item into a request form or assume its count is complete.
        changed();
        const config = browserConfig;
        if (config && !loop.reset) items.forEach((x) => {
          const b = config.settings.browser;
          if (x.read || shown.has(x.id) || !known(x) || !b.kinds[x.kind]) return;
          if (x.actor && x.actor.member_id === config.ctx.me.id) return;
          shown.add(x.id);
          const withText = b.content && b.content[x.kind] && typeof x.content === "string";
          const note = new window.Notification(x.redacted ? "Maity" : x.title, {
            tag: x.id,
            body: (x.project ? x.project.name : "") + (withText ? "\n" + x.content.slice(0, 120) : ""),
          });
          note.onclick = () => { window.focus(); M.route.go(linkOf(x)); note.close(); };
        });
        if (!items.length && Date.now() - asked < QUICK_MS && wanted()) await pause(PAUSE_MS);
      }
    })().finally(() => {
      if (browserLoop === loop) browserLoop = null;
      if (restartWanted && !halted) { restartWanted = false; ensureLoop(); }
    });
  }

  function wakeLoop() {
    if (!browserLoop || !browserLoop.wake) return;
    window.clearTimeout(browserLoop.timer);
    const wake = browserLoop.wake;
    browserLoop.wake = null;
    wake();
  }

  function startBrowser(ctx, settings) {
    const b = settings && settings.browser;
    browserConfig = b && b.enabled && ("Notification" in window) && window.Notification.permission === "granted"
      ? { ctx, settings } : null;
    if (browserLoop) browserLoop.reset = true;
    wakeLoop();
    ensureLoop();
  }

  // Before the page ends its session on purpose; resume() after, when it
  // still has one (a password change keeps this session, js/account.js).
  function halt() {
    halted = true;
    restartWanted = false;
    const loop = browserLoop;
    if (loop) {
      loop.reset = true;
      if (loop.abort) loop.abort();
    }
    wakeLoop();
  }
  function resume() {
    halted = false;
    if (browserLoop) restartWanted = true;
    else ensureLoop();
  }

  function stopBrowser() {
    browserConfig = null;
    wakeLoop();
  }

  function subscribe(fn) {
    if (!wanted() && browserLoop) browserLoop.reset = true;
    watchers.add(fn);
    wakeLoop();
    ensureLoop();
    return () => { watchers.delete(fn); wakeLoop(); };
  }

  M.notify = { known, keepsUnread, state, read, projectCount, title, bell, chatButton, linkOf, startBrowser, stopBrowser, halt, resume, running: () => !!browserConfig && !!browserLoop, subscribe, changed, KIND_WORDS };
})(window.Maity);
