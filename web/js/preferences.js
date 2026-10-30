// Preferences (docs/api.md §19.4): how the human likes to work, one Markdown
// text that they alone write. /account/preferences edits it, with the
// projects whose agents read it and the earlier versions. An agent only
// proposes: the proposal is reviewed in the personal inbox (the current
// text, the proposed one, a diff, the reason) and accepted as it is,
// accepted after an edit, or declined. The hub never merges: a proposal
// written against an older version is merged by hand in the editor here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const CAP = 8 * 1024;
  const VERSIONS_PAGE = 20;

  // The cap is in bytes of UTF-8 (§1.7), not in characters.
  function utf8Length(text) {
    let n = 0;
    for (const ch of text) {
      const c = ch.codePointAt(0);
      n += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;
    }
    return n;
  }
  // KiB with one decimal at most, in the reader's locale.
  const kib = (n) => M.fmt.number(n / 1024, { maximumFractionDigits: 1 });
  // "1.5 of 8 KiB", and over the cap the same with what it means.
  // forSave: the editor's own text, which over the cap cannot be saved.
  function sizeText(n, forSave) {
    const values = { size: kib(n), cap: CAP / 1024 };
    if (n <= CAP) return M.t("prefs.size", values);
    return forSave ? M.t("prefs.size_over_save", values) : M.t("prefs.size_over", values);
  }

  // A line diff: the common start and end as they are, the rest from the
  // longest common subsequence. 8 KiB can hold thousands of lines, so the
  // table is bounded: past DIFF_CELLS the changed part is shown as removed
  // then added (`coarse`), which reads, where the table would freeze the page.
  const DIFF_CELLS = 250000;
  function diffLines(before, after) {
    const a = before ? before.split("\n") : [];
    const b = after ? after.split("\n") : [];
    let lo = 0;
    while (lo < a.length && lo < b.length && a[lo] === b[lo]) lo++;
    let hiA = a.length;
    let hiB = b.length;
    while (hiA > lo && hiB > lo && a[hiA - 1] === b[hiB - 1]) { hiA--; hiB--; }
    const same = (text) => ({ op: "same", text });
    const out = a.slice(0, lo).map(same);
    const n = hiA - lo;
    const m = hiB - lo;
    let coarse = false;
    if ((n + 1) * (m + 1) > DIFF_CELLS) {
      coarse = true;
      for (let i = lo; i < hiA; i++) out.push({ op: "del", text: a[i] });
      for (let j = lo; j < hiB; j++) out.push({ op: "add", text: b[j] });
    } else {
      // One flat table, row by row: cell (i, j) at i * (m + 1) + j.
      const w = m + 1;
      const t = new Array((n + 1) * w).fill(0);
      for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
          t[i * w + j] = a[lo + i] === b[lo + j] ? t[(i + 1) * w + j + 1] + 1 : Math.max(t[(i + 1) * w + j], t[i * w + j + 1]);
        }
      }
      let i = 0;
      let j = 0;
      while (i < n && j < m) {
        if (a[lo + i] === b[lo + j]) { out.push(same(a[lo + i])); i++; j++; }
        else if (t[(i + 1) * w + j] >= t[i * w + j + 1]) out.push({ op: "del", text: a[lo + i++] });
        else out.push({ op: "add", text: b[lo + j++] });
      }
      while (i < n) out.push({ op: "del", text: a[lo + i++] });
      while (j < m) out.push({ op: "add", text: b[lo + j++] });
    }
    a.slice(hiA).forEach((text) => out.push(same(text)));
    out.coarse = coarse;
    return out;
  }

  // Inline, one line per row: it reads the same at 390 px as at 1280.
  const SIGNS = { same: " ", del: "−", add: "+" };
  // Getters: the words are the catalog's when shown.
  const SAID = { same: "", get del() { return M.t("prefs.diff.removed"); }, get add() { return M.t("prefs.diff.added"); } };
  function diffView(before, after) {
    if (before === after) return h("p", { class: "muted" }, M.t("prefs.diff.same"));
    const lines = diffLines(before, after);
    return [lines.coarse ? h("p", { class: "hint" }, M.t("prefs.diff.coarse")) : null,
      h("ol", { class: "pref-diff", "aria-label": M.t("prefs.diff.label") },
      lines.map((d) => h("li", { class: "pref-" + d.op },
        h("span", { class: "pref-sign", "aria-hidden": "true" }, SIGNS[d.op]),
        SAID[d.op] ? h("span", { class: "visually-hidden" }, SAID[d.op]) : null,
        h("span", { class: "pref-line" }, d.text || " "))))];
  }

  const handleOf = (who) => (who && who.handle ? "@" + who.handle : who && (who.member_id || who.id)) || M.t("prefs.someone");
  // Who wrote a version, who proposed it, who confirmed it: facts with a
  // middle dot between them, each one whole.
  function provenance(v) {
    if (!v || !v.version) return M.t("prefs.not_written");
    const parts = [M.t("prefs.version", { version: String(v.version) })];
    if (v.by) parts.push(v.by.kind === "agent" ? M.t("prefs.by_agent", { who: handleOf(v.by) }) : M.t("prefs.by", { who: handleOf(v.by) }));
    if (v.proposed_by) {
      parts.push(v.proposed_by.project ? M.t("prefs.proposed_in", { who: handleOf(v.proposed_by), project: v.proposed_by.project })
        : M.t("prefs.proposed", { who: handleOf(v.proposed_by) }));
    }
    if (v.confirmed_by) parts.push(M.t("prefs.confirmed", { who: handleOf(v.confirmed_by) }));
    const at = v.updated_at || v.at;
    if (at) parts.push(formatTime(at));
    return parts.join(" · ");
  }

  // The hub's refusals, in words.
  function said(err) {
    const fields = err.details && err.details.fields;
    if (err.code === "invalid" && fields && fields.markdown) return { message: M.t("prefs.refused.too_long", { cap: CAP / 1024 }) };
    if (err.code === "rate_limited") return { message: M.t("prefs.refused.rate") };
    return err;
  }

  // /account/preferences: the editor, the projects, the earlier versions.
  async function section(ctx) {
    const heading = h("h3", { class: "preferences-heading", tabindex: "-1" }, M.t("prefs.title"));
    const el = h("section", { class: "preferences" }, heading);
    let mine;
    try {
      mine = await M.api.get("/me/preferences");
    } catch (err) {
      append(el, M.errorBox(err));
      return { el, heading };
    }

    const hintId = "preferences-hint";
    const sizeId = "preferences-size";
    const text = h("textarea", { id: "preferences-text", rows: "10", "aria-describedby": hintId + " " + sizeId });
    text.value = mine.markdown || "";
    const size = h("p", { class: "hint", id: sizeId, "aria-live": "polite" });
    const line = h("p", { class: "muted preferences-version" });
    const status = M.statusLine();
    const conflictBox = h("div", { class: "preferences-conflict" });
    const save = h("button", { type: "submit", class: "primary" }, M.t("prefs.save"));
    let shown = mine;

    const drawState = () => {
      const n = utf8Length(text.value);
      size.textContent = sizeText(n, true);
      size.classList.toggle("over", n > CAP);
      save.disabled = n > CAP || text.value === (shown.markdown || "");
    };
    const drawLine = () => { line.textContent = provenance(shown); };
    text.addEventListener("input", drawState);

    async function put(baseVersion) {
      save.disabled = true;
      status.busy(M.t("prefs.saving"));
      clear(conflictBox);
      try {
        shown = await M.api.put("/me/preferences", { markdown: text.value, base_version: baseVersion });
        drawLine();
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("prefs.saved", { version: String(shown.version) })));
      } catch (err) {
        if (err.code === "conflict") await conflicted();
        else status.fail(M.t("prefs.not_saved"), said(err));
      } finally {
        drawState();
      }
    }
    // Saved meanwhile (another tab, an accepted proposal): the human's text
    // stays in the editor, the newer one is shown beside it, and they choose.
    async function conflicted() {
      let now;
      try {
        now = await M.api.get("/me/preferences");
      } catch (err) {
        status.fail(M.t("prefs.conflict.unread"), err);
        return;
      }
      status.done();
      const takeTheirs = h("button", { type: "button", onclick: () => {
        shown = now; text.value = now.markdown || ""; clear(conflictBox); drawLine(); drawState(); text.focus();
      } }, M.t("prefs.conflict.take", { version: String(now.version) }));
      const keepMine = h("button", { type: "button", onclick: () => { shown = now; drawLine(); put(now.version); } }, M.t("prefs.conflict.keep"));
      append(clear(conflictBox),
        h("p", { class: "flag", role: "alert" }, M.t("prefs.conflict.said", { now: provenance(now) })),
        h("h4", { class: "sub" }, M.t("prefs.conflict.diff", { version: String(now.version) })),
        diffView(now.markdown || "", text.value),
        h("div", { class: "actions" }, takeTheirs, keepMine));
    }

    const form = h("form", {
      class: "preferences-form",
      onsubmit: (e) => { e.preventDefault(); if (!save.disabled) put(shown.version); },
    },
    h("label", { for: "preferences-text" }, M.t("prefs.label")),
    h("p", { class: "hint", id: hintId }, M.t("prefs.hint")),
    text, size,
    h("div", { class: "actions" }, save),
    status.el, conflictBox);
    M.dom.sendOnCtrlEnter(text, () => { if (!save.disabled) put(shown.version); }, save);
    drawLine();
    drawState();

    append(el, h("p", { class: "muted" }, M.t("prefs.intro")),
      line, form, projectsBox(ctx, mine.projects || []), versionsBox());
    return { el, heading };
  }

  // Per project: whether its agents read the preferences (on by default).
  function projectsBox(ctx, projects) {
    if (!projects.length) return null;
    const nameOf = (full) => (ctx.projects.find((p) => p.full_name === full) || { name: full }).name;
    const status = M.statusLine();
    return h("fieldset", { class: "preferences-projects" },
      h("legend", null, M.t("prefs.projects.legend")),
      h("ul", null, projects.map((p) => {
        const id = "preferences-in-" + String(p.full_name).replace("/", "-");
        const box = h("input", { type: "checkbox", id, checked: p.include });
        box.checked = p.include;
        box.addEventListener("change", async () => {
          const want = box.checked;
          box.disabled = true;
          status.busy(M.t("prefs.saving"));
          try {
            await M.api.put("/me/preferences/projects/" + M.api.projectPath(p.full_name), { include: want });
            p.include = want;
            status.done();
          } catch (err) {
            box.checked = !want;
            status.fail(M.t("prefs.projects.failed", { name: nameOf(p.full_name) }), err);
          } finally {
            box.disabled = false;
          }
        });
        return h("li", null, box, h("label", { for: id }, nameOf(p.full_name)));
      })),
      h("p", { class: "hint" }, M.t("prefs.projects.hint")),
      status.el);
  }

  // Earlier versions, read when opened.
  function versionsBox() {
    const list = h("ol", { class: "preferences-versions" });
    const status = M.statusLine();
    const more = h("button", { type: "button", class: "small", hidden: true }, M.t("prefs.versions.older"));
    more.hidden = true;
    let cursor = null;
    let read = false;
    async function page() {
      more.disabled = true;
      status.busy(M.t("prefs.versions.reading"));
      try {
        const got = await M.api.get("/me/preferences/versions?limit=" + VERSIONS_PAGE + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
        append(list, got.items.map((v) => h("li", null,
          h("p", { class: "muted" }, provenance(v)),
          v.markdown ? h("pre", { class: "preferences-text" }, v.markdown) : h("p", { class: "muted" }, M.t("prefs.empty")))));
        if (!got.items.length && !cursor) append(list, h("li", { class: "muted" }, M.t("prefs.versions.none")));
        cursor = got.next_cursor;
        more.hidden = !cursor;
        status.done();
      } catch (err) {
        status.fail(M.t("prefs.versions.failed"), err);
      } finally {
        more.disabled = false;
      }
    }
    more.addEventListener("click", page);
    const box = h("details", { class: "preferences-history" }, h("summary", null, M.t("prefs.versions.title")), list, more, status.el);
    box.addEventListener("toggle", () => { if (box.open && !read) { read = true; page(); } });
    return box;
  }

  const isProposal = (req) => !!(req && req.memory_proposal && req.memory_proposal.store === "preferences");

  // The review of an open proposal, in the personal inbox. `answer(payload)`
  // sends it and resolves once the inbox moved on; it rejects with the
  // hub's error, which this review says in its own words.
  function review(ctx, req, answer) {
    const box = h("div", { class: "pref-review", "aria-busy": "true" },
      h("p", { class: "muted" }, M.t("prefs.review.reading")));
    // What the human typed outlives a redraw: a conflict shows the review
    // again against the newer version, with their edit and reason kept.
    const kept = { draft: null, editing: false, why: "" };
    let drawn = false;
    const draw = (full) => {
      drawn = true;
      box.removeAttribute("aria-busy");
      const p = full.memory_proposal;
      const current = p.current || { markdown: "", version: 0 };
      const stale = !!p.stale;
      const status = M.statusLine();
      const actions = h("div", { class: "actions pref-actions" });
      const busy = (yes) => box.querySelectorAll("button, textarea").forEach((x) => { x.disabled = yes; });
      const sendIt = async (payload, words) => {
        busy(true);
        status.busy(words);
        try {
          await answer(payload);
        } catch (err) {
          busy(false);
          if (err.code === "conflict") {
            status.done();
            const v = err.details && err.details.current_version;
            reload(v ? M.t("prefs.review.changed", { version: String(v) }) : M.t("prefs.review.changed_newer"));
          } else {
            status.fail(M.t("prefs.review.not_sent"), said(err));
          }
        }
      };

      const why = h("textarea", { id: "pref-why-" + req.id, rows: "2", placeholder: M.t("prefs.review.why_placeholder") });
      why.value = kept.why;
      why.addEventListener("input", () => { kept.why = why.value; });
      const decline = h("button", { type: "button", class: "reply", onclick: () => {
        const text = why.value.trim();
        sendIt(text ? { reply_id: "no", text } : { reply_id: "no" }, M.t("prefs.review.declining"));
      } }, M.t("prefs.review.decline"));
      const editor = h("textarea", { id: "pref-edit-" + req.id, rows: "10" });
      editor.value = kept.draft !== null ? kept.draft : p.markdown;
      const editSize = h("p", { class: "hint", "aria-live": "polite" });
      const drawEditSize = () => { editSize.textContent = sizeText(utf8Length(editor.value), false); };
      editor.addEventListener("input", () => { kept.draft = editor.value; drawEditSize(); });
      drawEditSize();
      const acceptEdit = () => {
        if (utf8Length(editor.value) > CAP) { editor.focus(); return; }
        sendIt({ reply_id: "go", markdown: editor.value, base_version: current.version }, M.t("prefs.review.accepting_edit"));
      };
      const acceptEditButton = h("button", { type: "button", class: "reply primary", onclick: acceptEdit }, M.t("prefs.review.accept_edit"));
      M.dom.sendOnCtrlEnter(editor, acceptEdit, acceptEditButton);
      const editPane = h("div", { class: "pref-edit", hidden: true },
        h("label", { for: editor.id }, stale ? M.t("prefs.review.merge_label", { keys: M.dom.SEND_KEYS }) : M.t("prefs.review.edit_label", { keys: M.dom.SEND_KEYS })),
        editor, editSize,
        h("div", { class: "actions" },
          // Cancel drops the edit: the next Edit starts from the proposal again.
          h("button", { type: "button", onclick: () => {
            kept.editing = false; kept.draft = null; editor.value = p.markdown; drawEditSize();
            editPane.hidden = true; editButton.hidden = false; editButton.focus();
          } }, M.t("prefs.review.cancel")),
          acceptEditButton));
      editPane.hidden = !kept.editing;
      const editButton = h("button", { type: "button", class: "reply", onclick: () => {
        kept.editing = true; editPane.hidden = false; editButton.hidden = true; editor.focus();
      } }, stale ? M.t("prefs.review.merge") : M.t("prefs.review.edit"));
      editButton.hidden = kept.editing;
      // A plain go on a stale base would drop the newer text unread (§19.4).
      const accept = stale ? null : h("button", { type: "button", class: "reply primary", onclick: () => sendIt({ reply_id: "go" }, M.t("prefs.review.accepting")) }, M.t("prefs.review.accept"));
      append(actions, decline, editButton, accept);

      append(clear(box),
        h("h3", { class: "sub" }, M.t("prefs.review.title")),
        p.reason ? h("p", null, M.tn("prefs.review.why", { reason: p.reason, label: h("strong", null, M.t("prefs.review.why_label")) })) : null,
        stale ? h("p", { class: "flag", role: "note" },
          M.t("prefs.review.stale", { base: String(p.base_version), version: String(current.version) })) : null,
        h("h4", { class: "sub" }, M.t("prefs.review.diff", { version: String(current.version) })),
        diffView(current.markdown, p.markdown),
        h("details", { class: "pref-texts" }, h("summary", null, M.t("prefs.review.both")),
          h("h4", { class: "sub" }, M.t("prefs.review.yours")), current.markdown ? h("pre", { class: "preferences-text" }, current.markdown) : h("p", { class: "muted" }, M.t("prefs.empty")),
          h("h4", { class: "sub" }, M.t("prefs.review.proposed")), p.markdown ? h("pre", { class: "preferences-text" }, p.markdown) : h("p", { class: "muted" }, M.t("prefs.empty"))),
        editPane,
        h("div", { class: "free-text" }, h("label", { for: why.id }, M.t("prefs.review.why_declining")), why),
        actions,
        status.el);
      // Drawn again while editing: the focus goes back into the edit.
      if (kept.editing) window.setTimeout(() => editor.focus(), 0);
    };
    // A failed read leaves a drawn review as it was, the edit included.
    const fail = (err) => {
      box.removeAttribute("aria-busy");
      if (drawn) box.insertBefore(h("p", { class: "send-status failed", role: "alert" }, M.t("prefs.review.reread_failed", { reason: err.message || err.code })), box.firstChild);
      else append(clear(box), M.errorBox(err));
    };
    // The inbox read the request on its own (js/inbox.js): its proposal
    // carries the human's current text. After a conflict it is read again.
    function reload(note) {
      M.api.get("/requests/" + encodeURIComponent(req.id)).then((full) => {
        draw(full);
        if (note) box.insertBefore(h("p", { class: "flag", role: "alert" }, note), box.firstChild);
      }, fail);
    }
    if (req.memory_proposal.current) draw(req);
    else reload();
    return box;
  }

  // An answered proposal: what became of it.
  function outcome(req) {
    const r = req.memory_proposal && req.memory_proposal.result;
    if (!r) return null;
    return h("p", { class: "muted" }, r.edited ? M.t("prefs.outcome.edited", { version: String(r.version) }) : M.t("prefs.outcome.as_proposed", { version: String(r.version) }));
  }

  // On an agent's card, for its owner only (§19.4): its resume carries the
  // owner's current preferences, a live reference, seen by no other member.
  function ownerToggle(ctx, m) {
    const id = "owner-preferences-" + m.id;
    const box = h("input", { type: "checkbox", id, checked: !!m.owner_preferences });
    box.checked = !!m.owner_preferences;
    const status = M.statusLine();
    box.addEventListener("change", async () => {
      const want = box.checked;
      box.disabled = true;
      status.busy(M.t("prefs.saving"));
      try {
        await M.api.patch(ctx.base + "/members/" + encodeURIComponent(m.id), { owner_preferences: want });
        m.owner_preferences = want;
        status.done();
      } catch (err) {
        box.checked = !want;
        status.fail(M.t("prefs.owner.failed"), err);
      } finally {
        box.disabled = false;
      }
    });
    return h("div", { class: "owner-preferences" },
      box, h("label", { for: id }, M.t("prefs.owner.label")),
      h("p", { class: "hint" }, M.t("prefs.owner.hint")),
      status.el);
  }

  M.preferences = { section, review, outcome, ownerToggle, isProposal, diffLines, utf8Length };
})(window.Maity);
