// (5) Chat: direct conversations with the agents the human owns. The
// conversations are listed beside the open one (presence, last message,
// unread), so switching is one click; on a phone the list is its own
// screen. Messages are events the agent picks up with wait or resume
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
  const PRESENCE_LABELS = { online: "online", away: "away", offline: "offline", paused: "paused" };

  // Unsent text per conversation ("<slug>/<agent id>"), kept while the
  // human switches between them in this tab; never stored or sent.
  const drafts = new Map();
  // Signing out ends them; the next human in this tab starts empty.
  M.clearChatDrafts = () => drafts.clear();

  // A chat as the list shows it: today one per owned agent (docs/api.md §9),
  // shaped for chats with several participants (a title, their avatars).
  function chatsOf(mine, byAgent) {
    return mine.map((m) => {
      const c = byAgent[m.id] || {};
      return { id: m.id, title: m.display_name, participants: [m], unread: c.unread || 0,
        last_message_at: c.last_message_at || null, last_message: c.last_message || null };
    });
  }

  // Newest chat first; the ones without messages after, by title.
  function ordered(chats) {
    const at = (c) => c.last_message_at || "";
    return chats.slice().sort((a, b) => (at(b) > at(a) ? 1 : at(b) < at(a) ? -1 : a.title.localeCompare(b.title)));
  }

  const initials = (name) => (name.match(/[\p{L}\p{N}]+/gu) || ["?"]).slice(0, 2).map((w) => [...w][0].toUpperCase()).join("");

  // Up to three participants' initials; with one, its presence as a dot.
  function avatars(chat) {
    const shown = chat.participants.slice(0, 3);
    return h("span", { class: "avatars", "aria-hidden": "true" },
      shown.map((m) => h("span", { class: "avatar" }, initials(m.display_name))),
      chat.participants.length === 1 ? h("span", { class: "dot " + chat.participants[0].presence }) : null);
  }

  // Under the title: who and how present, then an unsent draft, else the
  // last message where the hub sends it (`last_message`), else nothing.
  // The open chat's own draft is in its composer, not repeated here.
  function sublines(ctx, chat, current) {
    const who = chat.participants.length === 1
      ? PRESENCE_LABELS[chat.participants[0].presence] || chat.participants[0].presence
      : chat.participants.map((m) => m.display_name).join(", ");
    const draft = current ? null : drafts.get(ctx.slug + "/" + chat.id);
    const last = chat.last_message;
    let line = null;
    if (draft) line = "Draft: " + draft;
    else if (last && last.redacted) line = "A message was removed.";
    else if (last) line = (last.from === ctx.me.id ? "You: " : "") + last.body;
    return { who, line, draft: !!draft };
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
    h("span", { class: "conv-title" }, chat.title),
    when ? [apart(", "), h("span", { class: "conv-time" }, when)] : null,
    unread ? [apart(", "), h("span", { class: "count" }, String(unread)), apart(" unread")] : null,
    apart(", "), h("span", { class: "conv-sub" }, sub.who),
    sub.line ? [apart(": "), h("span", { class: "preview" + (sub.draft ? " draft" : "") }, sub.line)] : null));
  }

  // The conversation list; refresh() re-reads it and presence in place.
  function conversations(ctx, currentId) {
    const ul = h("ul", { class: "chat-list" });
    const status = M.statusLine();
    let mine = ctx.members.filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id);
    let byAgent = {};
    const none = h("p", { class: "muted" }, "You own no agents in this project.");
    const draw = () => {
      // A redraw keeps the keyboard where it was: on the same chat's link.
      const focused = document.activeElement && ul.contains && ul.contains(document.activeElement)
        ? document.activeElement.getAttribute("href") : null;
      clear(ul);
      ordered(chatsOf(mine, byAgent)).forEach((chat) => append(ul, listItem(ctx, chat, currentId)));
      none.hidden = mine.length > 0;
      if (focused) {
        const again = ul.querySelectorAll("a.conv").find((a) => a.getAttribute("href") === focused);
        if (again) again.focus();
      }
    };
    // One read at a time; a refresh asked for while one runs (it may
    // predate what the caller just changed) runs once more after it.
    let reading = null;
    let again = null;
    const read = (withMembers) => Promise.all([
      M.api.getAll(ctx.base + "/conversations"),
      withMembers ? M.api.getAll(ctx.base + "/members") : null,
    ]).then(([list, members]) => {
      byAgent = {};
      list.items.forEach((c) => { byAgent[c.agent_id] = c; });
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
    const el = h("nav", { class: "chat-list-pane", "aria-label": "Conversations" },
      h("h2", null, "Chat"), none, ul, status.el);
    none.hidden = mine.length > 0;
    return { el, refresh };
  }

  const metaText = (ctx, msg, own) => (own ? "" : ctx.nameOf(msg.from) + " · ") + formatTime(msg.sent_at)
    + (own ? (msg.delivered_at ? " · reached a session" : " · not picked up yet") : "");

  function message(ctx, msg, pending) {
    const own = msg.from === ctx.me.id;
    const meta = h("span", { class: "meta" }, metaText(ctx, msg, own));
    if (own && !msg.delivered_at) pending.set(msg.seq, (fresh) => { meta.textContent = metaText(ctx, fresh, true); });
    return h("li", { class: "msg " + (own ? "out" : "in") }, h("p", { class: "pre" }, msg.body), meta);
  }

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

  // One focus handler for the page; it serves the chat view on screen.
  let onFocus = null;
  window.addEventListener("focus", () => { if (onFocus) onFocus(); });

  M.views.chat = async function (ctx, root, args) {
    const mine = ctx.members.filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id);
    const agent = args[0] ? mine.find((m) => m.id === args[0]) : null;
    const list = conversations(ctx, agent ? agent.id : null);
    const layout = h("div", { class: "chat-layout" + (agent ? " open" : "") }, list.el);
    append(root, layout);
    const isChat = (e) => e.kind === "message" && e.payload && e.payload.type === "chat";
    ctx.onEvents((events) => { if (events.some(isChat)) list.refresh(false); });
    ctx.every(LIST_MS, () => list.refresh(true));
    if (!agent) {
      if (args[0]) append(layout, h("p", { class: "error", role: "alert" }, "No agent of yours with the id " + args[0] + "."));
      else if (mine.length) append(layout, h("p", { class: "chat-none muted" }, "Pick a conversation."));
      await list.refresh(false);
      return;
    }
    const pane = h("section", { class: "chat-pane", "aria-label": "Chat with " + agent.display_name });
    append(layout, pane);

    const path = ctx.base + "/conversations/" + encodeURIComponent(agent.id) + "/messages";
    const conv = await M.api.get(path);
    // Read after the messages, so that this conversation's unread is gone.
    await list.refresh(false);
    let cursor = conv.cursor || 0;
    const shown = new Set(conv.items.map((m) => m.seq));
    // The human's messages not picked up yet: seq -> update of their line.
    const pending = new Map();
    const messages = h("ol", { class: "messages", "aria-live": "polite" },
      conv.items.length ? conv.items.map((m) => message(ctx, m, pending)) : h("li", { class: "empty" }, "No messages yet."));
    const pollStatus = M.statusLine();

    let checking = false;
    async function checkDelivery() {
      if (!pending.size || checking) return;
      checking = true;
      try {
        // From just before the oldest pending message on (after=<seq>,
        // oldest first, docs/api.md §9), page by page.
        let after = Math.min(...pending.keys()) - 1;
        for (;;) {
          const page = await M.api.get(path + "?after=" + encodeURIComponent(after) + "&limit=200");
          page.items.forEach((m) => {
            const update = pending.get(m.seq);
            if (update && m.delivered_at) { update(m); pending.delete(m.seq); }
          });
          if (page.items.length < 200 || !pending.size) break;
          after = page.items[page.items.length - 1].seq;
        }
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
      const follow = own || atBottom(messages);
      const empty = messages.querySelector(".empty");
      if (empty) empty.remove();
      append(messages, message(ctx, msg, pending));
      if (follow) messages.scrollTop = messages.scrollHeight;
      if (msg.seq > cursor) cursor = msg.seq;
    }

    const mentions = (e) => isChat(e) && e.payload.conversation_id === agent.id && !shown.has(e.seq);
    ctx.onEvents(async (events) => {
      if (events.some((e) => e.actor && e.actor.member_id === agent.id)) checkDelivery();
      if (!events.some(mentions)) return;
      try {
        const fresh = await M.api.get(path + "?after=" + encodeURIComponent(cursor));
        fresh.items.forEach(add);
        if (fresh.cursor && fresh.cursor > cursor) cursor = fresh.cursor;
        pollStatus.done();
        // The list read on the same event may predate this read.
        list.refresh(false);
      } catch (err) {
        pollStatus.fail("New messages could not be fetched: ", err);
      }
    });
    const key = ctx.slug + "/" + agent.id;
    const text = h("textarea", { id: "chat-text", rows: "3", placeholder: "Message to " + agent.display_name });
    text.value = drafts.get(key) || "";
    text.addEventListener("input", () => {
      if (text.value.trim()) drafts.set(key, text.value); else drafts.delete(key);
    });
    const status = M.statusLine();
    const button = h("button", { type: "submit" }, "Send");

    async function send(e) {
      e.preventDefault();
      const body = text.value.trim();
      if (!body) { text.focus(); return; }
      button.disabled = true;
      status.busy("Sending…");
      try {
        const msg = await M.api.post(path, { body });
        add(msg, true);
        text.value = "";
        drafts.delete(key);
        status.done();
        list.refresh(false);
      } catch (err) {
        status.fail("Not sent: ", err);
      } finally {
        button.disabled = false;
      }
    }

    text.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(e);
    });

    const heading = h("h2", { tabindex: "-1" }, "Chat with " + agent.display_name);
    append(pane,
      h("a", { class: "chat-back", href: ctx.link("chat") }, "← Conversations"),
      h("div", { class: "toolbar" },
        heading,
        h("span", { class: "muted" }, agent.session
          ? "session " + agent.session.id + (agent.session.listening ? ", listening" : "")
          : "no session — picked up when it resumes")),
      messages,
      pollStatus.el,
      h("form", { class: "compose", onsubmit: send },
        h("label", { for: "chat-text" }, "Message (Ctrl+Enter sends)"),
        text, button, status.el));
    // Sizing, scrolling and focus need the view in the page, which the
    // router does once this function has returned.
    window.setTimeout(() => {
      fitToScreen(layout);
      messages.scrollTop = messages.scrollHeight;
      // On a phone the chat replaced the list: take the focus to its heading.
      if (window.matchMedia && window.matchMedia("(max-width: 720px)").matches) heading.focus();
    }, 0);
  };
})(window.Maity);
