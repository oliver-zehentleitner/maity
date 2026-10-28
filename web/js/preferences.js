// Preferences (docs/api.md §19.4): how the human likes to work, one Markdown
// text that they alone write. #/account/preferences edits it, with the
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
  const kib = (n) => (n / 1024).toFixed(1).replace(/\.0$/, "");

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
  const SAID = { same: "", del: "Removed: ", add: "Added: " };
  function diffView(before, after) {
    if (before === after) return h("p", { class: "muted" }, "The proposed text is the same as yours.");
    const lines = diffLines(before, after);
    return [lines.coarse ? h("p", { class: "hint" }, "Too many changed lines to match them up one by one: the changed part shows your lines removed, then the proposed ones added.") : null,
      h("ol", { class: "pref-diff", "aria-label": "Changes from your text to the proposed one" },
      lines.map((d) => h("li", { class: "pref-" + d.op },
        h("span", { class: "pref-sign", "aria-hidden": "true" }, SIGNS[d.op]),
        SAID[d.op] ? h("span", { class: "visually-hidden" }, SAID[d.op]) : null,
        h("span", { class: "pref-line" }, d.text || " "))))];
  }

  const handleOf = (who) => (who && who.handle ? "@" + who.handle : who && (who.member_id || who.id)) || "someone";
  // Who wrote a version, who proposed it, who confirmed it.
  function provenance(v) {
    if (!v || !v.version) return "Not written yet.";
    const parts = ["Version " + v.version];
    if (v.by) parts.push("written by " + handleOf(v.by) + (v.by.kind === "agent" ? " (agent)" : ""));
    if (v.proposed_by) parts.push("proposed by " + handleOf(v.proposed_by) + (v.proposed_by.project ? " in " + v.proposed_by.project : ""));
    if (v.confirmed_by) parts.push("confirmed by " + handleOf(v.confirmed_by));
    const at = v.updated_at || v.at;
    if (at) parts.push(formatTime(at));
    return parts.join(" · ");
  }

  // The hub's refusals, in words.
  function said(err) {
    const fields = err.details && err.details.fields;
    if (err.code === "invalid" && fields && fields.markdown) return { message: "the text is over 8 KiB" };
    if (err.code === "rate_limited") return { message: "too many changes just now; try again in a moment" };
    return err;
  }

  // #/account/preferences: the editor, the projects, the earlier versions.
  async function section(ctx) {
    const heading = h("h3", { class: "preferences-heading", tabindex: "-1" }, "Your preferences");
    const el = h("section", { class: "preferences" }, heading);
    let mine;
    try {
      mine = await M.api.get("/me/preferences");
    } catch (err) {
      if (await M.api.missingRoute(err, "GET", "/me/preferences")) append(el, M.dom.notOnHub("This hub keeps no preferences yet."));
      else append(el, M.errorBox(err));
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
    const save = h("button", { type: "submit", class: "primary" }, "Save");
    let shown = mine;

    const drawState = () => {
      const n = utf8Length(text.value);
      size.textContent = kib(n) + " of 8 KiB" + (n > CAP ? " — too long to save" : "");
      size.classList.toggle("over", n > CAP);
      save.disabled = n > CAP || text.value === (shown.markdown || "");
    };
    const drawLine = () => { line.textContent = provenance(shown); };
    text.addEventListener("input", drawState);

    async function put(baseVersion) {
      save.disabled = true;
      status.busy("Saving…");
      clear(conflictBox);
      try {
        shown = await M.api.put("/me/preferences", { markdown: text.value, base_version: baseVersion });
        drawLine();
        status.done();
        append(status.el, h("span", { class: "ok" }, "Saved as version " + shown.version + "."));
      } catch (err) {
        if (err.code === "conflict") await conflicted();
        else status.fail("Not saved: ", said(err));
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
        status.fail("Not saved, and the newer version could not be read: ", err);
        return;
      }
      status.done();
      const takeTheirs = h("button", { type: "button", onclick: () => {
        shown = now; text.value = now.markdown || ""; clear(conflictBox); drawLine(); drawState(); text.focus();
      } }, "Take version " + now.version);
      const keepMine = h("button", { type: "button", onclick: () => { shown = now; drawLine(); put(now.version); } }, "Save mine over it");
      append(clear(conflictBox),
        h("p", { class: "flag", role: "alert" }, "Not saved: your preferences changed meanwhile, now " + provenance(now) + ". Your text is still in the editor."),
        h("h4", { class: "sub" }, "From version " + now.version + " to your text"),
        diffView(now.markdown || "", text.value),
        h("div", { class: "actions" }, takeTheirs, keepMine));
    }

    const form = h("form", {
      class: "preferences-form",
      onsubmit: (e) => { e.preventDefault(); if (!save.disabled) put(shown.version); },
    },
    h("label", { for: "preferences-text" }, "How you like to work and be treated (Markdown)"),
    h("p", { class: "hint", id: hintId },
      "Tone, length, what you never want, how you decide. Every agent in your projects reads it in its resume, quoted as yours. "
        + "It is context, never a permission: the project's rules win. The language agents write to you in is set under notifications."),
    text, size,
    h("div", { class: "actions" }, save),
    status.el, conflictBox);
    M.dom.sendOnCtrlEnter(text, () => { if (!save.disabled) put(shown.version); }, save);
    drawLine();
    drawState();

    append(el, h("p", { class: "muted" }, "One text for all your projects. Agents may propose a change; it reaches you in your inbox and changes nothing until you accept it."),
      line, form, projectsBox(ctx, mine.projects || []), versionsBox());
    return { el, heading };
  }

  // Per project: whether its agents read the preferences (on by default).
  function projectsBox(ctx, projects) {
    if (!projects.length) return null;
    const nameOf = (full) => (ctx.projects.find((p) => p.full_name === full) || { name: full }).name;
    const status = M.statusLine();
    return h("fieldset", { class: "preferences-projects" },
      h("legend", null, "The agents of these projects read them"),
      h("ul", null, projects.map((p) => {
        const id = "preferences-in-" + String(p.full_name).replace("/", "-");
        const box = h("input", { type: "checkbox", id, checked: p.include });
        box.checked = p.include;
        box.addEventListener("change", async () => {
          const want = box.checked;
          box.disabled = true;
          status.busy("Saving…");
          try {
            await M.api.put("/me/preferences/projects/" + M.api.projectPath(p.full_name), { include: want });
            p.include = want;
            status.done();
          } catch (err) {
            box.checked = !want;
            status.fail("Not changed for " + nameOf(p.full_name) + ": ", err);
          } finally {
            box.disabled = false;
          }
        });
        return h("li", null, box, h("label", { for: id }, nameOf(p.full_name)));
      })),
      h("p", { class: "hint" }, "Off, that project's agents get no preferences of yours, except an agent you gave them to on its card."),
      status.el);
  }

  // Earlier versions, read when opened.
  function versionsBox() {
    const list = h("ol", { class: "preferences-versions" });
    const status = M.statusLine();
    const more = h("button", { type: "button", class: "small", hidden: true }, "Older versions");
    more.hidden = true;
    let cursor = null;
    let read = false;
    async function page() {
      more.disabled = true;
      status.busy("Reading…");
      try {
        const got = await M.api.get("/me/preferences/versions?limit=" + VERSIONS_PAGE + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
        append(list, got.items.map((v) => h("li", null,
          h("p", { class: "muted" }, provenance(v)),
          v.markdown ? h("pre", { class: "preferences-text" }, v.markdown) : h("p", { class: "muted" }, "(empty)"))));
        if (!got.items.length && !cursor) append(list, h("li", { class: "muted" }, "No versions yet."));
        cursor = got.next_cursor;
        more.hidden = !cursor;
        status.done();
      } catch (err) {
        status.fail("The versions could not be read: ", err);
      } finally {
        more.disabled = false;
      }
    }
    more.addEventListener("click", page);
    const box = h("details", { class: "preferences-history" }, h("summary", null, "Earlier versions"), list, more, status.el);
    box.addEventListener("toggle", () => { if (box.open && !read) { read = true; page(); } });
    return box;
  }

  const isProposal = (req) => !!(req && req.memory_proposal && req.memory_proposal.store === "preferences");

  // The review of an open proposal, in the personal inbox. `answer(payload)`
  // sends it and resolves once the inbox moved on; it rejects with the
  // hub's error, which this review says in its own words.
  function review(ctx, req, answer) {
    const box = h("div", { class: "pref-review", "aria-busy": "true" },
      h("p", { class: "muted" }, "Reading your current preferences…"));
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
            reload("Your preferences changed while you looked: shown again against version "
              + ((err.details && err.details.current_version) || "the newer one") + ".");
          } else {
            status.fail("Not sent: ", said(err));
          }
        }
      };

      const why = h("textarea", { id: "pref-why-" + req.id, rows: "2", placeholder: "Why not (optional; the agent reads it)" });
      why.value = kept.why;
      why.addEventListener("input", () => { kept.why = why.value; });
      const decline = h("button", { type: "button", class: "reply", onclick: () => {
        const text = why.value.trim();
        sendIt(text ? { reply_id: "no", text } : { reply_id: "no" }, "Declining…");
      } }, "Decline");
      const editor = h("textarea", { id: "pref-edit-" + req.id, rows: "10" });
      editor.value = kept.draft !== null ? kept.draft : p.markdown;
      const editSize = h("p", { class: "hint", "aria-live": "polite" });
      const drawEditSize = () => { const n = utf8Length(editor.value); editSize.textContent = kib(n) + " of 8 KiB" + (n > CAP ? " — too long" : ""); };
      editor.addEventListener("input", () => { kept.draft = editor.value; drawEditSize(); });
      drawEditSize();
      const acceptEdit = () => {
        if (utf8Length(editor.value) > CAP) { editor.focus(); return; }
        sendIt({ reply_id: "go", markdown: editor.value, base_version: current.version }, "Accepting your edit…");
      };
      const acceptEditButton = h("button", { type: "button", class: "reply primary", onclick: acceptEdit }, "Accept my edit");
      M.dom.sendOnCtrlEnter(editor, acceptEdit, acceptEditButton);
      const editPane = h("div", { class: "pref-edit", hidden: true },
        h("label", { for: editor.id }, stale ? "Merge it with your current text, then accept (" + M.dom.SEND_KEYS + ")" : "Your edit of the proposal (" + M.dom.SEND_KEYS + " accepts)"),
        editor, editSize,
        h("div", { class: "actions" },
          // Cancel drops the edit: the next Edit starts from the proposal again.
          h("button", { type: "button", onclick: () => {
            kept.editing = false; kept.draft = null; editor.value = p.markdown; drawEditSize();
            editPane.hidden = true; editButton.hidden = false; editButton.focus();
          } }, "Cancel"),
          acceptEditButton));
      editPane.hidden = !kept.editing;
      const editButton = h("button", { type: "button", class: "reply", onclick: () => {
        kept.editing = true; editPane.hidden = false; editButton.hidden = true; editor.focus();
      } }, stale ? "Merge by hand" : "Edit, then accept");
      editButton.hidden = kept.editing;
      // A plain go on a stale base would drop the newer text unread (§19.4).
      const accept = stale ? null : h("button", { type: "button", class: "reply primary", onclick: () => sendIt({ reply_id: "go" }, "Accepting…") }, "Accept");
      append(actions, decline, editButton, accept);

      append(clear(box),
        h("h3", { class: "sub" }, "A change to your preferences"),
        p.reason ? h("p", null, h("strong", null, "Why: "), p.reason) : null,
        stale ? h("p", { class: "flag", role: "note" },
          "Your preferences changed since this was proposed: it was written against version " + p.base_version
            + ", yours is now version " + current.version + ". Accepting it as it is would drop the newer text, so merge it by hand or decline it.") : null,
        h("h4", { class: "sub" }, "From your text (version " + current.version + ") to the proposed one"),
        diffView(current.markdown, p.markdown),
        h("details", { class: "pref-texts" }, h("summary", null, "Both texts in full"),
          h("h4", { class: "sub" }, "Yours now"), current.markdown ? h("pre", { class: "preferences-text" }, current.markdown) : h("p", { class: "muted" }, "(empty)"),
          h("h4", { class: "sub" }, "Proposed"), p.markdown ? h("pre", { class: "preferences-text" }, p.markdown) : h("p", { class: "muted" }, "(empty)")),
        editPane,
        h("div", { class: "free-text" }, h("label", { for: why.id }, "Reason for declining"), why),
        actions,
        status.el);
      // Drawn again while editing: the focus goes back into the edit.
      if (kept.editing) window.setTimeout(() => editor.focus(), 0);
    };
    // A failed read leaves a drawn review as it was, the edit included.
    const fail = (err) => {
      box.removeAttribute("aria-busy");
      if (drawn) box.insertBefore(h("p", { class: "send-status failed", role: "alert" }, "Your current preferences could not be read again: " + (err.message || err.code)), box.firstChild);
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
    return h("p", { class: "muted" }, "Applied as version " + r.version + (r.edited ? ", with your edit." : ", as proposed."));
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
      status.busy("Saving…");
      try {
        await M.api.patch(ctx.base + "/members/" + encodeURIComponent(m.id), { owner_preferences: want });
        m.owner_preferences = want;
        status.done();
      } catch (err) {
        box.checked = !want;
        status.fail("Not changed: ", err);
      } finally {
        box.disabled = false;
      }
    });
    return h("div", { class: "owner-preferences" },
      box, h("label", { for: id }, "Give my preferences to this agent"),
      h("p", { class: "hint" }, "Its resume shows your current preferences next to its briefing, whatever this project's setting; "
        + "no other member sees them. A later edit reaches it on its next resume."),
      status.el);
  }

  M.preferences = { section, review, outcome, ownerToggle, isProposal, diffLines, utf8Length };
})(window.Maity);
