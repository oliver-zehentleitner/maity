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
  const CLOSED_STATES = ["archived"];

  // The hub's refusals, in words.
  // Getters: the words are the catalog's when said.
  const REFUSED = {
    get too_few() { return M.t("group.refused.too_few"); },
    get too_many() { return M.t("group.refused.too_many"); },
    get not_a_member() { return M.t("group.refused.not_a_member"); },
    get use_direct() { return M.t("group.refused.use_direct"); },
  };
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    const why = fields && (fields.participants || fields.member_id);
    if (why) return { message: Object.hasOwn(REFUSED, why) ? REFUSED[why] : why };
    if (err.code === "project_closed") return { message: M.t("group.refused.project_closed") };
    if (err.code === "conversation_closed") return { message: M.t("group.refused.chat_closed") };
    if (err.code === "conversation_quota") return { message: M.t("group.refused.quota") };
    if (err.code === "forbidden" && err.details && err.details.reason === "observer") return { message: M.t("group.refused.observer") };
    return err;
  }

  const nameOf = (ctx, id) => (ctx.nameOf ? ctx.nameOf(id) : id);

  // ---- creating ----------------------------------------------------------

  function create(ctx, layout, list) {
    const pane = h("section", { class: "chat-pane group-new", "aria-label": M.t("group.new.title") });
    append(layout, pane);
    const back = h("a", { class: "chat-back", href: ctx.link("chat") }, M.t("group.back"));
    const heading = h("h2", { tabindex: "-1" }, M.t("group.new.title"));
    if (CLOSED_STATES.includes(ctx.project.state)) {
      append(pane, back, heading, h("p", { class: "muted" }, M.t("group.new.closed")));
      return;
    }
    const status = M.statusLine();
    const title = h("input", { id: "group-title", maxlength: "200", autocomplete: "off", placeholder: M.t("group.new.title_placeholder") });
    const others = ctx.members.filter((m) => m.id !== ctx.me.id && !m.removed_at);
    // ?with=<member id> (a Chat button on Members): that person chosen.
    const asked = M.route.current().query.get("with");
    const boxes = others.map((m) => {
      const box = h("input", { type: "checkbox", id: "group-member-" + m.id, value: m.id });
      box.checked = m.id === asked;
      const owner = m.kind === "agent" ? (m.owner_id === ctx.me.id ? M.t("group.new.your_agent") : M.t("group.new.agent_of", { name: nameOf(ctx, m.owner_id) })) : M.t("group.new.human");
      return { m, box, el: h("label", { class: "check", for: box.id }, box, " " + m.display_name, h("span", { class: "muted" }, " @" + m.handle + " · " + owner)) };
    });
    const error = h("p", { class: "field-error", id: "group-people-error", role: "alert" });
    const send = h("button", { type: "submit" }, M.t("group.new.create"));
    const form = h("form", {
      class: "project-form group-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        error.textContent = "";
        const chosen = boxes.filter((b) => b.box.checked).map((b) => b.m);
        // As the hub counts (§9.2): you and two to eleven others.
        if (!chosen.length) { error.textContent = M.t("group.new.choose"); return; }
        if (chosen.length + 1 > MAX_PEOPLE) { error.textContent = M.t("group.new.too_many"); return; }
        if (chosen.length === 1 && chosen[0].kind === "agent" && chosen[0].owner_id === ctx.me.id) {
          append(clear(error), M.tn("group.new.direct", { name: chosen[0].display_name,
            link: h("a", { href: ctx.link("chat", chosen[0].id) }, M.t("group.new.open_it")) }));
          return;
        }
        send.disabled = true;
        status.busy(M.t("group.new.creating"));
        try {
          const created = await M.api.post(ctx.base + "/conversations",
            { title: title.value.trim() || null, participants: chosen.map((m) => m.id) });
          status.done();
          M.route.go(ctx.link("chat", created.id));
        } catch (err) {
          status.fail(M.t("group.new.failed"), said(err));
        } finally {
          send.disabled = false;
        }
      },
    },
    h("label", { for: "group-title" }, M.t("group.new.title_label")), title,
    h("p", { class: "hint" }, M.t("group.new.title_hint")),
    h("fieldset", { class: "group-people", "aria-describedby": "group-people-error group-people-hint" },
      h("legend", null, M.t("group.new.participants")), boxes.map((b) => b.el)),
    h("p", { class: "hint", id: "group-people-hint" }, M.t("group.new.agents_hint")),
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
    const titleOf = () => view.title || view.participants.filter((p) => p.member_id !== ctx.me.id).map((p) => nameOf(ctx, p.member_id)).join(", ") || M.t("group.untitled");
    // An observer outside the project is not in the member list: said so, not by id.
    const observerName = (o) => (o === ctx.me.id ? M.t("group.observer.you") : ctx.outsider ? M.t("group.observer.another_owner")
      : ctx.memberById && ctx.memberById[o] ? M.dom.memberRef(ctx, o) : M.t("group.observer.outside"));

    const pane = h("section", { class: "chat-pane group-chat", "aria-label": M.t("group.pane", { title: titleOf() }) });
    append(layout, pane);
    const pollStatus = M.statusLine();
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");

    // The newest page only (js/chat.js newestPage, tsk-r1adgwp0a5dr): what
    // came before it, before one joined included (§9.2), with Show earlier
    // messages or on scroll-up.
    const first = await parts.newestPage(path, item.last_message && item.last_message.seq ? item.last_message.seq + 1 : null);
    const all = first.items;
    let earlier = first.earlier;
    let cursor = first.cursor || 0;
    await list.refresh(false);
    const theirs = all.filter((m) => m.from !== ctx.me.id);
    const firstUnread = !observer && unreadBefore && theirs.length >= unreadBefore ? theirs[theirs.length - unreadBefore].seq : null;

    // A human in the room removes a message for everyone (§8.5); never an
    // observer, and no agent uses this page.
    const mayRedact = !observer;
    async function redact(msg) {
      const reason = parts.askReason(M.t("group.redact.ask"));
      if (reason === null) return;
      status.busy(M.t("group.redact.busy"));
      try {
        await M.api.post(ctx.base + "/events/" + encodeURIComponent(msg.seq) + "/redact", { reason });
        // The answer is the event (§8.5); the message shows its tombstone.
        const at = all.findIndex((m) => m.seq === msg.seq);
        if (at >= 0) all[at] = Object.assign({}, all[at], { body: null, redacted: true, redaction: { by: ctx.me.id, reason } });
        redraw();
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("group.redact.done")));
      } catch (err) {
        status.fail(M.t("group.redact.failed"), err.code === "forbidden" ? { message: M.t("group.redact.forbidden") } : err);
      }
    }

    function quote(msg) {
      if (!text) return;
      text.value = parts.quoteOf(ctx, msg) + text.value;
      parts.drafts.set(key, text.value);
      text.focus();
    }
    // A human in the chat deletes a file of it, as it removes a message (§8.7).
    const opts = { group: true, onRedact: mayRedact ? redact : null, canDeleteFile: () => mayRedact && !closed };
    const messages = h("ol", { class: "messages", "aria-live": "polite" });
    // At the newest unless the reader scrolled up; then a pill counts what came (js/chat.js).
    // Newest leaves the focus in the composer, or on the title where there is none.
    const follow = parts.follower(messages, () => (text || heading).focus());
    let draw = null;
    // Drawn as one timeline (days, groups, the unread line); the earlier part
    // put before it means drawing it again.
    function redraw() {
      draw = parts.timeline(ctx, new Map(), firstUnread, observer || closed ? null : quote, opts);
      clear(messages);
      if (!all.length) {
        append(messages, h("li", { class: "empty" }, h("p", null, earlier === null ? M.t("group.empty.none") : M.t("group.empty.nothing_new")),
          h("p", { class: "muted" }, earlier === null ? M.t("group.empty.none_hint") : M.t("group.empty.nothing_new_hint"))));
      } else {
        all.forEach((m) => append(messages, draw(m)));
      }
    }
    redraw();

    // What was said before: read on demand, nothing marked (§9.2), with the
    // button or on scroll-up near the top; the reader's place is kept.
    const earlierBox = h("div", { class: "earlier" });
    let readingOlder = false;
    async function older(focusAfter) {
      if (earlier === null || readingOlder) return;
      readingOlder = true;
      try {
        const page = await M.api.get(path + "?before=" + encodeURIComponent(earlier) + "&limit=" + EARLIER_PAGE);
        const fresh = page.items.filter((m) => !all.some((x) => x.seq === m.seq));
        earlier = page.earlier === undefined ? null : page.earlier;
        const height = messages.scrollHeight;
        const top = messages.scrollTop;
        all.unshift(...fresh);
        redraw();
        messages.scrollTop = top + (messages.scrollHeight - height);
        drawEarlier();
        if (focusAfter) { const again = earlierBox.querySelector("button"); (again || messages).focus(); }
      } catch (err) {
        const button = earlierBox.querySelector("button");
        if (button) button.disabled = false;
        pollStatus.fail(M.t("group.earlier.failed"), err);
      } finally {
        readingOlder = false;
      }
    }
    function drawEarlier() {
      clear(earlierBox);
      if (earlier === null) return;
      append(earlierBox, h("button", {
        type: "button", class: "small",
        onclick: (e) => { e.target.disabled = true; older(true); },
      }, M.t("group.earlier.show")));
    }
    drawEarlier();
    messages.addEventListener("scroll", () => { if (messages.scrollTop < parts.NEAR_TOP) older(false); });

    function add(msg) {
      if (all.some((m) => m.seq === msg.seq)) return;
      all.push(msg);
      const empty = messages.querySelector(".empty");
      if (empty) { redraw(); } else { append(messages, draw(msg)); }
      follow.added(msg.from === ctx.me.id);
      if (msg.seq > cursor) cursor = msg.seq;
      // At the newest with a long tail drawn: the oldest are let go (js/chat.js).
      if (all.length > parts.KEEP && parts.atBottom(messages)) {
        all.splice(0, all.length - parts.PAGE * 2);
        earlier = all[0].seq;
        redraw();
        drawEarlier();
        messages.scrollTop = messages.scrollHeight;
      }
    }

    // A message of this chat fetches what is new; a change of the chat
    // (people, title) is drawn in place; a removal takes the text out.
    let resyncBefore = null;
    ctx.onEvents(async (events) => {
      if (events.some((e) => /^conversation_/.test(e.kind) && ((e.subject && e.subject.id === id) || (e.payload && e.payload.id === id)))) {
        refreshView();
      }
      // The global chat (js/chats.js) holds no feed: the chat itself and its
      // newest page are read again, its removals and deleted files taken over.
      if (events.some((e) => e.kind === parts.RESYNC)) {
        await refreshView();
        try {
          // One page per nudge, walking back over what is shown (js/chat.js).
          const before = resyncBefore || cursor + 1;
          const page = await M.api.get(path + "?before=" + encodeURIComponent(before) + "&limit=" + parts.HISTORY_PAGE);
          const oldestShown = all.length ? all[0].seq : 0;
          const lowest = page.items.length ? Math.min(...page.items.map((m) => m.seq)) : null;
          resyncBefore = lowest !== null && page.items.length === parts.HISTORY_PAGE && lowest > oldestShown ? lowest : null;
          let changed = false;
          page.items.forEach((m) => {
            const at = all.findIndex((x) => x.seq === m.seq);
            if (at >= 0 && parts.isRemoved(m) && !parts.isRemoved(all[at])) { all[at] = Object.assign({}, all[at], m); changed = true; }
            (m.attachments || []).filter((a) => a.deleted_at).forEach((a) => M.attachments && M.attachments.markDeleted(messages, a.id));
          });
          if (changed) { const top = messages.scrollTop; redraw(); messages.scrollTop = top; }
        } catch (err) {
          pollStatus.fail(M.t("group.reread_failed"), err);
        }
      }
      events.filter((e) => e.kind === "attachment_deleted" && e.payload).forEach((e) => M.attachments.markDeleted(messages, e.payload.attachment_id));
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
        pollStatus.fail(M.t("group.fetch_failed"), err);
      }
    });

    // Who is in it, and who else reads it (§9.2: shown in the chat itself).
    // Lists of nodes: the comma between them is a separator, the sentence around them the catalog's.
    const listed = (nodes) => nodes.map((n, i) => [i ? ", " : null, n]);
    const people = () => h("p", { class: "muted group-people-line" }, M.tn("group.people.in", {
      people: listed(view.participants.map((p) => p.kind === "agent" ? M.tn("group.people.agent", { member: M.dom.memberRef(ctx, p.member_id) }) : M.dom.memberRef(ctx, p.member_id))) }));
    const observers = () => ((view.observers || []).length
      ? h("p", { class: "muted group-observers" }, M.tn("group.people.observers", {
        observers: listed(view.observers.map((o) => M.tn("group.people.observer", { name: observerName(o),
          agents: listed(view.participants.filter((p) => p.owner_id === o).map((p) => M.dom.memberRef(ctx, p.member_id))) }))) }))
      : null);

    // Managing: rename, add, remove; anyone in it leaves. The disclosure
    // stays open across a redraw of the head.
    let manageOpen = false;
    let renameDraft = null;
    function manage() {
      if (observer || closed) return null;
      const box = h("details", { class: "group-manage" }, h("summary", null, manager() ? M.t("group.manage.title") : M.t("group.manage.leave_title")));
      if (manageOpen) box.setAttribute("open", "");
      box.addEventListener("toggle", () => { manageOpen = box.hasAttribute ? box.hasAttribute("open") : manageOpen; });
      // A change is drawn in place; the status line says what happened and has the focus.
      // busy: the status line meanwhile; failed: its prefix to the hub's words.
      const act = async (busy, failed, done, call, after) => {
        status.busy(busy);
        try {
          await call();
        } catch (err) {
          status.fail(failed, said(err));
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
          act(M.t("group.manage.renaming"), M.t("group.manage.rename_failed"), M.t("group.manage.renamed"),
            () => M.api.patch(base, { title: typed }).then(() => { renameDraft = null; }));
        } }, h("label", { for: "group-rename" }, M.t("group.manage.title_label")), name, h("button", { type: "submit", class: "small" }, M.t("group.manage.rename"))));
        const free = ctx.members.filter((m) => !inChat(m.id) && !m.removed_at);
        if (projectClosed) {
          append(box, h("p", { class: "muted" }, M.t("group.manage.closed")));
        } else if (free.length && view.participants.length < MAX_PEOPLE) {
          const pick = h("select", { id: "group-add" }, free.map((m) => h("option", { value: m.id }, M.t("group.manage.option", { name: m.display_name, handle: m.handle }))));
          pick.value = free[0].id;
          append(box, h("form", { class: "inline-form", onsubmit: (e) => {
            e.preventDefault();
            const who = free.find((m) => m.id === pick.value);
            act(M.t("group.manage.adding"), M.t("group.manage.add_failed"), M.t("group.manage.added", { name: who.display_name }),
              () => M.api.post(base + "/participants", { member_id: pick.value }));
          } }, h("label", { for: "group-add" }, M.t("group.manage.add")), pick, h("button", { type: "submit", class: "small" }, M.t("group.manage.add"))),
          h("p", { class: "hint" }, M.t("group.manage.add_hint")));
        }
        append(box, h("ul", { class: "group-members" }, view.participants.filter((p) => p.member_id !== ctx.me.id).map((p) =>
          h("li", null, M.dom.memberRef(ctx, p.member_id), " ", h("button", { type: "button", class: "small", "aria-label": M.t("group.manage.remove_label", { name: nameOf(ctx, p.member_id) }), onclick: () => {
            if (!window.confirm(M.t("group.manage.remove_confirm", { name: nameOf(ctx, p.member_id) }))) return;
            act(M.t("group.manage.removing"), M.t("group.manage.remove_failed"), M.t("group.manage.removed", { name: nameOf(ctx, p.member_id) }),
              () => M.api.del(base + "/participants/" + encodeURIComponent(p.member_id)));
          } }, M.t("group.manage.remove"))))));
      }
      const lastHuman = view.participants.filter((p) => p.kind === "human").length === 1;
      append(box, h("button", { type: "button", class: "danger", onclick: () => {
        if (!window.confirm(lastHuman ? M.t("group.manage.leave_confirm_last") : M.t("group.manage.leave_confirm"))) return;
        act(M.t("group.manage.leaving"), M.t("group.manage.leave_failed"), M.t("group.manage.left"),
          () => M.api.del(base + "/participants/" + encodeURIComponent(ctx.me.id)), () => { M.route.go(ctx.link("chat")); });
      } }, M.t("group.manage.leave")));
      return box;
    }

    // Writing: a participant of an open chat. A mention reaches only
    // someone in it (§8.6); the hint says when a handle is not.
    const key = ctx.slug + "/" + id;
    let text = null;
    let compose = null;
    let hintMention = () => {};
    if (observer) {
      compose = h("p", { class: "muted group-readonly" }, M.t("group.readonly.observer"));
    } else if (closed) {
      compose = h("p", { class: "muted group-readonly" }, M.t("group.readonly.closed"));
    } else {
      text = h("textarea", { id: "chat-text", rows: "3", placeholder: M.t("group.compose.placeholder") });
      text.value = parts.drafts.get(key) || "";
      const hint = h("p", { class: "hint mention-hint", "aria-live": "polite", hidden: true });
      const MENTIONED = /(^|[^A-Za-z0-9_.@/+-])@([a-z0-9-]*[a-z0-9])(?![A-Za-z0-9_])/g;
      // Read from the view each time: someone added in place is reachable at once.
      hintMention = () => {
        const handles = new Set(view.participants.map((p) => p.handle));
        const outside = [...parts.withoutCode(text.value).matchAll(MENTIONED)].map((x) => x[2]).filter((hd) => !handles.has(hd));
        clear(hint);
        hint.hidden = !outside.length;
        if (outside.length) append(hint, M.t("group.compose.outside", { handle: outside[0] }));
      };
      text.addEventListener("input", () => {
        if (text.value.trim()) parts.drafts.set(key, text.value); else parts.drafts.delete(key);
        hintMention();
      });
      hintMention();
      const button = h("button", { type: "submit", class: "primary" }, M.t("group.compose.send"));
      const files = M.attachments ? M.attachments.picker(ctx, "group") : null;
      const sendIt = async (e) => {
        e.preventDefault();
        const body = text.value.trim();
        const ids = files ? files.ids() : [];
        if (!body && !ids.length) { text.focus(); return; }
        if (files && files.busy()) { status.fail(M.t("group.compose.failed"), { message: M.t("group.compose.uploading") }); return; }
        button.disabled = true;
        status.busy(M.t("group.compose.sending"));
        try {
          add(await M.api.post(path, ids.length ? { body, attachments: ids } : { body }));
          if (files) files.clear(ids);
          text.value = "";
          parts.drafts.delete(key);
          hintMention();
          status.done();
          list.refresh(false);
        } catch (err) {
          status.fail(M.t("group.compose.failed"), said(err));
        } finally {
          button.disabled = false;
        }
      };
      M.dom.sendOnCtrlEnter(text, sendIt, button);
      compose = h("form", { class: "compose", onsubmit: sendIt },
        h("label", { for: "chat-text" }, M.tn("group.compose.label", { keys: h("span", { class: "visually-hidden" }, M.t("group.compose.keys", { keys: M.dom.SEND_KEYS })) })),
        text, hint, files ? files.el : null, parts.actionRow(files, button));
    }

    const heading = h("h2", { class: "group-title", tabindex: "-1" }, titleOf());
    const head = h("div", { class: "group-head" });
    // The head drawn again keeps the focus on the same field, and the
    // mention hint follows the people now in the chat.
    function drawHead() {
      const had = document.activeElement && head.contains(document.activeElement) ? document.activeElement.id : null;
      heading.textContent = titleOf();
      pane.setAttribute("aria-label", M.t("group.pane", { title: titleOf() }));
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
        pollStatus.fail(M.t("group.reread_failed"), err);
        return;
      }
      if (fresh.access !== view.access || !!fresh.closed_at !== closed) { ctx.refresh(); return; }
      view = fresh;
      drawHead();
    }
    drawHead();
    append(pane,
      h("a", { class: "chat-back", href: ctx.link("chat") }, M.t("group.back")),
      h("div", { class: "toolbar" }, heading, closed ? h("span", { class: "flag" }, M.t("group.closed_flag")) : null),
      head,
      earlierBox,
      messages,
      follow.pill,
      pollStatus.el,
      compose,
      status.el);
    window.setTimeout(() => {
      parts.fitToScreen(layout);
      follow.open(messages.querySelector(".new-line"));
      if (window.matchMedia && window.matchMedia("(max-width: 720px)").matches) heading.focus();
    }, 0);
    // An observer is in no audience (§9.2): its view re-reads what is new.
    // From outside the project no event says a message was removed, so the
    // newest page is read again; a 404 means the access has ended.
    if (observer && ctx.outsider) {
      ctx.every(30000, async () => {
        try {
          // The newest page again, never the whole history (tsk-r1adgwp0a5dr):
          // what it holds replaces what is shown in its range, what is older stays.
          const page = await M.api.get(path + "?before=" + Number.MAX_SAFE_INTEGER + "&limit=" + parts.PAGE);
          const fresh = page.items;
          const from = fresh.length ? fresh[0].seq : Infinity;
          const newestShown = all.length ? all[all.length - 1].seq : 0;
          // More came than one page holds: what is shown no longer meets the
          // page, so it is let go, and scrolling up reads the gap in order.
          const gap = fresh.length && from > newestShown && page.earlier !== null && page.earlier !== undefined && all.length > 0;
          let next = gap ? fresh.slice() : all.filter((m) => m.seq < from).concat(fresh);
          if (gap) { earlier = page.earlier; drawEarlier(); }
          // At the newest with a long tail drawn: the oldest are let go, as in add().
          if (next.length > parts.KEEP && parts.atBottom(messages)) {
            next = next.slice(next.length - parts.PAGE * 2);
            earlier = next[0].seq;
            drawEarlier();
          }
          // Drawn again only on a change: the list is a live region.
          const sig = (list) => JSON.stringify(list.map((m) => [m.seq, m.body, !!m.redacted]));
          if (sig(next) !== sig(all)) {
            all.splice(0, all.length, ...next);
            if (all.length) cursor = Math.max(cursor, all[all.length - 1].seq);
            const top = messages.scrollTop;
            redraw();
            messages.scrollTop = top;
          }
          pollStatus.done();
        } catch (err) {
          if (err.status === 404) pollStatus.fail(M.t("group.gone"), { message: M.t("group.gone_reason") });
          else pollStatus.fail(M.t("group.reread_failed"), err);
        }
      });
    } else if (observer) {
      ctx.every(30000, async () => {
        try {
          const fresh = await M.api.get(path + "?after=" + encodeURIComponent(cursor));
          fresh.items.forEach(add);
          pollStatus.done();
        } catch (err) {
          pollStatus.fail(M.t("group.fetch_failed"), err);
        }
      });
    }
  }

  M.groupChat = { create, open };
})(window.Maity);
