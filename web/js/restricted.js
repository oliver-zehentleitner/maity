// A card's restricted text and the project's restricted-access set (docs/api.md §6.1
// "Restricted access", §6.4 "Restricted text"): the "Restricted" box on a card, for a
// member in the set only, and the setting in the project's settings, changed by a human
// with project:admin after a step-up (§2.8.4). The text is kept in memory only: never in
// the browser's storage, a URL or a cache (§6.4 "Caching"), and shown as plain text.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const MODES = ["nobody_except", "all_except"];
  // Unicode code points, as the hub counts them (§6.4 "The text").
  const MAX = 1000;
  const length = (s) => [...s].length;
  const setting = (ctx) => ((ctx.project && ctx.project.settings) || {}).restricted_access || null;

  // Who is in the set (§6.1 "Who is in the set"), as the hub resolves it, from the
  // members the page knows: for the preview before a change that widens the set. An
  // active member without trust guest that is not isolated; an agent only while its
  // owner is an active member without trust guest, and under all_except only while its
  // owner is in the set too.
  function resolve(value, members) {
    const found = new Set();
    if (!value || !MODES.includes(value.mode)) return found;
    const listed = new Set(value.members || []);
    const allExcept = value.mode === "all_except";
    const named = (id) => (allExcept ? !listed.has(id) : listed.has(id));
    const seated = (m) => !!m && m.kind === "human" && m.trust !== "guest";
    const eligible = (m) => !!m && m.trust !== "guest" && !m.isolated;
    const byId = {};
    (members || []).forEach((m) => { byId[m.id] = m; });
    const humanIn = (m) => seated(m) && eligible(m) && named(m.id);
    (members || []).forEach((m) => {
      if (m.kind !== "agent") {
        if (humanIn(m)) found.add(m.id);
        return;
      }
      const owner = byId[m.owner_id];
      if (!(eligible(m) && seated(owner) && named(m.id))) return;
      if (allExcept && !humanIn(owner)) return;
      found.add(m.id);
    });
    return found;
  }

  // A member as the setting and the preview name it: an agent with its owner next to it (§6.1).
  function who(ctx, m) {
    const name = (x) => (x.display_name || x.handle || x.id) + (x.handle ? " (@" + x.handle + ")" : "");
    if (m.kind !== "agent") return name(m);
    const owner = (ctx.memberById || {})[m.owner_id];
    return M.t("restricted.agent_of", { agent: name(m), owner: owner ? name(owner) : m.owner_id || "—" });
  }

  // ---- the setting (§6.1) ---------------------------------------------------

  const FIELD_WORDS = {
    unknown_mode: () => M.t("restricted.settings.error.unknown_mode"),
    too_many: () => M.t("restricted.settings.error.too_many"),
    duplicate: () => M.t("restricted.settings.error.duplicate"),
    not_a_member: () => M.t("restricted.settings.error.not_a_member"),
    guest: () => M.t("restricted.settings.error.guest"),
    owner_not_a_member: () => M.t("restricted.settings.error.owner_not_a_member"),
  };
  const fieldWords = (why) => (Object.hasOwn(FIELD_WORDS, why) ? FIELD_WORDS[why]() : why);

  // The section in the project's settings, for those with project:admin. A human edits it;
  // an admin agent reads only its mode and whether it is in the set (`{mode, included}`).
  // `saved(words)` draws the settings again with what the save did.
  function settingsSection(ctx, saved) {
    const value = setting(ctx);
    const section = h("section", { class: "restricted-settings", id: "restricted-access", "aria-labelledby": "restricted-title" },
      h("h2", { class: "panel-title", id: "restricted-title" }, M.t("restricted.settings.title")),
      h("p", { class: "hint" }, M.t("restricted.settings.hint")),
      h("p", { class: "restricted-not-encryption" }, M.t("restricted.not_encryption")));
    if (ctx.me.kind !== "human") {
      append(section, h("p", { class: "restricted-state" }, !value ? M.t("restricted.settings.closed")
        : value.included ? M.t("restricted.settings.you_in", { mode: modeWords(value.mode) })
          : M.t("restricted.settings.you_out", { mode: modeWords(value.mode) })));
      return section;
    }
    const stored = value ? { mode: value.mode, members: (value.members || []).slice() } : null;
    const members = ctx.members || [];
    const now = resolve(stored, members);
    const inSetNow = members.filter((m) => now.has(m.id));
    append(section,
      h("p", { class: "restricted-state" }, !stored ? M.t("restricted.settings.closed")
        : inSetNow.length ? M.t("restricted.settings.in_set", { list: inSetNow.map((m) => who(ctx, m)).join(", ") })
          : M.t("restricted.settings.nobody")),
      value && typeof value.cards_with_text === "number"
        ? h("p", { class: "restricted-count" }, M.t("restricted.settings.cards", { count: value.cards_with_text })) : null);

    const mode = h("select", { id: "restricted-mode" },
      h("option", { value: "" }, M.t("restricted.mode.closed")),
      MODES.map((v) => h("option", { value: v }, modeWords(v))));
    mode.value = stored ? stored.mode : "";
    const modeHint = h("p", { class: "hint", id: "restricted-mode-hint" });
    // The list: every member of the project, and an id the stored list holds that is no
    // member now, kept as it is (§6.1 "The list is never pruned"). A guest is never in the set.
    const listed = stored ? stored.members : [];
    const rows = members.map((m) => ({ id: m.id, label: who(ctx, m), guest: m.trust === "guest" }))
      .concat(listed.filter((id) => !members.some((m) => m.id === id))
        .map((id) => ({ id, label: M.t("restricted.settings.gone", { id }), guest: false })));
    const boxes = rows.map((r) => {
      const box = h("input", { type: "checkbox", id: "restricted-member-" + r.id, value: r.id,
        disabled: r.guest && !listed.includes(r.id) ? true : null });
      box.checked = listed.includes(r.id);
      return box;
    });
    const list = h("fieldset", { class: "restricted-members" },
      h("legend", { id: "restricted-members-legend" }),
      rows.map((r, i) => h("label", { class: "check", for: "restricted-member-" + r.id }, boxes[i], " ", r.label,
        r.guest ? h("span", { class: "muted" }, " " + M.t("restricted.settings.guest_never")) : null)));
    const drawMode = () => {
      modeHint.textContent = mode.value === "all_except" ? M.t("restricted.mode.hint.all_except")
        : mode.value === "nobody_except" ? M.t("restricted.mode.hint.nobody_except") : M.t("restricted.mode.hint.closed");
      list.hidden = !mode.value;
      list.querySelector("legend").textContent = mode.value === "all_except"
        ? M.t("restricted.settings.members.all_except") : M.t("restricted.settings.members.nobody_except");
    };
    mode.addEventListener("change", drawMode);
    drawMode();
    const errors = h("ul", { class: "field-error restricted-errors", role: "alert" });
    const confirmBox = h("div", { class: "restricted-confirm", hidden: true });
    const stepSlot = h("div", { class: "step-up-slot" });
    stepSlot.hidden = true;
    const status = M.statusLine();
    const save = h("button", { type: "submit" }, M.t("restricted.settings.save"));

    const edited = () => (mode.value ? { mode: mode.value, members: rows.filter((r, i) => boxes[i].checked).map((r) => r.id) } : null);
    const same = (a, b) => (!a && !b) || (!!a && !!b && a.mode === b.mode
      && a.members.length === b.members.length && a.members.every((id) => b.members.includes(id)));

    async function send(next) {
      clear(errors);
      confirmBox.hidden = true;
      save.disabled = true;
      status.busy(M.t("settings.saving"));
      try {
        await M.stepUp.run(() => M.api.patch(ctx.base, { settings: { restricted_access: next } }), stepSlot, M.t("restricted.settings.step_up"));
        saved(M.t("restricted.settings.saved"));
      } catch (err) {
        save.disabled = false;
        if (err.code === "cancelled") { status.done(); return; }
        const fields = (err.code === "invalid" && err.details && err.details.fields) || {};
        const mine = Object.keys(fields).filter((k) => k.startsWith("settings.restricted_access"));
        if (mine.length) {
          status.done();
          mine.forEach((k) => {
            const id = k.split(".members.")[1];
            const row = id ? rows.find((r) => r.id === id) : null;
            append(errors, h("li", null, row ? M.t("restricted.settings.error.at", { who: row.label, why: fieldWords(fields[k]) }) : fieldWords(fields[k])));
          });
          return;
        }
        status.fail(M.t("restricted.settings.not_saved"), err);
      }
    }

    // Before a change that widens the set (§6.1 "Widening the set"): how many cards have a
    // text, who newly reads them, each agent with its owner, and under all_except that every
    // future member reads them too; saved only once the human confirms.
    function askWiden(next, newly) {
      clear(confirmBox);
      const count = value && typeof value.cards_with_text === "number" ? value.cards_with_text : 0;
      append(confirmBox,
        h("p", { class: "restricted-confirm-cards" }, M.t("restricted.widen.cards", { count })),
        newly.length ? [h("p", null, M.t("restricted.widen.newly")),
          h("ul", { class: "restricted-newly" }, newly.map((m) => h("li", null, who(ctx, m))))] : null,
        next.mode === "all_except" ? h("p", { class: "restricted-confirm-future" }, M.t("restricted.widen.future")) : null,
        h("div", { class: "actions" },
          h("button", { type: "button", class: "restricted-widen-back", onclick: () => { confirmBox.hidden = true; save.disabled = false; save.focus(); } }, M.t("restricted.widen.back")),
          h("button", { type: "button", class: "restricted-widen-go", onclick: () => send(next) }, M.t("restricted.widen.go"))));
      confirmBox.hidden = false;
      save.disabled = true;
      confirmBox.querySelector("button.restricted-widen-go").focus();
    }

    append(section, h("form", {
      class: "inline-form restricted-form",
      onsubmit: (e) => {
        e.preventDefault();
        clear(errors);
        const next = edited();
        if (same(next, stored)) { status.done(); append(status.el, h("span", null, M.t("restricted.settings.unchanged"))); return; }
        const before = resolve(stored, members);
        const after = resolve(next, members);
        const newly = members.filter((m) => after.has(m.id) && !before.has(m.id));
        const future = !!next && next.mode === "all_except" && !(stored && stored.mode === "all_except");
        if (newly.length || future) { askWiden(next, newly); return; }
        send(next);
      },
    },
    h("label", { for: "restricted-mode" }, M.t("restricted.settings.mode")), mode, modeHint,
    list, errors, confirmBox, save, stepSlot, status.el));
    return section;
  }

  function modeWords(mode) {
    return mode === "all_except" ? M.t("restricted.mode.all_except") : M.t("restricted.mode.nobody_except");
  }

  // ---- the box on a card (§6.4) ---------------------------------------------

  // The "Restricted" box, for a member in the set alone (`included`); null otherwise, so
  // nobody outside the set sees a sign that a card has a text. Read with GET …/restricted
  // when the card opens, never with the board.
  function cardBox(ctx, c) {
    const value = setting(ctx);
    if (!value || value.included !== true) return null;
    const path = ctx.base + "/tasks/" + encodeURIComponent(c.id) + "/restricted";
    const archived = () => !!(ctx.project && ctx.project.state === "archived");
    const body = h("div", { class: "card-restricted-body" });
    const status = M.statusLine();
    const box = h("section", { class: "card-restricted", "aria-labelledby": "card-restricted-title" },
      h("h3", { id: "card-restricted-title" }, M.t("restricted.box.title")),
      h("p", { class: "hint restricted-not-encryption" }, M.t("restricted.not_encryption")),
      body, status.el);
    // The last read: { text, version, history }, in memory only.
    let current = null;
    let reads = 0;

    async function load(said) {
      const run = ++reads;
      status.busy(M.t("restricted.box.loading"));
      try {
        const got = await M.api.get(path);
        if (run !== reads) return;
        current = got;
        status.done();
        draw(said);
      } catch (err) {
        if (run !== reads) return;
        status.done();
        refused(err);
      }
    }

    // A refusal of the read: outside a session in good standing the sentence and the session
    // list (§6.4 "Access"); out of the set since the card opened; anything else as it came.
    function refused(err) {
      clear(body);
      const reason = err.details && err.details.reason;
      if (err.code === "forbidden" && reason === "not_in_good_standing") {
        append(body, h("p", { class: "restricted-standing" }, M.tn("restricted.box.not_in_good_standing",
          { sessions: h("a", { href: "/account/security/sessions" }, M.t("restricted.box.sessions")) })));
      } else if (err.code === "forbidden" && reason === "restricted") {
        append(body, h("p", { class: "muted" }, M.t("restricted.box.left_set")));
      } else {
        status.fail(M.t("restricted.box.not_read"), err);
      }
    }

    function by(x) {
      return x && x.handle ? "@" + x.handle : M.t("restricted.box.someone");
    }

    function draw(said) {
      clear(body);
      const text = current.text;
      const actions = h("div", { class: "actions" },
        archived() ? null : h("button", { type: "button", class: "small restricted-edit", onclick: () => edit(text || "") },
          text ? M.t("restricted.box.edit") : M.t("restricted.box.add")),
        text ? h("button", { type: "button", class: "small restricted-clear", onclick: () => remove() }, M.t("restricted.box.clear")) : null);
      append(body,
        text ? h("p", { class: "restricted-text" }, text) : h("p", { class: "muted restricted-none" }, M.t("restricted.box.none")),
        current.updated_by && current.updated_at
          ? h("p", { class: "muted restricted-updated" }, M.t("restricted.box.updated", { who: by(current.updated_by), when: M.dom.formatTime(current.updated_at) })) : null,
        actions,
        said ? h("p", { class: "ok", role: "status" }, said) : null,
        (current.history || []).length ? h("details", { class: "restricted-history" },
          h("summary", null, M.t("restricted.box.history")),
          h("ul", null, current.history.map((x) => h("li", null, x.action === "cleared"
            ? M.t("restricted.box.history.cleared", { who: by(x.by), when: M.dom.formatTime(x.at) })
            : M.t("restricted.box.history.set", { who: by(x.by), when: M.dom.formatTime(x.at) }))))) : null);
    }

    const TEXT_WORDS = {
      empty: () => M.t("restricted.box.error.empty"),
      too_long: () => M.t("restricted.box.error.too_long"),
      control_character: () => M.t("restricted.box.error.control_character"),
    };

    // Edit in place; `typed` is what the field starts with (the stored text, or what was
    // typed before a conflict).
    function edit(typed, said) {
      clear(body);
      const field = h("textarea", { id: "restricted-text-" + c.id, rows: "5", "aria-describedby": "restricted-count-" + c.id + " restricted-error-" + c.id });
      field.value = typed;
      const count = h("p", { class: "hint", id: "restricted-count-" + c.id });
      const error = h("p", { class: "field-error", id: "restricted-error-" + c.id, role: "alert" });
      const counted = () => { count.textContent = M.t("restricted.box.count", { count: length(field.value), max: MAX }); };
      field.addEventListener("input", counted);
      counted();
      const save = h("button", { type: "submit" }, M.t("restricted.box.save"));
      append(body, said ? h("p", { class: "restricted-said", role: "status" }, said) : null, h("form", {
        class: "restricted-edit-form",
        onkeydown: (e) => { if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); draw(); } },
        onsubmit: async (e) => {
          e.preventDefault();
          error.textContent = "";
          if (!field.value.trim()) { error.textContent = TEXT_WORDS.empty(); field.focus(); return; }
          if (length(field.value) > MAX) { error.textContent = TEXT_WORDS.too_long(); field.focus(); return; }
          save.disabled = true;
          status.busy(M.t("restricted.box.saving"));
          try {
            await M.api.put(path, { text: field.value, base_version: current.version });
            await load(M.t("restricted.box.saved"));
          } catch (err) {
            save.disabled = false;
            status.done();
            const why = err.code === "invalid" && err.details && err.details.fields && err.details.fields.text;
            if (why) { error.textContent = Object.hasOwn(TEXT_WORDS, why) ? TEXT_WORDS[why]() : why; field.focus(); return; }
            if (err.code === "conflict") { await conflicted(field.value); return; }
            if (err.code === "forbidden") { refused(err); return; }
            status.fail(M.t("restricted.box.not_saved"), err);
          }
        },
      },
      h("label", { for: "restricted-text-" + c.id }, M.t("restricted.box.label")), field, count, error,
      h("div", { class: "actions" },
        h("button", { type: "button", class: "restricted-cancel", onclick: () => draw() }, M.t("restricted.box.cancel")), save)));
      field.focus();
    }

    // Someone changed the text since it was read (§6.4 "Versions"): read it again and keep
    // what was typed in the field, to be saved again on the new version.
    async function conflicted(typed) {
      try {
        current = await M.api.get(path);
      } catch (err) { refused(err); return; }
      edit(typed, M.t("restricted.box.conflict", { current: current.text === null ? M.t("restricted.box.none") : current.text }));
    }

    async function remove() {
      if (!window.confirm(M.t("restricted.box.clear_ask"))) return;
      status.busy(M.t("restricted.box.saving"));
      try {
        await M.api.del(path + "?base_version=" + encodeURIComponent(String(current.version)));
        await load(M.t("restricted.box.cleared"));
      } catch (err) {
        status.done();
        if (err.code === "conflict") { await load(M.t("restricted.box.conflict_clear")); return; }
        if (err.code === "forbidden") { refused(err); return; }
        status.fail(M.t("restricted.box.not_saved"), err);
      }
    }

    load();
    return box;
  }

  // ---- before a way into the set (§6.1 "Every way into the set") -------------

  // What the page says before an action that brings a member into the set: a join, a
  // guest's raise, an isolation's end. `change(members)` returns the project's members
  // as the action would leave them (copies, to change freely); `fresh` lists ids the
  // action makes new, which no list can name. The text names who enters, with the count
  // of cards with a text where the reader is served it; null when nobody does, and
  // nothing is said while the set names nobody.
  // A reader served only `{mode, included}` sees no list (§6.1 "Reading the setting"),
  // so the page says no more than it knows: under all_except "unless the list leaves
  // them out", under nobody_except "if the list names them" (lotse, tsk-g8ts5vxhj1md).
  function ahead(ctx, change, fresh) {
    const value = setting(ctx);
    if (!value || !MODES.includes(value.mode)) return null;
    const members = ctx.members || [];
    const after = change(members.map((m) => Object.assign({}, m)));
    const known = Array.isArray(value.members);
    const freshIds = new Set(fresh || []);
    const meListed = value.mode === "all_except" ? value.included === false : value.included === true;
    // Without the list: the widest list the page cannot rule out, the reader's own
    // place on it from `included`.
    const list = known ? value.members
      : value.mode === "all_except" ? (meListed ? [ctx.me.id] : [])
        : after.map((m) => m.id).filter((id) => !freshIds.has(id) && (id !== ctx.me.id || meListed));
    const assumed = { mode: value.mode, members: list };
    const before = resolve(assumed, members);
    const later = resolve(assumed, after);
    const entering = after.filter((m) => later.has(m.id) && !before.has(m.id));
    if (!entering.length) return null;
    const names = entering.map((m) => who(ctx, m)).join(", ");
    const words = [known ? M.t("restricted.ahead.will", { list: names })
      : value.mode === "all_except" ? M.t("restricted.ahead.unless_listed", { list: names })
        : M.t("restricted.ahead.if_listed", { list: names })];
    if (typeof value.cards_with_text === "number") words.push(M.t("restricted.settings.cards", { count: value.cards_with_text }));
    return words.join(" ");
  }

  // The same, for the owners of an organisation the project moves into (§6.26): who they
  // are the page does not know, so it says what the setting lets them do. Under all_except
  // they read unless the list leaves them out; under nobody_except only if it names them,
  // which a list the reader sees rules out when it names nobody outside the set now.
  function aheadOrgOwners(ctx, org) {
    const value = setting(ctx);
    if (!value || !MODES.includes(value.mode)) return null;
    let text;
    if (value.mode === "all_except") {
      text = M.t("restricted.ahead.org_owners_unless", { org });
    } else {
      if (Array.isArray(value.members)) {
        const now = resolve(value, ctx.members || []);
        const agentIds = new Set((ctx.members || []).filter((m) => m.kind === "agent").map((m) => m.id));
        if (!value.members.some((id) => !now.has(id) && !agentIds.has(id))) return null;
      }
      text = M.t("restricted.ahead.org_owners_if_listed", { org });
    }
    return typeof value.cards_with_text === "number"
      ? text + " " + M.t("restricted.settings.cards", { count: value.cards_with_text }) : text;
  }

  // Where a human becomes an owner of an organisation (an invitation's go, a promotion,
  // §6.26), the page reads no project's setting: one general sentence, said whatever the
  // projects hold (lotse, tsk-g8ts5vxhj1md). `who` null speaks to the reader.
  function aheadOrg(org, whoName) {
    return whoName ? M.t("restricted.ahead.org_member", { org, who: whoName }) : M.t("restricted.ahead.org_you", { org });
  }

  // The sentence as a line in a form, drawn again by `draw()` as the form changes.
  function aheadLine() {
    const line = h("p", { class: "restricted-ahead", hidden: true });
    return { el: line, show: (text) => { line.textContent = text || ""; line.hidden = !text; } };
  }

  M.restricted = { resolve, settingsSection, cardBox, ahead, aheadOrgOwners, aheadOrg, aheadLine };
})(window.Maity);
