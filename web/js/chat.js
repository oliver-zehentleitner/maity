// (5) Chat: a direct conversation with an agent the human owns. Messages
// are events the agent picks up with wait or resume (docs/api.md §9); a
// chat event of this conversation in the project's feed fetches the new
// messages. The inbox stays the primary surface.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, formatTime, formatAgo } = M.dom;

  async function picker(ctx, mine) {
    const list = await M.api.getAll(ctx.base + "/conversations");
    const byAgent = {};
    list.items.forEach((c) => { byAgent[c.agent_id] = c; });
    return h("div", null,
      h("h2", null, "Chat"),
      mine.length
        ? h("ul", { class: "chat-picker" }, mine.map((m) => {
          const c = byAgent[m.id];
          return h("li", null, h("a", { href: ctx.link("chat", m.id) }, m.display_name),
            c && c.unread ? h("span", { class: "count", "aria-label": c.unread + " unread" }, String(c.unread)) : null,
            h("span", { class: "muted" }, " · " + m.role + " · " + m.presence
              + (c && c.last_message_at ? " · last message " + formatAgo(c.last_message_at) : "")));
        }))
        : h("p", { class: "muted" }, "You own no agents in this project."));
  }

  function message(ctx, msg) {
    const own = msg.from === ctx.me.id;
    return h("li", { class: "msg " + (own ? "out" : "in") },
      h("p", { class: "pre" }, msg.body),
      h("span", { class: "meta" },
        (own ? "" : ctx.nameOf(msg.from) + " · ") + formatTime(msg.sent_at)
        + (own ? (msg.delivered_at ? " · reached a session" : " · not picked up yet") : "")));
  }

  M.views.chat = async function (ctx, root, args) {
    const mine = ctx.members.filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id);
    const agent = args[0] ? mine.find((m) => m.id === args[0]) : null;
    if (!agent) {
      if (args[0]) append(root, h("p", { class: "error", role: "alert" }, "No agent of yours with the id " + args[0] + "."));
      append(root, await picker(ctx, mine));
      return;
    }

    const path = ctx.base + "/conversations/" + encodeURIComponent(agent.id) + "/messages";
    const conv = await M.api.get(path);
    let cursor = conv.cursor || 0;
    const shown = new Set(conv.items.map((m) => m.seq));
    const list = h("ol", { class: "messages", "aria-live": "polite" },
      conv.items.length ? conv.items.map((m) => message(ctx, m)) : h("li", { class: "empty" }, "No messages yet."));
    const pollStatus = M.statusLine();

    function add(msg) {
      if (shown.has(msg.seq)) return;
      shown.add(msg.seq);
      const empty = list.querySelector(".empty");
      if (empty) empty.remove();
      append(list, message(ctx, msg));
      if (msg.seq > cursor) cursor = msg.seq;
    }

    const mentions = (e) => e.kind === "message" && e.payload && e.payload.type === "chat"
      && e.payload.conversation_id === agent.id && !shown.has(e.seq);
    ctx.onEvents(async (events) => {
      if (!events.some(mentions)) return;
      try {
        const fresh = await M.api.get(path + "?after=" + encodeURIComponent(cursor));
        fresh.items.forEach(add);
        if (fresh.cursor && fresh.cursor > cursor) cursor = fresh.cursor;
        pollStatus.done();
      } catch (err) {
        pollStatus.fail("New messages could not be fetched: ", err);
      }
    });
    const text = h("textarea", { id: "chat-text", rows: "3", placeholder: "Message to " + agent.display_name });
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
        add(msg);
        text.value = "";
        status.done();
      } catch (err) {
        status.fail("Not sent: ", err);
      } finally {
        button.disabled = false;
      }
    }

    text.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(e);
    });

    append(root,
      h("div", { class: "toolbar" },
        h("h2", null, "Chat with " + agent.display_name),
        h("span", { class: "muted" }, agent.session
          ? "session " + agent.session.id + (agent.session.listening ? ", listening" : "")
          : "no session — picked up when it resumes"),
        h("a", { href: ctx.link("chat") }, "Other agents")),
      list,
      pollStatus.el,
      h("form", { class: "compose", onsubmit: send },
        h("label", { for: "chat-text" }, "Message (Ctrl+Enter sends)"),
        text, button, status.el));
  };
})(window.Maity);
