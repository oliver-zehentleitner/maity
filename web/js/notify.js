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
    inbox: "Requests", chat: "Chats", mention: "Mentions", card: "Your cards", agent: "Agents stopped",
    ticker: "Changes", jour_fixe: "Jour fixe", security: "Sign-ins and address", system: "Mail delivery",
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
  // inbox (§18.2 names #/requests/<id>). A security item of another target
  // goes to the sessions too, where it is confirmed.
  function linkOf(item) {
    const t0 = item.target || {};
    if (t0.type === "session" || item.kind === "security") return "#/account/sessions";
    if (t0.type === "settings") return "#/account/notifications";
    const slug = item.project && item.project.slug;
    if (!slug || item.project.member === false) return "#/all";
    const base = "#/p/" + encodeURIComponent(slug) + "/";
    const t = item.target || {};
    if (t.type === "conversation") return base + "chat/" + encodeURIComponent(t.id);
    if (t.type === "task") return base + "board";
    if (t.type === "placement") return base + "agents";
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
      M.api.absent.note("GET", "/me/notifications");
      state.available = false;
    }
    return state;
  }

  // What asks for the human in one project of theirs, as the hub counts it.
  function projectCount(p) {
    const c = state.byProject[p.slug];
    if (!c || c.member === false) return { requests: p.open_requests || 0, chat: 0, mention: 0, total: p.open_requests || 0 };
    return { requests: c.inbox || 0, chat: c.chat || 0, mention: c.mention || 0, total: c.total || 0 };
  }

  // The tab title: "(6) " before it while anything asks for the human.
  function title(base) {
    const n = state.available && state.counts ? state.counts.total : 0;
    return (n ? "(" + n + ") " : "") + base;
  }

  // The bell: the unread count on it, the latest items under it, each a
  // link to where it happened, unread ones marked, and Mark all read.
  function bell(ctx, onChange) {
    if (!state.available) return null;
    // What is unread on the bell: every kind but the open requests, which
    // the inbox and the switcher show. Sign-in and address alerts count,
    // but "mark all read" never reaches them (§18.3).
    const counts = state.counts || {};
    const unread = Object.keys(KIND_WORDS).filter((k) => k !== "inbox").reduce((n, k) => n + (counts[k] || 0), 0);
    const markable = unread - (counts.security || 0);
    const box = h("div", { class: "bell-box" });
    const list = h("div", { class: "bell-panel", id: "bell-panel", role: "region", "aria-label": "Notifications" });
    list.hidden = true;
    const label = "Notifications" + (unread ? ", " + unread + " unread" : "");
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
                if (!x.read && x.kind !== "security") M.api.post("/me/notifications/read", { ids: [x.id] }).then(onChange, () => {});
              },
            }, x.redacted ? "Removed" : x.title),
            h("span", { class: "muted" }, " · " + (x.project ? x.project.name + " · " : "") + formatAgo(x.at)),
            x.read ? null : h("span", { class: "visually-hidden" }, " (unread)"))))
          : h("p", { class: "muted" }, "No notifications in the last 30 days."),
        h("p", { class: "hint" }, h("a", { href: "#/account/notifications", onclick: () => close(false) }, "Notification settings")),
        status.el);
    }
    // The latest 20 are read when the bell opens; "mark all read" marks up to
    // that answer's position.
    button.addEventListener("click", async () => {
      if (!list.hidden) { close(true); return; }
      try {
        const answer = await M.api.get("/me/notifications?limit=20");
        items = answer.items || [];
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
  const shown = new Set();

  // Shows what is new while a tab is open, for the kinds switched on; the
  // item's id is the tag, so two tabs show it once. Never one's own.
  function startBrowser(ctx, settings) {
    stopBrowser();
    const b = settings && settings.browser;
    if (!b || !b.enabled || !("Notification" in window) || window.Notification.permission !== "granted") return;
    if (M.api.absent.has("GET", "/me/notifications")) return;
    // A pause ends early when the loop is stopped, so nothing is left waiting.
    const loop = { stopped: false, timer: null, wake: null };
    browserLoop = loop;
    // From now: a fresh head on every start and after another tab had the
    // long-poll, so nothing since the page loaded pops up at once.
    let after = null;
    const pause = (ms) => new Promise((done) => {
      loop.wake = done;
      loop.timer = window.setTimeout(done, ms);
    });
    (async () => {
      while (!loop.stopped) {
        const asked = Date.now();
        let answer;
        try {
          if (after === null) after = (await M.api.get("/me/notifications?limit=0")).next_after;
          answer = await M.api.get("/me/notifications?after=" + encodeURIComponent(after) + "&wait=" + WAIT_S + "&limit=50");
        } catch (err) {
          // Not on this hub: the loop ends instead of retrying for ever.
          if (M.api.notOnHub(err)) { M.api.absent.note("GET", "/me/notifications"); return; }
          await pause(PAUSE_MS);
          continue;
        }
        if (loop.stopped) return;
        if (answer.superseded) { await pause(SUPERSEDED_MS); after = null; continue; }
        const items = answer.items || [];
        // The hub's next position, passed back unchanged (§18.2).
        if (answer.next_after) after = answer.next_after;
        items.forEach((x) => {
          if (x.read || shown.has(x.id) || !b.kinds[x.kind]) return;
          if (x.actor && x.actor.member_id === ctx.me.id) return;
          shown.add(x.id);
          const withText = b.content && b.content[x.kind] && typeof x.content === "string";
          const note = new window.Notification(x.redacted ? "Maity" : x.title, {
            tag: x.id,
            body: (x.project ? x.project.name : "") + (withText ? "\n" + x.content.slice(0, 120) : ""),
          });
          note.onclick = () => { window.focus(); window.location.hash = linkOf(x); note.close(); };
        });
        if (!items.length && Date.now() - asked < QUICK_MS) await pause(PAUSE_MS);
      }
    })();
  }

  function stopBrowser() {
    const loop = browserLoop;
    browserLoop = null;
    if (!loop) return;
    loop.stopped = true;
    window.clearTimeout(loop.timer);
    if (loop.wake) loop.wake();
  }

  M.notify = { state, read, projectCount, title, bell, linkOf, startBrowser, stopBrowser, running: () => !!browserLoop, KIND_WORDS };
})(window.Maity);
