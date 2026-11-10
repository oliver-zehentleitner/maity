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

  // A label or a status is a word of the contract; the other fields are what was written.
  const VALUE_WORDS = { label: "label", status: "status", "contract.state": "contract" };
  function fieldValue(field, v) {
    const said = Object.hasOwn(VALUE_WORDS, field) && typeof v === "string" && v ? M.dom.word(VALUE_WORDS[field], v) : v;
    return said === v ? shortValue(v) : said;
  }

  // Who changed or wrote it, as @handle, an agent with its instance
  // (§6.17) where the hub names one.
  const byline = (ctx, who) => (who && (who.member_id || who.handle)
    ? M.dom.memberRef(ctx, who, { text: "handle", instance: who.instance }) : "@?");

  // A redacted note keeps its place; its body is §8.5's tombstone, {redacted, reason,
  // by, at}, never Markdown (§6.16). The reason reaches the owners and admins and
  // the redactor; every other reader gets reason null and reads the removal alone.
  const removedNote = (n) => !!n.body && typeof n.body === "object";
  function noteTombstone(ctx, t) {
    const reason = t.reason || "";
    const who = t.by ? M.dom.memberRef(ctx, t.by) : null;
    const said = who
      ? (reason ? M.tn("cardpanel.notes.removed_by", { who, reason }) : M.tn("cardpanel.notes.removed_by.unsaid", { who }))
      : (reason ? M.t("cardpanel.notes.removed", { reason }) : M.t("cardpanel.notes.removed.unsaid"));
    return h("p", { class: "muted msg-redacted card-note-removed", tabindex: "-1" }, said, t.at ? " · " + formatTime(t.at) : "");
  }

  // An edited note says who edited it last and when, with the reason when one
  // was given (§6.16): never the earlier text, which the hub no longer keeps.
  function noteEdited(ctx, e) {
    const o = { who: byline(ctx, e.by), at: formatTime(e.at) };
    return h("p", { class: "muted card-note-edited" }, e.reason
      ? M.tn("cardpanel.notes.edited_reason", Object.assign(o, { reason: e.reason })) : M.tn("cardpanel.notes.edited", o));
  }

  // The hub asks for a reason to remove a note (§8.5): asked again until one is
  // given; null when cancelled.
  function askRemoveReason() {
    let reason = window.prompt(M.t("cardpanel.notes.remove.ask"), "");
    while (reason !== null && !reason.trim()) reason = window.prompt(M.t("cardpanel.notes.remove.reason_needed"), "");
    return reason === null ? null : reason.trim();
  }

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
      before: h("span", { class: "history-before" }, fieldValue(e.field, e.before)), after: h("span", { class: "history-after" }, fieldValue(e.field, e.after)) }), when);
  }

  // A commit's checks and its required check's status (§6.13, §6.6), in words.
  const CHECK_WORDS = {
    success: () => M.t("board.checks.success"), failure: () => M.t("board.checks.failure"), pending: () => M.t("board.checks.pending"),
    none: () => M.t("board.checks.none"), unknown: () => M.t("board.checks.unknown"),
    cancelled: () => M.t("board.checks.cancelled"), missing: () => M.t("board.checks.missing"),
  };
  const checkWord = (value) => (Object.hasOwn(CHECK_WORDS, value) ? CHECK_WORDS[value]() : String(value));

  // A commit (§6.13): its short sha, the checks and required check the hub observed on it,
  // and whether the default branch has moved past it.
  function commitWords(l, url) {
    const ref = l.repository && typeof l.sha === "string" ? l.repository + "@" + l.sha.slice(0, 7) : String(url);
    let words = M.t("cardpanel.link.commit", { ref });
    const o = l.observed;
    if (!o) return words;
    if (o.found === false) return M.t("cardpanel.link.commit_missing", { link: words });
    if (o.checks) words = M.t("cardpanel.link.commit_checks", { link: words, checks: checkWord(o.checks) });
    const rc = o.required_check;
    if (rc) words = M.t("cardpanel.link.required_check", { link: words, name: rc.name, status: checkWord(rc.status) });
    if (o.ahead === true) words = M.t("cardpanel.link.ahead", { link: words });
    return words;
  }

  // A pull request or an issue: its reference, with the title and state the hub observed.
  function forgeWords(l, url) {
    if (l.kind === "commit") return commitWords(l, url);
    const ref = l.repository ? l.repository + "#" + l.number : String(url);
    let words = l.kind === "pr" ? M.t("cardpanel.link.pr", { ref }) : M.t("cardpanel.link.issue", { ref });
    if (l.observed && l.observed.title) words = M.t("cardpanel.link.titled", { link: words, title: l.observed.title });
    if (l.observed && l.observed.state) words = M.t("cardpanel.link.state", { link: words, state: M.dom.word("pr", l.observed.state) });
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
    // Add a note is drawn once per panel, below the list, and stays while the list
    // is drawn again: whoever types in it keeps the field, its focus, caret and text.
    // `posting` is the text of a post on its way (null when none).
    let noteFormEl = null, posting = null;
    // Each read of the list counts; only the latest draws it, so an older read that
    // ends later draws nothing and says so to its caller (false).
    let notesRead = 0;
    const notesList = h("div", { class: "card-note-items" });
    append(notesBox, notesList);
    const box = h("aside", { class: "card-panel", "aria-labelledby": "card-panel-title" },
      h("div", { class: "card-panel-head" }, h("span", { class: "card-id" }, c.id),
        h("span", { class: "card-panel-actions" }, watchButton,
          h("button", { type: "button", class: "small card-panel-close", onclick: () => close() }, M.t("cardpanel.close")))),
      watchStatus.el,
      heading,
      cardSlot,
      h("h3", null, M.t("cardpanel.description")),
      c.body ? h("div", { class: "md card-body" }, M.markdown(c.body, where, { mentions: c.mentions, hrefOf: (id) => ctx.link("team", id), ctx }))
        : h("p", { class: "muted" }, M.t("cardpanel.description.none")),
      (c.links || []).length ? [h("h3", null, M.t("cardpanel.links")), h("ul", { class: "card-links" }, c.links.map(linkItem))] : null,
      // The restricted text (§6.4): a box for a member in the set alone, read when the card opens.
      M.restricted ? M.restricted.cardBox(ctx, c) : null,
      h("h3", null, M.t("cardpanel.notes")), notesBox,
      updatesBox,
      h("h3", null, M.t("cardpanel.history")), historyBox);
    box.addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.defaultPrevented) close(); });

    // Who may do what to a note (§6.16): its author edits it, a human holding
    // events:admin (owner, admin) edits any note and removes it. A removed note
    // is the end of it; a closed project takes no edit, a removal still.
    const closed = () => !!(ctx.project && ctx.project.state === "archived");
    const mine = (n) => !!(ctx.me && n.author && n.author.member_id === ctx.me.id);
    const mayEdit = (n) => !removedNote(n) && !closed() && (mine(n) || !!ctx.canAdmin);
    const mayRemove = (n) => !removedNote(n) && !!ctx.canAdmin;
    const reading = () => notesList.getAttribute("aria-busy") === "true";
    const noteItem = (id) => Array.from(notesBox.querySelectorAll("li.card-note")).find((li) => li.getAttribute("data-note") === id);
    // After an edit, removal or post, the focus moves on only when it is still where
    // that action left it: inside `from` (the edit form, the note's line, the Add a note
    // form, kept even once the list is drawn again), on nothing, or on an element gone
    // from the page. Someone who moved on, say into Add a note, keeps it.
    const focusFree = (from) => {
      const a = document.activeElement;
      return !a || a === document.body || a.isConnected === false || from.contains(a);
    };
    // What a removal says, below the list.
    const removeStatus = M.statusLine();

    function noteBody(n) {
      return removedNote(n) ? noteTombstone(ctx, n.body)
        : h("div", { class: "md" }, M.markdown(n.body, where, { mentions: n.mentions, hrefOf: (id) => ctx.link("team", id), ctx }));
    }

    // A note's author as the byline says it (@handle), as plain text for a button's label,
    // so a screen reader's list of buttons tells one note's Edit from the next.
    const whoOf = (n) => { const b = byline(ctx, n.author); return typeof b === "string" ? b : b.textContent; };

    function noteLine(n) {
      const actions = mayEdit(n) || mayRemove(n) ? h("span", { class: "card-note-actions" },
        mayEdit(n) ? h("button", { type: "button", class: "small card-note-edit", "aria-label": M.t("cardpanel.notes.edit.label_of", { who: whoOf(n), when: formatTime(n.created_at) }), onclick: () => editNote(n) }, M.t("cardpanel.notes.edit")) : null,
        mayRemove(n) ? h("button", { type: "button", class: "small card-note-remove", "aria-label": M.t("cardpanel.notes.remove.label_of", { who: whoOf(n), when: formatTime(n.created_at) }), onclick: () => removeNote(n) }, M.t("cardpanel.notes.remove")) : null) : null;
      return h("li", { class: "card-note", "data-note": n.id },
        h("p", { class: "muted" }, byline(ctx, n.author), " · " + formatTime(n.created_at)),
        !removedNote(n) && n.edited ? noteEdited(ctx, n.edited) : null,
        noteBody(n), actions);
    }

    // Edit in place: the text and, for someone else's note, the reason the hub
    // asks for (§6.16); Cancel or Escape leaves the note as it was.
    function editNote(n) {
      if (reading()) return;
      const li = noteItem(n.id);
      // The note as the edit was made on: its version is the edit's base_version
      // (§6.16); a conflict replaces it with the note as it is now.
      let read = n;
      if (!li || li.querySelector("form.card-note-edit-form")) return;
      const own = mine(n);
      const fieldId = "card-note-edit-" + n.id, reasonId = "card-note-reason-" + n.id;
      const text = M.dom.sendOnCtrlEnter(h("textarea", { id: fieldId, rows: "4", maxlength: "4096" }));
      text.value = n.body;
      const reasonError = h("p", { class: "field-error", id: reasonId + "-error", hidden: "" });
      const reason = h("input", { type: "text", id: reasonId, maxlength: "500", required: own ? null : "required", "aria-describedby": reasonId + "-error" });
      const save = h("button", { type: "submit" }, M.t("cardpanel.notes.edit.save"));
      const editStatus = M.statusLine();
      let saving = false;
      const back = () => {
        // Drop the form before the redraw so notes() does not keep this edit (Cancel / save).
        form.remove();
        notes().then((drawn) => {
          const b = drawn && noteItem(n.id) && noteItem(n.id).querySelector("button.card-note-edit");
          if (b && focusFree(form)) b.focus();
        });
      };
      const form = h("form", {
        class: "card-note-edit-form",
        onkeydown: (e) => { if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); back(); } },
        onsubmit: async (e) => {
          e.preventDefault();
          if (saving) return;
          if (!text.value.trim()) { text.focus(); return; }
          if (!own && !reason.value.trim()) {
            reasonError.textContent = M.t("cardpanel.notes.edit.reason_needed");
            reasonError.hidden = false;
            reason.setAttribute("aria-invalid", "true");
            reason.focus();
            return;
          }
          reasonError.hidden = true;
          reason.removeAttribute("aria-invalid");
          saving = true;
          save.disabled = true;
          editStatus.busy(M.t("cardpanel.notes.edit.saving"));
          const body = { body: text.value, base_version: read.version };
          if (reason.value.trim()) body.reason = reason.value.trim();
          try {
            await M.api.patch(base + "/notes/" + encodeURIComponent(n.id), body);
          } catch (err) {
            saving = false;
            save.disabled = false;
            const now = err && err.code === "conflict" && err.details ? err.details.note : null;
            // The hub checks a removal before the version (§6.16): a note removed meanwhile
            // answers `invalid` with `reason: "redacted"`, whatever version the edit names.
            const gone = !!(err && err.code === "invalid" && err.details && err.details.reason === "redacted");
            if (gone || (now && removedNote(now))) {
              // Removed meanwhile: nothing left to edit; the list shows the tombstone,
              // the line says the writer's text is gone with the form, and the focus
              // goes to the tombstone, as after a removal of one's own.
              await notes();
              removeStatus.fail("", { message: M.t("cardpanel.notes.edit.conflict_removed") });
              focusStone(n.id, form);
              return;
            }
            if (now) {
              // Changed meanwhile: show the text as it is now, keep the writer's own,
              // and the next save is made on the version just read.
              read = now;
              const shown = form.querySelector(".card-note-now");
              if (shown) shown.remove();
              form.insertBefore(h("div", { class: "card-note-now" },
                h("p", { class: "muted" }, M.t("cardpanel.notes.edit.now")), noteBody(now)), form.firstChild);
              editStatus.fail("", { message: M.t("cardpanel.notes.edit.conflict") });
              return;
            }
            editStatus.fail(M.t("cardpanel.notes.edit.not_saved"), M.boardEdit ? M.boardEdit.said(err) : err);
            return;
          }
          back();
        },
      },
      h("label", { for: fieldId }, M.t("cardpanel.notes.edit.field")), text, M.projectMentionPicker(ctx, text),
      h("label", { for: reasonId }, own ? M.t("cardpanel.notes.edit.reason") : M.t("cardpanel.notes.edit.reason_required")), reason, reasonError,
      h("p", { class: "hint" }, M.t("cardpanel.notes.edit.hint")),
      h("span", { class: "card-note-edit-actions" }, save,
        h("button", { type: "button", class: "secondary", onclick: () => back() }, M.t("cardpanel.notes.edit.cancel"))),
      editStatus.el);
      Array.from(li.querySelectorAll(".md, .card-note-actions")).forEach((x) => x.remove());
      append(li, form);
      text.focus();
    }

    // Remove for everyone (§8.5): the text becomes the tombstone, the note keeps its place.
    async function removeNote(n) {
      if (reading()) return;
      // The note's line as it is now: Remove, which had the focus, is in it.
      const line = noteItem(n.id);
      const reason = askRemoveReason();
      if (reason === null) return;
      removeStatus.busy(M.t("cardpanel.notes.remove.busy"));
      try {
        await M.api.post(base + "/notes/" + encodeURIComponent(n.id) + "/redact", { reason, base_version: n.version });
      } catch (err) {
        if (err && err.code === "conflict") {
          // Changed meanwhile: the list shows the text as it is now, nothing was removed;
          // or someone removed it first, and the list shows its tombstone.
          await notes();
          const now = err.details && err.details.note;
          if (now && removedNote(now)) removeStatus.busy(M.t("cardpanel.notes.remove.already"));  // a plain line, no failure
          else removeStatus.fail("", { message: M.t("cardpanel.notes.remove.conflict") });
          return;
        }
        removeStatus.fail(M.t("cardpanel.notes.remove.failed"), err);
        return;
      }
      await notes();
      removeStatus.done();
      // The button that had the focus is gone with the text.
      focusStone(n.id, line);
    }

    function focusStone(id, from) {
      const stone = noteItem(id) && noteItem(id).querySelector(".card-note-removed");
      if (stone && focusFree(from)) stone.focus();
    }

    async function notes() {
      // The list stays as drawn while it is read; the latest read alone replaces it.
      // Meanwhile its Edit and Remove wait: an edit begun on the old list would go with it.
      // An edit already open stays: its li is kept across the redraw (tsk-wvf8s7f44vz7).
      const read = ++notesRead;
      notesList.setAttribute("aria-busy", "true");
      notesList.querySelectorAll("button.card-note-edit, button.card-note-remove").forEach((b) => { b.disabled = true; });
      let list;
      try {
        list = (await M.api.getAll(base + "/notes?state=open")).items;
      } catch (err) {
        if (read !== notesRead) return false;
        notesList.removeAttribute("aria-busy");
        append(clear(notesList), h("p", { class: "send-status failed" }, M.t("cardpanel.notes.read_failed", { reason: err.message })));
        return true;
      }
      if (read !== notesRead) return false;
      notesList.removeAttribute("aria-busy");
      // Keep each open edit's li (form and typed text) when that note is still there.
      // Detaching the row blurs its field; remember focus and selection so a post's
      // "focus Add a note when free" does not steal them when the edit still held them.
      const openEdits = new Map();
      let restoreEdit = null;
      Array.from(notesList.querySelectorAll("li.card-note")).forEach((li) => {
        if (li.querySelector("form.card-note-edit-form")) {
          const a = document.activeElement;
          if (a && li.contains(a)) {
            restoreEdit = {
              el: a,
              start: typeof a.selectionStart === "number" ? a.selectionStart : null,
              end: typeof a.selectionEnd === "number" ? a.selectionEnd : null,
            };
          }
          openEdits.set(li.getAttribute("data-note"), li);
          li.remove();
        }
      });
      const rows = list.map((n) => {
        const kept = openEdits.get(n.id);
        if (kept && !removedNote(n)) {
          openEdits.delete(n.id);
          return kept;
        }
        return noteLine(n);
      });
      append(clear(notesList), list.length
        ? h("ul", { class: "card-note-list" }, rows)
        : h("p", { class: "muted" }, M.t("cardpanel.notes.none")), removeStatus.el);
      if (closed()) {
        if (noteFormEl) noteFormEl.remove();
        noteFormEl = null;
      } else if (!noteFormEl) {
        append(notesBox, noteFormEl = noteForm());
      }
      // Put the caret back only when that edit was kept and still owns the node; a
      // reader who moved focus elsewhere during the read is left alone (restoreEdit
      // is set only when the edit held focus at redraw).
      if (restoreEdit && restoreEdit.el.isConnected !== false && notesList.contains(restoreEdit.el)) {
        restoreEdit.el.focus();
        if (restoreEdit.start !== null && restoreEdit.end !== null) {
          if (typeof restoreEdit.el.setSelectionRange === "function") {
            restoreEdit.el.setSelectionRange(restoreEdit.start, restoreEdit.end);
          } else {
            restoreEdit.el.selectionStart = restoreEdit.start;
            restoreEdit.el.selectionEnd = restoreEdit.end;
          }
        }
      }
      return true;
    }

    // One post at a time: a second tap or Ctrl+Enter while the first is on its way
    // sends nothing; a refusal makes the button usable again. On success exactly the
    // text sent leaves the field; anything typed since stays.
    function noteForm() {
      const text = M.dom.sendOnCtrlEnter(h("textarea", { id: "card-note-body", rows: "3", maxlength: "4096", placeholder: M.t("cardpanel.notes.placeholder") }));
      const status = M.statusLine();
      const submit = h("button", { type: "submit" }, M.t("cardpanel.notes.post"));
      const form = h("form", {
        class: "card-note-form",
        onsubmit: async (e) => {
          e.preventDefault();
          if (posting !== null) return;
          if (!text.value.trim()) { text.focus(); return; }
          const sent = posting = text.value;
          submit.disabled = true;
          status.busy(M.t("cardpanel.notes.posting"));
          try {
            await M.api.post(base + "/notes", { body: sent });
          } catch (err) {
            posting = null;
            submit.disabled = false;
            status.fail(M.t("cardpanel.notes.not_posted"), M.boardEdit ? M.boardEdit.said(err) : err);
            return;
          }
          posting = null;
          submit.disabled = false;
          status.done();
          if (text.value === sent) text.value = "";
          await notes();
          if (focusFree(form)) text.focus();
        },
      },
      h("label", { for: "card-note-body" }, M.t("cardpanel.notes.add")), text, M.projectMentionPicker(ctx, text),
      h("p", { class: "hint" }, M.t("cardpanel.notes.hint")),
      submit, status.el);
      return form;
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
    // newest page of updates, this card's among them (context/board.md).
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
            h("div", { class: "md" }, M.markdown(m.body || "", where, { mentions: m.mentions, hrefOf: (id) => ctx.link("team", id), ctx })))))
          : h("p", { class: "muted" }, page.next_cursor === null ? M.t("cardpanel.updates.none") : M.t("cardpanel.updates.none_latest")));
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
