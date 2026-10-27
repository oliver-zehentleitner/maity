// (11) Messages (#/p/<slug>/messages): the project's messages the reader
// may see (docs/api.md §8.4, every type but chat), newest first, by type:
// who wrote to whom, about which card, the text as Markdown, the members
// it mentions as links, and its files (§8.7). The uploader or an admin
// deletes a file; an admin removes a message (§8.5). The hub has no
// message listing yet (§8.8 is in the contract): the view reads the
// project's latest events with wait=0, page by page, and keeps the
// messages; new ones, removals and deleted files arrive with the
// project's feed and change the list in place.
//
// No removed message is shown while the view reads /events: a removed
// chat message looks the same there as a removed project message (§8.5
// replaces the whole payload), and §8.8 lists only the latter.
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
  // How far back the view reads: the project's latest events, said when cut.
  const WINDOW = 5000;
  const MAX_PAGES = Math.ceil(WINDOW / PAGE) + 1;

  // A project message that is still there; a removed one is never kept.
  const isMessage = (e) => e.kind === "message" && !e.redacted && e.payload && e.payload.type !== "chat";

  function toWords(ctx, to) {
    if (to === "all") return "everyone";
    if (/^role:/.test(to || "")) return "every " + to.slice(5);
    return M.dom.memberRef(ctx, to);
  }

  // The latest WINDOW events from the head, oldest first; stops when the
  // view was left, and fails loud on a cursor that does not move.
  async function scan(ctx, stillHere) {
    const head = (await M.api.get(ctx.base + "/events?after=latest&wait=0")).cursor;
    const start = Math.max(0, head - WINDOW);
    const kept = [];
    let after = start;
    for (let n = 0; n < MAX_PAGES; n++) {
      if (!stillHere()) return null;
      const page = await M.api.get(ctx.base + "/events?after=" + after + "&wait=0&limit=" + PAGE);
      kept.push(...page.items.filter(isMessage));
      if (page.items.length < PAGE) return { kept, cut: start > 0 };
      const next = page.items[page.items.length - 1].seq;
      if (!(next > after)) throw new Error("the hub's event cursor did not move past " + after);
      after = next;
    }
    return { kept, cut: true };
  }

  M.views.messages = async function (ctx, root) {
    const here = window.location.hash;
    const read = await scan(ctx, () => window.location.hash === here);
    if (!read) return;
    const all = read.kept;
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    let filter = "";
    const list = h("ol", { class: "project-messages" });
    const shows = (e) => !filter || e.payload.type === filter;
    const itemOf = (seq) => Array.from(list.querySelectorAll("li.pmsg")).find((li) => li.getAttribute("data-seq") === String(seq));
    const empty = () => h("li", { class: "empty muted" }, filter ? "No message of this type." : "No project messages yet.");
    const fillEmpty = () => {
      const blank = list.querySelector("li.empty");
      const any = list.querySelector("li.pmsg");
      if (any && blank) list.removeChild(blank);
      if (!any && !blank) append(list, empty());
    };

    // Gone from the list: removed here or by someone else.
    function drop(seq) {
      const i = all.findIndex((x) => x.seq === seq);
      if (i >= 0) all.splice(i, 1);
      const li = itemOf(seq);
      if (li) list.removeChild(li);
      fillEmpty();
    }

    async function remove(e) {
      const reason = M.chatParts.askReason("Remove this message for everyone who can read it? Its text and files are replaced by a note. Say why:");
      if (reason === null) return;
      status.busy("Removing…");
      try {
        await M.api.post(ctx.base + "/events/" + encodeURIComponent(e.seq) + "/redact", { reason });
      } catch (err) {
        status.fail("Not removed: ", err);
        return;
      }
      drop(e.seq);
      status.done();
      append(status.el, h("span", { class: "ok" }, "Removed."));
      status.el.focus();
    }

    function item(e) {
      const p = e.payload;
      const from = e.actor && e.actor.member_id;
      // The file's uploader is the message's sender; an admin deletes any (§8.7).
      const canDelete = () => from === ctx.me.id || ctx.canAdmin;
      return h("li", { class: "pmsg type-" + p.type, "data-seq": String(e.seq) },
        h("div", { class: "pmsg-head" },
          h("span", { class: "badge" }, TYPE_WORDS[p.type] || p.type),
          h("span", null, " ", M.dom.memberRef(ctx, from, { instance: e.actor }), " to ", toWords(ctx, p.to)),
          p.task_id ? [" · ", h("a", { href: ctx.link("tasks", p.task_id) }, p.task_id)] : null,
          " · ", h("span", { class: "muted" }, formatTime(e.at))),
        p.body ? h("div", { class: "md" }, M.markdown(p.body, M.ids.where(ctx))) : null,
        (p.mentions || []).length
          ? h("p", { class: "muted pmsg-mentions" }, "Mentions: ",
            [...new Map(p.mentions.map((x) => [x.member_id, x])).values()].map((x, i) => [i ? ", " : null,
              h("a", { href: ctx.link("members", x.member_id) }, "@" + M.dom.handleOf(ctx, { kind: x.name ? "agent" : "human", handle: x.handle, name: x.name }))]))
          : null,
        M.attachments ? M.attachments.render(ctx, { attachments: p.attachments, body: p.body || "" }, canDelete) : null,
        ctx.canAdmin ? h("div", { class: "actions" },
          h("button", { type: "button", class: "small", "aria-label": "Remove this message for everyone", onclick: () => remove(e) }, "Remove")) : null);
    }

    // The whole list, only when the filter changes; the feed patches it.
    function draw() {
      clear(list);
      all.filter(shows).slice().reverse().forEach((e) => append(list, item(e)));
      fillEmpty();
    }

    ctx.onEvents((events) => {
      let added = 0;
      events.forEach((e) => {
        if (isMessage(e) && !all.some((x) => x.seq === e.seq)) {
          all.push(e);
          if (shows(e)) { list.insertBefore(item(e), list.firstChild); added += 1; }
        }
        if (e.kind === "event_redacted" && e.payload) drop(e.payload.seq);
        if (e.kind === "attachment_deleted" && e.payload) {
          // Kept on the message, so a later redraw shows it removed too.
          all.forEach((x) => (x.payload.attachments || []).forEach((a) => { if (a.id === e.payload.attachment_id) a.removed = true; }));
          M.attachments.markDeleted(list, e.payload.attachment_id);
        }
      });
      if (added) {
        fillEmpty();
        status.done();
        append(status.el, h("span", null, added === 1 ? "1 new message." : added + " new messages."));
      }
    });

    const pick = h("select", { id: "messages-type", onchange: (ev) => { filter = ev.target.value; draw(); } },
      h("option", { value: "" }, "every type"), TYPES.map(([v, l]) => h("option", { value: v }, l)));
    append(root,
      h("div", { class: "toolbar" }, h("h2", null, "Messages"), h("a", { class: "button small", href: ctx.link("message") }, "Message the project")),
      h("p", { class: "muted" }, "The project's messages you can read, newest first. Chats are in Chat."),
      read.cut ? h("p", { class: "muted pmsg-cut" }, "Only the messages among the project's latest " + WINDOW + " events are shown; older ones are not read here.") : null,
      h("form", { class: "board-filter", role: "search", onsubmit: (ev) => ev.preventDefault() },
        h("label", { for: "messages-type" }, "Type"), pick),
      status.el, list);
    draw();
  };
})(window.Maity);
