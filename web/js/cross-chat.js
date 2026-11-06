// Cross-project group chats (docs/api.md §9.5), on the Chats page
// (js/chats.js): a room the owner holds for agent profiles they own,
// including agents that share no project. No attachments, no meat-proxy
// switch and no per-participant wake: a mention is the only wake, and
// reporting a message here is not built (§16.8). Messages are drawn as
// in a group chat (js/chat.js, M.chatParts).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const MAX_PEOPLE = 12;
  const EARLIER_PAGE = 50;

  const REFUSED = {
    get too_few() { return M.t("cross.refused.too_few"); },
    get too_many() { return M.t("cross.refused.too_many", { count: MAX_PEOPLE }); },
    get agents_only() { return M.t("cross.refused.agents_only"); },
    get deleted() { return M.t("cross.refused.deleted"); },
    get no_membership() { return M.t("cross.refused.no_membership"); },
    get use_group() { return M.t("cross.refused.use_group"); },
    get not_in_cross_chat() { return M.t("cross.compose.no_files"); },
  };
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    const why = fields && (fields.participants || fields.member_id || fields.attachments);
    if (why && Object.hasOwn(REFUSED, why)) return { message: REFUSED[why] };
    if (err.code === "conversation_closed") return { message: M.t("cross.refused.closed") };
    if (err.code === "conversation_quota") return { message: M.t("cross.refused.quota") };
    if (err.status === 404) return { message: M.t("cross.refused.not_found") };
    if (err.details && err.details.reason === "already_redacted") return { message: M.t("cross.refused.already") };
    return err;
  }

  const titleOf = (ctx, view) => view.title || M.fmt.list(view.participants.filter((p) => p.member_id !== ctx.me.id).map((p) => ctx.nameOf(p.member_id))) || M.t("cross.untitled");

  // One's own agent profiles (§6.3). A profile with no membership cannot be added.
  async function profiles(ctx) {
    const list = await M.api.getAll("/agents");
    return list.items.filter((a) => a.owner_id === ctx.me.id && !a.deleted_at);
  }

  function indexMembers(ctx, view) {
    const map = {};
    Object.values(ctx.pctxs || {}).forEach((p) => {
      Object.keys(p.memberById || {}).forEach((id) => { map[id] = p.memberById[id]; });
    });
    (view ? view.participants : []).forEach((p) => {
      if (map[p.member_id]) return;
      const named = ctx.agentNames && ctx.agentNames[p.member_id];
      map[p.member_id] = { id: p.member_id, kind: p.kind, handle: p.handle, display_name: named || p.handle || p.member_id, presence: "offline" };
    });
    return map;
  }

  // The projects the hub put on an agent participant, as marks.
  function projectMarks(ctx, fullNames) {
    if (!fullNames || !fullNames.length) return null;
    return h("span", { class: "msg-projects" }, fullNames.map((full, i) => {
      const known = (ctx.projects || []).find((p) => p.full_name === full);
      const name = (known && known.name) || full;
      return h("span", { class: "msg-project", title: name },
        M.projectMark(full, name, (ctx.projectViews || {})[full], "small"),
        h("span", { class: "visually-hidden" }, (i ? ", " : "") + name));
    }));
  }

  // ---- creating ----------------------------------------------------------

  async function create(ctx, holder) {
    const pane = h("section", { class: "chat-pane cross-new", "aria-label": M.t("cross.new.title") });
    append(holder, pane);
    const back = h("a", { class: "chat-back", href: "/chats" }, M.t("group.back"));
    const heading = h("h2", { tabindex: "-1" }, M.t("cross.new.title"));
    const status = M.statusLine();
    let agents = [];
    try {
      agents = await profiles(ctx);
    } catch (err) {
      append(pane, back, heading, h("p", { class: "send-status failed" }, M.t("cross.new.failed") + err.message));
      return;
    }
    if (ctx.stale && ctx.stale()) return;
    const usable = agents.filter((a) => (a.memberships || []).length);
    if (usable.length < 2) {
      append(pane, back, heading, h("p", { class: "muted" }, M.t("cross.new.none")));
      window.setTimeout(() => heading.focus(), 0);
      return;
    }
    const title = h("input", { id: "cross-title", maxlength: "200", autocomplete: "off", placeholder: M.t("group.new.title_placeholder") });
    const boxes = agents.map((a) => {
      const box = h("input", { type: "checkbox", id: "cross-member-" + a.id, value: a.id });
      const where = (a.memberships || []).map((m) => m.project).join(", ");
      const note = where ? where : M.t("cross.new.no_project");
      if (!where) box.disabled = true;
      return { a, box, el: h("label", { class: "check", for: box.id }, box, " " + a.display_name, h("span", { class: "muted" }, " @" + a.handle + " · " + note)) };
    });
    const error = h("p", { class: "field-error", role: "alert" });
    const send = h("button", { type: "submit" }, M.t("group.new.create"));
    const form = h("form", {
      class: "project-form group-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        error.textContent = "";
        const chosen = boxes.filter((b) => b.box.checked).map((b) => b.a);
        if (chosen.length < 2) { error.textContent = M.t("cross.refused.too_few"); return; }
        if (chosen.length + 1 > MAX_PEOPLE) { error.textContent = M.t("cross.refused.too_many", { count: MAX_PEOPLE }); return; }
        send.disabled = true;
        status.busy(M.t("group.new.creating"));
        try {
          const created = await M.api.post("/me/cross-chats", { title: title.value.trim() || null, participants: chosen.map((a) => a.id) });
          status.done();
          M.route.go("/chats/cross/" + encodeURIComponent(created.id));
        } catch (err) {
          status.fail(M.t("cross.new.failed"), said(err));
        } finally {
          send.disabled = false;
        }
      },
    },
    h("label", { for: "cross-title" }, M.t("group.new.title_label")), title,
    h("p", { class: "hint" }, M.t("cross.new.title_hint")),
    h("fieldset", { class: "group-people" },
      h("legend", null, M.t("group.new.participants")), boxes.map((b) => b.el)),
    h("p", { class: "hint" }, M.t("cross.new.hint")),
    error,
    h("div", { class: "actions" }, send),
    status.el);
    append(pane, back, heading, form);
    window.setTimeout(() => heading.focus(), 0);
  }

  // ---- the open chat -----------------------------------------------------

  async function open(ctx, holder, list, id, parts) {
    const base = "/me/cross-chats/" + encodeURIComponent(id);
    const path = base + "/messages";
    let view;
    try {
      view = await M.api.get(base);
    } catch (err) {
      if (err.status === 404) {
        append(holder, h("p", { class: "error", role: "alert" }, M.t("cross.missing")));
        return;
      }
      throw err;
    }
    if (ctx.stale && ctx.stale()) return;
    ctx.memberById = indexMembers(ctx, view);
    ctx.nameOf = (who) => {
      const member = ctx.memberById[who];
      return (member && member.display_name) || who;
    };
    // An agent's projects are the ones the hub put on the participant (§9.5).
    ctx.projectsOf = (memberId) => {
      const person = view.participants.find((p) => p.member_id === memberId);
      if (!person || person.kind !== "agent") return [];
      return (person.projects || []).map((full) => {
        const known = (ctx.projects || []).find((p) => p.full_name === full);
        return { slug: full, name: (known && known.name) || full, view: (ctx.projectViews || {})[full] };
      });
    };
    const item = list.crossItem ? list.crossItem(id) : null;
    const unreadBefore = item && item.unread || 0;
    const closed = () => !!view.closed_at;
    const owner = () => view.created_by === ctx.me.id;
    const inChat = (memberId) => view.participants.some((p) => p.member_id === memberId);

    const pane = h("section", { class: "chat-pane cross-chat", "aria-label": M.t("cross.pane", { title: titleOf(ctx, view) }) });
    append(holder, pane);
    const pollStatus = M.statusLine();
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");

    const first = await parts.newestPage(path, item && item.last_message && item.last_message.seq ? item.last_message.seq + 1 : null, ctx.stale);
    if (ctx.stale && ctx.stale()) return;
    const all = first.items;
    let earlier = first.earlier;
    let cursor = first.cursor || 0;
    if (list.refresh) list.refresh(false);
    const theirs = all.filter((m) => m.from !== ctx.me.id);
    const firstUnread = unreadBefore && theirs.length >= unreadBefore ? theirs[theirs.length - unreadBefore].seq : null;

    async function redact(msg) {
      const reason = parts.askReason(M.t("group.redact.ask"));
      if (reason === null) return;
      status.busy(M.t("group.redact.busy"));
      try {
        const fresh = await M.api.post(base + "/messages/" + encodeURIComponent(msg.id) + "/redact", { reason });
        const at = all.findIndex((m) => m.seq === msg.seq);
        if (at >= 0) all[at] = fresh;
        redraw();
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("group.redact.done")));
      } catch (err) {
        status.fail(M.t("group.redact.failed"), said(err));
      }
    }

    function quote(msg) {
      if (!text) return;
      if (text.composeOpen) text.composeOpen();
      text.value = parts.quoteOf(ctx, msg) + text.value;
      parts.drafts.set(key, text.value);
      text.focus();
    }
    const mayRedact = () => owner();
    const opts = { group: true, onRedact: mayRedact() ? redact : null, canDeleteFile: () => false };
    const messages = h("ol", { class: "messages", "aria-live": "polite" });
    let text = null;
    const follow = parts.follower(messages, () => (text || heading).focus());
    let draw = null;
    function redraw() {
      opts.onRedact = mayRedact() ? redact : null;
      draw = parts.timeline(ctx, new Map(), firstUnread, closed() ? null : quote, opts);
      clear(messages);
      if (!all.length) {
        append(messages, h("li", { class: "empty" }, h("p", null, earlier === null ? M.t("group.empty.none") : M.t("group.empty.nothing_new")),
          h("p", { class: "muted" }, earlier === null ? M.t("group.empty.none_hint") : M.t("group.empty.nothing_new_hint"))));
      } else {
        all.forEach((m) => append(messages, draw(m)));
      }
    }
    redraw();

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
      if (empty) redraw();
      else append(messages, draw(msg));
      follow.added(msg.from === ctx.me.id);
      if (msg.seq > cursor) cursor = msg.seq;
    }

    ctx.onEvents(async (events) => {
      if (!events.some((e) => e.kind === "message" || e.kind === parts.RESYNC)) return;
      try {
        const fresh = await M.api.get(path + "?after=" + encodeURIComponent(cursor));
        fresh.items.forEach(add);
        const again = await M.api.get(base);
        if (again.access !== view.access || !!again.closed_at !== closed()) { ctx.refresh(); return; }
        view = again;
        ctx.memberById = indexMembers(ctx, view);
        drawHead();
        pollStatus.done();
        if (list.refresh) list.refresh(false);
      } catch (err) {
        if (err.status === 404) pollStatus.fail(M.t("group.gone"), { message: M.t("cross.missing") });
        else pollStatus.fail(M.t("group.fetch_failed"), err);
      }
    });

    const listed = (nodes) => nodes.map((n, i) => [i ? ", " : null, n]);
    const people = () => h("p", { class: "muted group-people-line" }, M.tn("cross.people", {
      people: listed(view.participants.map((p) => {
        const ref = M.dom.memberRef(ctx, p.member_id, { instance: null });
        const marks = p.kind === "agent" ? projectMarks(ctx, p.projects) : null;
        return marks ? h("span", { class: "cross-person" }, ref, " ", marks) : ref;
      })),
    }));

    let manageOpen = false;
    let renameDraft = null;
    let agentList = null;
    function manage() {
      if (closed() || !owner() || view.access !== "participant") return null;
      const box = h("details", { class: "group-manage" }, h("summary", null, M.t("group.manage.title")));
      if (manageOpen) box.setAttribute("open", "");
      box.addEventListener("toggle", () => { manageOpen = box.hasAttribute ? box.hasAttribute("open") : manageOpen; });
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
      const name = h("input", { id: "cross-rename", maxlength: "200", autocomplete: "off" });
      name.value = renameDraft !== null ? renameDraft : view.title || "";
      name.addEventListener("input", () => { renameDraft = name.value; });
      append(box, h("form", { class: "inline-form", onsubmit: (e) => {
        e.preventDefault();
        act(M.t("group.manage.renaming"), M.t("group.manage.rename_failed"), M.t("group.manage.renamed"),
          () => M.api.patch(base, { title: name.value.trim() || null }).then(() => { renameDraft = null; }));
      } }, h("label", { for: "cross-rename" }, M.t("group.manage.title_label")), name, h("button", { type: "submit", class: "small" }, M.t("group.manage.rename"))));
      const free = (agentList || []).filter((a) => !inChat(a.id) && (a.memberships || []).length);
      if (view.participants.length >= MAX_PEOPLE) {
        append(box, h("p", { class: "muted" }, M.t("cross.refused.too_many", { count: MAX_PEOPLE })));
      } else if (free.length) {
        const pick = h("select", { id: "cross-add" }, free.map((a) => h("option", { value: a.id }, M.t("group.manage.option", { name: a.display_name, handle: a.handle }))));
        pick.value = free[0].id;
        append(box, h("form", { class: "inline-form", onsubmit: (e) => {
          e.preventDefault();
          const who = free.find((a) => a.id === pick.value);
          act(M.t("group.manage.adding"), M.t("group.manage.add_failed"), M.t("group.manage.added", { name: who.display_name }),
            () => M.api.post(base + "/participants", { member_id: pick.value }));
        } }, h("label", { for: "cross-add" }, M.t("group.manage.add")), pick, h("button", { type: "submit", class: "small" }, M.t("group.manage.add"))),
        h("p", { class: "hint" }, M.t("group.manage.add_hint")));
      }
      append(box, h("ul", { class: "group-members" }, view.participants.filter((p) => p.member_id !== ctx.me.id).map((p) =>
        h("li", null, M.dom.memberRef(ctx, p.member_id), " ", h("button", {
          type: "button", class: "small",
          "aria-label": M.t("group.manage.remove_label", { name: ctx.nameOf(p.member_id) }),
          onclick: () => {
            if (!window.confirm(M.t("group.manage.remove_confirm", { name: ctx.nameOf(p.member_id) }))) return;
            act(M.t("group.manage.removing"), M.t("group.manage.remove_failed"), M.t("group.manage.removed", { name: ctx.nameOf(p.member_id) }),
              () => M.api.del(base + "/participants/" + encodeURIComponent(p.member_id)));
          },
        }, M.t("group.manage.remove"))))));
      append(box, h("button", { type: "button", class: "danger", onclick: () => {
        if (!window.confirm(M.t("cross.manage.leave_confirm"))) return;
        act(M.t("group.manage.leaving"), M.t("group.manage.leave_failed"), M.t("cross.manage.left"),
          () => M.api.del(base + "/participants/" + encodeURIComponent(ctx.me.id)), () => ctx.refresh());
      } }, M.t("cross.manage.leave")));
      return box;
    }

    const key = "cross/" + id;
    let compose = null;
    let hintMention = () => {};
    if (closed()) {
      compose = h("p", { class: "muted group-readonly" }, M.t("cross.readonly.closed"));
    } else {
      text = h("textarea", { id: "chat-text", rows: "3", placeholder: M.t("group.compose.placeholder") });
      text.value = parts.drafts.get(key) || "";
      const hint = h("p", { class: "hint mention-hint", "aria-live": "polite", hidden: true });
      const MENTIONED = /(^|[^A-Za-z0-9_.@/+-])@([a-z0-9-]*[a-z0-9])(?![A-Za-z0-9_])/g;
      hintMention = () => {
        const handles = new Set(view.participants.map((p) => p.handle));
        const outside = [...parts.withoutCode(text.value).matchAll(MENTIONED)].map((x) => x[2]).filter((hd) => !handles.has(hd));
        clear(hint);
        hint.hidden = !outside.length;
        if (outside.length) append(hint, M.t("group.compose.outside", { handle: outside[0] }));
      };
      const typedInChat = () => {
        if (text.value.trim()) parts.drafts.set(key, text.value); else parts.drafts.delete(key);
        hintMention();
      };
      text.addEventListener("input", typedInChat);
      hintMention();
      const button = h("button", { type: "submit", class: "primary" }, M.t("group.compose.send"));
      const offered = () => view.participants.map((p) => {
        const member = ctx.memberById[p.member_id] || {};
        return Object.assign({}, member, { id: p.member_id, kind: p.kind, handle: p.handle, display_name: member.display_name || p.handle });
      });
      const sendIt = async (e) => {
        e.preventDefault();
        const body = text.value.trim();
        if (!body) { text.focus(); return; }
        button.disabled = true;
        status.busy(M.t("group.compose.sending"));
        try {
          add(await M.api.post(path, { body }));
          text.value = "";
          parts.drafts.delete(key);
          hintMention();
          status.done();
          if (list.refresh) list.refresh(false);
        } catch (err) {
          status.fail(M.t("group.compose.failed"), said(err));
        } finally {
          button.disabled = false;
        }
      };
      M.dom.sendOnCtrlEnter(text, sendIt, button);
      compose = h("form", { class: "compose", onsubmit: sendIt });
      append(compose,
        parts.composeHead(compose, text, h("label", { for: "chat-text" }, M.tn("group.compose.label", { keys: h("span", { class: "visually-hidden" }, M.t("group.compose.keys", { keys: M.dom.SEND_KEYS })) }))),
        text, M.mentionPicker(text, () => Promise.resolve(offered()), ctx.me.id, { allowed: (m) => inChat(m.id), onPick: typedInChat }), hint,
        parts.actionRow(null, button, null, status));
    }

    const heading = h("h2", { class: "group-title", tabindex: "-1" }, titleOf(ctx, view));
    const head = h("div", { class: "group-head" });
    function drawHead() {
      const had = document.activeElement && head.contains(document.activeElement) ? document.activeElement.id : null;
      heading.textContent = titleOf(ctx, view);
      pane.setAttribute("aria-label", M.t("cross.pane", { title: titleOf(ctx, view) }));
      append(clear(head), people(), manage());
      const again = had && Array.from(head.querySelectorAll("input, select, button")).find((e) => e.id === had);
      if (again) again.focus();
      hintMention();
    }
    async function refreshView() {
      let fresh;
      try {
        fresh = await M.api.get(base);
      } catch (err) {
        if (err.status === 404) { ctx.refresh(); return; }
        pollStatus.fail(M.t("group.fetch_failed"), err);
        return;
      }
      if (fresh.access !== view.access || !!fresh.closed_at !== closed()) { ctx.refresh(); return; }
      view = fresh;
      ctx.memberById = indexMembers(ctx, view);
      drawHead();
    }
    drawHead();
    append(pane,
      h("a", { class: "chat-back", href: "/chats" }, M.t("group.back")),
      h("div", { class: "toolbar" }, heading, closed() ? h("span", { class: "flag" }, M.t("group.closed_flag")) : null),
      head, earlierBox, messages, follow.pill, pollStatus.el, compose,
      status.el.parentNode ? null : status.el);
    profiles(ctx).then((agents) => {
      if (ctx.stale && ctx.stale()) return;
      agentList = agents;
      ctx.agentNames = {};
      agents.forEach((a) => { if (a.display_name) ctx.agentNames[a.id] = a.display_name; });
      ctx.memberById = indexMembers(ctx, view);
      drawHead();
    }).catch(() => { agentList = []; });
    window.setTimeout(() => {
      parts.fitToScreen(holder.parentNode || holder);
      follow.open(messages.querySelector(".new-line"));
      if (window.matchMedia && window.matchMedia("(max-width: 720px)").matches) heading.focus();
    }, 0);
  }

  M.crossChat = { create, open };
})(window.Maity);
