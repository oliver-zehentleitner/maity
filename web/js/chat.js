// (5) Chat: direct conversations with the agents the human owns, and
// group chats (docs/api.md §9.2, js/group-chat.js). The conversations are
// listed beside the open one (presence, last message, unread), so
// switching is one click; on a phone the list is its own screen. Messages are events the agent picks up with wait or resume
// (docs/api.md §9); a chat event of a conversation in the project's feed
// fetches its new messages and re-reads the list. No event says that a
// message reached the agent's session, so while one of the human's
// messages is not picked up yet, the next event of that agent, or the
// window getting the focus back, re-reads the messages for their
// delivered_at. The inbox stays the primary surface.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;

  // Presence emits no event (docs/api.md §5.3): the list re-reads it.
  const LIST_MS = 30000;
  // The global chat's "read what is shown again" (js/chats.js), in place of
  // the project feed's events it does not hold.
  const RESYNC = "chat_resync";
  const PRESENCE_LABELS = { online: "online", away: "away", offline: "offline", paused: "paused" };

  // Unsent text per conversation ("<full name>/<agent id>"), kept while the
  // human switches between them in this tab; never stored or sent.
  const drafts = new Map();
  // Signing out ends them; the next human in this tab starts empty.
  M.clearChatDrafts = () => drafts.clear();

  // A chat as the list shows it: one per owned agent (§9.1), and the group
  // chats the hub lists (§9.3); a chat's kind comes from the hub, never from
  // the shape of its id.
  function chatsOf(ctx, mine, byAgent, groups) {
    const direct = mine.map((m) => {
      const c = byAgent[m.id] || {};
      return { id: m.id, kind: "direct", title: m.display_name, participants: [m], unread: c.unread || 0,
        last_message_at: c.last_message_at || null, last_message: c.last_message || null };
    });
    const byId = ctx.memberById || {};
    const member = (p) => byId[p.member_id] || { id: p.member_id, display_name: "@" + p.handle, kind: p.kind };
    return direct.concat(groups.map((g) => {
      const people = g.participants.map(member).filter((x) => x.id !== ctx.me.id);
      return { id: g.id, kind: "group", title: g.title || people.map((x) => x.display_name).join(", ") || "Group chat",
        participants: people, unread: g.unread || 0, mentions: g.mentions_unread || 0, access: g.access, closed: !!g.closed_at,
        last_message_at: g.last_message_at || g.created_at || null, last_message: g.last_message || null };
    }));
  }

  // Unread chats first, then the newest; the ones without messages after,
  // by title. The open chat counts as read, as the list shows it.
  function ordered(chats, currentId) {
    const at = (c) => c.last_message_at || "";
    const unread = (c) => (c.id !== currentId && (c.unread || c.mentions) ? 1 : 0);
    return chats.slice().sort((a, b) => unread(b) - unread(a)
      || (at(b) > at(a) ? 1 : at(b) < at(a) ? -1 : a.title.localeCompare(b.title)));
  }

  // Up to three participants' pictures (js/avatar.js); with one, its
  // presence as a dot.
  function avatars(chat) {
    const shown = chat.participants.slice(0, 3);
    return h("span", { class: "avatars", "aria-hidden": "true" },
      shown.map((m) => M.avatar(m, 32)),
      chat.participants.length === 1 ? h("span", { class: "dot " + chat.participants[0].presence }) : null);
  }

  // Under the title: who it is — for a direct chat the agent's handle and
  // harness, which tell apart names that share their owner's prefix; for a
  // group its people — then an unsent draft, else the last message where
  // the hub sends it (`last_message`), else nothing. Presence is the dot
  // (and its words for a screen reader), not a line of its own. The open
  // chat's own draft is in its composer, not repeated here.
  function sublines(ctx, chat, current) {
    const one = chat.participants.length === 1 ? chat.participants[0] : null;
    const who = chat.kind === "group"
      ? (chat.access === "observer" ? "you read along · " : "") + (chat.closed ? "closed · " : "") + "group · " + chat.participants.map((m) => m.display_name).join(", ")
      : one
      ? [one.kind === "human" ? "human" : "agent", one.handle ? "@" + M.dom.handleOf(ctx, one) : null, one.harness || null].filter(Boolean).join(" · ")
      : chat.participants.map((m) => m.display_name).join(", ");
    const presence = chat.kind !== "group" && one ? PRESENCE_LABELS[one.presence] || one.presence || null : null;
    const draft = current ? null : drafts.get(ctx.slug + "/" + chat.id);
    const last = chat.last_message;
    let line = null;
    if (draft) line = "Draft: " + draft;
    else if (last && last.redacted) line = "A message was removed.";
    else if (last) line = (last.from === ctx.me.id ? "You: " : "") + last.body;
    return { who, presence, line, draft: !!draft };
  }

  function listItem(ctx, chat, currentId) {
    const current = chat.id === currentId;
    // The open chat is read: its unread is gone even before the list says so.
    const unread = current ? 0 : chat.unread;
    const sub = sublines(ctx, chat, current);
    const when = chat.last_message_at ? formatAgo(chat.last_message_at) : "";
    // The row's name is its text, in the order it shows; hidden separators
    // keep the parts apart for a screen reader (no aria-label: it would
    // have to repeat the visible text word for word).
    const apart = (t) => h("span", { class: "visually-hidden" }, t);
    return h("li", null, h("a", {
      href: ctx.link("chat", chat.id),
      class: "conv" + (current ? " current" : "") + (unread ? " unread" : ""),
      "aria-current": current ? "page" : null,
    },
    avatars(chat),
    // The full name, wrapped, never cut; as the tooltip too.
    h("span", { class: "conv-title", title: chat.title }, chat.title),
    sub.presence ? apart(", " + sub.presence) : null,
    when ? [apart(", "), h("span", { class: "conv-time" }, when)] : null,
    // Both counters in one cell, side by side: the unread count, then the @.
    unread || (!current && chat.mentions) ? h("span", { class: "conv-counts" },
      unread ? [apart(", "), h("span", { class: "count" }, String(unread)), apart(" unread")] : null,
      !current && chat.mentions ? [apart(", "), h("span", { class: "count mention-count", title: "mentions you" }, "@"), apart(" mentions you")] : null) : null,
    apart(", "), h("span", { class: "conv-sub" }, sub.who),
    sub.line ? [apart(": "), h("span", { class: "preview" + (sub.draft ? " draft" : "") }, sub.line)] : null));
  }

  // The conversation list; refresh() re-reads it and presence in place.
  function conversations(ctx, currentId, groupsServed) {
    const ul = h("ul", { class: "chat-list" });
    const status = M.statusLine();
    let mine = ctx.members.filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id);
    let byAgent = {};
    let groups = [];
    const none = h("p", { class: "muted" }, groupsServed
      ? "You own no agents in this project, and are in no group chat."
      : "You own no agents in this project.");
    const draw = () => {
      // A redraw keeps the keyboard where it was: on the same chat's link.
      const focused = document.activeElement && ul.contains && ul.contains(document.activeElement)
        ? document.activeElement.getAttribute("href") : null;
      clear(ul);
      ordered(chatsOf(ctx, mine, byAgent, groups), currentId).forEach((chat) => append(ul, listItem(ctx, chat, currentId)));
      none.hidden = mine.length > 0 || groups.length > 0;
      if (focused) {
        const again = Array.from(ul.querySelectorAll("a.conv")).find((a) => a.getAttribute("href") === focused);
        if (again) again.focus();
      }
    };
    // One read at a time; a refresh asked for while one runs (it may
    // predate what the caller just changed) runs once more after it.
    let reading = null;
    let again = null;
    // observed=true: the group chats read along as an agent's owner too (§9.3).
    // An owner outside the project reads no member list (§9.2: not_found).
    const read = (withMembers) => Promise.all([
      M.api.getAll(ctx.base + "/conversations?observed=true"),
      withMembers && !ctx.outsider ? M.api.getAll(ctx.base + "/members") : null,
    ]).then(([list, members]) => {
      byAgent = {};
      groups = [];
      // A hub before group chats lists direct items without a kind.
      list.items.forEach((c) => { if ((c.kind || "direct") === "direct") byAgent[c.agent_id || c.id] = c; else groups.push(c); });
      if (members) mine = members.items.filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id);
      draw();
      status.done();
    }).catch((err) => status.fail("The conversations could not be read: ", err));
    const refresh = (withMembers) => {
      if (reading) {
        again = { withMembers: (again && again.withMembers) || withMembers };
        return reading;
      }
      reading = read(withMembers).then(() => {
        reading = null;
        if (!again) return null;
        const next = again;
        again = null;
        return refresh(next.withMembers);
      });
      return reading;
    };
    // A closed project takes no new group chat (§9.2).
    // nor one read along from outside the project.
    const closedProject = ctx.outsider || ["accepted", "archived"].includes(ctx.project.state);
    const el = h("nav", { class: "chat-list-pane", "aria-label": "Conversations" },
      h("div", { class: "toolbar" }, h("h2", null, ctx.outsider ? "Group chats" : "Chat"),
        // A human guest creates no group chat (§2.3, §9.2).
        closedProject || !groupsServed || M.trust.guest(ctx) ? null : h("a", { class: "button small new-group", href: ctx.link("chat", "new") }, "New group chat"),
        // A message to the project is talk too (the maintainer's wish,
        // tsk-r1adgwp0a5dr): it starts here, no longer in the inbox.
        ctx.outsider ? null : h("a", { class: "button small message-project", href: ctx.link("message") }, "Message the project")),
      none, ul,
      // Not an empty-looking list: a hub before group chats lists none.
      groupsServed ? null : h("p", { class: "muted no-groups" }, "This hub has no group chats yet."),
      status.el);
    none.hidden = mine.length > 0;
    return { el, refresh, groups: () => groups };
  }

  // A message: its body as Markdown (js/markdown.js, text nodes only), and
  // a Quote button that puts it into the composer as a quote. grouped: it
  // follows the same sender's within GROUP_MS, so it shows neither the
  // picture nor the name again.
  const isRemoved = (msg) => !!msg.redacted || msg.body === null;
  // The hub needs a reason for a removal (§8.5): asked again until one is
  // given; null when cancelled.
  function askReason(question) {
    let reason = window.prompt(question, "");
    while (reason !== null && !reason.trim()) reason = window.prompt("A reason is needed to remove a message. Say why, or cancel:", "");
    return reason === null ? null : reason.trim();
  }
  function tombstone(ctx, r) {
    return h("p", { class: "muted msg-redacted" }, "This message was removed",
      r && r.by ? [" by ", M.dom.memberRef(ctx, r.by)] : null, (r && r.reason ? ": " + r.reason : "") + ".");
  }

  // A composer's one row of actions (the designer's pass on #431): Attach
  // at the start, the keys and Send at the end.
  const actionRow = (files, button) => h("div", { class: "compose-actions" }, files ? files.chooser : null, button);

  // In the global chat (ctx.projectsOf, js/chats.js) an agent's message
  // names the projects it is in, each by its logo with the name on hover;
  // only projects the reader is in, whose member lists the page has read.
  function projectsOf(ctx, sender) {
    if (!ctx.projectsOf || !sender || sender.kind !== "agent") return null;
    const projects = ctx.projectsOf(sender.id);
    if (!projects.length) return null;
    return h("span", { class: "msg-projects" }, h("span", { class: "visually-hidden" }, ", in "),
      projects.map((p, i) => h("span", { class: "msg-project", title: p.name },
        M.projectMark(p.slug, p.name, p.view, "small"), h("span", { class: "visually-hidden" }, (i ? ", " : "") + p.name))));
  }

  // opts.group: a group chat's message (no delivery: several recipients,
  // §9.2); opts.onRedact: offered to a human in the room (§8.5).
  function message(ctx, msg, pending, grouped, onQuote, opts) {
    const o = opts || {};
    const own = msg.from === ctx.me.id;
    // A grouped message says when, not again who.
    const delivery = (m) => (own && !o.group ? (m.delivered_at ? " · reached a session" : " · not picked up yet") : "");
    // Who (a link to them), then when; a delivery update rewrites the when alone.
    const said = (m) => formatTime(m.sent_at) + delivery(m);
    const when = h("span", { class: "when" }, said(msg));
    const sender = ctx.memberById ? ctx.memberById[msg.from] : null;
    // An agent's message names its instance (from_instance, §9, §6.17).
    const meta = h("span", { class: "meta" }, grouped || own ? null
      : [M.dom.memberRef(ctx, msg.from, { instance: msg.from_instance }), projectsOf(ctx, sender), " · "], when);
    if (own && !o.group && !msg.delivered_at) pending.set(msg.seq, (fresh) => { when.textContent = said(fresh); });
    // A removed message reads body null (§9); who and why only where known
    // (this page's own removal, or the event_redacted that said so).
    const removed = isRemoved(msg);
    const body = removed ? tombstone(ctx, msg.redaction) : h("div", { class: "md" }, M.markdown(msg.body, M.ids.where(ctx)));
    return h("li", { class: "msg " + (own ? "out" : "in") + (grouped ? " grouped" : ""), "data-seq": String(msg.seq) },
      !own && !grouped ? h("span", { class: "msg-avatar" }, M.avatar(sender || { id: msg.from }, 28)) : null,
      h("div", { class: "msg-body" }, body,
        M.attachments ? M.attachments.render(ctx, msg, o.canDeleteFile) : null, meta,
        onQuote && !removed ? h("button", { type: "button", class: "small msg-quote", "aria-label": "Quote this message", onclick: () => onQuote(msg) }, "Quote") : null,
        o.onRedact && !removed ? h("button", { type: "button", class: "small msg-quote", "aria-label": "Remove this message for everyone", onclick: () => o.onRedact(msg) }, "Remove") : null));
  }

  // The newest page of a conversation, and nothing before it (the
  // maintainer's wish, tsk-r1adgwp0a5dr, and the rule after the 2026-10-26
  // incident: no request whose cost grows with history). The last PAGE
  // messages are read back (before=, which marks nothing), then once
  // forward from the first of them, which marks them read and delivered as
  // opening a chat always did and takes what came meanwhile. Two requests,
  // whatever the length of the history; older pages come on scroll-up.
  // The forward read keeps to a group chat's window (§9.2): what lies
  // before one joined is not shown, only offered (earlier).
  const PAGE = 50;
  async function newestPage(path, newest) {
    const back = await M.api.get(path + "?before=" + encodeURIComponent(newest || Number.MAX_SAFE_INTEGER) + "&limit=" + PAGE);
    const from = back.items.length ? back.items[0].seq - 1 : 0;
    const fwd = await M.api.get(path + "?after=" + encodeURIComponent(from) + "&limit=" + PAGE);
    const start = fwd.items.length ? fwd.items[0].seq : Infinity;
    const bySeq = new Map();
    back.items.filter((m) => m.seq >= start).concat(fwd.items).forEach((m) => bySeq.set(m.seq, Object.assign(bySeq.get(m.seq) || {}, m)));
    const items = Array.from(bySeq.values()).sort((a, b) => a.seq - b.seq);
    const backEarlier = back.earlier === undefined ? null : back.earlier;
    let earlier = null;
    if (items.length) earlier = backEarlier !== null || back.items.some((m) => m.seq < items[0].seq) ? items[0].seq : null;
    else if (back.items.length) earlier = back.items[back.items.length - 1].seq + 1;
    return { items, earlier, cursor: Math.max(fwd.cursor || 0, items.length ? items[items.length - 1].seq : 0) };
  }
  // A long chat keeps at most KEEP messages drawn while the reader is at
  // the newest; the older ones are read again on scroll-up.
  const KEEP = 300;
  // Older messages are read once the reader is this close to the top.
  const NEAR_TOP = 120;

  // Messages of one sender this close together are one group.
  const GROUP_MS = 5 * 60 * 1000;
  // The history is read to its end in pages of this size (the hub's maximum).
  const HISTORY_PAGE = 200;
  const dayOf = (iso) => { const d = new Date(iso); return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate(); };
  function dayLabel(iso, now) {
    const d = new Date(iso);
    const today = new Date(now);
    const yesterday = new Date(now - 86400000);
    if (dayOf(iso) === dayOf(today.toISOString())) return "Today";
    if (dayOf(iso) === dayOf(yesterday.toISOString())) return "Yesterday";
    return d.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  }

  // The history as it is drawn: day separators, groups, and once the line
  // before the first message that was unread when the chat was opened.
  function timeline(ctx, pending, firstUnread, onQuote, opts) {
    let last = null;
    return (msg) => {
      const out = [];
      if (!last || dayOf(last.sent_at) !== dayOf(msg.sent_at)) {
        out.push(h("li", { class: "day" }, h("span", null, dayLabel(msg.sent_at, Date.now()))));
        last = null;
      }
      if (firstUnread && msg.seq === firstUnread) out.push(h("li", { class: "new-line" }, h("span", null, "New messages")));
      // Two instances of one agent are two senders.
      const grouped = !!last && last.from === msg.from && (last.from_instance || null) === (msg.from_instance || null)
        && Date.parse(msg.sent_at) - Date.parse(last.sent_at) < GROUP_MS
        && !(firstUnread && msg.seq === firstUnread);
      out.push(message(ctx, msg, pending, grouped, onQuote, opts));
      last = msg;
      return out;
    };
  }

  // A text with its fenced blocks and code spans blanked out, as the hub
  // reads it for mentions (docs/api.md §8.6).
  function withoutCode(value) {
    const out = [];
    let fence = null;
    for (const line of value.split("\n")) {
      const open = /^(`{3,}|~{3,})/.exec(line);
      if (fence) {
        if (open && open[1][0] === fence[0] && open[1].length >= fence.length && !line.slice(open[1].length).trim()) fence = null;
        out.push("");
      } else if (open) {
        fence = open[1];
        out.push("");
      } else {
        out.push(line);
      }
    }
    return out.join("\n").replace(/(?<!`)(`+)(?!`)[\s\S]*?[^`]\1(?!`)/g, " ");
  }

  // The quote of a message, as Markdown: each line behind "> ", the sender first.
  const quoteOf = (ctx, msg) => "> " + String(ctx.nameOf(msg.from)).replace(/\s+/g, " ").trim() + ":\n" + String(msg.body || "").split("\n").map((l) => "> " + l).join("\n") + "\n\n";

  // The chat fills the screen below the header, so that only its history
  // scrolls and the composer stays at the bottom; the visual viewport
  // shrinks with a phone's on-screen keyboard, 100dvh does not everywhere.
  function fitToScreen(layout) {
    const fit = () => {
      if (layout.isConnected === false) {
        window.removeEventListener("resize", fit);
        if (window.visualViewport) window.visualViewport.removeEventListener("resize", fit);
        return;
      }
      const header = document.getElementById("header");
      const top = header && header.getBoundingClientRect ? Math.max(0, header.getBoundingClientRect().bottom) : 0;
      const height = window.visualViewport ? window.visualViewport.height : window.innerHeight;
      if (layout.style.setProperty) layout.style.setProperty("--chat-h", Math.max(240, Math.floor(height - top - 16)) + "px");
    };
    window.addEventListener("resize", fit);
    if (window.visualViewport) window.visualViewport.addEventListener("resize", fit);
    fit();
  }

  // Stays at the newest message unless the human scrolled up to read.
  const atBottom = (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 48;

  // Keeping a reader at the newest message (an open chat that had not
  // scrolled read as an agent that had gone quiet). Whether the reader is at
  // the end comes from their own scrolling, not from a measure when a
  // message arrives: content that grows after it was drawn (an image that
  // loads, the pane resized) no longer leaves them behind. Scrolled up to
  // read, a new message is counted on the pill, which goes to the end.
  // Jumps, never smooth scrolling, so reduced motion is respected as it is.
  function follower(messages, onEnd) {
    let stuck = true;
    let unseen = 0;
    const end = () => { messages.scrollTop = messages.scrollHeight; };
    const pill = h("button", { type: "button", class: "small jump-latest", hidden: true }, "Newest");
    const draw = () => {
      pill.hidden = stuck;
      pill.textContent = unseen ? unseen + " new · Newest" : "Newest";
    };
    messages.addEventListener("scroll", () => { stuck = atBottom(messages); if (stuck) unseen = 0; draw(); });
    messages.addEventListener("load", () => { if (stuck) end(); }, true);
    if (window.ResizeObserver) new window.ResizeObserver(() => { if (stuck) end(); }).observe(messages);
    pill.addEventListener("click", () => { stuck = true; unseen = 0; end(); draw(); if (onEnd) onEnd(); });
    return {
      pill,
      // A message drawn at the end: followed when the reader is there or wrote it.
      added(own) {
        if (own || stuck) { stuck = true; end(); } else { unseen += 1; draw(); }
      },
      // On opening: at the first unread message where there is one, else at the end.
      open(marker) {
        if (marker && typeof marker.offsetTop === "number" && marker.offsetTop > 0) {
          messages.scrollTop = marker.offsetTop;
          stuck = atBottom(messages);
        } else { stuck = true; end(); }
        draw();
      },
    };
  }

  // What js/group-chat.js draws with: the same history, Markdown, quotes,
  // drafts, sizing and the same reading of mentions.
  M.chatParts = { actionRow, newestPage, PAGE, KEEP, NEAR_TOP, timeline, quoteOf, withoutCode, atBottom, follower, fitToScreen, drafts, isRemoved, askReason, HISTORY_PAGE,
    chatsOf, ordered, listItem, LIST_MS, RESYNC };

  // One focus handler for the page; it serves the chat view on screen.
  let onFocus = null;
  window.addEventListener("focus", () => { if (onFocus) onFocus(); });

  // given.list: a conversation list of the caller's (the global chat's,
  // js/chats.js), which refreshes itself; the project's own otherwise.
  M.views.chat = async function (ctx, root, args, given) {
    const mine = ctx.members.filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id);
    const agent = args[0] ? mine.find((m) => m.id === args[0]) : null;
    const groupsServed = await M.groupChat.served();
    const list = (given && given.list) || conversations(ctx, args[0] || null, groupsServed);
    const layout = h("div", { class: "chat-layout" + (args[0] ? " open" : "") }, list.el);
    append(root, layout);
    const isChat = (e) => e.kind === "message" && e.payload && e.payload.type === "chat";
    if (!given) {
      ctx.onEvents((events) => { if (events.some((e) => isChat(e) || /^conversation_|^event_redacted$/.test(e.kind))) list.refresh(false); });
      // A hidden tab reads no list; the next round after it is shown does.
      ctx.every(LIST_MS, () => (document.visibilityState === "hidden" ? null : list.refresh(true)));
    }
    // A new group chat, or a group chat the hub lists (§9.2, js/group-chat.js).
    if (args[0] === "new") {
      if (groupsServed) M.groupChat.create(ctx, layout, list);
      else append(layout, h("p", { class: "chat-none muted" }, "This hub has no group chats yet: there is none to create."));
      await list.refresh(false);
      return;
    }
    if (!agent && args[0]) {
      await list.refresh(false);
      const group = list.groups().find((g) => g.id === args[0]);
      if (group) { await M.groupChat.open(ctx, root, layout, list, group, M.chatParts); return; }
    }
    if (!agent) {
      // A group chat's link on a hub without group chats is no error of the reader's.
      if (args[0] && !groupsServed && /^cnv-/.test(args[0])) append(layout, M.dom.notOnHub("This hub has no group chats yet, so this link cannot open here."));
      else if (args[0]) append(layout, h("p", { class: "error", role: "alert" }, "No conversation of yours with the id " + args[0] + "."));
      else if (mine.length || ctx.outsider) append(layout, h("p", { class: "chat-none muted" }, "Pick a conversation."));
      await list.refresh(false);
      return;
    }
    const pane = h("section", { class: "chat-pane", "aria-label": "Chat with " + agent.display_name });
    append(layout, pane);

    const path = ctx.base + "/conversations/" + encodeURIComponent(agent.id) + "/messages";
    // How many of the agent's messages were unread, before reading marks them
    // read. A message arriving between this read and the messages' shifts the
    // line by one; a failed read draws no line and says so below.
    let unreadFailed = null;
    const before = await M.api.getAll(ctx.base + "/conversations?observed=true").catch((err) => { unreadFailed = err; return { items: [] }; });
    const unreadBefore = ((before.items.find((c) => (c.agent_id || c.id) === agent.id) || {}).unread) || 0;
    // The newest page only (docs/api.md §9); older ones on scroll-up. The
    // list's last message says where the newest is.
    const listed = before.items.find((c) => (c.agent_id || c.id) === agent.id);
    const newest = listed && listed.last_message && listed.last_message.seq ? listed.last_message.seq + 1 : null;
    const conv = await newestPage(path, newest);
    // What is drawn, oldest first; `earlier`: the seq to read before, or null.
    const loaded = conv.items;
    let earlier = conv.earlier;
    const theirs = loaded.filter((m) => m.from === agent.id);
    // More unread than the page holds: the line stands at its top.
    const firstUnread = unreadBefore && theirs.length ? theirs[Math.max(0, theirs.length - unreadBefore)].seq : null;
    // Read after the messages, so that this conversation's unread is gone.
    await list.refresh(false);
    let cursor = conv.cursor || 0;
    const shown = new Set(loaded.map((m) => m.seq));
    // The human's messages not picked up yet: seq -> update of their line.
    const pending = new Map();
    // The human party removes a message of the chat, the agent's or their own (§8.5).
    // §8.5: it needs events:admin too, which owner and admin hold.
    // The human party deletes a file of the chat (§8.7), whoever sent it.
    const drawOpts = { onRedact: ctx.canAdmin ? redactDirect : null, canDeleteFile: () => true };
    let draw = timeline(ctx, pending, firstUnread, quote, drawOpts);
    const messages = h("ol", { class: "messages", "aria-live": "polite" });
    // Everything loaded drawn again as one timeline (days, groups): after
    // older messages came in front, or the oldest were let go.
    function redrawAll() {
      draw = timeline(ctx, pending, firstUnread, quote, drawOpts);
      clear(messages);
      shown.clear();
      loaded.forEach((m) => shown.add(m.seq));
      if (loaded.length) append(messages, loaded.map(draw));
      else {
        append(messages, h("li", { class: "empty" }, h("p", null, "No messages yet."),
          h("p", { class: "muted" }, M.dom.memberRef(ctx, agent.id), " reads what you write here at its next wait or resume.")));
      }
      drawEarlier();
    }
    // Older messages: on scroll-up near the top, or with the button for a
    // keyboard; one page at a time, the reader's place kept.
    const earlierBox = h("div", { class: "earlier" });
    let readingOlder = false;
    async function older() {
      if (earlier === null || readingOlder) return;
      readingOlder = true;
      try {
        const page = await M.api.get(path + "?before=" + encodeURIComponent(earlier) + "&limit=" + PAGE);
        const fresh = page.items.filter((m) => !shown.has(m.seq));
        earlier = page.earlier === undefined ? null : page.earlier;
        const height = messages.scrollHeight;
        const top = messages.scrollTop;
        loaded.unshift(...fresh);
        redrawAll();
        messages.scrollTop = top + (messages.scrollHeight - height);
      } catch (err) {
        pollStatus.fail("The earlier messages could not be read: ", err);
      } finally {
        readingOlder = false;
      }
    }
    function drawEarlier() {
      clear(earlierBox);
      if (earlier === null) return;
      append(earlierBox, h("button", { type: "button", class: "small", onclick: () => older() }, "Show earlier messages"));
    }
    messages.addEventListener("scroll", () => { if (messages.scrollTop < NEAR_TOP) older(); });
    redrawAll();
    // Back to the newest, when the human has scrolled up; with what came
    // meanwhile. The pill goes away: the focus goes to the composer.
    const follow = follower(messages, () => text.focus());
    const jump = follow.pill;
    const pollStatus = M.statusLine();
    if (unreadFailed) pollStatus.fail("Which messages are new could not be read: ", unreadFailed);

    let checking = false;
    // Where the last check stopped: one page per check, the next one goes on
    // from there, so a long tail is never read in one go.
    let deliveryFrom = null;
    async function checkDelivery() {
      if (!pending.size || checking) return;
      checking = true;
      try {
        // From just before the oldest pending message on (after=<seq>,
        // oldest first, docs/api.md §9), one page.
        const after = Math.max(Math.min(...pending.keys()) - 1, deliveryFrom || 0);
        const page = await M.api.get(path + "?after=" + encodeURIComponent(after) + "&limit=200");
        page.items.forEach((m) => {
          const update = pending.get(m.seq);
          if (update && m.delivered_at) { update(m); pending.delete(m.seq); }
        });
        deliveryFrom = page.items.length === 200 && pending.size ? page.items[page.items.length - 1].seq : null;
      } catch (err) {
        pollStatus.fail("Whether your messages were picked up could not be read: ", err);
      } finally {
        checking = false;
      }
    }
    onFocus = () => {
      if (!root.isConnected && root.isConnected !== undefined) { onFocus = null; return; }
      checkDelivery();
    };

    function add(msg, own) {
      if (shown.has(msg.seq)) return;
      shown.add(msg.seq);
      loaded.push(msg);
      const empty = messages.querySelector(".empty");
      if (empty) empty.remove();
      append(messages, draw(msg));
      follow.added(own);
      if (msg.seq > cursor) cursor = msg.seq;
      // At the newest with a long tail drawn: the oldest are let go, and
      // read again on scroll-up.
      if (loaded.length > KEEP && atBottom(messages)) {
        loaded.splice(0, loaded.length - PAGE * 2);
        earlier = loaded[0].seq;
        redrawAll();
        messages.scrollTop = messages.scrollHeight;
      }
    }

    const mentions = (e) => isChat(e) && e.payload.conversation_id === agent.id && !shown.has(e.seq);
    ctx.onEvents(async (events) => {
      // The global chat has no feed to say what changed in what is shown: it
      // asks for the newest page again (before=, which marks nothing read)
      // and takes its removals and deleted files over.
      if (events.some((e) => e.kind === RESYNC)) await resync();
      // A message of this chat removed (§8.5): its text goes at once.
      events.filter((e) => e.kind === "event_redacted" && e.payload)
        .forEach((e) => markRemoved(e.payload.seq, e.actor && e.actor.member_id, e.payload.reason));
      events.filter((e) => e.kind === "attachment_deleted" && e.payload)
        .forEach((e) => M.attachments.markDeleted(messages, e.payload.attachment_id));
      if (events.some((e) => e.actor && e.actor.member_id === agent.id)) await checkDelivery();
      if (!events.some(mentions)) return;
      try {
        const fresh = await M.api.get(path + "?after=" + encodeURIComponent(cursor));
        // Someone else's message never pulls a reader who scrolled up down.
        fresh.items.forEach((m) => add(m, m.from === ctx.me.id));
        if (fresh.cursor && fresh.cursor > cursor) cursor = fresh.cursor;
        pollStatus.done();
        // The list read on the same event may predate this read.
        list.refresh(false);
      } catch (err) {
        pollStatus.fail("New messages could not be fetched: ", err);
      }
    });
    // One page per nudge, newest first, walking back over what is shown and
    // starting at the newest again once it reached the oldest.
    let resyncBefore = null;
    async function resync() {
      try {
        const before = resyncBefore || cursor + 1;
        const page = await M.api.get(path + "?before=" + encodeURIComponent(before) + "&limit=" + HISTORY_PAGE);
        const oldestShown = Math.min(...shown);
        const lowest = page.items.length ? Math.min(...page.items.map((m) => m.seq)) : null;
        resyncBefore = lowest !== null && page.items.length === HISTORY_PAGE && lowest > oldestShown ? lowest : null;
        page.items.filter((m) => shown.has(m.seq)).forEach((m) => {
          if (isRemoved(m)) markRemoved(m.seq, m.redaction && m.redaction.by, m.redaction && m.redaction.reason);
          (m.attachments || []).filter((a) => a.deleted_at).forEach((a) => M.attachments && M.attachments.markDeleted(messages, a.id));
        });
      } catch (err) {
        pollStatus.fail("The conversation could not be read again: ", err);
      }
    }
    // A message's text replaced by its tombstone, in place; its buttons go.
    function markRemoved(seq, by, reason) {
      const li = Array.from(messages.querySelectorAll("li.msg")).find((x) => x.getAttribute("data-seq") === String(seq));
      const md = li && li.querySelector(".md");
      if (!md) return;
      const kept = loaded.find((m) => m.seq === seq);
      if (kept) Object.assign(kept, { body: null, redacted: true, redaction: { by, reason } });
      md.parentNode.insertBefore(tombstone(ctx, { by, reason }), md);
      md.remove();
      Array.from(li.querySelectorAll("button.msg-quote")).forEach((b) => b.remove());
    }
    async function redactDirect(msg) {
      const reason = askReason("Remove this message from the chat with " + agent.display_name + "? Its text is replaced by a note. Say why:");
      if (reason === null) return;
      status.busy("Removing…");
      try {
        await M.api.post(ctx.base + "/events/" + encodeURIComponent(msg.seq) + "/redact", { reason });
        markRemoved(msg.seq, ctx.me.id, reason);
        status.done();
        append(status.el, h("span", { class: "ok" }, "Removed."));
        // The button that had the focus is gone with the text.
        status.el.setAttribute("tabindex", "-1");
        status.el.focus();
        list.refresh(false);
      } catch (err) {
        status.fail("Not removed: ", err);
      }
    }
    // Quote: the message goes into the composer as a quote, before what is there.
    function quote(msg) {
      text.value = quoteOf(ctx, msg) + text.value;
      drafts.set(key, text.value);
      hintMention();
      text.focus();
      if (text.setSelectionRange) text.setSelectionRange(text.value.length, text.value.length);
    }
    const key = ctx.slug + "/" + agent.id;
    const text = h("textarea", { id: "chat-text", rows: "3", placeholder: "Message to " + agent.display_name });
    text.value = drafts.get(key) || "";
    // In a chat a mention is plain text and tells nobody (docs/api.md §8.6).
    // When one is being written, the page says so and offers a project
    // message with it, where it would reach the member.
    const mentionHint = h("p", { class: "hint mention-hint", "aria-live": "polite", hidden: true });
    // What the hub would take as a mention (§8.6): nothing inside code.
    // A short handle or owner/handle, either with an instance's #id (§6.17).
    const MENTIONED = /(^|[^A-Za-z0-9_.@/+-])@([a-z0-9-]*[a-z0-9](?:\/[a-z0-9-]*[a-z0-9])?(?:#[2-9a-hjkmnp-z]{4,5})?)(?![A-Za-z0-9_])/;
    function hintMention() {
      const found = MENTIONED.exec(withoutCode(text.value));
      clear(mentionHint);
      mentionHint.hidden = !found;
      if (!found) return;
      append(mentionHint, "In this chat @" + found[2] + " notifies nobody. ",
        h("a", { href: ctx.link("message", "@" + found[2]) }, "Write a project message to draw them in"), ".");
    }
    text.addEventListener("input", () => {
      if (text.value.trim()) drafts.set(key, text.value); else drafts.delete(key);
      hintMention();
    });
    hintMention();
    const status = M.statusLine();
    const button = h("button", { type: "submit", class: "primary" }, "Send");

    // Files go with the message (§8.7): uploaded when chosen, named when sent.
    const files0 = M.attachments ? M.attachments.picker(ctx, "chat") : null;
    async function send(e) {
      e.preventDefault();
      const body = text.value.trim();
      const files = files0 ? files0.ids() : [];
      if (!body && !files.length) { text.focus(); return; }
      if (files0 && files0.busy()) { status.fail("Not sent: ", { message: "a file is still uploading" }); return; }
      button.disabled = true;
      status.busy("Sending…");
      try {
        const msg = await M.api.post(path, files.length ? { body, attachments: files } : { body });
        add(msg, true);
        if (files0) files0.clear(files);
        text.value = "";
        drafts.delete(key);
        hintMention();
        status.done();
        list.refresh(false);
      } catch (err) {
        status.fail("Not sent: ", err);
      } finally {
        button.disabled = false;
      }
    }

    M.dom.sendOnCtrlEnter(text, send, button);

    const heading = h("h2", { tabindex: "-1" }, "Chat with ", M.dom.memberRef(ctx, agent.id));
    append(pane,
      h("a", { class: "chat-back", href: ctx.link("chat") }, "← Conversations"),
      h("div", { class: "toolbar" },
        heading,
        h("span", { class: "muted" }, agent.session
          ? "session " + agent.session.id + (agent.session.listening ? ", listening" : "")
          : "no session — picked up when it resumes")),
      earlierBox,
      messages,
      jump,
      pollStatus.el,
      h("form", { class: "compose", onsubmit: send },
        h("label", { for: "chat-text" }, "Message", h("span", { class: "visually-hidden" }, " (" + M.dom.SEND_KEYS + " sends)")),
        text, mentionHint, files0 ? files0.el : null, actionRow(files0, button), status.el));
    // Sizing, scrolling and focus need the view in the page, which the
    // router does once this function has returned.
    window.setTimeout(() => {
      fitToScreen(layout);
      follow.open(messages.querySelector(".new-line"));
      // On a phone the chat replaced the list: take the focus to its heading.
      if (window.matchMedia && window.matchMedia("(max-width: 720px)").matches) heading.focus();
    }, 0);
  };
})(window.Maity);
