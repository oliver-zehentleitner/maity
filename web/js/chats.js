// Every chat across one's projects (/chats, the header's Chat button),
// laid out as a project's Chat tab (js/chat.js): the list beside the open
// conversation, on a phone the list its own screen. The list merges each
// project's direct and group chats (docs/api.md §9.3, GET /me/conversations),
// in the hub's order (four bands: pinned with unread, quietly pinned,
// unpinned with unread, the rest), each with its project; a human pins one here too. A conversation opens
// in place (/chats/<owner>/<slug>/<id>) with chat.js's own pane, in its project's
// context. Going from one chat to another changes the pane alone: the page, the
// list and every project's context stay, and the pane being left stands dimmed until
// the next is drawn.
//
// Live updates hold no events feed of any project: the notifications stream
// (js/notify.js), which the page reads anyway, tells that something changed;
// the list is read again once a burst settles, and the open conversation
// fetches what came after it. Besides, the list is read every 30 seconds as
// a project's is.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const SETTLE_MS = 400;
  // No project feed here: the notification counts say a chat changed. They
  // are read this often while the view is shown, as the /me round did before
  // it went to 60 seconds (context/refresh.md).
  const NOTICE_MS = 15000;
  const chatLink = (full, id) => "/chats" + (id ? "/" + M.api.projectPath(full) + "/" + encodeURIComponent(id) : "");

  // The hub's order across projects (`rank`, its position in GET
  // /me/conversations), never re-sorted; agents without a conversation after it, by title.
  function ordered(all) {
    const ranked = (x) => typeof x.chat.rank === "number";
    return all.slice().sort((a, b) => (ranked(a) && ranked(b) ? a.chat.rank - b.chat.rank
      : ranked(a) ? -1 : ranked(b) ? 1 : a.chat.title.localeCompare(b.chat.title)));
  }

  // The merged list. pctxs: full name -> the project's context; opened: what
  // gives the open conversation's {slug: its project's full name, id}, or null. Shaped as chat.js's own list.
  function globalList(ctx, pctxs, opened) {
    const P = M.chatParts;
    const ul = h("ul", { class: "chat-list" });
    const status = M.statusLine();
    const failed = h("div");
    const none = h("p", { class: "muted" }, M.t("chats.none"));
    none.hidden = true;
    // slug -> { chats, groups } as last read.
    const read = {};
    const draw = () => {
      const open = opened();
      const currentKey = open ? open.slug + "/" + open.id : null;
      // A redraw keeps the keyboard on the same chat's link.
      const focused = document.activeElement && ul.contains && ul.contains(document.activeElement)
        ? document.activeElement.getAttribute("href") : null;
      const fresh = h("div");
      const all = [];
      Object.keys(read).forEach((slug) => read[slug].chats.forEach((chat) => all.push({ slug, chat, key: slug + "/" + chat.id })));
      ordered(all).forEach((x) => {
        const pctx = pctxs[x.slug];
        const onPin = pctx.me.kind === "human" && P.pinColumn.isShown() ? (chat) => P.togglePin(pctx, chat, status, () => refresh()) : null;
        const li = P.listItem(pctx, x.chat, x.key === currentKey ? x.chat.id : null, onPin);
        const a = li.querySelector("a.conv");
        if (a) a.className += " with-project";
        // Its project as a 14 px mark after the who line, as a message's
        // meta has it (the designer's pass on #429), the name on hover and
        // read out at the row's end.
        const name = pctx.project.name || x.slug;
        const who = a && a.querySelector(".conv-sub");
        if (who) append(who, h("span", { class: "conv-project", title: name }, M.projectMark(x.slug, name, (pctx.projectViews || {})[x.slug], "small")));
        if (a) append(a, h("span", { class: "visually-hidden" }, ", ", M.t("chats.in_project", { project: name })));
        append(fresh, li);
      });
      M.dom.keepImages(ul, fresh);
      append(clear(ul), Array.from(fresh.childNodes));
      none.hidden = all.length > 0 || Object.keys(read).length === 0;
      if (focused) {
        const again = Array.from(ul.querySelectorAll("a.conv")).find((a) => a.getAttribute("href") === focused);
        if (again) again.focus();
      }
    };
    // A project's items as the list shows them, with one's own agents
    // that have no conversation yet.
    function take(slug, items) {
      const pctx = pctxs[slug];
      const byAgent = {};
      const groups = [];
      items.forEach((c) => { if (c.kind === "direct") byAgent[c.agent_id || c.id] = c; else groups.push(c); });
      const mine = pctx.members.filter((m) => m.kind === "agent" && m.owner_id === pctx.me.id);
      read[slug] = { chats: P.chatsOf(pctx, mine, byAgent, groups), groups, items };
    }
    // One read across projects (docs/api.md §9.3, GET /me/conversations).
    async function readOnce() {
      let list;
      try {
        list = await M.api.getAll("/me/conversations?observed=true");
      } catch (err) {
        append(clear(failed), h("p", { class: "send-status failed" }, M.t("chats.read_failed", { reason: err.message })));
        return;
      }
      const bySlug = {};
      list.items.forEach((c, i) => { c.rank = i; const slug = c.project && c.project.full_name; (bySlug[slug] = bySlug[slug] || []).push(c); });
      Object.keys(pctxs).forEach((slug) => take(slug, bySlug[slug] || []));
      clear(failed);
    }
    async function readAll() {
      await readOnce();
      draw();
      status.done();
    }
    // One read of every project at a time; one asked for meanwhile runs once after it.
    let reading = null;
    let again = false;
    const refresh = () => {
      if (reading) { again = true; return reading; }
      reading = readAll().then(() => {
        reading = null;
        if (!again) return null;
        again = false;
        return refresh();
      });
      return reading;
    };
    const el = h("nav", { class: "chat-list-pane", "aria-label": M.t("chats.conversations") },
      // After the Lead's slot, so that on a phone the heading keeps its row and the Lead its place
      // under it at the left edge; only a human pins (§9.3, tsk-4nf344w4c52c).
      h("div", { class: "toolbar" }, h("h2", null, M.t("chats.title")), h("span", { class: "chats-lead" }),
        ctx.me.kind === "human" ? P.pinColumn.toggle(ctx, () => draw()) : null),
      h("p", { class: "muted" }, M.t("chats.hint")),
      none, failed, ul, status.el);
    const shown = (open) => (open && read[open.slug]) || { chats: [], groups: [], items: [] };
    return { el, refresh, draw, groups: () => shown(opened()).groups, conversations: () => shown(opened()).items,
      knows: (x) => shown(x).chats.some((c) => c.id === x.id) };
  }

  M.views.chats = async function (ctx, root, args) {
    const chatAt = ([owner, name, id] = []) => (owner && name && id ? { slug: owner + "/" + name, id } : null);
    let open = chatAt(args);
    // Each project's context, read once when the view opens; one that fails is said, the rest shown.
    const pctxs = {};
    const unreadable = [];
    await Promise.all(ctx.projects.map((p) => M.projectContext(ctx, p.full_name, chatLink)
      .then((pctx) => { pctxs[p.full_name] = pctx; }, (err) => { unreadable.push(h("p", { class: "send-status failed" }, M.t("chats.project_failed", { project: p.name, reason: err.message }))); })));
    append(root, unreadable);
    // The projects an agent is in, as far as the reader may see: those of
    // the reader's whose member list names it (tsk-p94e7njrmg1p), in the
    // switcher's order. Never a project the reader is not in.
    const projectsOf = (memberId) => ctx.projects
      .filter((p) => pctxs[p.full_name] && pctxs[p.full_name].memberById && pctxs[p.full_name].memberById[memberId])
      .map((p) => ({ slug: p.full_name, name: p.name || p.full_name, view: (ctx.projectViews || {})[p.full_name] }));
    Object.values(pctxs).forEach((x) => { x.projectsOf = projectsOf; });
    const list = globalList(ctx, pctxs, () => open);
    // The pane on screen: its project's context with timers and listeners of its own.
    let pane = null;
    let paneSeq = 0;

    // The stream says something changed: the list once it settles, and the
    // open conversation what came after it, as its project's feed would.
    // One update at a time: the pane's reads, the lists and (every 30
    // seconds) the members; whatever is asked for meanwhile is one pass
    // after it, never a second one alongside.
    let running = null;
    let next = null;
    let disposed = false;
    async function update(withMembers) {
      if (withMembers) {
        // Names, presence, a newly joined agent of one's own; the open pane
        // keeps its draft and focus, and draws with them from then on.
        await Promise.all(Object.values(pctxs).map((x) => M.api.getAll(x.base + "/members")
          .then((r) => { M.withMembers(x, r.items); }, () => null)));
      }
      if (pane) {
        const changed = [{ kind: "message", seq: Number.MAX_SAFE_INTEGER, actor: { member_id: open.id }, payload: { type: "chat", conversation_id: open.id } },
          { kind: M.chatParts.RESYNC }];
        await Promise.all(pane.ctx.listeners.map((fn) => Promise.resolve(fn(changed)).catch(() => null)));
      }
      await list.refresh();
    }
    function run(withMembers) {
      if (disposed) return null;
      if (running) { next = { withMembers: (next && next.withMembers) || withMembers }; return running; }
      running = update(withMembers).finally(() => {
        running = null;
        if (!next || disposed) return;
        const again = next;
        next = null;
        run(again.withMembers);
      });
      return running;
    }
    let settle = null;
    // Only a stream answer with a chat or mention in it, or one that moved the chat counts (§18.2
    // counts.chat, by_project's chat). Each answer, and each counts read every NOTICE_MS, used to read
    // every project's chats and the open conversation again, whatever it was about (tsk-d61rvjm6gteh):
    // an inbox item, a sign-in, a long-poll that only timed out. The rest waits for the round.
    const chatCounts = () => {
      const st = M.notify.state;
      const per = Object.keys(st.byProject || {}).sort().map((k) => [k, (st.byProject[k] || {}).chat || 0]);
      return JSON.stringify([st.counts ? st.counts.chat || 0 : 0, per]);
    };
    let seenCounts = chatCounts();
    const CHATTY = new Set(["chat", "mention"]);
    // A group chat read along as an agent's owner brings no chat item and no count (§9.3, `unread`
    // null for an observer): while one is open, the counts read every NOTICE_MS still nudges, as it did
    // before the counts decided (web roll-up 3, gb8w's post-merge P3 on #1527).
    const readAlong = () => !!open && list.groups().some((g) => g.id === open.id && g.access === "observer");
    const nudge = (items) => {
      const now = chatCounts();
      const countsRead = items === undefined;
      if (now === seenCounts && !(countsRead && readAlong()) && !(items || []).some((x) => x && CHATTY.has(x.kind))) return;
      seenCounts = now;
      window.clearTimeout(settle);
      settle = window.setTimeout(() => run(false), SETTLE_MS);
    };
    const unsubscribe = M.notify.subscribe(nudge);
    ctx.onDispose(() => { disposed = true; window.clearTimeout(settle); unsubscribe(); paneSeq++; if (pane) pane.close(); });
    // Every project's chats each round: none while the tab is hidden.
    ctx.every(M.chatParts.LIST_MS, () => (document.visibilityState === "hidden" ? null : run(true)));
    ctx.every(NOTICE_MS, () => (document.visibilityState === "hidden" ? null : M.notify.read().catch(() => null)));

    const layout = h("div", { class: "chat-layout" }, list.el);
    append(root, layout);
    if (M.leadOnChats) M.leadOnChats(layout.querySelector(".chats-lead"));  // a phone's way to the Lead (js/app.js)
    // What stands beside the list: the view's parts go in together, once they are ready.
    const place = (parts) => {
      layout.className = "chat-layout" + (open ? " open" : "");
      Array.from(layout.childNodes).filter((c) => c !== list.el).forEach((c) => layout.removeChild(c));
      append(layout, parts);
    };
    let fitted = false;
    // Draws what the address names; a newer one takes over from one still reading.
    async function showPane() {
      const seq = ++paneSeq;
      const stale = () => seq !== paneSeq || disposed;
      list.draw();
      if (pane) pane.close();
      pane = null;
      Array.from(layout.childNodes).filter((c) => c !== list.el).forEach((c) => { c.setAttribute("inert", ""); c.setAttribute("aria-busy", "true"); });
      const pctx = open ? pctxs[open.slug] : null;
      if (!pctx) {
        place(open ? h("p", { class: "error", role: "alert" }, M.t("chats.no_project", { project: open.slug }))
          : h("p", { class: "chat-none muted" }, M.t("chats.pick")));
        return false;
      }
      const timers = [];
      const sub = Object.create(pctx);
      sub.listeners = [];
      sub.onEvents = (fn) => { sub.listeners.push(fn); };
      sub.every = (ms, fn) => { if (!stale()) timers.push(window.setInterval(fn, ms)); };
      sub.stale = stale;
      pane = { ctx: sub, close: () => timers.forEach((t) => window.clearInterval(t)) };
      // The list is read after the pane is drawn, not on its way: nothing waits for it.
      let drawn = false;
      const paneList = Object.assign({}, list, { refresh: (...a) => (drawn ? list.refresh(...a) : Promise.resolve()) });
      const holder = h("div");
      try {
        await M.views.chat(sub, root, [open.id], { list: paneList, holder, stale });
      } catch (err) {
        if (stale()) return false;
        throw err;
      }
      if (stale()) return false;
      place(Array.from(holder.childNodes));
      drawn = true;
      if (!fitted) { fitted = true; M.chatParts.fitToScreen(layout); }
      list.refresh();
      return true;
    }
    await list.refresh();
    await showPane();
    // Within this view the address changes the pane alone. A project or chat that is
    // not on this page (a group made or an agent joined since the last read, reached by its
    // address), or a failed read, draws the page anew, which reads them or says what is wrong;
    // what a chat already left answers changes nothing, nor does a session that ended,
    // whose own page is up by then.
    ctx.followRoute((where) => {
      if (where.scope !== "chats") return false;
      const next = chatAt(where.args);
      if (next && !list.knows(next)) return false;
      open = next;
      showPane().then((drawn) => (drawn ? M.notify.read() : null)).catch(() => { if (!disposed) ctx.refresh(); });
      return true;
    });
  };

  M.chats = { chatLink };
})(window.Maity);
