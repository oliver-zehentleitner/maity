// A card opened (/<owner>/<slug>/tasks/<id>): a panel beside the board on a
// wide screen and above it, full width, on a phone. It holds the card as
// the board draws it, controls included, and what the board leaves out:
// the body (Markdown), the links (§6.13), the open notes with a form to add
// one (§6.16), the updates the reader's watch brings and the history (§6.15),
// and the reader's own watch (§6.4). Close, Escape and Back go to the
// board, which marks the card and gives its title the focus.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;

  const FIELD_WORDS = {
    title: () => M.t("cardpanel.field.title"), body: () => M.t("cardpanel.field.body"), label: () => M.t("cardpanel.field.label"),
    area: () => M.t("cardpanel.field.area"), status: () => M.t("cardpanel.field.status"),
    depends_on: () => M.t("cardpanel.field.depends_on"), ships_with: () => M.t("cardpanel.field.ships_with"),
    parent: () => M.t("cardpanel.field.parent"), related: () => M.t("cardpanel.field.related"),
    assigned_to: () => M.t("cardpanel.field.assigned_to"), ktw_ref: () => M.t("cardpanel.field.ktw_ref"), links: () => M.t("cardpanel.field.links"),
    "contract.state": () => M.t("cardpanel.field.contract_state"), "contract.path": () => M.t("cardpanel.field.contract_path"),
    "contract.section": () => M.t("cardpanel.field.contract_section"),
  };
  const UPDATES_PAGE = 100;
  const fieldWord = (f) => (Object.hasOwn(FIELD_WORDS, f) ? FIELD_WORDS[f]() : f);

  // A value of the history as a short text; a body or title as its diff.
  function shortValue(v) {
    if (v === null || v === undefined || v === "") return "–";
    if (Array.isArray(v)) return v.length ? M.fmt.list(v.map(String)) : "–";
    if (typeof v === "object") return v.url || v.forge_url || v.label || JSON.stringify(v);
    return String(v);
  }

  // Who changed or wrote it, as @handle, an agent with its instance
  // (§6.17) where the hub names one.
  const byline = (ctx, who) => (who && (who.member_id || who.handle)
    ? M.dom.memberRef(ctx, who, { text: "handle", instance: who.instance }) : "@?");

  function historyLine(ctx, e) {
    const who = h("span", null, byline(ctx, e.actor));
    const when = h("span", { class: "muted" }, " · " + formatAgo(e.at, M.api.now()));
    const field = fieldWord(e.field);
    if (e.field === "created") return h("li", null, M.tn("cardpanel.history.created", { who }), when);
    if (e.redacted) return h("li", null, M.tn("cardpanel.history.changed_removed", { who, field }), when);
    if (e.diff) {
      return h("li", null, M.tn("cardpanel.history.changed", { who, field }), when,
        h("details", null, h("summary", null, M.t("cardpanel.history.what_changed")), h("pre", { class: "history-diff" }, e.diff)));
    }
    return h("li", null, M.tn("cardpanel.history.changed_value", { who, field,
      before: h("span", { class: "history-before" }, shortValue(e.before)), after: h("span", { class: "history-after" }, shortValue(e.after)) }), when);
  }

  // A pull request or an issue: its reference, with the title and state the hub observed.
  function forgeWords(l, url) {
    const ref = l.repository ? l.repository + "#" + l.number : String(url);
    let words = l.kind === "pr" ? M.t("cardpanel.link.pr", { ref }) : M.t("cardpanel.link.issue", { ref });
    if (l.observed && l.observed.title) words = M.t("cardpanel.link.titled", { link: words, title: l.observed.title });
    if (l.observed && l.observed.state) words = M.t("cardpanel.link.state", { link: words, state: l.observed.state });
    return words;
  }

  function linkItem(l) {
    const url = l.kind === "url" ? l.url : l.forge_url;
    const safe = typeof url === "string" && /^https:\/\//.test(url);
    const words = l.kind === "url" ? (l.label || url) : forgeWords(l, url);
    return h("li", null, safe ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, words) : h("span", null, words));
  }

  // ctx, the card, its board element (js/board.js card(), the title not a
  // link), close(): what Close and Escape do, and changed(card): the hub's
  // answer about this card, for the board to draw.
  function render(ctx, c, cardEl, close, changed) {
    const where = M.ids.where(ctx);
    const base = ctx.base + "/tasks/" + encodeURIComponent(c.id);
    // The panel is the card (the designer's pass part 2): its id in the
    // bar beside Close, its title the panel's heading, where the focus goes.
    const heading = h("h2", { class: "panel-title", id: "card-panel-title", tabindex: "-1" }, M.ids.link(c.title, where));
    const cardSlot = h("div", { class: "card-panel-card" }, cardEl);
    const notesBox = h("div", { class: "card-notes" });
    const historyBox = h("div", { class: "card-history" });
    const updatesBox = h("div", { class: "card-updates" });
    // Only the hub knows whether a card of the reader's depends on this one:
    // an implied watch shows as any other, and taking it away is refused.
    let watching = c.watching === true;
    let updatesRun = 0;
    const watchStatus = M.statusLine();
    const watchButton = h("button", { type: "button", class: "small card-watch", onclick: () => toggleWatch() });
    const drawWatch = () => {
      watchButton.setAttribute("aria-pressed", watching ? "true" : "false");
      append(clear(watchButton), watching ? M.t("cardpanel.watch.on") : M.t("cardpanel.watch.off"));
    };
    drawWatch();
    // The note field as last drawn: it gets the focus back after a post.
    let noteField = null;
    const box = h("aside", { class: "card-panel", "aria-labelledby": "card-panel-title" },
      h("div", { class: "card-panel-head" }, h("span", { class: "card-id" }, c.id),
        h("span", { class: "card-panel-actions" }, watchButton,
          h("button", { type: "button", class: "small card-panel-close", onclick: () => close() }, M.t("cardpanel.close")))),
      watchStatus.el,
      heading,
      cardSlot,
      h("h3", null, M.t("cardpanel.description")),
      c.body ? h("div", { class: "md card-body" }, M.markdown(c.body, where, { mentions: c.mentions, hrefOf: (id) => ctx.link("members", id), ctx }))
        : h("p", { class: "muted" }, M.t("cardpanel.description.none")),
      (c.links || []).length ? [h("h3", null, M.t("cardpanel.links")), h("ul", { class: "card-links" }, c.links.map(linkItem))] : null,
      h("h3", null, M.t("cardpanel.notes")), notesBox,
      updatesBox,
      h("h3", null, M.t("cardpanel.history")), historyBox);
    box.addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.defaultPrevented) close(); });

    async function notes() {
      clear(notesBox);
      let list;
      try {
        list = (await M.api.getAll(base + "/notes?state=open")).items;
      } catch (err) {
        append(notesBox, h("p", { class: "send-status failed" }, M.t("cardpanel.notes.read_failed", { reason: err.message })));
        return;
      }
      append(notesBox, list.length
        ? h("ul", { class: "card-note-list" }, list.map((n) => h("li", null,
          h("p", { class: "muted" }, byline(ctx, n.author), " · " + formatTime(n.created_at)),
          h("div", { class: "md" }, M.markdown(n.body, where, { mentions: n.mentions, hrefOf: (id) => ctx.link("members", id), ctx })))))
        : h("p", { class: "muted" }, M.t("cardpanel.notes.none")));
      const closed = ctx.project && ctx.project.state === "archived";
      if (closed) return;
      const text = noteField = M.dom.sendOnCtrlEnter(h("textarea", { id: "card-note-body", rows: "3", maxlength: "4096", placeholder: M.t("cardpanel.notes.placeholder") }));
      const status = M.statusLine();
      const submit = h("button", { type: "submit" }, M.t("cardpanel.notes.post"));
      // One post at a time: a second tap or Ctrl+Enter while the first is
      // on its way sends nothing; a refusal makes the button usable again.
      let posting = false;
      append(notesBox, h("form", {
        class: "card-note-form",
        onsubmit: async (e) => {
          e.preventDefault();
          if (posting) return;
          if (!text.value.trim()) { text.focus(); return; }
          posting = true;
          submit.disabled = true;
          status.busy(M.t("cardpanel.notes.posting"));
          try {
            await M.api.post(base + "/notes", { body: text.value });
          } catch (err) {
            posting = false;
            submit.disabled = false;
            status.fail(M.t("cardpanel.notes.not_posted"), M.boardEdit ? M.boardEdit.said(err) : err);
            return;
          }
          await notes();
          if (noteField) noteField.focus();
        },
      },
      h("label", { for: "card-note-body" }, M.t("cardpanel.notes.add")), text,
      h("p", { class: "hint" }, M.t("cardpanel.notes.hint")),
      submit, status.el));
    }

    async function toggleWatch() {
      if (watchButton.disabled) return;
      watchButton.disabled = true;
      watchStatus.busy(M.t("cardpanel.watch.saving"));
      try {
        const answer = watching ? await M.api.del(base + "/watch") : await M.api.put(base + "/watch");
        watching = answer.watching === true;
        drawWatch();
        watchStatus.done();
        if (changed) changed(answer);
        updates();
      } catch (err) {
        const implied = err.code === "invalid" && err.details && err.details.reason === "implied";
        if (implied) watchStatus.fail("", { message: M.t("cardpanel.watch.implied") });
        else watchStatus.fail(M.t("cardpanel.watch.not_saved"), err);
      } finally {
        watchButton.disabled = false;
      }
    }

    // A watcher's news on the card (§6.4). The status changes it also brings
    // are in the history below. The hub's listing has no card filter: the
    // newest page of updates, this card's among them (context/views.md).
    async function updates() {
      const run = ++updatesRun; // a read still on its way when the watch changes draws nothing
      clear(updatesBox);
      if (!watching) return;
      try {
        const page = await M.api.get(ctx.base + "/messages?type=update&limit=" + UPDATES_PAGE);
        if (run !== updatesRun) return;
        const items = page.items.filter((m) => m.task_id === c.id);
        append(updatesBox, h("h3", null, M.t("cardpanel.updates")), items.length
          ? h("ul", { class: "card-update-list" }, items.map((m) => h("li", null,
            h("p", { class: "muted" }, byline(ctx, { member_id: m.from, instance: m.from_instance }), " · " + formatTime(m.sent_at)),
            h("div", { class: "md" }, M.markdown(m.body || "", where, { mentions: m.mentions, hrefOf: (id) => ctx.link("members", id), ctx })))))
          : h("p", { class: "muted" }, M.t("cardpanel.updates.none")));
      } catch (err) {
        if (run !== updatesRun) return;
        append(updatesBox, h("h3", null, M.t("cardpanel.updates")),
          h("p", { class: "send-status failed" }, M.t("cardpanel.updates.read_failed", { reason: err.message })));
      }
    }

    async function history() {
      clear(historyBox);
      try {
        const page = await M.api.get(base + "/history");
        append(historyBox, page.items.length
          ? h("ul", { class: "card-history-list" }, page.items.map((e) => historyLine(ctx, e)))
          : h("p", { class: "muted" }, M.t("cardpanel.history.none")));
      } catch (err) {
        append(historyBox, h("p", { class: "send-status failed" }, M.t("cardpanel.history.read_failed", { reason: err.message })));
      }
    }

    notes();
    updates();
    history();

    return {
      el: box,
      id: c.id,
      focus: () => heading.focus(),
      // The board redrew: the card part follows, and the heading with its
      // title, which may have changed (H on #461); the rest stays as read.
      update: (fresh) => {
        append(clear(cardSlot), fresh);
        const title = fresh && fresh.getAttribute && fresh.getAttribute("aria-label");
        if (title) append(clear(heading), M.ids.link(title, where));
      },
    };
  }

  M.cardPanel = { render };
})(window.Maity);
