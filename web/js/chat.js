// (5) Chat: a direct conversation with an agent the human owns. Messages
// go out as events the agent picks up; the inbox stays the primary
// surface.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, formatTime } = M.dom;

  function picker(ctx, mine) {
    return h("div", null,
      h("h2", null, "Chat"),
      mine.length
        ? h("ul", { class: "chat-picker" }, mine.map((m) =>
          h("li", null, h("a", { href: "#/chat/" + encodeURIComponent(m.id) }, m.display_name),
            h("span", { class: "muted" }, " · " + m.role + (m.session ? " · live" : " · offline")))))
        : h("p", { class: "muted" }, "You own no agents in this project."));
  }

  function message(ctx, msg) {
    const own = msg.from === ctx.me.id;
    return h("li", { class: "msg " + (own ? "out" : "in") },
      h("p", { class: "pre" }, msg.body),
      h("span", { class: "meta" },
        (own ? "" : ctx.nameOf(msg.from) + " · ") + formatTime(msg.sent_at)
        + (own ? (msg.delivered_at ? " · delivered" : " · waiting for the agent") : "")));
  }

  M.views.chat = async function (ctx, root, args) {
    const mine = ctx.members.filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id);
    const agent = args[0] ? mine.find((m) => m.id === args[0]) : null;
    if (!agent) {
      root.append(picker(ctx, mine));
      if (args[0]) root.prepend(h("p", { class: "error", role: "alert" }, "No agent of yours with the id " + args[0] + "."));
      return;
    }

    const conv = await M.api.get(ctx.base + "/conversations/" + encodeURIComponent(agent.id) + "/messages");
    const list = h("ol", { class: "messages", "aria-live": "polite" },
      conv.items.length ? conv.items.map((m) => message(ctx, m)) : h("li", { class: "empty" }, "No messages yet."));
    const text = h("textarea", { id: "chat-text", rows: "3", placeholder: "Message to " + agent.display_name });
    const status = h("p", { class: "send-status", role: "status" });
    const button = h("button", { type: "submit" }, "Send");

    async function send(e) {
      e.preventDefault();
      const body = text.value.trim();
      if (!body) { text.focus(); return; }
      button.disabled = true;
      status.textContent = "Sending…";
      status.className = "send-status";
      try {
        const msg = await M.api.post(ctx.base + "/conversations/" + encodeURIComponent(agent.id) + "/messages", { body });
        const empty = list.querySelector(".empty");
        if (empty) empty.remove();
        list.append(message(ctx, msg));
        text.value = "";
        status.textContent = "";
      } catch (err) {
        status.textContent = "Not sent: " + err.message;
        status.className = "send-status failed";
      } finally {
        button.disabled = false;
      }
    }

    text.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(e);
    });

    root.append(
      h("div", { class: "toolbar" },
        h("h2", null, "Chat with " + agent.display_name),
        h("span", { class: "muted" }, agent.session ? "live session " + agent.session.id : "no live session — delivered when it resumes"),
        h("a", { href: "#/chat" }, "Other agents")),
      list,
      h("form", { class: "compose", onsubmit: send },
        h("label", { for: "chat-text" }, "Message (Ctrl+Enter sends)"),
        text, button, status));
  };
})(window.Maity);
