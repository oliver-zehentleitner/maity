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

  // A field of a section or of an item: its key, its label, its kind and
  // its limit. Kinds: text (one line), long (several lines), md (Markdown),
  // cta ({label, href}), href (a link's target), lines (one entry per line:
  // the points, handles, projects), stats (counters to tick), count (a
  // number), choice (one of `choices`), group (an object of `fields`).
  const f = (key, label, kind, max, extra) => Object.assign({ key, label, kind, max }, extra || {});
  const STATS = [["people", "People"], ["agents", "Agents"], ["public_projects", "Public projects"], ["cards_done_week", "Cards done this week"],
    ["people_online", "People online"], ["agents_online", "Agents online"]];
  // The types the hub renders in this version (§16.7); activity and collab
  // are kept as they are, never offered.
  const TYPES = {
    hero: { label: "Hero", fields: [f("eyebrow", "Eyebrow", "text", 40), f("title", "Title", "text", 120), f("subline", "Subline", "long", 300),
      f("cta_primary", "Main button", "cta"), f("cta_secondary", "Second button (optional)", "cta", null, { optional: true }), f("note", "Note (Markdown)", "md", 500)] },
    stats: { label: "Counters", fields: [f("items", "Counters", "stats")] },
    steps: { label: "Steps", fields: [f("title", "Title", "text", 120)],
      items: { min: 1, max: 6, label: "Step", fields: [f("title", "Title", "text", 80), f("text", "Text", "long", 300), f("code", "Code (optional)", "long", 300, { optional: true })] } },
    scales: { label: "Scales", fields: [f("title", "Title", "text", 120)],
      items: { min: 1, max: 4, label: "Scale", fields: [f("tag", "Tag", "text", 40), f("title", "Title", "text", 80), f("text", "Text", "long", 300),
        f("points", "Points, one per line", "lines", 5)] } },
    faq: { label: "Questions", fields: [f("title", "Title", "text", 120)],
      items: { min: 1, max: 20, label: "Question", fields: [f("q", "Question", "text", 200), f("a", "Answer (Markdown)", "md", 2000)] } },
    cta_band: { label: "Call to action", fields: [f("title", "Title", "text", 120), f("text", "Text", "long", 300), f("cta", "Button", "cta")] },
    text: { label: "Text", fields: [f("title", "Title (optional)", "text", 120, { optional: true }), f("markdown", "Text (Markdown)", "md", 16384)] },
    profiles: { label: "Profiles", note: "Shown only while public pages are on; a handle without a public profile is left out.",
      fields: [f("title", "Title", "text", 120), f("markdown", "Text (Markdown)", "md", 2000), f("handles", "Handles, one per line", "lines", 2)] },
    explore: { label: "Explore", note: "Shown only while public pages are on; empty for the hub's own choice.",
      fields: [f("title", "Title", "text", 120), f("projects", "Projects (owner/slug), one per line", "lines", 3)] },
    // §16.7 (#737): a terminal typed line by line, the question an agent asks
    // its human, and exactly three steps; the page shows them all without script.
    demo: { label: "Demo", fields: [f("title", "Title", "text", 120), f("subline", "Subline (optional)", "long", 300, { optional: true }),
      f("inbox", "Inbox item (optional)", "group", null, { optional: true, fields: [f("from", "From", "text", 80), f("question", "Question", "long", 300),
        f("context", "Context (optional)", "long", 300, { optional: true })] })],
      lists: [
        { key: "terminal_lines", min: 1, max: 8, label: "Terminal line", fields: [f("kind", "Kind", "choice", null, { choices: [["cmd", "Command typed"], ["out", "Its output"], ["note", "Comment"]] }),
          f("text", "Text", "text", 200)] },
        { key: "steps", min: 3, max: 3, label: "Step", fields: [f("title", "Title", "text", 80), f("text", "Text", "long", 300)] },
      ] },
    opensource: { label: "Open source", fields: [f("title", "Title", "text", 120), f("markdown", "Text (Markdown, optional)", "md", 600, { optional: true })],
      lists: [
        { key: "tiles", min: 1, max: 3, label: "Tile", fields: [f("title", "Title", "text", 80), f("text", "Text", "long", 300)] },
        { key: "links", min: 0, max: 4, label: "Link", fields: [f("label", "Label", "text", 40), f("href", "Link", "href")] },
      ] },
  };
  // A type's lists of entries: its items, and the named lists of the newer types.
  const listsOf = (type) => (type.items ? [Object.assign({ key: "items" }, type.items)] : []).concat(type.lists || []);
  const KEPT = { activity: "Activity", collab: "Collaboration" };

  // A new object of `fields`, as the hub would take it.
  function freshOf(fields) {
    const o = {};
    fields.forEach((x) => {
      if (x.optional) return;
      if (x.kind === "cta") o[x.key] = { label: "", href: "" };
      else if (x.kind === "stats" || x.kind === "lines") o[x.key] = [];
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
    required: "required", control_character: "holds a control character", html: "holds HTML outside fenced code",
    invalid_href: "not an https URL or a path on this host", unknown_type: "not a section this hub knows", extra_forbidden: "not a field of this section",
    too_many: "too many", too_few: "at least one is needed", invalid: "not valid here", default_language_missing: "the default language has no page",
    rate_limited: "changed too often today",
    // §16.7: the stored setting is at most 256 KiB of UTF-8.
    too_large: "the page is too large: at most 256 KiB stored, all languages together",
  };
  const reasonText = (r) => REASONS[r] || String(r).replace(/_/g, " ");
  // A field's limit in words (§16.7, §16.7.1): KiB where the hub counts bytes, else characters.
  const limitWords = (max) => (max >= 1024 && max % 1024 === 0 ? "at most " + max / 1024 + " KiB" : "at most " + max + " characters");

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
        const add = h("button", { type: "button", class: "small" }, "Add " + x.label.replace(/ \(optional\)$/, "").toLowerCase());
        add.addEventListener("click", () => { obj[x.key] = { label: "", href: "" }; redraw(); });
        return h("div", { class: "lp-field" }, h("span", { class: "lp-label" }, x.label), add, error);
      }
      const cta = obj[x.key];
      const label = h("input", Object.assign({ id: id + "-label", maxlength: "40" }, described));
      label.value = cta.label || "";
      label.addEventListener("input", () => { cta.label = label.value; });
      const href = h("input", { id: id + "-href", placeholder: "/register or https://…", "aria-describedby": id + "-href-error", "data-path": path + ".href" });
      href.value = cta.href || "";
      href.addEventListener("input", () => { cta.href = href.value.trim(); });
      const hrefError = h("p", { class: "field-error", id: id + "-href-error", role: "alert" });
      errors[path + ".href"] = hrefError;
      errors[path + ".label"] = error;
      const remove = x.optional ? h("button", { type: "button", class: "small" }, "Remove") : null;
      if (remove) remove.addEventListener("click", () => { delete obj[x.key]; redraw(); });
      return h("fieldset", { class: "lp-field lp-cta" }, h("legend", null, x.label),
        h("label", { for: id + "-label" }, "Label"), label, error,
        h("label", { for: id + "-href" }, "Link"), href, hrefError, remove);
    }
    if (x.kind === "stats") {
      const chosen = obj[x.key] = obj[x.key] || [];
      return h("fieldset", { class: "lp-field lp-stats" }, h("legend", null, x.label),
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
        h("p", { class: "hint" }, "An online count below 5 is shown as “< 5”."), error);
    }
    if (x.kind === "choice") {
      input = h("select", Object.assign({ id }, described), x.choices.map(([v, l]) => h("option", { value: v }, l)));
      input.value = obj[x.key] || x.choices[0][0];
      input.addEventListener("change", () => { obj[x.key] = input.value; });
      return h("div", { class: "lp-field" }, h("label", { for: id }, x.label), input, error);
    }
    if (x.kind === "group") {
      if (!obj[x.key]) {
        const add = h("button", { type: "button", class: "small" }, "Add " + x.label.replace(/ \(optional\)$/, "").toLowerCase());
        add.addEventListener("click", () => { obj[x.key] = freshOf(x.fields); redraw(); });
        return h("div", { class: "lp-field" }, h("span", { class: "lp-label" }, x.label), add, error);
      }
      const remove = x.optional ? h("button", { type: "button", class: "small" }, "Remove") : null;
      if (remove) remove.addEventListener("click", () => { delete obj[x.key]; redraw(); });
      return h("fieldset", { class: "lp-field lp-group" }, h("legend", null, x.label),
        x.fields.map((y) => control(y, obj[x.key], path + "." + y.key, errors, redraw)), remove, error);
    }
    if (x.kind === "href") {
      input = h("input", Object.assign({ id, placeholder: "/register or https://…" }, described));
      input.value = obj[x.key] || "";
      input.addEventListener("input", () => { obj[x.key] = input.value.trim(); });
      return h("div", { class: "lp-field" }, h("label", { for: id }, x.label), input, error);
    }
    if (x.kind === "lines") {
      input = h("textarea", Object.assign({ id, rows: String(Math.max(2, x.max)) }, described));
      input.value = (obj[x.key] || []).join("\n");
      input.addEventListener("input", () => { obj[x.key] = input.value.split("\n").map((s) => s.trim()).filter(Boolean); });
      return h("div", { class: "lp-field" }, h("label", { for: id }, x.label + " (at most " + x.max + ")"), input, error);
    }
    input = x.kind === "text"
      ? h("input", Object.assign({ id, maxlength: String(x.max) }, described))
      : h("textarea", Object.assign({ id, rows: x.kind === "md" ? "6" : "3" }, described));
    input.value = obj[x.key] || "";
    input.addEventListener("input", () => {
      if (x.optional && !input.value) delete obj[x.key];
      else obj[x.key] = input.value;
    });
    return h("div", { class: "lp-field" }, h("label", { for: id }, x.label), input,
      x.kind === "md" ? h("p", { class: "hint" }, "Headings, paragraphs, emphasis, lists, quotes, fenced code and links (https, or a path like /register); no images, no HTML. "
        + limitWords(x.max).replace(/^at/, "At") + ".")
        : x.kind === "long" ? h("p", { class: "hint" }, limitWords(x.max).replace(/^at/, "At") + ".") : null,
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

  function sectionBox(lang, sections, i, errors, redraw) {
    const s = sections[i];
    const path = "pages." + lang + ".sections." + i;
    const type = TYPES[s.type];
    const on = h("input", { type: "checkbox", id: "lp-" + lang + "-" + i + "-enabled" });
    on.checked = s.enabled !== false;
    on.addEventListener("change", () => { s.enabled = on.checked; });
    const error = h("p", { class: "field-error", role: "alert" });
    errors[path] = error;
    errors[path + ".type"] = error;
    const head = h("div", { class: "lp-section-head" },
      h("h5", { class: "lp-section-title" }, (i + 1) + ". " + (type ? type.label : KEPT[s.type] || s.type)),
      h("label", { class: "check", for: "lp-" + lang + "-" + i + "-enabled" }, on, " Shown"),
      small("Up", () => move(sections, i, -1), i === 0, redraw), small("Down", () => move(sections, i, 1), i === sections.length - 1, redraw),
      small("Remove", () => sections.splice(i, 1), false, redraw));
    if (!type) {
      return h("li", { class: "lp-section kept" }, head,
        h("p", { class: "muted" }, "Kept as it is: this hub shows this section in a later version, not yet."), error);
    }
    // Each list of entries: moved, removed down to its least, added up to its most.
    const lists = listsOf(type).map((l) => {
      const items = s[l.key] = s[l.key] || [];
      const listError = h("p", { class: "field-error", role: "alert" });
      errors[path + "." + l.key] = listError;
      return [l.min === l.max ? h("p", { class: "hint" }, "Exactly " + l.min + ".") : null,
        h("ol", { class: "lp-items", "data-list": l.key }, items.map((item, k) => h("li", { class: "lp-item" },
          h("div", { class: "lp-section-head" }, h("span", { class: "lp-item-title" }, l.label + " " + (k + 1)),
            small("Up", () => move(items, k, -1), k === 0, redraw), small("Down", () => move(items, k, 1), k === items.length - 1, redraw),
            small("Remove", () => items.splice(k, 1), items.length <= l.min, redraw)),
          l.fields.map((x) => control(x, item, path + "." + l.key + "." + k + "." + x.key, errors, redraw))))),
        l.min === l.max ? null : small("Add " + l.label.toLowerCase(), () => items.push(freshOf(l.fields)), items.length >= l.max, redraw),
        listError];
    });
    return h("li", { class: "lp-section" }, head, type.note ? h("p", { class: "hint" }, type.note) : null,
      type.fields.map((x) => control(x, s, path + "." + x.key, errors, redraw)), lists, error);
  }

  function pageEditor(draft, lang, errors, redraw) {
    const p = draft.pages[lang];
    p.sections = p.sections || [];
    const title = control(f("title", "Page title", "text", 120), p, "pages." + lang + ".title", errors, redraw);
    const description = control(f("description", "Description (for search engines)", "long", 300), p, "pages." + lang + ".description", errors, redraw);
    const kind = h("select", { id: "lp-add-type-" + lang }, Object.entries(TYPES).map(([k, t]) => h("option", { value: k }, t.label)));
    const add = small("Add the section", () => p.sections.push(fresh(kind.value)), p.sections.length >= 20, redraw);
    return h("div", { class: "lp-page" }, title, description,
      h("h4", null, "Sections"),
      p.sections.length ? h("ol", { class: "lp-sections" }, p.sections.map((s, i) => sectionBox(lang, p.sections, i, errors, redraw)))
        : h("p", { class: "muted" }, "No section yet: the page would show only its header and footer."),
      h("div", { class: "inline-form lp-add" }, h("label", { for: "lp-add-type-" + lang }, "New section"), kind, add,
        h("span", { class: "hint" }, "At most 20 sections.")));
  }

  // The hub's refusal said at each field it names; a path without a field
  // on screen is listed in the status line.
  // prefix: what the status line says before the hub's words; a save's by default.
  function showErrors(errors, err, status, prefix) {
    const before = prefix || "Not saved: ";
    Object.values(errors).forEach((e) => { e.textContent = ""; });
    const fields = err && err.code === "invalid" && err.details && err.details.fields;
    // A request over the hub's cap (§16.7: 512 KiB for these two calls) never reaches the checks.
    if (err && err.code === "payload_too_large") { status.fail(before, { message: "the draft is larger than the hub takes in one request (512 KiB)" }); return; }
    if (!fields) { status.fail(before, err); return; }
    const rest = [];
    let first = null;
    Object.entries(fields).forEach(([path, reason]) => {
      const at = errors[path];
      const words = at && at.limit && reason === "invalid" ? "empty, or longer than allowed (" + at.limit + ")" : reasonText(reason);
      if (at) { at.textContent = words; if (!first) first = at; } else rest.push(path + ": " + words);
    });
    status.fail(before, { message: rest.length ? rest.join("; ") : "see the fields marked below" });
    const input = first && first.parentNode && first.parentNode.querySelector ? first.parentNode.querySelector("input, textarea") : null;
    if (input && input.focus) input.focus();
  }

  // A draft opened as the hub would serve it (§16.7, §16.7.1; a legal page's
  // draft is its languages alone, the page named in ?page=): stored by a
  // POST with the CSRF token, then opened by its url in a tab of its own, a
  // top-level page under the page's own policy. The tab is opened at the
  // click, before the hub answers, so no pop-up blocker stops it.
  const PREVIEW = /^(\/api\/v1)?\/admin\/settings\/(landing|legal)\/preview\/[A-Za-z0-9_-]+$/;
  async function preview(path, body, lang, status, errors) {
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    status.busy("Preparing the preview…");
    try {
      const answer = await M.api.post(path, body);
      const at = new URL(String((answer && answer.url) || ""), window.location.href);
      if (at.origin !== window.location.origin || !PREVIEW.test(at.pathname)) throw new Error("the hub answered no preview address of its own");
      if (lang && !at.searchParams.has("lang")) at.searchParams.set("lang", lang);
      if (tab) tab.location.href = at.href; else window.open(at.href, "_blank", "noopener");
      status.done();
      append(status.el, h("span", { class: "ok" }, "The preview opened in a new tab; it is kept for 10 minutes."));
    } catch (err) {
      if (tab) tab.close();
      showErrors(errors, err, status);
    }
  }

  async function section(ctx, root) {
    const status = M.statusLine();
    const box = h("div", { class: "lp-editor" });
    append(root, h("h3", null, "Landing page"),
      h("p", { class: "hint" }, "What a visitor without a session sees at the root of this instance, per language. The hub renders it itself, "
        + "without a script; sign-in and registration stay one click away."), status.el, box);
    let saved = await M.api.get(LANDING);
    let draft = JSON.parse(JSON.stringify(saved));
    draft.pages = draft.pages || {};
    draft.footer = draft.footer || { operator: "", social: [] };
    let lang = draft.default_language || Object.keys(draft.pages)[0] || "en";
    // The fields drawn last, by the hub's path: an import's check marks them.
    let errors = {};
    const draw = () => {
      errors = {};
      const langs = Object.keys(draft.pages);
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
      const addLang = h("button", { type: "button", class: "small" }, "Add the language");
      addLang.addEventListener("click", () => {
        const tag = newLang.value.trim();
        if (!LANG.test(tag) || draft.pages[tag]) { newLang.focus(); return; }
        draft.pages[tag] = { title: "", description: "", sections: [] };
        if (!draft.default_language || !draft.pages[draft.default_language]) draft.default_language = tag;
        lang = tag;
        draw();
      });
      const tabs = h("div", { class: "lp-tabs", role: "group", "aria-label": "Languages" }, langs.map((l) => {
        const b = h("button", { type: "button", "aria-pressed": String(l === lang) }, l);
        b.addEventListener("click", () => { lang = l; draw(); });
        return b;
      }));
      const footer = draft.footer;
      footer.social = footer.social || [];
      const social = h("ol", { class: "lp-items" }, footer.social.map((x, k) => h("li", { class: "lp-item" },
        control(f("link", "Link " + (k + 1), "cta"), { link: x }, "footer.social." + k, errors, draw),
        small("Remove", () => footer.social.splice(k, 1), false, draw))));
      const form = h("form", {
        class: "lp-form project-form",
        onsubmit: async (e) => {
          e.preventDefault();
          status.busy("Saving…");
          const body = { enabled: !!draft.enabled, default_language: draft.default_language, pages: draft.pages, footer: draft.footer };
          try {
            saved = await M.api.patch(LANDING, body);
            draft = JSON.parse(JSON.stringify(saved));
            draft.pages = draft.pages || {};
            draft.footer = draft.footer || { operator: "", social: [] };
            draw();
            status.done();
            append(status.el, h("span", { class: "ok" }, "Saved. Visitors see it within a minute."));
          } catch (err) {
            showErrors(errors, err, status);
          }
        },
      },
      h("p", { class: "check" }, enabled, h("label", { for: "lp-enabled" }, " Show the landing page to visitors without a session")), errors.enabled,
      h("div", { class: "inline-form" }, h("label", { for: "lp-new-language" }, "Languages"), tabs, newLang, addLang),
      langs.length ? [h("label", { for: "lp-default-language" }, "Default language"), def, errors.default_language,
        lang ? [small("Remove this language", () => { delete draft.pages[lang]; if (draft.default_language === lang) draft.default_language = Object.keys(draft.pages)[0] || "en"; }, false, draw),
          pageEditor(draft, lang, errors, draw)] : null]
        : h("p", { class: "muted" }, "No language yet: add one to write its page."),
      h("h4", null, "Footer, for every language"),
      control(f("operator", "Operator line (name, country)", "text", 120), footer, "footer.operator", errors, draw),
      social, small("Add a social link", () => footer.social.push({ label: "", href: "" }), footer.social.length >= 8, draw),
      h("p", { class: "hint" }, "A Mastodon link gets rel=“me”. The legal pages set below are linked here too."),
      h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, "Save the landing page"),
        h("button", { type: "button", onclick: () => preview(LANDING + "/preview", { default_language: draft.default_language, pages: draft.pages, footer: draft.footer }, lang, status, errors) },
          "Preview the draft"),
        // The saved page as a visitor sees it (§16.7, ?as=public), only while it is on.
        saved.enabled ? h("a", { href: "/?as=public" + (lang ? "&lang=" + encodeURIComponent(lang) : ""), target: "_blank", rel: "noopener" }, "View as a visitor") : null),
      saved.updated_at ? h("p", { class: "muted" }, "Last saved " + formatTime(saved.updated_at) + ".") : null);
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
      const file = h("input", { type: "file", id: "lp-json-file", accept: ".json,application/json" });
      file.addEventListener("change", async () => {
        const chosen = file.files && file.files[0];
        if (!chosen) return;
        try { area.value = await chosen.text(); io.done(); } catch (err) { io.fail(M.t("landing.json.file_failed"), err); }
      });
      const bodyOf = () => ({ enabled: !!draft.enabled, default_language: draft.default_language, pages: draft.pages, footer: draft.footer });
      const exportIt = () => {
        area.value = JSON.stringify(bodyOf(), null, 2);
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
        const object = data && typeof data === "object" && !Array.isArray(data);
        // The body of PATCH …/landing, or one language's page.
        const whole = object && data.pages && typeof data.pages === "object" && !Array.isArray(data.pages);
        const one = object && !whole && Array.isArray(data.sections);
        if (!whole && !one) { io.fail(M.t("landing.json.not_loaded"), { message: M.t("landing.json.shape") }); area.focus(); return; }
        const target = lang || "en";
        if (!window.confirm(whole ? M.t("landing.json.confirm_all") : M.t("landing.json.confirm_page", { lang: target }))) return;
        if (whole) {
          draft = { enabled: !!data.enabled, default_language: data.default_language || Object.keys(data.pages)[0] || "en",
            pages: data.pages, footer: data.footer && typeof data.footer === "object" ? data.footer : { operator: "", social: [] } };
          lang = draft.default_language;
        } else {
          draft.pages[target] = { title: data.title || "", description: data.description || "", sections: data.sections };
          if (!draft.default_language || !draft.pages[draft.default_language]) draft.default_language = target;
          lang = target;
        }
        draw();
        status.busy(M.t("landing.json.checking"));
        try {
          await M.api.post(LANDING + "/preview", { default_language: draft.default_language, pages: draft.pages, footer: draft.footer });
          status.done();
          append(status.el, h("span", { class: "ok" }, M.t("landing.json.loaded")));
        } catch (err) {
          showErrors(errors, err, status, M.t("landing.json.refused"));
        }
      }
      return h("details", { class: "lp-json" }, h("summary", null, M.t("landing.json.title")),
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

  const PAGES = [["imprint", "Imprint", "/impressum"], ["privacy", "Privacy", "/privacy"], ["terms", "Terms of use", "/terms"]];

  function legalPage(key, label, served, current, defaultLanguage, done) {
    const status = M.statusLine();
    const errors = {};
    const draft = JSON.parse(JSON.stringify((current && current.languages) || {}));
    // It opens on the setting's default language where the page has it.
    let lang = draft[defaultLanguage] ? defaultLanguage : Object.keys(draft)[0] || null;
    const body = h("div");
    const draw = () => {
      Object.keys(errors).forEach((k) => delete errors[k]);
      const langs = Object.keys(draft);
      if (!langs.includes(lang)) lang = langs[0] || null;
      const newLang = h("input", { id: "lg-" + key + "-new-language", placeholder: "de", maxlength: "20", autocomplete: "off", spellcheck: "false" });
      const addLang = h("button", { type: "button", class: "small" }, "Add the language");
      addLang.addEventListener("click", () => {
        const tag = newLang.value.trim();
        if (!LANG.test(tag) || draft[tag] || langs.length >= 8) { newLang.focus(); return; }
        draft[tag] = { title: label, markdown: "" };
        lang = tag;
        draw();
      });
      const tabs = h("div", { class: "lp-tabs", role: "group", "aria-label": label + ": languages" }, langs.map((l) => {
        const b = h("button", { type: "button", "aria-pressed": String(l === lang) }, l);
        b.addEventListener("click", () => { lang = l; draw(); });
        return b;
      }));
      const save = h("button", { type: "submit", class: "primary" }, "Save the " + label.toLowerCase());
      const unset = current ? h("button", { type: "button", class: "danger" }, "Take the page down") : null;
      if (unset) {
        unset.addEventListener("click", async () => {
          if (!window.confirm("Take the " + label.toLowerCase() + " down? Its earlier versions stay readable at their addresses.")) return;
          status.busy("Taking it down…");
          try { done(await M.api.patch(LEGAL, { [key]: null }), "The " + label.toLowerCase() + " is down."); } catch (err) { showErrors(errors, err, status); }
        });
      }
      const form = h("form", {
        class: "lg-form project-form",
        onsubmit: async (e) => {
          e.preventDefault();
          status.busy("Saving…");
          try { done(await M.api.patch(LEGAL, { [key]: draft }), "Saved as a new version of the " + label.toLowerCase() + "."); } catch (err) { showErrors(errors, err, status); }
        },
      },
      h("div", { class: "inline-form" }, h("label", { for: "lg-" + key + "-new-language" }, "Languages"), tabs, newLang, addLang),
      lang ? [control(f("title", "Title", "text", 120), draft[lang], key + "." + lang + ".title", errors, draw),
        control(f("markdown", "Text (Markdown)", "md", 65536), draft[lang], key + "." + lang + ".markdown", errors, draw),
        small("Remove this language", () => { delete draft[lang]; }, false, draw)] : h("p", { class: "muted" }, "No language yet: add one to write the page."),
      h("div", { class: "actions" }, save,
        lang ? h("button", { type: "button", onclick: () => preview(LEGAL + "/preview?page=" + key, draft, lang, status, errors) }, "Preview the draft") : null,
        unset), status.el);
      append(clear(body), form);
    };
    draw();
    const versions = (current && current.versions) || [];
    return h("section", { class: "lg-page", "aria-label": label },
      h("h4", null, label),
      current
        ? h("p", { class: "muted" }, "Served at ", h("a", { href: served, target: "_blank", rel: "noopener" }, served), ", as of " + formatTime(current.version) + ".",
          versions.length ? [" Earlier: ", versions.map((v, i) => [i ? ", " : null, h("a", { href: served + "/" + v, target: "_blank", rel: "noopener" }, formatTime(v))])] : null)
        : h("p", { class: "muted" }, "Not set: " + served + " answers not found, and nothing links to it."),
      body);
  }

  async function legalSection(ctx, root) {
    const note = h("div");
    const box = h("div");
    append(root, h("h3", null, "Legal pages"),
      h("p", { class: "hint" }, "The imprint, the privacy notice and the terms, served by the hub as static pages and linked from the landing page, "
        + "the login and the registration. Each save is a new version; the earlier ones stay readable, since a person may have accepted one."),
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
