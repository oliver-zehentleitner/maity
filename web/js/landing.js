// The instance's web presence in the admin area (docs/api.md §16.7,
// §16.7.1): the landing page, per language an ordered list of sections of
// the contract's types, with its footer; and the legal pages (imprint,
// privacy, terms) per language. The hub renders both itself as static HTML
// for visitors; the dashboard only edits them. A save sends the whole
// draft, and the hub's refusal names each field by its path
// (pages.de.sections.2.items.0.title), which is said at that field.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;
  const LANDING = "/admin/settings/landing";
  const LEGAL = "/admin/settings/legal";
  const LANG = /^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/;
  // A variant's slug and a campaign's code (§16.7.2): lowercase, digits and
  // dashes, 1–40, a variant's neither starting nor ending with a dash.
  const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/;
  const CODE = /^[a-z0-9-]{1,40}$/;

  // A field of a section or of an item: its key, its label, its kind and
  // its limit. Kinds: text (one line), long (several lines), md (Markdown),
  // cta ({label, href}), href (a link's target), lines (one entry per line:
  // the points, handles, projects), stats (counters to tick), agents (an
  // ordered pick from the hub's list), count (a
  // number), choice (one of `choices`), group (an object of `fields`).
  // `label` is a function, read when said, so a language set after the page loads applies.
  const f = (key, label, kind, max, extra) => Object.defineProperty(Object.assign({ key, kind, max }, extra || {}), "label", { get: label, enumerable: true });
  // [value, words], the words read when said (as the board's columns, js/board-edit.js).
  const pair = (value, words) => Object.defineProperty([value], 1, { get: words, enumerable: true });
  // The small line above a section's title, optional on the types §16.7 lists; the words are the catalog's when said.
  const eyebrowField = { key: "eyebrow", kind: "text", max: 40, optional: true, get label() { return M.t("landing.eyebrow"); } };
  const STATS = [pair("people", () => M.t("landing.stat.people")), pair("agents", () => M.t("landing.stat.agents")), pair("public_projects", () => M.t("landing.stat.public_projects")), pair("cards_done_week", () => M.t("landing.stat.cards_done_week")), pair("people_online", () => M.t("landing.stat.people_online")), pair("agents_online", () => M.t("landing.stat.agents_online"))];
  // The agents a works_with section may name, as the hub's fixed list (§16.7, AGENTS in
  // hub/src/maity_hub/landing.py; smoke compares the two).
  // Product names, not words of the dashboard: they stay out of the catalog.
  const AGENTS = "claude-code=Claude Code|codex=Codex|opencode=OpenCode|gemini=Gemini|antigravity=Antigravity|copilot=Copilot|cursor=Cursor|pi=Pi|goose=Goose|cline=Cline|roo=Roo Code|kilo=Kilo Code|amp=Amp|droid=Droid|windsurf=Windsurf|zed=Zed|kiro-cli=Kiro CLI|trae=Trae|openclaw=OpenClaw".split("|").map((x) => x.split("="));
  // The types the hub renders in this version (§16.7); activity and collab
  // are kept as they are, never offered.
  const TYPES = {
    hero: { get label() { return M.t("landing.type.hero"); }, fields: [f("eyebrow", () => M.t("landing.field.eyebrow"), "text", 40), f("title", () => M.t("landing.field.title"), "text", 120), f("subline", () => M.t("landing.field.subline"), "long", 300),
      f("cta_primary", () => M.t("landing.field.main_button"), "cta"), f("cta_secondary", () => M.t("landing.field.second_button_optional"), "cta", null, { optional: true, addWords: () => M.t("landing.add.second_button") }), f("note", () => M.t("landing.field.note_markdown"), "md", 500)] },
    stats: { get label() { return M.t("landing.type.counters"); }, fields: [f("items", () => M.t("landing.field.counters"), "stats")] },
    steps: { get label() { return M.t("landing.type.steps"); }, fields: [eyebrowField, f("title", () => M.t("landing.field.title"), "text", 120)],
      items: { min: 1, max: 6, numbered: (n) => M.t("landing.item.step", { n: String(n) }), add: () => M.t("landing.item.step.add"), fields: [f("title", () => M.t("landing.field.title"), "text", 80), f("text", () => M.t("landing.field.text"), "long", 300), f("code", () => M.t("landing.field.code_optional"), "long", 300, { optional: true })] } },
    scales: { get label() { return M.t("landing.type.scales"); }, fields: [eyebrowField, f("title", () => M.t("landing.field.title"), "text", 120)],
      items: { min: 1, max: 4, numbered: (n) => M.t("landing.item.scale", { n: String(n) }), add: () => M.t("landing.item.scale.add"), fields: [f("tag", () => M.t("landing.field.tag"), "text", 40), f("title", () => M.t("landing.field.title"), "text", 80), f("text", () => M.t("landing.field.text"), "long", 300),
        f("points", () => M.t("landing.field.points_one_per_line"), "lines", 5)] } },
    faq: { get label() { return M.t("landing.type.questions"); }, fields: [eyebrowField, f("title", () => M.t("landing.field.title"), "text", 120)],
      items: { min: 1, max: 20, numbered: (n) => M.t("landing.item.question", { n: String(n) }), add: () => M.t("landing.item.question.add"), fields: [f("q", () => M.t("landing.field.question"), "text", 200), f("a", () => M.t("landing.field.answer_markdown"), "md", 2000)] } },
    cta_band: { get label() { return M.t("landing.type.call_to_action"); }, fields: [f("title", () => M.t("landing.field.title"), "text", 120), f("text", () => M.t("landing.field.text"), "long", 300), f("cta", () => M.t("landing.field.button"), "cta")] },
    text: { get label() { return M.t("landing.type.text"); }, fields: [eyebrowField, f("title", () => M.t("landing.field.title_optional"), "text", 120, { optional: true }), f("markdown", () => M.t("landing.field.text_markdown"), "md", 16384)] },
    // Getters: the words are the catalog's when said.
    works_with: { get label() { return M.t("landing.works_with.title"); }, fields: [
      { key: "label", kind: "text", max: 40, get label() { return M.t("landing.works_with.label"); } },
      { key: "items", kind: "agents", get label() { return M.t("landing.works_with.agents"); } },
      { key: "more", kind: "text", max: 60, optional: true, get label() { return M.t("landing.works_with.more"); } }] },
    profiles: { get label() { return M.t("landing.type.profiles"); }, get note() { return M.t("landing.type.profiles.note"); },
      fields: [eyebrowField, f("title", () => M.t("landing.field.title"), "text", 120), f("markdown", () => M.t("landing.field.text_markdown"), "md", 2000), f("handles", () => M.t("landing.field.handles_one_per_line"), "lines", 2)] },
    explore: { get label() { return M.t("landing.type.explore"); }, get note() { return M.t("landing.type.explore.note"); },
      fields: [f("title", () => M.t("landing.field.title"), "text", 120), f("projects", () => M.t("landing.field.projects_owner_slug_one_per_line"), "lines", 3)] },
    // §16.7 (#737): a terminal typed line by line, the question an agent asks
    // its human, and exactly three steps; the page shows them all without script.
    demo: { get label() { return M.t("landing.type.demo"); }, fields: [eyebrowField, f("title", () => M.t("landing.field.title"), "text", 120), f("subline", () => M.t("landing.field.subline_optional"), "long", 300, { optional: true }),
      f("inbox", () => M.t("landing.field.inbox_item_optional"), "group", null, { optional: true, addWords: () => M.t("landing.add.inbox_item"), fields: [f("from", () => M.t("landing.field.from"), "text", 80), f("question", () => M.t("landing.field.question"), "long", 300),
        f("context", () => M.t("landing.field.context_optional"), "long", 300, { optional: true })] })],
      lists: [
        { key: "terminal_lines", min: 1, max: 8, numbered: (n) => M.t("landing.item.terminal_line", { n: String(n) }), add: () => M.t("landing.item.terminal_line.add"), fields: [f("kind", () => M.t("landing.field.kind"), "choice", null, { choices: [pair("cmd", () => M.t("landing.terminal.cmd")), pair("out", () => M.t("landing.terminal.out")), pair("note", () => M.t("landing.terminal.note"))] }),
          f("text", () => M.t("landing.field.text"), "text", 200)] },
        { key: "steps", min: 3, max: 3, numbered: (n) => M.t("landing.item.step", { n: String(n) }), add: () => M.t("landing.item.step.add"), fields: [f("title", () => M.t("landing.field.title"), "text", 80), f("text", () => M.t("landing.field.text"), "long", 300)] },
      ] },
    opensource: { get label() { return M.t("landing.type.open_source"); }, fields: [eyebrowField, f("title", () => M.t("landing.field.title"), "text", 120), f("markdown", () => M.t("landing.field.text_markdown_optional"), "md", 600, { optional: true })],
      lists: [
        { key: "tiles", min: 1, max: 3, numbered: (n) => M.t("landing.item.tile", { n: String(n) }), add: () => M.t("landing.item.tile.add"), fields: [{ key: "label", kind: "text", max: 40, optional: true, get label() { return M.t("landing.tile_label"); } }, f("title", () => M.t("landing.field.title"), "text", 80), f("text", () => M.t("landing.field.text"), "long", 300)] },
        { key: "links", min: 0, max: 4, numbered: (n) => M.t("landing.item.link", { n: String(n) }), add: () => M.t("landing.item.link.add"), fields: [f("label", () => M.t("landing.field.label"), "text", 40), f("href", () => M.t("landing.field.link"), "href")] },
      ] },
  };
  // A type's lists of entries: its items, and the named lists of the newer types.
  const listsOf = (type) => (type.items ? [Object.assign({ key: "items" }, type.items)] : []).concat(type.lists || []);
  const KEPT = { activity: () => M.t("landing.type.activity"), collab: () => M.t("landing.type.collab") };

  // Whether pages can be drawn as the editor: each page an object, its
  // sections a list of objects, and every value the editor binds to an
  // object or a list of the right kind: a button (cta) an object, or absent
  // where optional; a group an object or absent; each list a list of
  // objects whose own fields hold the same; lines and counters lists. What
  // the values say is the hub's to check; only their kind decides here.
  const isObject = (x) => !!x && typeof x === "object" && !Array.isArray(x);
  function fieldsOk(fields, obj) {
    return fields.every((x) => {
      const v = obj[x.key];
      if (x.kind === "cta") return x.optional ? v === undefined || v === null || isObject(v) : isObject(v);
      if (x.kind === "group") return v === undefined || v === null || (isObject(v) && fieldsOk(x.fields, v));
      if (x.kind === "lines" || x.kind === "stats" || x.kind === "agents") return v === undefined || Array.isArray(v);
      return true;
    });
  }
  function sectionOk(sec) {
    if (!isObject(sec)) return false;
    // Own keys only: "constructor" or "__proto__" as a type is no section type.
    const type = Object.hasOwn(TYPES, sec.type) ? TYPES[sec.type] : null;
    if (!type) return true;
    return fieldsOk(type.fields || [], sec) && listsOf(type).every((l) => sec[l.key] === undefined
      || (Array.isArray(sec[l.key]) && sec[l.key].every((item) => isObject(item) && fieldsOk(l.fields, item))));
  }
  function drawable(pages, footer) {
    const social = footer && footer.social;
    return Object.values(pages).every((pg) => isObject(pg) && (pg.sections === undefined || (Array.isArray(pg.sections) && pg.sections.every(sectionOk))))
      && (!footer || (isObject(footer) && (social === undefined || (Array.isArray(social) && social.every(isObject)))));
  }

  // A new object of `fields`, as the hub would take it.
  function freshOf(fields) {
    const o = {};
    fields.forEach((x) => {
      if (x.optional) return;
      if (x.kind === "cta") o[x.key] = { label: "", href: "" };
      else if (x.kind === "stats" || x.kind === "lines" || x.kind === "agents") o[x.key] = [];
      else if (x.kind === "choice") o[x.key] = x.choices[0][0];
      else if (x.kind === "group") o[x.key] = freshOf(x.fields);
      else o[x.key] = "";
    });
    return o;
  }
  // A new section of a type: each list with its least entries; one that
  // may be empty (an open source section's links) starts empty.
  function fresh(type) {
    const s = Object.assign({ type, enabled: true }, freshOf(TYPES[type].fields || []));
    listsOf(TYPES[type]).forEach((l) => { s[l.key] = Array.from({ length: l.min === 0 ? 0 : Math.max(l.min, 1) }, () => freshOf(l.fields)); });
    return s;
  }

  // The hub's reasons, in words; any other reason is shown as it comes.
  const REASONS = {
    required: () => M.t("landing.reason.required"),
    control_character: () => M.t("landing.reason.control_character"),
    html: () => M.t("landing.reason.html"),
    invalid_href: () => M.t("landing.reason.invalid_href"),
    unknown_type: () => M.t("landing.reason.unknown_type"),
    extra_forbidden: () => M.t("landing.reason.extra_forbidden"),
    too_many: () => M.t("landing.reason.too_many"),
    too_few: () => M.t("landing.reason.too_few"),
    invalid: () => M.t("landing.reason.invalid"),
    default_language_missing: () => M.t("landing.reason.default_language_missing"),
    rate_limited: () => M.t("landing.reason.rate_limited"),
    unknown_agent: () => M.t("landing.works_with.unknown_agent"), duplicate: () => M.t("landing.works_with.duplicate"),
    // §16.7: the stored setting is at most 256 KiB of UTF-8.
    too_large: () => M.t("landing.reason.too_large"),
  };
  const reasonText = (r) => (Object.hasOwn(REASONS, r) ? REASONS[r]() : String(r).replace(/_/g, " "));
  // A field's limit in words (§16.7, §16.7.1): KiB where the hub counts bytes, else characters.
  const inKib = (max) => max >= 1024 && max % 1024 === 0;
  const limitWords = (max) => (inKib(max) ? M.t("landing.limit.kib", { kib: max / 1024 }) : M.t("landing.limit.chars", { max }));
  const limitSentence = (max) => (inKib(max) ? M.t("landing.limit.kib_sentence", { kib: max / 1024 }) : M.t("landing.limit.chars_sentence", { max }));

  // One field's control, bound to the draft object `obj[key]`; `path` is
  // the hub's path of it, for its error.
  function control(x, obj, path, errors, redraw) {
    const id = "lp-" + path.replace(/[^A-Za-z0-9]+/g, "-");
    const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
    // Its limit, said with the hub's refusal of it: the hub reports an empty and
    // a too long text alike as `invalid` (§16.7, §16.7.1).
    if (x.max && ["text", "long", "md"].includes(x.kind)) error.limit = limitWords(x.max);
    errors[path] = error;
    const described = { "aria-describedby": id + "-error", "data-path": path };
    let input;
    if (x.kind === "cta") {
      if (!obj[x.key] && x.optional) {
        const add = h("button", { type: "button", class: "small" }, x.addWords());
        add.addEventListener("click", () => { obj[x.key] = { label: "", href: "" }; redraw(); });
        return h("div", { class: "lp-field field-stack" }, h("span", { class: "lp-label" }, x.label), add, error);
      }
      const cta = obj[x.key];
      const label = h("input", Object.assign({ id: id + "-label", maxlength: "40" }, described));
      label.value = cta.label || "";
      label.addEventListener("input", () => { cta.label = label.value; });
      const href = h("input", { id: id + "-href", placeholder: M.t("landing.href_placeholder"), "aria-describedby": id + "-href-error", "data-path": path + ".href" });
      href.value = cta.href || "";
      href.addEventListener("input", () => { cta.href = href.value.trim(); });
      const hrefError = h("p", { class: "field-error", id: id + "-href-error", role: "alert" });
      errors[path + ".href"] = hrefError;
      errors[path + ".label"] = error;
      const remove = x.optional ? h("button", { type: "button", class: "small" }, M.t("landing.entry.remove")) : null;
      if (remove) remove.addEventListener("click", () => { delete obj[x.key]; redraw(); });
      return h("fieldset", { class: "lp-field field-stack lp-cta" }, h("legend", null, x.label),
        h("label", { for: id + "-label" }, M.t("landing.field.label")), label, error,
        h("label", { for: id + "-href" }, M.t("landing.field.link")), href, hrefError, remove);
    }
    if (x.kind === "stats") {
      const chosen = obj[x.key] = obj[x.key] || [];
      return h("fieldset", { class: "lp-field field-stack lp-stats" }, h("legend", null, x.label),
        STATS.map(([k, l]) => {
          const box = h("input", { type: "checkbox", id: id + "-" + k });
          box.checked = chosen.includes(k);
          box.addEventListener("change", () => {
            const at = chosen.indexOf(k);
            if (box.checked && at < 0) chosen.push(k);
            if (!box.checked && at >= 0) chosen.splice(at, 1);
          });
          return h("label", { class: "check", for: id + "-" + k }, box, " " + l);
        }),
        h("p", { class: "hint" }, M.t("landing.online_hint")), error);
    }
    if (x.kind === "agents") {
      const chosen = obj[x.key] = obj[x.key] || [];
      const nameOf = (slug) => (AGENTS.find(([s]) => s === slug) || [slug, String(slug)])[1];
      const free = AGENTS.filter(([s]) => !chosen.includes(s));
      const pick = h("select", { id: id + "-pick" }, free.map(([s, name]) => h("option", { value: s }, name)));
      return h("fieldset", { class: "lp-field field-stack lp-agents" }, h("legend", null, x.label),
        h("ol", { class: "lp-items", "data-list": x.key }, chosen.map((slug, k) => h("li", { class: "lp-item" },
          h("div", { class: "lp-section-head" }, h("span", { class: "lp-item-title" }, nameOf(slug)),
            entryButtons(chosen, k, 0, redraw)),
          (errors[path + "." + k] = h("p", { class: "field-error", role: "alert" }))))),
        free.length ? h("div", { class: "inline-form" }, h("label", { for: id + "-pick" }, M.t("landing.works_with.pick")), pick,
          small(M.t("landing.works_with.add"), () => chosen.push(pick.value), false, redraw)) : null, error);
    }
    if (x.kind === "choice") {
      input = h("select", Object.assign({ id }, described), x.choices.map(([v, l]) => h("option", { value: v }, l)));
      input.value = obj[x.key] || x.choices[0][0];
      input.addEventListener("change", () => { obj[x.key] = input.value; });
      return h("div", { class: "lp-field field-stack" }, h("label", { for: id }, x.label), input, error);
    }
    if (x.kind === "group") {
      if (!obj[x.key]) {
        const add = h("button", { type: "button", class: "small" }, x.addWords());
        add.addEventListener("click", () => { obj[x.key] = freshOf(x.fields); redraw(); });
        return h("div", { class: "lp-field field-stack" }, h("span", { class: "lp-label" }, x.label), add, error);
      }
      const remove = x.optional ? h("button", { type: "button", class: "small" }, M.t("landing.entry.remove")) : null;
      if (remove) remove.addEventListener("click", () => { delete obj[x.key]; redraw(); });
      return h("fieldset", { class: "lp-field field-stack lp-group" }, h("legend", null, x.label),
        x.fields.map((y) => control(y, obj[x.key], path + "." + y.key, errors, redraw)), remove, error);
    }
    if (x.kind === "href") {
      input = h("input", Object.assign({ id, placeholder: M.t("landing.href_placeholder") }, described));
      input.value = obj[x.key] || "";
      input.addEventListener("input", () => { obj[x.key] = input.value.trim(); });
      return h("div", { class: "lp-field field-stack" }, h("label", { for: id }, x.label), input, error);
    }
    if (x.kind === "lines") {
      input = h("textarea", Object.assign({ id, rows: String(Math.max(2, x.max)) }, described));
      input.value = (obj[x.key] || []).join("\n");
      input.addEventListener("input", () => { obj[x.key] = input.value.split("\n").map((s) => s.trim()).filter(Boolean); });
      return h("div", { class: "lp-field field-stack" }, h("label", { for: id }, M.t("landing.lines_label", { label: x.label, max: x.max })), input, error);
    }
    input = x.kind === "text"
      ? h("input", Object.assign({ id, maxlength: String(x.max) }, described))
      : h("textarea", Object.assign({ id, rows: x.kind === "md" ? "6" : "3" }, described));
    input.value = obj[x.key] || "";
    input.addEventListener("input", () => {
      if (x.optional && !input.value) delete obj[x.key];
      else obj[x.key] = input.value;
    });
    return h("div", { class: "lp-field field-stack" }, h("label", { for: id }, x.label), input,
      x.kind === "md" ? h("p", { class: "hint" }, M.t("landing.md_hint", { limit: limitSentence(x.max) }))
        : x.kind === "long" ? h("p", { class: "hint" }, limitSentence(x.max)) : null,
      error);
  }

  // Moves, removals and additions change the draft's shape: the editor is
  // drawn again from the draft, keeping what was typed.
  const move = (list, i, by) => { const j = i + by; if (j < 0 || j >= list.length) return; [list[i], list[j]] = [list[j], list[i]]; };
  const small = (label, fn, disabled, redraw) => {
    const b = h("button", { type: "button", class: "small" }, label);
    b.disabled = !!disabled;
    b.addEventListener("click", () => { fn(); redraw(); });
    return b;
  };

  // An entry's own buttons in a list of them: moved, and removed while more than `min` are left.
  const entryButtons = (list, k, min, redraw) => [small(M.t("landing.entry.up"), () => move(list, k, -1), k === 0, redraw),
    small(M.t("landing.entry.down"), () => move(list, k, 1), k === list.length - 1, redraw),
    small(M.t("landing.entry.remove"), () => list.splice(k, 1), list.length <= min, redraw)];

  // prefix: where the pages sit in the setting, "pages" or "variants.<slug>.pages" (§16.7.2).
  function sectionBox(prefix, lang, sections, i, errors, redraw) {
    const s = sections[i];
    const path = prefix + "." + lang + ".sections." + i;
    const type = Object.hasOwn(TYPES, s.type) ? TYPES[s.type] : null;
    const on = h("input", { type: "checkbox", id: "lp-" + lang + "-" + i + "-enabled" });
    on.checked = s.enabled !== false;
    on.addEventListener("change", () => { s.enabled = on.checked; });
    const error = h("p", { class: "field-error", role: "alert" });
    errors[path] = error;
    errors[path + ".type"] = error;
    const head = h("div", { class: "lp-section-head" },
      h("h5", { class: "lp-section-title" }, (i + 1) + ". " + (type ? type.label : Object.hasOwn(KEPT, s.type) ? KEPT[s.type]() : s.type)),
      h("label", { class: "check", for: "lp-" + lang + "-" + i + "-enabled" }, on, " ", M.t("landing.section.shown")),
      small(M.t("landing.entry.up"), () => move(sections, i, -1), i === 0, redraw), small(M.t("landing.entry.down"), () => move(sections, i, 1), i === sections.length - 1, redraw),
      small(M.t("landing.entry.remove"), () => sections.splice(i, 1), false, redraw));
    if (!type) {
      return h("li", { class: "lp-section kept" }, head,
        h("p", { class: "muted" }, M.t("landing.section.kept")), error);
    }
    // Each list of entries: moved, removed down to its least, added up to its most.
    const lists = listsOf(type).map((l) => {
      const items = s[l.key] = s[l.key] || [];
      const listError = h("p", { class: "field-error", role: "alert" });
      errors[path + "." + l.key] = listError;
      return [l.min === l.max ? h("p", { class: "hint" }, M.t("landing.list.exactly", { count: l.min })) : null,
        h("ol", { class: "lp-items", "data-list": l.key }, items.map((item, k) => h("li", { class: "lp-item" },
          h("div", { class: "lp-section-head" }, h("span", { class: "lp-item-title" }, l.numbered(k + 1)),
            entryButtons(items, k, l.min, redraw)),
          l.fields.map((x) => control(x, item, path + "." + l.key + "." + k + "." + x.key, errors, redraw))))),
        l.min === l.max ? null : small(l.add(), () => items.push(freshOf(l.fields)), items.length >= l.max, redraw),
        listError];
    });
    return h("li", { class: "lp-section" }, head, type.note ? h("p", { class: "hint" }, type.note) : null,
      type.fields.map((x) => control(x, s, path + "." + x.key, errors, redraw)), lists, error);
  }

  function pageEditor(pages, prefix, lang, errors, redraw) {
    const p = pages[lang];
    p.sections = p.sections || [];
    const title = control(f("title", () => M.t("landing.field.page_title"), "text", 120), p, prefix + "." + lang + ".title", errors, redraw);
    const description = control(f("description", () => M.t("landing.field.description_for_search_engines"), "long", 300), p, prefix + "." + lang + ".description", errors, redraw);
    const kind = h("select", { id: "lp-add-type-" + lang }, Object.entries(TYPES).map(([k, t]) => h("option", { value: k }, t.label)));
    const add = small(M.t("landing.section.add"), () => p.sections.push(fresh(kind.value)), p.sections.length >= 20, redraw);
    return h("div", { class: "lp-page" }, title, description,
      h("h4", null, M.t("landing.sections")),
      p.sections.length ? h("ol", { class: "lp-sections" }, p.sections.map((s, i) => sectionBox(prefix, lang, p.sections, i, errors, redraw)))
        : h("p", { class: "muted" }, M.t("landing.sections.none")),
      h("div", { class: "inline-form lp-add" }, h("label", { for: "lp-add-type-" + lang }, M.t("landing.section.new")), kind, add,
        h("span", { class: "hint" }, M.t("landing.sections.max", { max: 20 }))));
  }

  // The hub's refusal said at each field it names; a path without a field
  // on screen is listed in the status line.
  // prefix: what the status line says before the hub's words; a save's by default.
  function showErrors(errors, err, status, prefix) {
    const before = prefix || M.t("landing.not_saved");
    Object.values(errors).forEach((e) => { e.textContent = ""; });
    const fields = err && err.code === "invalid" && err.details && err.details.fields;
    // A request over the hub's cap (§16.7: 512 KiB for these two calls) never reaches the checks.
    if (err && err.code === "payload_too_large") { status.fail(before, { message: M.t("landing.too_large_request") }); return; }
    if (!fields) { status.fail(before, err); return; }
    const rest = [];
    let first = null;
    Object.entries(fields).forEach(([path, reason]) => {
      const at = errors[path];
      const words = at && at.limit && reason === "invalid" ? M.t("landing.empty_or_long", { limit: at.limit }) : reasonText(reason);
      if (at) { at.textContent = words; if (!first) first = at; } else rest.push(path + ": " + words);
    });
    status.fail(before, { message: rest.length ? rest.join("; ") : M.t("landing.see_fields") });
    const input = first && first.parentNode && first.parentNode.querySelector ? first.parentNode.querySelector("input, textarea") : null;
    if (input && input.focus) input.focus();
  }

  // A draft opened as the hub would serve it (§16.7, §16.7.1; a legal page's
  // draft is its languages alone, the page named in ?page=): stored by a
  // POST with the CSRF token, then opened by its url in a tab of its own, a
  // top-level page under the page's own policy. The tab is opened at the
  // click, before the hub answers, so no pop-up blocker stops it.
  // A preview while the JSON field holds text not loaded would show the
  // editor's draft, not that text: said instead, and the field shown.
  function unloaded(pending, status, focus) {
    if (!pending()) return false;
    status.fail(M.t("jsonio.pending_prefix"), { message: M.t("jsonio.pending") });
    focus();
    return true;
  }

  const PREVIEW = /^(\/api\/v1)?\/admin\/settings\/(landing|legal)\/preview\/[A-Za-z0-9_-]+$/;
  async function preview(path, body, lang, status, errors, variant) {
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    status.busy(M.t("landing.preview.preparing"));
    try {
      const answer = await M.api.post(path, body);
      const at = new URL(String((answer && answer.url) || ""), window.location.href);
      if (at.origin !== window.location.origin || !PREVIEW.test(at.pathname)) throw new Error(M.t("landing.preview.no_address"));
      if (lang && !at.searchParams.has("lang")) at.searchParams.set("lang", lang);
      // A variant's draft (§16.7.2); without it the main page.
      if (variant) at.searchParams.set("variant", variant);
      if (tab) tab.location.href = at.href; else window.open(at.href, "_blank", "noopener");
      status.done();
      append(status.el, h("span", { class: "ok" }, M.t("landing.preview.opened")));
    } catch (err) {
      if (tab) tab.close();
      showErrors(errors, err, status);
    }
  }

  async function section(ctx, root) {
    const status = M.statusLine();
    const box = h("div", { class: "lp-editor" });
    append(root, h("h3", null, M.t("landing.title")),
      h("p", { class: "hint" }, M.t("landing.intro")), status.el, box);
    let saved = await M.api.get(LANDING);
    // The setting as the editor holds it: every part present, variants and campaigns included (§16.7.2).
    const editable = (x) => {
      const d = JSON.parse(JSON.stringify(x));
      d.pages = d.pages || {};
      // No operator line is none, never an empty one, which the hub refuses (§16.7).
      d.footer = d.footer || { social: [] };
      d.variants = isObject(d.variants) ? d.variants : {};
      d.campaigns = Array.isArray(d.campaigns) ? d.campaigns : [];
      return d;
    };
    let draft = editable(saved);
    let lang = draft.default_language || Object.keys(draft.pages)[0] || "en";
    // The page being edited: the main page (null) or a variant's slug.
    let which = null;
    const pagesOf = () => (which ? draft.variants[which].pages : draft.pages);
    const prefixOf = () => (which ? "variants." + which + ".pages" : "pages");
    // What the JSON field holds and was not loaded (jsonPart sets these).
    let jsonPending = () => false;
    let jsonFocus = () => {};
    // The fields drawn last, by the hub's path: an import's check marks them.
    let errors = {};
    // Where the step-up asks for the second factor, kept across redraws.
    const stepSlot = h("div", { class: "step-up-slot" });
    stepSlot.hidden = true;
    const draw = () => {
      errors = {};
      if (which && !draft.variants[which]) which = null;
      const pages = pagesOf();
      const langs = Object.keys(pages);
      if (!langs.includes(lang)) lang = langs[0] || null;
      const enabled = h("input", { type: "checkbox", id: "lp-enabled" });
      enabled.checked = !!draft.enabled;
      enabled.addEventListener("change", () => { draft.enabled = enabled.checked; });
      const def = h("select", { id: "lp-default-language", "data-path": "default_language" }, langs.map((l) => h("option", { value: l }, l)));
      def.value = draft.default_language;
      def.addEventListener("change", () => { draft.default_language = def.value; });
      errors.default_language = h("p", { class: "field-error", role: "alert" });
      errors.enabled = h("p", { class: "field-error", role: "alert" });
      const newLang = h("input", { id: "lp-new-language", placeholder: "de", maxlength: "20", autocomplete: "off", spellcheck: "false" });
      const addLang = h("button", { type: "button", class: "small" }, M.t("landing.language.add"));
      addLang.addEventListener("click", () => {
        const tag = newLang.value.trim();
        if (!LANG.test(tag) || pages[tag]) { newLang.focus(); return; }
        pages[tag] = { title: "", description: "", sections: [] };
        if (!which && (!draft.default_language || !draft.pages[draft.default_language])) draft.default_language = tag;
        lang = tag;
        draw();
      });
      const tabs = h("div", { class: "lp-tabs", role: "group", "aria-label": M.t("landing.languages") }, langs.map((l) => {
        const b = h("button", { type: "button", "aria-pressed": String(l === lang) }, l);
        b.addEventListener("click", () => { lang = l; draw(); });
        return b;
      }));
      const footer = draft.footer;
      footer.social = footer.social || [];
      const social = h("ol", { class: "lp-items" }, footer.social.map((x, k) => h("li", { class: "lp-item" },
        control(f("link", () => M.t("landing.social_link", { n: String(k + 1) }), "cta"), { link: x }, "footer.social." + k, errors, draw),
        small(M.t("landing.entry.remove"), () => footer.social.splice(k, 1), false, draw))));
      // Variants (§16.7.2): the main page and up to 5 more, each at /for/<slug>,
      // edited here one at a time with the same page editor.
      const variantsPart = () => {
        const slugs = Object.keys(draft.variants);
        const pick = h("div", { class: "lp-variant-tabs", role: "group", "aria-label": M.t("landing.variant.pages") },
          [[null, M.t("landing.variant.main")]].concat(slugs.map((v) => [v, "/for/" + v])).map(([v, label]) => {
            const b = h("button", { type: "button", "aria-pressed": String(v === which), "data-variant": v || "" }, label);
            // The language shown stays where the other page has it too.
            b.addEventListener("click", () => { which = v; if (!pagesOf()[lang]) lang = draft.default_language; draw(); });
            return b;
          }));
        const slug = h("input", { id: "lp-new-variant", maxlength: "40", autocomplete: "off", spellcheck: "false",
          "aria-describedby": ["lp-new-variant-hint", "lp-new-variant-error"].join(" ") });
        const slugError = h("p", { class: "field-error", id: "lp-new-variant-error", role: "alert" });
        errors.variants = slugError;
        const add = h("button", { type: "button", class: "small" }, M.t("landing.variant.add"));
        add.disabled = slugs.length >= 5;
        add.addEventListener("click", () => {
          const v = slug.value.trim();
          if (!SLUG.test(v) || v === "default" || draft.variants[v]) { slugError.textContent = M.t("landing.variant.bad_slug"); slug.focus(); return; }
          const dl = draft.default_language || "en";
          draft.variants[v] = { pages: { [dl]: { title: "", description: "", sections: [] } } };
          which = v;
          lang = dl;
          draw();
        });
        // A saved variant is seen as a visitor sees it, in a page of its own (never the app's router).
        const savedOne = which && saved.enabled && isObject(saved.variants) && saved.variants[which];
        return h("section", { class: "lp-variant-box", "aria-labelledby": "lp-variants-title" },
          h("h4", { id: "lp-variants-title" }, M.t("landing.variant.title")),
          h("p", { class: "hint" }, M.t("landing.variant.hint")),
          pick,
          h("div", { class: "inline-form" }, h("label", { for: "lp-new-variant" }, M.t("landing.variant.slug")), slug, add,
            h("span", { class: "hint", id: "lp-new-variant-hint" }, M.t("landing.variant.slug_hint"))), slugError,
          which ? h("div", { class: "actions" },
            small(M.t("landing.variant.remove", { slug: which }), () => { delete draft.variants[which]; which = null; }, false, draw),
            savedOne ? h("a", { href: "/for/" + encodeURIComponent(which), target: "_blank", rel: "noopener" }, M.t("landing.variant.open", { slug: which })) : null) : null);
      };
      // Campaigns (§16.7.2): the codes the hub counts, each with a label for the admin.
      const campaignsPart = () => {
        const list = draft.campaigns;
        return h("section", { class: "lp-campaigns", "aria-labelledby": "lp-campaigns-title" },
          h("h4", { id: "lp-campaigns-title" }, M.t("landing.campaign.title")),
          h("p", { class: "hint" }, M.t("landing.campaign.hint")),
          h("p", { class: "hint lp-privacy" }, M.t("landing.campaign.privacy")),
          list.length ? h("ol", { class: "lp-items lp-campaign-list" }, list.map((c, k) => h("li", { class: "lp-item" },
            control(f("code", () => M.t("landing.campaign.code"), "text", 40), c, "campaigns." + k + ".code", errors, draw),
            control(f("label", () => M.t("landing.campaign.label"), "text", 120), c, "campaigns." + k + ".label", errors, draw),
            CODE.test(c.code || "") ? h("p", { class: "muted lp-campaign-param" }, "?c=" + c.code) : null,
            small(M.t("landing.campaign.remove"), () => list.splice(k, 1), false, draw))))
            : h("p", { class: "muted" }, M.t("landing.campaign.none")),
          small(M.t("landing.campaign.add"), () => list.push({ code: "", label: "" }), list.length >= 200, draw));
      };
      const form = h("form", {
        class: "lp-form project-form",
        onsubmit: async (e) => {
          e.preventDefault();
          status.busy(M.t("landing.saving"));
          const body = { enabled: !!draft.enabled, default_language: draft.default_language, pages: draft.pages, footer: draft.footer,
            variants: draft.variants, campaigns: draft.campaigns };
          try {
            // A sensitive call (§2.8.4): the second factor asked for here when the hub wants it.
            saved = await M.stepUp.run(() => M.api.patch(LANDING, body), stepSlot, M.t("landing.save.step_up"));
            draft = editable(saved);
            if (which && !draft.variants[which]) which = null;
            draw();
            status.done();
            append(status.el, h("span", { class: "ok" }, M.t("landing.saved")));
          } catch (err) {
            if (err.code === "cancelled") status.done();
            else showErrors(errors, err, status);
          }
        },
      },
      h("p", { class: "check" }, enabled, h("label", { for: "lp-enabled" }, " " + M.t("landing.enabled"))), errors.enabled,
      variantsPart(),
      h("div", { class: "inline-form" }, h("label", { for: "lp-new-language" }, M.t("landing.languages")), tabs, newLang, addLang),
      langs.length ? [which ? h("p", { class: "hint" }, M.t("landing.variant.fallback", { lang: draft.default_language || "en" }))
        : [h("label", { for: "lp-default-language" }, M.t("landing.language.default")), def, errors.default_language],
        lang ? [small(M.t("landing.language.remove"), () => { delete pages[lang]; if (!which && draft.default_language === lang) draft.default_language = Object.keys(draft.pages)[0] || "en"; }, false, draw),
          pageEditor(pages, prefixOf(), lang, errors, draw)] : null]
        : h("p", { class: "muted" }, M.t("landing.language.none")),
      h("h4", null, M.t("landing.footer")),
      control(f("operator", () => M.t("landing.field.operator_line_name_country"), "text", 120, { optional: true }), footer, "footer.operator", errors, draw),
      social, small(M.t("landing.social_add"), () => footer.social.push({ label: "", href: "" }), footer.social.length >= 8, draw),
      h("p", { class: "hint" }, M.t("landing.footer_hint")),
      campaignsPart(),
      stepSlot,
      h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, M.t("landing.save")),
        h("button", { type: "button", onclick: () => {
          if (unloaded(jsonPending, status, jsonFocus)) return;
          preview(LANDING + "/preview", { default_language: draft.default_language, pages: draft.pages, footer: draft.footer, variants: draft.variants }, lang, status, errors, which);
        } }, which ? M.t("landing.variant.preview", { slug: which }) : M.t("landing.preview")),
        // The saved page as a visitor sees it (§16.7, ?as=public), only while it is on.
        saved.enabled ? h("a", { href: "/?as=public" + (lang ? "&lang=" + encodeURIComponent(lang) : ""), target: "_blank", rel: "noopener" }, M.t("landing.view_as_visitor")) : null),
      saved.updated_at ? h("p", { class: "muted" }, M.t("landing.last_saved", { time: formatTime(saved.updated_at) })) : null);
      append(clear(box), form);
    };
    draw();
    append(root, jsonPart());

    // Import and export as JSON (tsk-36d575f5yybz): the draft as text, or
    // text as the draft. An import replaces the draft after a confirmation
    // and is checked by the hub's preview call, which stores nothing; only
    // Save saves it, as for a draft typed by hand.
    function jsonPart() {
      const io = M.statusLine();
      const area = h("textarea", { id: "lp-json", rows: "10", spellcheck: "false", "aria-describedby": "lp-json-hint" });
      // The text last exported or loaded: anything else in the field is not in the editor.
      let settled = "";
      jsonPending = () => area.value.trim() !== "" && area.value !== settled;
      jsonFocus = () => { area.parentNode.open = true; area.focus(); };
      const file = h("input", { type: "file", id: "lp-json-file", accept: ".json,application/json" });
      file.addEventListener("change", async () => {
        const chosen = file.files && file.files[0];
        if (!chosen) return;
        try { area.value = await chosen.text(); io.done(); } catch (err) { io.fail(M.t("landing.json.file_failed"), err); }
      });
      const bodyOf = () => ({ enabled: !!draft.enabled, default_language: draft.default_language, pages: draft.pages, footer: draft.footer,
        variants: draft.variants, campaigns: draft.campaigns });
      const exportIt = () => {
        area.value = settled = JSON.stringify(bodyOf(), null, 2);
        io.done();
        append(io.el, h("span", { class: "ok" }, M.t("landing.json.exported")));
        area.focus();
      };
      const copy = async () => {
        try { await navigator.clipboard.writeText(area.value); io.done(); append(io.el, h("span", { class: "ok" }, M.t("landing.json.copied"))); }
        catch (err) { io.fail(M.t("landing.json.copy_failed"), err); }
      };
      async function importIt() {
        let data;
        try { data = JSON.parse(area.value); } catch (err) { io.fail(M.t("landing.json.not_loaded"), { message: M.t("landing.json.not_json", { reason: err.message }) }); area.focus(); return; }
        // The body of PATCH …/landing, or one language's page.
        const whole = isObject(data) && isObject(data.pages);
        const one = isObject(data) && !whole && Array.isArray(data.sections);
        if (!whole && !one) { io.fail(M.t("landing.json.not_loaded"), { message: M.t("landing.json.shape") }); area.focus(); return; }
        const target = lang || "en";
        if (!window.confirm(whole ? M.t("landing.json.confirm_all") : M.t("landing.json.confirm_page", { lang: target }))) return;
        const before = { draft, lang };
        // Footer, variants and campaigns as in the whole site's import: a value of the wrong kind refuses, never the draft's in its place.
        const wrongKind = whole && (("footer" in data && !isObject(data.footer)) || ("variants" in data && !isObject(data.variants)) || ("campaigns" in data && !Array.isArray(data.campaigns)));
        let next;
        if (whole) {
          // A field the body leaves out keeps what the editor has, as a PATCH keeps the stored one (§16.7).
          next = { enabled: "enabled" in data ? !!data.enabled : !!draft.enabled,
            default_language: data.default_language || Object.keys(data.pages)[0] || "en",
            pages: data.pages, footer: isObject(data.footer) ? data.footer : draft.footer,
            variants: isObject(data.variants) ? data.variants : draft.variants, campaigns: Array.isArray(data.campaigns) ? data.campaigns : draft.campaigns };
        } else {
          // One language's page goes into the page being edited: the main page or a variant's.
          const one = { [target]: { title: data.title || "", description: data.description || "", sections: data.sections } };
          next = which
            ? Object.assign({}, draft, { variants: Object.assign({}, draft.variants, { [which]: { pages: Object.assign({}, draft.variants[which].pages, one) } }) })
            : Object.assign({}, draft, { pages: Object.assign({}, draft.pages, one) });
          if (!next.default_language || !next.pages[next.default_language]) next.default_language = target;
        }
        // The hub checks it first: a part of the wrong kind (a list that is no list) is its to
        // name, and the editor is drawn from what it would take.
        status.busy(M.t("landing.json.checking"));
        let refused = null;
        try {
          await M.api.post(LANDING + "/preview", { default_language: next.default_language, pages: next.pages, footer: next.footer, variants: next.variants, campaigns: next.campaigns });
        } catch (err) {
          refused = err;
        }
        // Not drawable as an editor: the draft stays as it was, the hub's refusals listed.
        if (wrongKind || !drawable(next.pages, next.footer) || !Object.values(next.variants || {}).every((v) => isObject(v) && isObject(v.pages) && drawable(v.pages, next.footer))
          || !(next.campaigns || []).every(isObject)) {
          draft = before.draft;
          lang = before.lang;
          showErrors({}, wrongKind ? { message: M.t("landing.json.wrong_kind") } : refused || { message: M.t("landing.json.shape") }, status, M.t("landing.json.not_loaded"));
          return;
        }
        draft = editable(next);
        if (whole) which = null;
        lang = whole ? next.default_language : target;
        settled = area.value;
        draw();
        if (refused) { showErrors(errors, refused, status, M.t("landing.json.refused")); return; }
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("landing.json.loaded")));
      }
      return h("details", { class: "lp-json field-stack" }, h("summary", null, M.t("landing.json.title")),
        h("p", { class: "hint", id: "lp-json-hint" }, M.t("landing.json.hint")),
        h("label", { for: "lp-json" }, M.t("landing.json.label")), area,
        h("div", { class: "inline-form" }, h("label", { for: "lp-json-file" }, M.t("landing.json.file")), file),
        h("div", { class: "actions" },
          h("button", { type: "button", onclick: importIt }, M.t("landing.json.import")),
          h("button", { type: "button", onclick: exportIt }, M.t("landing.json.export")),
          h("button", { type: "button", onclick: copy }, M.t("landing.json.copy"))),
        io.el);
    }
  }

  // ---- the legal pages (§16.7.1) ------------------------------------------

  // [key, name, address], the name read when said.
  const legal = (k, name, served) => Object.defineProperty([k, undefined, served], 1, { get: name, enumerable: true });
  const PAGES = [legal("imprint", () => M.t("legal.imprint"), "/impressum"), legal("privacy", () => M.t("legal.privacy"), "/privacy"), legal("terms", () => M.t("legal.terms"), "/terms")];
  // Whole sentences per page: a page's name does not bend the same way in every language.
  const LEGAL_WORDS = {
    imprint: { save: () => M.t("legal.imprint.save"), confirm: () => M.t("legal.imprint.confirm"), down: () => M.t("legal.imprint.down"), saved: () => M.t("legal.imprint.saved") },
    privacy: { save: () => M.t("legal.privacy.save"), confirm: () => M.t("legal.privacy.confirm"), down: () => M.t("legal.privacy.down"), saved: () => M.t("legal.privacy.saved") },
    terms: { save: () => M.t("legal.terms.save"), confirm: () => M.t("legal.terms.confirm"), down: () => M.t("legal.terms.down"), saved: () => M.t("legal.terms.saved") },
  };

  function legalPage(key, label, served, current, defaultLanguage, done) {
    const status = M.statusLine();
    const errors = {};
    const draft = JSON.parse(JSON.stringify((current && current.languages) || {}));
    // It opens on the setting's default language where the page has it.
    let lang = draft[defaultLanguage] ? defaultLanguage : Object.keys(draft)[0] || null;
    const body = h("div");
    // A sensitive call (§2.8.4: PATCH /admin/settings/*): the second factor asked for here when the hub wants it.
    const stepSlot = h("div", { class: "step-up-slot" });
    stepSlot.hidden = true;
    const patchLegal = (value) => M.stepUp.run(() => M.api.patch(LEGAL, value), stepSlot, M.t("legal.save.step_up", { page: label }));
    const failed = (err) => { if (err.code === "cancelled") status.done(); else showErrors(errors, err, status); };
    const draw = () => {
      Object.keys(errors).forEach((k) => delete errors[k]);
      const langs = Object.keys(draft);
      if (!langs.includes(lang)) lang = langs[0] || null;
      const newLang = h("input", { id: "lg-" + key + "-new-language", placeholder: "de", maxlength: "20", autocomplete: "off", spellcheck: "false" });
      const addLang = h("button", { type: "button", class: "small" }, M.t("landing.language.add"));
      addLang.addEventListener("click", () => {
        const tag = newLang.value.trim();
        if (!LANG.test(tag) || draft[tag] || langs.length >= 10) { newLang.focus(); return; }
        draft[tag] = { title: label, markdown: "" };
        lang = tag;
        draw();
      });
      const tabs = h("div", { class: "lp-tabs", role: "group", "aria-label": M.t("legal.languages", { page: label }) }, langs.map((l) => {
        const b = h("button", { type: "button", "aria-pressed": String(l === lang) }, l);
        b.addEventListener("click", () => { lang = l; draw(); });
        return b;
      }));
      const save = h("button", { type: "submit", class: "primary" }, LEGAL_WORDS[key].save());
      const unset = current ? h("button", { type: "button", class: "danger" }, M.t("legal.take_down")) : null;
      if (unset) {
        unset.addEventListener("click", async () => {
          if (!window.confirm(LEGAL_WORDS[key].confirm())) return;
          status.busy(M.t("legal.taking_down"));
          try { done(await patchLegal({ [key]: null }), LEGAL_WORDS[key].down()); } catch (err) { failed(err); }
        });
      }
      const form = h("form", {
        class: "lg-form project-form",
        onsubmit: async (e) => {
          e.preventDefault();
          status.busy(M.t("landing.saving"));
          try { done(await patchLegal({ [key]: draft }), LEGAL_WORDS[key].saved()); } catch (err) { failed(err); }
        },
      },
      h("div", { class: "inline-form" }, h("label", { for: "lg-" + key + "-new-language" }, M.t("landing.languages")), tabs, newLang, addLang),
      lang ? [control(f("title", () => M.t("landing.field.title"), "text", 120), draft[lang], key + "." + lang + ".title", errors, draw),
        control(f("markdown", () => M.t("landing.field.text_markdown"), "md", 65536), draft[lang], key + "." + lang + ".markdown", errors, draw),
        small(M.t("landing.language.remove"), () => { delete draft[lang]; }, false, draw)] : h("p", { class: "muted" }, M.t("legal.language.none")),
      h("div", { class: "actions" }, save,
        lang ? h("button", { type: "button", onclick: () => {
          if (unloaded(json.pending, status, json.focus)) return;
          preview(LEGAL + "/preview?page=" + key, draft, lang, status, errors);
        } }, M.t("landing.preview")) : null,
        unset), stepSlot, status.el);
      append(clear(body), form);
    };
    // Import and export of this page's languages (§16.7.1: a PATCH changes one page).
    const json = M.jsonIo.part({
      id: "lg-" + key + "-json",
      hint: M.t("jsonio.legal.hint", { page: key }),
      body: () => draft,
      load: async (data, io) => {
        const langs = M.jsonIo.isObject(data) && Object.hasOwn(data, key) ? data[key] : data;
        const tags = M.jsonIo.isObject(langs) ? Object.keys(langs) : [];
        if (!tags.length || tags.length > 10 || !tags.every((t) => LANG.test(t) && M.jsonIo.isObject(langs[t])
          && typeof langs[t].title === "string" && typeof langs[t].markdown === "string")) {
          io.fail(M.t("jsonio.not_loaded"), { message: M.t("jsonio.legal.shape") });
          return false;
        }
        if (!window.confirm(M.t("jsonio.legal.confirm", { page: label }))) return false;
        io.busy(M.t("jsonio.checking"));
        // The hub checks it by its preview call, which stores nothing (§16.7.1).
        let refused = null;
        try { await M.api.post(LEGAL + "/preview?page=" + key, langs); } catch (err) { refused = err; }
        Object.keys(draft).forEach((t) => { delete draft[t]; });
        tags.forEach((t) => { draft[t] = { title: langs[t].title, markdown: langs[t].markdown }; });
        lang = draft[defaultLanguage] ? defaultLanguage : tags[0];
        draw();
        io.done();
        if (refused) { showErrors(errors, refused, status, M.t("jsonio.refused")); return true; }
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("jsonio.loaded")));
        // A file of several pages loads only this one (a PATCH changes one page): the others named.
        const others = PAGES.map(([k]) => k).filter((k) => k !== key && M.jsonIo.isObject(data) && Object.hasOwn(data, k));
        if (others.length) append(status.el, " ", h("span", { class: "muted" }, M.t("jsonio.legal.others", { pages: M.fmt.list(others) })));
        return true;
      },
    });
    draw();
    const versions = (key !== "imprint" && current && current.versions) || []; // the imprint serves none (§16.7.1)
    return h("section", { class: "lg-page", "aria-label": label },
      h("h4", null, label),
      current
        ? h("p", { class: "muted" }, M.tn("legal.served", { address: h("a", { href: served, target: "_blank", rel: "noopener" }, served), time: formatTime(current.version) }),
          versions.length ? [" ", M.tn("legal.earlier", { versions: versions.map((v, i) => [i ? ", " : null, h("a", { href: served + "/" + v, target: "_blank", rel: "noopener" }, formatTime(v))]) })] : null)
        : h("p", { class: "muted" }, M.t("legal.not_set", { address: served })),
      body, json.el);
  }

  async function legalSection(ctx, root) {
    const note = h("div");
    const box = h("div");
    append(root, h("h3", null, M.t("legal.title")),
      h("p", { class: "hint" }, M.t("legal.intro")),
      note, box);
    const draw = (value, words) => {
      clear(note);
      if (words) append(note, h("p", { class: "ok", role: "status" }, words));
      append(clear(box), PAGES.map(([key, label, served]) => legalPage(key, label, served, (value.pages || {})[key] || null, value.default_language, (now, said) => draw(now, said))));
    };
    draw(await M.api.get(LEGAL));
  }

  // The legal pages that are set, as links (§16.7.1: the login and the
  // registration page link to them): an element filled once GET /legal answers.
  function links() {
    const p = h("p", { class: "legal-links muted" });
    M.api.get("/legal").then((v) => {
      const set = v && v.pages ? PAGES.filter(([key]) => v.pages[key]) : [];
      set.forEach(([, label, served], i) => append(p, i ? " · " : null, h("a", { href: served }, label)));
    }, () => {});
    return p;
  }

  M.landing = { section, TYPES };
  M.legal = { section: legalSection, links };
})(window.Maity);
