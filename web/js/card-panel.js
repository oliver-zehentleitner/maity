// A card opened (/<owner>/<slug>/tasks/<id>): a panel beside the board on a
// wide screen and above it, full width, on a phone. It holds the card as
// the board draws it, controls included, and what the board leaves out:
// the body (Markdown), the links (§6.13), the open notes with a form to add
// one (§6.16) and the history (§6.15). Close, Escape and Back go to the
// board, which marks the card and gives its title the focus.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;

  const FIELD_WORDS = { title: "the title", body: "the description", label: "the label", area: "the area", status: "the status",
    depends_on: "the dependencies", ships_with: "ships with", parent: "the parent", related: "the related cards",
    assigned_to: "the assignee", ktw_ref: "the Keep the Why reference", links: "the links",
    "contract.state": "the contract's state", "contract.path": "the contract's path", "contract.section": "the contract's section" };

  // A value of the history as a short text; a body or title as its diff.
  function shortValue(v) {
    if (v === null || v === undefined || v === "") return "–";
    if (Array.isArray(v)) return v.length ? v.join(", ") : "–";
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
    if (e.field === "created") return h("li", null, who, " created the card", when);
    if (e.redacted) return h("li", null, who, " changed " + (FIELD_WORDS[e.field] || e.field) + " (removed)", when);
    if (e.diff) {
      return h("li", null, who, " changed " + (FIELD_WORDS[e.field] || e.field), when,
        h("details", null, h("summary", null, "What changed"), h("pre", { class: "history-diff" }, e.diff)));
    }
    return h("li", null, who, " changed " + (FIELD_WORDS[e.field] || e.field) + ": ",
      h("span", { class: "history-before" }, shortValue(e.before)), " → ", h("span", { class: "history-after" }, shortValue(e.after)), when);
  }

  function linkItem(l) {
    const url = l.kind === "url" ? l.url : l.forge_url;
    const safe = typeof url === "string" && /^https:\/\//.test(url);
    const words = l.kind === "url" ? (l.label || url)
      : (l.kind === "pr" ? "Pull request " : "Issue ") + (l.repository ? l.repository + "#" + l.number : url)
        + (l.observed && l.observed.title ? ": " + l.observed.title : "") + (l.observed && l.observed.state ? " (" + l.observed.state + ")" : "");
    return h("li", null, safe ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, words) : h("span", null, words));
  }

  // ctx, the card, its board element (js/board.js card(), the title not a
  // link), and close(): what Close and Escape do.
  function render(ctx, c, cardEl, close) {
    const where = M.ids.where(ctx);
    const base = ctx.base + "/tasks/" + encodeURIComponent(c.id);
    // The panel is the card (the designer's pass part 2): its id in the
    // bar beside Close, its title the panel's heading, where the focus goes.
    const heading = h("h2", { class: "panel-title", id: "card-panel-title", tabindex: "-1" }, M.ids.link(c.title, where));
    const cardSlot = h("div", { class: "card-panel-card" }, cardEl);
    const notesBox = h("div", { class: "card-notes" });
    const historyBox = h("div", { class: "card-history" });
    // The note field as last drawn: it gets the focus back after a post.
    let noteField = null;
    const box = h("aside", { class: "card-panel", "aria-labelledby": "card-panel-title" },
      h("div", { class: "card-panel-head" }, h("span", { class: "card-id" }, c.id),
        h("button", { type: "button", class: "small card-panel-close", onclick: () => close() }, "Close")),
      heading,
      cardSlot,
      h("h3", null, "Description"),
      c.body ? h("div", { class: "md card-body" }, M.markdown(c.body, where)) : h("p", { class: "muted" }, "No description."),
      (c.links || []).length ? [h("h3", null, "Links"), h("ul", { class: "card-links" }, c.links.map(linkItem))] : null,
      h("h3", null, "Notes"), notesBox,
      h("h3", null, "History"), historyBox);
    box.addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.defaultPrevented) close(); });

    async function notes() {
      clear(notesBox);
      let list;
      try {
        list = (await M.api.getAll(base + "/notes?state=open")).items;
      } catch (err) {
        append(notesBox, h("p", { class: "send-status failed" }, "Could not read the notes: " + err.message));
        return;
      }
      append(notesBox, list.length
        ? h("ul", { class: "card-note-list" }, list.map((n) => h("li", null,
          h("p", { class: "muted" }, byline(ctx, n.author), " · " + formatTime(n.created_at)),
          h("div", { class: "md" }, M.markdown(n.body, where, { mentions: n.mentions, hrefOf: (id) => ctx.link("members", id), ctx })))))
        : h("p", { class: "muted" }, "No open notes."));
      const closed = ctx.project && ctx.project.state === "archived";
      if (closed) return;
      const text = noteField = M.dom.sendOnCtrlEnter(h("textarea", { id: "card-note-body", rows: "3", maxlength: "4096", placeholder: "A finding, a missing case, a pointer (Markdown)" }));
      const status = M.statusLine();
      const submit = h("button", { type: "submit" }, "Post the note");
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
          status.busy("Posting…");
          try {
            await M.api.post(base + "/notes", { body: text.value });
          } catch (err) {
            posting = false;
            submit.disabled = false;
            status.fail("Not posted: ", M.boardEdit ? M.boardEdit.said(err) : err);
            return;
          }
          await notes();
          if (noteField) noteField.focus();
        },
      },
      h("label", { for: "card-note-body" }, "Add a note"), text,
      h("p", { class: "hint" }, "A note does not change the card; whoever may edit it works it in."),
      submit, status.el));
    }

    async function history() {
      clear(historyBox);
      try {
        const page = await M.api.get(base + "/history");
        append(historyBox, page.items.length
          ? h("ul", { class: "card-history-list" }, page.items.map((e) => historyLine(ctx, e)))
          : h("p", { class: "muted" }, "No changes recorded."));
      } catch (err) {
        append(historyBox, h("p", { class: "send-status failed" }, "Could not read the history: " + err.message));
      }
    }

    notes();
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
