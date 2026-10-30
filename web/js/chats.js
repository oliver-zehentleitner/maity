// Every chat across one's projects (/chats, the header's Chat button),
// laid out as a project's Chat tab (js/chat.js): the list beside the open
// conversation, on a phone the list its own screen. The list merges each
// project's direct and group chats (docs/api.md §9.3, one read per project),
// unread first, then the newest, each with its project. A conversation opens
// in place (/chats/<owner>/<slug>/<id>) with chat.js's own pane, in its project's
// context.
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

  // Unread first, then the newest, then by title; the open one counts as read.
  function ordered(all, currentKey) {
    const at = (x) => x.chat.last_message_at || "";
    const unread = (x) => (x.key !== currentKey && (x.chat.unread || x.chat.mentions) ? 1 : 0);
    return all.slice().sort((a, b) => unread(b) - unread(a)
      || (at(b) > at(a) ? 1 : at(b) < at(a) ? -1 : a.chat.title.localeCompare(b.chat.title)));
  }

  // The merged list. pctxs: full name -> the project's context; open: the
  // open conversation's {slug: its project's full name, id}, or null. Shaped as chat.js's own list.
  function globalList(pctxs, open) {
    const P = M.chatParts;
    const ul = h("ul", { class: "chat-list" });
    const status = M.statusLine();
    const failed = h("div");
    const none = h("p", { class: "muted" }, "You own no agents in your projects, and are in no group chat.");
    none.hidden = true;
    // slug -> { chats, groups } as last read.
    const read = {};
    const currentKey = open ? open.slug + "/" + open.id : null;
    const draw = () => {
      // A redraw keeps the keyboard on the same chat's link.
      const focused = document.activeElement && ul.contains && ul.contains(document.activeElement)
        ? document.activeElement.getAttribute("href") : null;
      clear(ul);
      const all = [];
      Object.keys(read).forEach((slug) => read[slug].chats.forEach((chat) => all.push({ slug, chat, key: slug + "/" + chat.id })));
      ordered(all, currentKey).forEach((x) => {
        const pctx = pctxs[x.slug];
        const li = P.listItem(pctx, x.chat, x.key === currentKey ? x.chat.id : null);
        const a = li.querySelector("a.conv");
        if (a) a.className += " with-project";
        // Its project as a 14 px mark after the who line, as a message's
        // meta has it (the designer's pass on #429), the name on hover and
        // read out at the row's end.
        const name = pctx.project.name || x.slug;
        const who = a && a.querySelector(".conv-sub");
        if (who) append(who, h("span", { class: "conv-project", title: name }, M.projectMark(x.slug, name, (pctx.projectViews || {})[x.slug], "small")));
        if (a) append(a, h("span", { class: "visually-hidden" }, ", in " + name));
        append(ul, li);
      });
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
      read[slug] = { chats: P.chatsOf(pctx, mine, byAgent, groups), groups };
    }
    // One read across projects (docs/api.md §9.3, GET /me/conversations).
    async function readOnce() {
      let list;
      try {
        list = await M.api.getAll("/me/conversations?observed=true");
      } catch (err) {
        append(clear(failed), h("p", { class: "send-status failed" }, "Your chats could not be read: " + err.message));
        return;
      }
      const bySlug = {};
      list.items.forEach((c) => { const slug = c.project && c.project.full_name; (bySlug[slug] = bySlug[slug] || []).push(c); });
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
    const el = h("nav", { class: "chat-list-pane", "aria-label": "Conversations" },
      h("div", { class: "toolbar" }, h("h2", null, "Chats")),
      h("p", { class: "muted" }, "Your chats in every project, unread first."),
      none, failed, ul, status.el);
    return { el, refresh, groups: () => (open && read[open.slug] ? read[open.slug].groups : []) };
  }

  M.views.chats = async function (ctx, root, args) {
    const [owner, name, id] = args || [];
    const open = owner && name && id ? { slug: owner + "/" + name, id } : null;
    // Each project's context, read once when the view opens; one that fails is said, the rest shown.
    const pctxs = {};
    const unreadable = [];
    await Promise.all(ctx.projects.map((p) => M.projectContext(ctx, p.full_name, chatLink)
      .then((pctx) => { pctxs[p.full_name] = pctx; }, (err) => { unreadable.push(h("p", { class: "send-status failed" }, "Could not read " + p.name + ": " + err.message)); })));
    append(root, unreadable);
    // The projects an agent is in, as far as the reader may see: those of
    // the reader's whose member list names it (tsk-p94e7njrmg1p), in the
    // switcher's order. Never a project the reader is not in.
    const projectsOf = (memberId) => ctx.projects
      .filter((p) => pctxs[p.full_name] && pctxs[p.full_name].memberById && pctxs[p.full_name].memberById[memberId])
      .map((p) => ({ slug: p.full_name, name: p.name || p.full_name, view: (ctx.projectViews || {})[p.full_name] }));
    Object.values(pctxs).forEach((x) => { x.projectsOf = projectsOf; });
    const list = globalList(pctxs, open);
    const pctx = open ? pctxs[open.slug] : null;

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
      if (pctx) {
        const changed = [{ kind: "message", seq: Number.MAX_SAFE_INTEGER, actor: { member_id: open.id }, payload: { type: "chat", conversation_id: open.id } },
          { kind: M.chatParts.RESYNC }];
        await Promise.all(pctx.listeners.map((fn) => Promise.resolve(fn(changed)).catch(() => null)));
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
    const nudge = () => { window.clearTimeout(settle); settle = window.setTimeout(() => run(false), SETTLE_MS); };
    const unsubscribe = M.notify.subscribe(nudge);
    ctx.onDispose(() => { disposed = true; window.clearTimeout(settle); unsubscribe(); });
    // Every project's chats each round: none while the tab is hidden.
    ctx.every(M.chatParts.LIST_MS, () => (document.visibilityState === "hidden" ? null : run(true)));
    ctx.every(NOTICE_MS, () => (document.visibilityState === "hidden" ? null : M.notify.read().catch(() => null)));

    if (!open || !pctx) {
      append(root, h("div", { class: "chat-layout" + (open ? " open" : "") }, list.el,
        open ? h("p", { class: "error", role: "alert" }, "No project of yours named " + open.slug + ".")
          : h("p", { class: "chat-none muted" }, "Pick a conversation.")));
      await list.refresh();
      return;
    }
    await list.refresh();
    await M.views.chat(pctx, root, [open.id], { list });
  };

  M.chats = { chatLink };
})(window.Maity);
