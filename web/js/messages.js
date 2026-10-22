// (11) Messages (#/p/<slug>/messages): the project's messages the reader
// may see (docs/api.md §8.4, every type but chat), newest first, by type:
// who wrote to whom, about which card, the text as Markdown, the members
// it mentions as links, and its files (§8.7). The uploader or an admin
// deletes a file; an admin removes a message (§8.5). There is no message
// listing in the contract: the view reads the project's events from the
// start with wait=0, page by page, and keeps the messages; new ones and
// removals arrive with the project's feed.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const TYPES = [
    ["notice", "Notice"], ["handover", "Handover"], ["blocker", "Blocker"], ["go_request", "Asks for a go"],
    ["review_result", "Review result"], ["interface_change", "Interface change"],
  ];
  const TYPE_WORDS = Object.fromEntries(TYPES);
  const PAGE = 200;

  // A project message, or a removed one (whose payload says nothing more).
  const isMessage = (e) => e.kind === "message" && (e.redacted || (e.payload && e.payload.type !== "chat"));

  function toWords(ctx, to) {
    if (to === "all") return "everyone";
    if (/^role:/.test(to || "")) return "every " + to.slice(5);
    return ctx.nameOf(to);
  }

  M.views.messages = async function (ctx, root) {
    const all = [];
    for (let after = 0; ;) {
      const page = await M.api.get(ctx.base + "/events?after=" + after + "&wait=0&limit=" + PAGE);
      all.push(...page.items.filter(isMessage));
      if (page.items.length < PAGE) break;
      after = page.items[page.items.length - 1].seq;
    }
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    let filter = "";
    const list = h("ol", { class: "project-messages", "aria-live": "polite" });

    async function remove(e) {
      const reason = M.chatParts.askReason("Remove this message for everyone who can read it? Its text and files are replaced by a note. Say why:");
      if (reason === null) return;
      status.busy("Removing…");
      try {
        await M.api.post(ctx.base + "/events/" + encodeURIComponent(e.seq) + "/redact", { reason });
        Object.assign(e, { redacted: true, payload: { redacted: true, reason, by: ctx.me.id } });
        draw();
        status.done();
        append(status.el, h("span", { class: "ok" }, "Removed."));
        status.el.focus();
      } catch (err) {
        status.fail("Not removed: ", err);
      }
    }

    function item(e) {
      const p = e.payload || {};
      const from = e.actor && e.actor.member_id;
      const when = h("span", { class: "muted" }, formatTime(e.at));
      if (e.redacted) {
        return h("li", { class: "pmsg removed", "data-seq": String(e.seq) },
          h("p", { class: "muted msg-redacted" }, "A message was removed" + (p.by ? " by " + ctx.nameOf(p.by) : "") + (p.reason ? ": " + p.reason : "") + "."), when);
      }
      // The file's uploader is the message's sender; an admin deletes any (§8.7).
      const canDelete = () => from === ctx.me.id || ctx.canAdmin;
      return h("li", { class: "pmsg type-" + p.type, "data-seq": String(e.seq) },
        h("div", { class: "pmsg-head" },
          h("span", { class: "badge" }, TYPE_WORDS[p.type] || p.type),
          h("span", null, " " + ctx.nameOf(from) + " to " + toWords(ctx, p.to)),
          p.task_id ? [" · ", h("a", { href: ctx.link("board") }, p.task_id)] : null,
          " · ", when),
        p.body ? h("div", { class: "md" }, M.markdown(p.body)) : null,
        (p.mentions || []).length
          ? h("p", { class: "muted pmsg-mentions" }, "Mentions: ",
            [...new Map(p.mentions.map((x) => [x.member_id, x])).values()].map((x, i) => [i ? ", " : null,
              h("a", { href: ctx.link("members", x.member_id) }, "@" + x.handle)]))
          : null,
        M.attachments ? M.attachments.render(ctx, { attachments: p.attachments, body: p.body || "" }, canDelete) : null,
        ctx.canAdmin ? h("div", { class: "actions" },
          h("button", { type: "button", class: "small", "aria-label": "Remove this message for everyone", onclick: () => remove(e) }, "Remove")) : null);
    }

    function draw() {
      clear(list);
      // A removed message has no type left: it shows only without a filter.
      const shown = all.filter((e) => !filter || (!e.redacted && e.payload && e.payload.type === filter)).slice().reverse();
      if (!shown.length) append(list, h("li", { class: "empty muted" }, filter ? "No message of this type." : "No project messages yet."));
      shown.forEach((e) => append(list, item(e)));
    }

    // New messages, removals and deleted files, from the project's feed.
    ctx.onEvents((events) => {
      let changed = false;
      events.forEach((e) => {
        if (isMessage(e) && !all.some((x) => x.seq === e.seq)) { all.push(e); changed = true; }
        if (e.kind === "event_redacted" && e.payload) {
          const x = all.find((y) => y.seq === e.payload.seq);
          if (x && !x.redacted) { Object.assign(x, { redacted: true, payload: { redacted: true, reason: e.payload.reason, by: e.actor && e.actor.member_id } }); changed = true; }
        }
        if (e.kind === "attachment_deleted" && e.payload) M.attachments.markDeleted(list, e.payload.attachment_id);
      });
      if (changed) draw();
    });

    const pick = h("select", { id: "messages-type", onchange: (ev) => { filter = ev.target.value; draw(); } },
      h("option", { value: "" }, "every type"), TYPES.map(([v, l]) => h("option", { value: v }, l)));
    append(root,
      h("div", { class: "toolbar" }, h("h2", null, "Messages"), h("a", { class: "button small", href: ctx.link("message") }, "Message the project")),
      h("p", { class: "muted" }, "The project's messages you can read, newest first. Chats are in Chat."),
      h("form", { class: "board-filter", role: "search", onsubmit: (ev) => ev.preventDefault() },
        h("label", { for: "messages-type" }, "Type"), pick),
      status.el, list);
    draw();
  };
})(window.Maity);
