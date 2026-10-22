// Group chats (docs/api.md §9.2), in the chat view's two panes: creating
// one, and the open chat — its people and who reads along, the history
// before one joined on demand, writing, removing a message (§8.5), and
// for the creator or an admin renaming it and adding or removing people.
// An agent's owner who is not in the chat reads along and writes nothing.
// Messages are drawn as in a direct chat (js/chat.js, M.chatParts).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const MAX_PEOPLE = 12;
  const EARLIER_PAGE = 50;
  const CLOSED_STATES = ["accepted", "archived"];

  // The hub's refusals, in words.
  const REFUSED = {
    too_few: "a group chat needs at least one other participant",
    too_many: "a group chat has at most twelve participants, you included",
    not_a_member: "someone chosen is not a member of this project",
    use_direct: "that is your direct chat with your agent",
  };
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    const why = fields && (fields.participants || fields.member_id);
    if (why) return { message: REFUSED[why] || why };
    if (err.code === "project_closed") return { message: "the project is closed: no new group chats and no one added" };
    if (err.code === "conversation_closed") return { message: "the chat is closed: no human is in it any more" };
    if (err.code === "conversation_quota") return { message: "this project has as many open group chats as the hub allows" };
    if (err.code === "forbidden" && err.details && err.details.reason === "observer") return { message: "you read along as an agent's owner and do not write here" };
    return err;
  }

  const nameOf = (ctx, id) => (ctx.nameOf ? ctx.nameOf(id) : id);

  // ---- creating ----------------------------------------------------------

  function create(ctx, layout, list) {
    const pane = h("section", { class: "chat-pane group-new", "aria-label": "New group chat" });
    append(layout, pane);
    const back = h("a", { class: "chat-back", href: ctx.link("chat") }, "← Conversations");
    const heading = h("h2", { tabindex: "-1" }, "New group chat");
    if (CLOSED_STATES.includes(ctx.project.state)) {
      append(pane, back, heading, h("p", { class: "muted" }, "The project is closed: it takes no new group chat."));
      return;
    }
    const status = M.statusLine();
    const title = h("input", { id: "group-title", maxlength: "200", autocomplete: "off", placeholder: "What it is about" });
    const others = ctx.members.filter((m) => m.id !== ctx.me.id && !m.removed_at);
    const boxes = others.map((m) => {
      const box = h("input", { type: "checkbox", id: "group-member-" + m.id, value: m.id });
      const owner = m.kind === "agent" ? (m.owner_id === ctx.me.id ? "your agent" : "agent of " + nameOf(ctx, m.owner_id)) : "human";
      return { m, box, el: h("label", { class: "check", for: box.id }, box, " " + m.display_name, h("span", { class: "muted" }, " @" + m.handle + " · " + owner)) };
    });
    const error = h("p", { class: "field-error", id: "group-people-error", role: "alert" });
    const send = h("button", { type: "submit" }, "Create");
    const form = h("form", {
      class: "project-form group-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        error.textContent = "";
        const chosen = boxes.filter((b) => b.box.checked).map((b) => b.m);
        // As the hub counts (§9.2): you and two to eleven others.
        if (!chosen.length) { error.textContent = "Choose at least one other participant."; return; }
        if (chosen.length + 1 > MAX_PEOPLE) { error.textContent = "At most twelve participants, you included."; return; }
        if (chosen.length === 1 && chosen[0].kind === "agent" && chosen[0].owner_id === ctx.me.id) {
          append(clear(error), "That is your direct chat with " + chosen[0].display_name + ": ",
            h("a", { href: ctx.link("chat", chosen[0].id) }, "open it"), ".");
          return;
        }
        send.disabled = true;
        status.busy("Creating…");
        try {
          const created = await M.api.post(ctx.base + "/conversations",
            { title: title.value.trim() || null, participants: chosen.map((m) => m.id) });
          status.done();
          window.location.hash = ctx.link("chat", created.id);
        } catch (err) {
          status.fail("Not created: ", said(err));
        } finally {
          send.disabled = false;
        }
      },
    },
    h("label", { for: "group-title" }, "Title (optional)"), title,
    h("p", { class: "hint" }, "Without one, the chat is named after its participants."),
    h("fieldset", { class: "group-people", "aria-describedby": "group-people-error group-people-hint" },
      h("legend", null, "Participants"), boxes.map((b) => b.el)),
    h("p", { class: "hint", id: "group-people-hint" }, "Agents read a group chat when they resume and answer when mentioned (@handle). "
      + "Their owners read along, also when they are not in the chat."),
    error,
    h("div", { class: "actions" }, send),
    status.el);
    append(pane, back, heading, form);
    window.setTimeout(() => heading.focus(), 0);
    if (list) list.refresh(false);
  }

  // ---- the open chat -----------------------------------------------------

  async function open(ctx, root, layout, list, item, parts) {
    const id = item.id;
    const base = ctx.base + "/conversations/" + encodeURIComponent(id);
    const path = base + "/messages";
    // The view changes in place (a rename, someone added); a change of the
    // caller's access or of closed draws the whole chat again.
    let view = await M.api.get(base);
    const unreadBefore = item.unread || 0;
    const observer = view.access === "observer";
    const closed = !!view.closed_at;
    const projectClosed = CLOSED_STATES.includes(ctx.project.state);
    const inChat = (memberId) => view.participants.some((p) => p.member_id === memberId);
    const manager = () => !observer && !closed && (view.created_by === ctx.me.id || ctx.canAdmin || ctx.isOwner);
    const titleOf = () => view.title || view.participants.filter((p) => p.member_id !== ctx.me.id).map((p) => nameOf(ctx, p.member_id)).join(", ") || "Group chat";
    // An observer outside the project is not in the member list: said so, not by id.
    const observerName = (o) => (ctx.memberById && ctx.memberById[o] ? nameOf(ctx, o) : "an owner outside the project");

    const pane = h("section", { class: "chat-pane group-chat", "aria-label": "Group chat " + titleOf() });
    append(layout, pane);
    const pollStatus = M.statusLine();
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");

    // The window: from this participant's latest join on (§9.2), read to its end.
    const first = await M.api.get(path + "?limit=" + parts.HISTORY_PAGE);
    const all = first.items.slice();
    let earlier = first.earlier === undefined ? null : first.earlier;
    for (let page = first; page.items.length === parts.HISTORY_PAGE;) {
      page = await M.api.get(path + "?after=" + encodeURIComponent(page.items[page.items.length - 1].seq) + "&limit=" + parts.HISTORY_PAGE);
      all.push(...page.items);
    }
    let cursor = all.length ? all[all.length - 1].seq : (first.cursor || 0);
    await list.refresh(false);
    const theirs = all.filter((m) => m.from !== ctx.me.id);
    const firstUnread = !observer && unreadBefore && theirs.length >= unreadBefore ? theirs[theirs.length - unreadBefore].seq : null;

    // A human in the room removes a message for everyone (§8.5); never an
    // observer, and no agent uses this page.
    const mayRedact = !observer;
    async function redact(msg) {
      // The hub needs a reason (§8.5): asked again until one is given, or cancelled.
      let reason = window.prompt("Remove this message for everyone in the chat? Its text is replaced by a note. Say why:", "");
      while (reason !== null && !reason.trim()) reason = window.prompt("A reason is needed to remove a message. Say why, or cancel:", "");
      if (reason === null) return;
      status.busy("Removing…");
      try {
        await M.api.post(ctx.base + "/events/" + encodeURIComponent(msg.seq) + "/redact", { reason: reason.trim() });
        // The answer is the event (§8.5); the message shows its tombstone.
        const at = all.findIndex((m) => m.seq === msg.seq);
        if (at >= 0) all[at] = Object.assign({}, all[at], { body: null, redacted: true, redaction: { by: ctx.me.id, reason: reason.trim() } });
        redraw();
        status.done();
        append(status.el, h("span", { class: "ok" }, "Removed."));
      } catch (err) {
        status.fail("Not removed: ", err.code === "forbidden" ? { message: "only a human in the chat removes a message" } : err);
      }
    }

    function quote(msg) {
      if (!text) return;
      text.value = parts.quoteOf(ctx, msg) + text.value;
      parts.drafts.set(key, text.value);
      text.focus();
    }
    const opts = { group: true, onRedact: mayRedact ? redact : null };
    const messages = h("ol", { class: "messages", "aria-live": "polite" });
    let draw = null;
    // Drawn as one timeline (days, groups, the unread line); the earlier part
    // put before it means drawing it again.
    function redraw() {
      draw = parts.timeline(ctx, new Map(), firstUnread, observer || closed ? null : quote, opts);
      clear(messages);
      if (!all.length) {
        append(messages, h("li", { class: "empty" }, h("p", null, earlier === null ? "No messages yet." : "Nothing new since you joined."),
          h("p", { class: "muted" }, earlier === null ? "The agents in it read it when they resume, and answer when mentioned."
            : "What was said before is there with Show earlier messages.")));
      } else {
        all.forEach((m) => append(messages, draw(m)));
      }
    }
    redraw();

    // What was said before one joined: read on demand, nothing marked (§9.2).
    const earlierBox = h("div", { class: "earlier" });
    function drawEarlier() {
      clear(earlierBox);
      if (earlier === null) return;
      append(earlierBox, h("button", {
        type: "button", class: "small",
        onclick: async (e) => {
          const button = e.target;
          button.disabled = true;
          try {
            const page = await M.api.get(path + "?before=" + encodeURIComponent(earlier) + "&limit=" + EARLIER_PAGE);
            all.unshift(...page.items.filter((m) => !all.some((x) => x.seq === m.seq)));
            earlier = page.earlier === undefined ? null : page.earlier;
            redraw();
            drawEarlier();
            const again = earlierBox.querySelector("button");
            (again || messages).focus();
          } catch (err) {
            button.disabled = false;
            pollStatus.fail("The earlier messages could not be read: ", err);
          }
        },
      }, "Show earlier messages"));
    }
    drawEarlier();

    function add(msg) {
      if (all.some((m) => m.seq === msg.seq)) return;
      const follow = msg.from === ctx.me.id || parts.atBottom(messages);
      all.push(msg);
      const empty = messages.querySelector(".empty");
      if (empty) { redraw(); } else { append(messages, draw(msg)); }
      if (follow) messages.scrollTop = messages.scrollHeight;
      if (msg.seq > cursor) cursor = msg.seq;
    }

    // A message of this chat fetches what is new; a change of the chat
    // (people, title) is drawn in place; a removal takes the text out.
    ctx.onEvents(async (events) => {
      if (events.some((e) => /^conversation_/.test(e.kind) && ((e.subject && e.subject.id === id) || (e.payload && e.payload.id === id)))) {
        refreshView();
      }
      const removedHere = events.filter((e) => e.kind === "event_redacted" && e.payload && all.some((m) => m.seq === e.payload.seq));
      if (removedHere.length) {
        removedHere.forEach((e) => {
          const at = all.findIndex((m) => m.seq === e.payload.seq);
          all[at] = Object.assign({}, all[at], { body: null, redacted: true, redaction: { by: e.actor && e.actor.member_id, reason: e.payload.reason } });
        });
        const top = messages.scrollTop;
        redraw();
        messages.scrollTop = top;
      }
      if (!events.some((e) => e.kind === "message" && e.payload && e.payload.conversation_id === id)) return;
      try {
        const fresh = await M.api.get(path + "?after=" + encodeURIComponent(cursor));
        fresh.items.forEach(add);
        pollStatus.done();
        list.refresh(false);
      } catch (err) {
        pollStatus.fail("New messages could not be fetched: ", err);
      }
    });

    // Who is in it, and who else reads it (§9.2: shown in the chat itself).
    const people = () => h("p", { class: "muted group-people-line" }, "In it: ",
      view.participants.map((p, i) => [i ? ", " : null, nameOf(ctx, p.member_id), p.kind === "agent" ? " (agent)" : null]));
    const observers = () => ((view.observers || []).length
      ? h("p", { class: "muted group-observers" }, "Also read by: ",
        view.observers.map((o, i) => [i ? ", " : null, observerName(o),
          " (owner of " + view.participants.filter((p) => p.owner_id === o).map((p) => nameOf(ctx, p.member_id)).join(", ") + ")"]),
        ". They read every message and write nothing.")
      : null);

    // Managing: rename, add, remove; anyone in it leaves. The disclosure
    // stays open across a redraw of the head.
    let manageOpen = false;
    let renameDraft = null;
    function manage() {
      if (observer || closed) return null;
      const box = h("details", { class: "group-manage" }, h("summary", null, manager() ? "Manage this chat" : "Leave this chat"));
      if (manageOpen) box.setAttribute("open", "");
      box.addEventListener("toggle", () => { manageOpen = box.hasAttribute ? box.hasAttribute("open") : manageOpen; });
      // A change is drawn in place; the status line says what happened and has the focus.
      const act = async (label, done, call, after) => {
        status.busy(label + "…");
        try {
          await call();
        } catch (err) {
          status.fail(label + " failed: ", said(err));
          return;
        }
        if (after) { after(); return; }
        await refreshView();
        status.done();
        append(status.el, h("span", { class: "ok" }, done));
        status.el.focus();
      };
      if (manager()) {
        const name = h("input", { id: "group-rename", maxlength: "200", autocomplete: "off" });
        // A title being typed survives someone else's change of the chat.
        name.value = renameDraft !== null ? renameDraft : view.title || "";
        name.addEventListener("input", () => { renameDraft = name.value; });
        append(box, h("form", { class: "inline-form", onsubmit: (e) => {
          e.preventDefault();
          const typed = name.value.trim() || null;
          act("Renaming", "Renamed.", () => M.api.patch(base, { title: typed }).then(() => { renameDraft = null; }));
        } }, h("label", { for: "group-rename" }, "Title"), name, h("button", { type: "submit", class: "small" }, "Rename")));
        const free = ctx.members.filter((m) => !inChat(m.id) && !m.removed_at);
        if (projectClosed) {
          append(box, h("p", { class: "muted" }, "The project is closed: no one can be added."));
        } else if (free.length && view.participants.length < MAX_PEOPLE) {
          const pick = h("select", { id: "group-add" }, free.map((m) => h("option", { value: m.id }, m.display_name + " @" + m.handle)));
          pick.value = free[0].id;
          append(box, h("form", { class: "inline-form", onsubmit: (e) => {
            e.preventDefault();
            const who = free.find((m) => m.id === pick.value);
            act("Adding", who.display_name + " is in the chat.", () => M.api.post(base + "/participants", { member_id: pick.value }));
          } }, h("label", { for: "group-add" }, "Add"), pick, h("button", { type: "submit", class: "small" }, "Add")),
          h("p", { class: "hint" }, "Someone added starts with what is said from then on, and can read what came before with Show earlier messages. "
            + "Write here as for everyone who is or will be in the chat."));
        }
        append(box, h("ul", { class: "group-members" }, view.participants.filter((p) => p.member_id !== ctx.me.id).map((p) =>
          h("li", null, nameOf(ctx, p.member_id), " ", h("button", { type: "button", class: "small", "aria-label": "Remove " + nameOf(ctx, p.member_id) + " from the chat", onclick: () => {
            if (!window.confirm("Remove " + nameOf(ctx, p.member_id) + " from this chat? They no longer read it.")) return;
            act("Removing", nameOf(ctx, p.member_id) + " is no longer in the chat.", () => M.api.del(base + "/participants/" + encodeURIComponent(p.member_id)));
          } }, "Remove")))));
      }
      const lastHuman = view.participants.filter((p) => p.kind === "human").length === 1;
      append(box, h("button", { type: "button", class: "danger", onclick: () => {
        const what = lastHuman ? " You are its last human: it closes, and no one writes in it any more." : "";
        if (!window.confirm("Leave this chat?" + what)) return;
        act("Leaving", "You left the chat.", () => M.api.del(base + "/participants/" + encodeURIComponent(ctx.me.id)),
          () => { window.location.hash = ctx.link("chat"); });
      } }, "Leave the chat"));
      return box;
    }

    // Writing: a participant of an open chat. A mention reaches only
    // someone in it (§8.6); the hint says when a handle is not.
    const key = ctx.slug + "/" + id;
    let text = null;
    let compose = null;
    let hintMention = () => {};
    if (observer) {
      compose = h("p", { class: "muted group-readonly" }, "You read along as the owner of an agent in this chat. You do not write here.");
    } else if (closed) {
      compose = h("p", { class: "muted group-readonly" }, "This chat is closed: no human is in it any more. It stays readable.");
    } else {
      text = h("textarea", { id: "chat-text", rows: "3", placeholder: "Message to everyone in the chat" });
      text.value = parts.drafts.get(key) || "";
      const hint = h("p", { class: "hint mention-hint", "aria-live": "polite", hidden: true });
      const MENTIONED = /(^|[^A-Za-z0-9_.@/+-])@([a-z0-9-]*[a-z0-9])(?![A-Za-z0-9_])/g;
      // Read from the view each time: someone added in place is reachable at once.
      hintMention = () => {
        const handles = new Set(view.participants.map((p) => p.handle));
        const outside = [...parts.withoutCode(text.value).matchAll(MENTIONED)].map((x) => x[2]).filter((hd) => !handles.has(hd));
        clear(hint);
        hint.hidden = !outside.length;
        if (outside.length) append(hint, "@" + outside[0] + " is not in this chat: it reaches nobody.");
      };
      text.addEventListener("input", () => {
        if (text.value.trim()) parts.drafts.set(key, text.value); else parts.drafts.delete(key);
        hintMention();
      });
      hintMention();
      const button = h("button", { type: "submit" }, "Send");
      const sendIt = async (e) => {
        e.preventDefault();
        const body = text.value.trim();
        if (!body) { text.focus(); return; }
        button.disabled = true;
        status.busy("Sending…");
        try {
          add(await M.api.post(path, { body }));
          text.value = "";
          parts.drafts.delete(key);
          hintMention();
          status.done();
          list.refresh(false);
        } catch (err) {
          status.fail("Not sent: ", said(err));
        } finally {
          button.disabled = false;
        }
      };
      text.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendIt(e); });
      compose = h("form", { class: "compose", onsubmit: sendIt },
        h("label", { for: "chat-text" }, "Message (Ctrl+Enter sends; @handle reaches someone in the chat)"),
        text, hint, button);
    }

    const heading = h("h2", { class: "group-title", tabindex: "-1" }, titleOf());
    const head = h("div", { class: "group-head" });
    // The head drawn again keeps the focus on the same field, and the
    // mention hint follows the people now in the chat.
    function drawHead() {
      const had = document.activeElement && head.contains(document.activeElement) ? document.activeElement.id : null;
      heading.textContent = titleOf();
      pane.setAttribute("aria-label", "Group chat " + titleOf());
      append(clear(head), people(), observers(), manage());
      const again = had && Array.from(head.querySelectorAll("input, select, button")).find((e) => e.id === had);
      if (again) again.focus();
      hintMention();
    }
    // The chat as the hub has it now, drawn in place; access or closed
    // changed (removed, the chat closed) means the whole view again.
    async function refreshView() {
      let fresh;
      try {
        fresh = await M.api.get(base);
      } catch (err) {
        if (err.status === 404) { ctx.refresh(); return; }
        pollStatus.fail("The chat could not be read again: ", err);
        return;
      }
      if (fresh.access !== view.access || !!fresh.closed_at !== closed) { ctx.refresh(); return; }
      view = fresh;
      drawHead();
    }
    drawHead();
    append(pane,
      h("a", { class: "chat-back", href: ctx.link("chat") }, "← Conversations"),
      h("div", { class: "toolbar" }, heading, closed ? h("span", { class: "flag" }, "closed") : null),
      head,
      earlierBox,
      messages,
      pollStatus.el,
      compose,
      status.el);
    window.setTimeout(() => {
      parts.fitToScreen(layout);
      messages.scrollTop = messages.scrollHeight;
      if (window.matchMedia && window.matchMedia("(max-width: 720px)").matches) heading.focus();
    }, 0);
    // An observer is in no audience (§9.2): its view re-reads what is new.
    if (observer) {
      ctx.every(30000, async () => {
        try {
          const fresh = await M.api.get(path + "?after=" + encodeURIComponent(cursor));
          fresh.items.forEach(add);
          pollStatus.done();
        } catch (err) {
          pollStatus.fail("New messages could not be fetched: ", err);
        }
      });
    }
  }

  M.groupChat = { create, open };
})(window.Maity);
