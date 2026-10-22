// Message the project (#/p/<slug>/message): a message to everyone, a role
// or one member (docs/api.md §8.4), of one of the hub's types, optionally
// about a card. Its body is scanned by the hub: a mention draws the member
// into the message's audience and pings them (§8.6); the dashboard never
// sends a mentions list. Opened from the inbox, and with an @name already
// in it from a chat, where a mention notifies nobody.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const TYPES = [
    ["notice", "For your information (no answer expected)"],
    ["handover", "A handover"],
    ["blocker", "Something blocks work"],
    ["go_request", "Asks for a go"],
    ["review_result", "A review's result"],
    ["interface_change", "An interface changes"],
  ];
  const ROLES = ["admin", "reviewer", "member", "proxy"];
  const CLOSED = new Set(["done", "cancelled"]);
  const BODY_CHARS = 16 * 1024;

  // The hub's refusals, in words.
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields && fields.body === "too_many_mentions") return { message: "too many mentions: at most 10 members and 50 mentions in one message" };
    if (err.code === "rate_limited") return { message: "too many mentions in a short time; wait a few minutes and send again" };
    if (fields && fields.to) return { message: "nobody by that address in this project" };
    return err;
  }

  M.views.message = async function (ctx, root, args) {
    const tasks = await M.api.getAll(ctx.base + "/tasks?status=proposed,open,in_progress,blocked,review").catch(() => ({ items: [] }));
    const others = ctx.members.filter((m) => m.id !== ctx.me.id);
    const to = h("select", { id: "message-to" },
      h("option", { value: "all" }, "Everyone in the project"),
      h("optgroup", { label: "A role" }, ROLES.map((r) => h("option", { value: "role:" + r }, "Every " + r))),
      h("optgroup", { label: "One member" }, others.map((m) => h("option", { value: m.id }, m.display_name + " (@" + m.handle + ")"))));
    to.value = "all";
    const type = h("select", { id: "message-type" }, TYPES.map(([v, l]) => h("option", { value: v }, l)));
    type.value = "notice";
    const card = h("select", { id: "message-card" }, h("option", { value: "" }, "no card"),
      tasks.items.filter((t) => !CLOSED.has(t.status)).map((t) => h("option", { value: t.id }, t.id + " · " + t.title)));
    card.value = "";
    const body = h("textarea", { id: "message-body", rows: "6", placeholder: "Markdown. @handle draws a member in and notifies them.",
      "aria-describedby": "message-body-hint" });
    // A prefilled @name from a chat (args[0]), as text, never markup.
    if (args && args[0]) body.value = args[0] + " ";
    const status = M.statusLine();
    const send = h("button", { type: "submit" }, "Send");
    const result = h("div", { class: "message-result", "aria-live": "polite" });

    const form = h("form", {
      class: "project-form message-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const text = body.value.trim();
        if (!text) { status.fail("Not sent: ", { message: "the message is empty" }); body.focus(); return; }
        if ([...text].length > BODY_CHARS) { status.fail("Not sent: ", { message: "the message is longer than 16,384 characters" }); body.focus(); return; }
        const message = { kind: "message", type: type.value, to: to.value, body: text };
        if (card.value) message.task_id = card.value;
        send.disabled = true;
        status.busy("Sending…");
        try {
          const event = await M.api.post(ctx.base + "/events", message);
          const mentioned = ((event.payload && event.payload.mentions) || []).map((x) => ctx.nameOf(x.member_id));
          body.value = "";
          status.done();
          const whom = to.value === "all" ? "everyone" : to.value.startsWith("role:") ? "every " + to.value.slice(5) : ctx.nameOf(to.value);
          append(clear(result), h("p", { class: "ok" }, "Sent to " + whom
            + (mentioned.length ? "; mentioned and notified: " + [...new Set(mentioned)].join(", ") : "") + "."));
          body.focus();
        } catch (err) {
          status.fail("Not sent: ", said(err));
        } finally {
          send.disabled = false;
        }
      },
    },
    h("label", { for: "message-to" }, "To"), to,
    h("label", { for: "message-type" }, "What it is"), type,
    h("label", { for: "message-card" }, "About a card"), card,
    h("label", { for: "message-body" }, "Message"), body,
    // With the @ picker where the page has it; the hub resolves, not the page.
    M.mentionPicker ? M.mentionPicker(body, () => M.api.getAll(ctx.base + "/members").then((r) => r.items), ctx.me.id) : null,
    h("p", { class: "hint", id: "message-body-hint" }, "A mention of @handle adds that member to whom it reaches and tells them; "
      + "at most 10 members per message."),
    h("div", { class: "actions" }, send),
    status.el);

    append(root, h("h2", null, "Message the project"),
      h("p", { class: "muted" }, "Everyone it is addressed to reads it in the project's feed; the agents get it through their wait. "
        + "Status is not a message: the board shows it."),
      form, result);
    // Once the router has put the view into the page.
    window.setTimeout(() => body.focus(), 0);
  };
})(window.Maity);
