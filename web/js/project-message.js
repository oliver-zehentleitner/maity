// Message the project (/<owner>/<slug>/message): a message to everyone, a role
// or one member (docs/api.md §8.4), of one of the hub's types, optionally
// about a card. Its body is scanned by the hub: a mention draws the member
// into the message's audience and pings them (§8.6); the dashboard never
// sends a mentions list. Opened from the Chat tab and the Messages view,
// and with an @name already in it from a chat, where a mention notifies
// nobody.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // No review_result: it carries its verdict, head and cites (§8.4), which
  // come from the CLI's --review-file (context/views.md).
  const TYPES = [
    ["notice", () => M.t("projectmessage.type.notice")],
    ["handover", () => M.t("projectmessage.type.handover")],
    ["blocker", () => M.t("projectmessage.type.blocker")],
    ["go_request", () => M.t("projectmessage.type.go_request")],
    ["interface_change", () => M.t("projectmessage.type.interface_change")],
  ];
  const CLOSED = new Set(["done", "cancelled"]);
  const BODY_CHARS = 16 * 1024;

  // The hub's refusals, in words.
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields && fields.body === "too_many_mentions") return { message: M.t("projectmessage.refused.too_many_mentions", { members: 10, mentions: 50 }) };
    if (err.code === "rate_limited") return { message: M.t("projectmessage.refused.rate_limited") };
    if (fields && fields.to) return { message: M.t("projectmessage.refused.to") };
    return err;
  }

  M.views.message = async function (ctx, root, args) {
    const tasks = await M.api.getAll(ctx.base + "/tasks?status=proposed,open,in_progress,blocked,review").catch(() => ({ items: [] }));
    const others = ctx.members.filter((m) => m.id !== ctx.me.id);
    const to = h("select", { id: "message-to" },
      h("option", { value: "all" }, M.t("projectmessage.to.all")),
      // §8.4: trust:owner, trust:admin or a role (§2.3).
      h("optgroup", { label: M.t("projectmessage.to.trust") },
        h("option", { value: "trust:owner" }, M.t("projectmessage.to.trust_owner")),
        h("option", { value: "trust:admin" }, M.t("projectmessage.to.trust_admin"))),
      h("optgroup", { label: M.t("projectmessage.to.role") }, M.trust.ROLES.map((r) => h("option", { value: "role:" + r }, M.t("projectmessage.to.every_role", { role: M.trust.roleLabel(r).toLowerCase() })))),
      h("optgroup", { label: M.t("projectmessage.to.member") }, others.map((m) => h("option", { value: m.id }, M.t("projectmessage.to.member_option", { name: m.display_name, handle: M.dom.handleOf(ctx, m) })))));
    to.value = "all";
    const type = h("select", { id: "message-type" }, TYPES.map(([v, l]) => h("option", { value: v }, l())));
    type.value = "notice";
    const card = h("select", { id: "message-card" }, h("option", { value: "" }, M.t("projectmessage.no_card")),
      tasks.items.filter((t) => !CLOSED.has(t.status)).map((t) => h("option", { value: t.id }, t.id + " · " + t.title)));
    card.value = "";
    const body = M.dom.sendOnCtrlEnter(h("textarea", { id: "message-body", rows: "6", placeholder: M.t("projectmessage.body.placeholder"),
      "aria-describedby": "message-body-hint" }));
    // A prefilled @name from a chat (args[0]), as text, never markup.
    if (args && args[0]) body.value = args[0] + " ";
    const status = M.statusLine();
    const send = h("button", { type: "submit" }, M.t("projectmessage.send"));
    // Files go with the message (§8.7): a message with files may have no text.
    const files = M.attachments ? M.attachments.picker(ctx, "message") : null;
    const result = h("div", { class: "message-result", "aria-live": "polite" });

    const form = h("form", {
      class: "project-form message-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const text = body.value.trim();
        const ids = files ? files.ids() : [];
        if (!text && !ids.length) { status.fail(M.t("projectmessage.not_sent"), { message: M.t("projectmessage.empty") }); body.focus(); return; }
        if (files && files.busy()) { status.fail(M.t("projectmessage.not_sent"), { message: M.t("projectmessage.uploading") }); return; }
        if ([...text].length > BODY_CHARS) { status.fail(M.t("projectmessage.not_sent"), { message: M.t("projectmessage.too_long", { max: BODY_CHARS }) }); body.focus(); return; }
        // What is sent is what the confirmation speaks of: the fields are
        // held while it is on its way, so nothing typed meanwhile is lost.
        const message = { kind: "message", type: type.value, to: to.value, body: text };
        if (card.value) message.task_id = card.value;
        if (ids.length) message.attachments = ids;
        const fields = [to, type, card, body, send];
        fields.forEach((f) => { f.disabled = true; });
        status.busy(M.t("projectmessage.sending"));
        try {
          const event = await M.api.post(ctx.base + "/events", message);
          const mentioned = ((event.payload && event.payload.mentions) || []).map((x) => ctx.nameOf(x.member_id));
          if (body.value.trim() === text) body.value = "";
          if (files) files.clear(ids);
          status.done();
          const whom = message.to === "all" ? M.t("projectmessage.sent.everyone") : /^(role|trust):/.test(message.to) ? M.trust.tokenWords(message.to) : ctx.nameOf(message.to);
          append(clear(result), h("p", { class: "ok" }, mentioned.length
            ? M.t("projectmessage.sent.mentioned", { whom, names: M.fmt.list([...new Set(mentioned)]) })
            : M.t("projectmessage.sent", { whom })));
        } catch (err) {
          status.fail(M.t("projectmessage.not_sent"), said(err));
        } finally {
          fields.forEach((f) => { f.disabled = false; });
          body.focus();
        }
      },
    },
    h("label", { for: "message-to" }, M.t("projectmessage.label.to")), to,
    h("label", { for: "message-type" }, M.t("projectmessage.label.type")), type,
    h("label", { for: "message-card" }, M.t("projectmessage.label.card")), card,
    h("label", { for: "message-body" }, M.t("projectmessage.label.body", { keys: M.dom.SEND_KEYS })), body,
    // With the @ picker; the hub resolves, not the page.
    M.projectMentionPicker(ctx, body),
    h("p", { class: "hint", id: "message-body-hint" }, M.t("projectmessage.body.hint", { members: 10 })),
    files ? files.el : null,
    h("div", { class: "actions" }, send),
    status.el);

    append(root, h("h2", null, M.t("projectmessage.title")),
      h("p", { class: "muted" }, M.t("projectmessage.intro")),
      form, result);
    // Once the router has put the view into the page.
    window.setTimeout(() => body.focus(), 0);
    // Leaving the page with an unsent message asks first; going to another
    // view of the dashboard keeps nothing, so the hint says so.
    const unsent = (e) => {
      if (!body.isConnected && body.isConnected !== undefined) { window.removeEventListener("beforeunload", unsent); return; }
      if (body.value.trim()) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", unsent);
  };
})(window.Maity);
