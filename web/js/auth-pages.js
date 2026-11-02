// The pitch of /login and /register per language (docs/api.md §16.7.4): two sub-tabs of the
// admin's Pages tab over one setting, which a save replaces as a whole, so Save in either
// sends both. Only these six words per language: every word of the forms is the catalogue's.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const URL = "/admin/settings/auth-pages";
  const PAGES = ["sign_in", "sign_up"];
  // §16.7's languages, hub/src/maity_hub/landing.py LANGUAGES.
  const LANGUAGES = ["en", "de", "fr", "es", "pt", "it", "nl", "ja", "ko", "zh-Hans"];
  // Getters: the words are the catalog's when said.
  const FIELDS = [
    { key: "title", get label() { return M.t("auth_pages.field.title"); } },
    { key: "subline", get label() { return M.t("auth_pages.field.subline"); } },
    { key: "point_1", get label() { return M.t("auth_pages.field.point_1"); } },
    { key: "point_2", get label() { return M.t("auth_pages.field.point_2"); } },
    { key: "point_3", get label() { return M.t("auth_pages.field.point_3"); } },
    { key: "note", long: true, get label() { return M.t("auth_pages.field.note"); } },
  ];
  const isObject = (v) => !!v && typeof v === "object" && !Array.isArray(v);
  const shapeOk = (page) => isObject(page) && Object.values(page).every(isObject);

  // What a save sends: an empty field is a key left out, and a language with none is no language.
  function bodyOf(draft) {
    const pages = {};
    PAGES.forEach((page) => {
      pages[page] = {};
      Object.entries(draft.pages[page] || {}).forEach(([lang, texts]) => {
        const kept = Object.fromEntries(Object.entries(texts).filter(([, v]) => typeof v !== "string" || v.trim()));
        if (Object.keys(kept).length) pages[page][lang] = kept;
      });
    });
    return { default_language: draft.default_language, pages };
  }

  // The hub's refusal in a few words: the fields it names, or its message.
  const refusal = (err) => {
    const fields = err && err.code === "invalid" && err.details && err.details.fields;
    if (err && err.code === "cancelled") return M.t("auth_pages.cancelled");
    return fields ? Object.entries(fields).map(([f, r]) => f + ": " + r).join("; ") : (err && err.message) || String(err);
  };

  // One editor per admin page: the setting is read once, and both sub-tabs draw from it.
  function editor() {
    let reading = null;
    let draft = null;
    let errors = {};
    const redraws = [];
    const read = () => (reading = reading || M.api.get(URL).then((s) => { draft = { default_language: s.default_language, pages: s.pages }; }));
    const redrawAll = () => redraws.forEach((draw) => draw());

    async function section(page, root) {
      await read();
      const status = M.statusLine();
      const slot = h("div", { class: "step-up-slot" });
      slot.hidden = true;
      const form = h("div", { class: "field-stack" });
      let lang = draft.default_language;
      const id = (key) => "ap-" + page + "-" + key;

      function draw() {
        const texts = (draft.pages[page] || {})[lang] || {};
        const tabs = h("div", { class: "lp-tabs", role: "group", "aria-label": M.t("auth_pages.languages") }, LANGUAGES.map((l) => h("button", {
          type: "button", "aria-pressed": String(l === lang), onclick: () => { lang = l; draw(); },
        }, l)));
        const language = h("select", { id: id("default"), onchange: (e) => { draft.default_language = e.target.value; redrawAll(); } },
          LANGUAGES.map((l) => h("option", { value: l, selected: l === draft.default_language ? true : null }, l)));
        const edit = (key, value) => {
          draft.pages[page] = draft.pages[page] || {};
          draft.pages[page][lang] = draft.pages[page][lang] || {};
          draft.pages[page][lang][key] = value;
        };
        append(clear(form), h("label", { for: id("default") }, M.t("auth_pages.default_language")), language, tabs,
          FIELDS.map((f) => {
            const said = errors["pages." + page + "." + lang + "." + f.key];
            const attrs = { id: id(f.key), oninput: (e) => edit(f.key, e.target.value) };
            const input = f.long ? h("textarea", Object.assign({ rows: "4" }, attrs)) : h("input", Object.assign({ maxlength: "500" }, attrs));
            // The property, not the attribute: a textarea does not read the attribute.
            input.value = texts[f.key] || "";
            return [h("label", { for: id(f.key) }, f.label), input, said ? h("p", { class: "field-error" }, said === "unresolved_placeholder" ? M.t("auth_pages.placeholder") : M.t("auth_pages.invalid")) : null];
          }));
      }
      redraws.push(draw);
      draw();

      const save = h("button", { type: "button", class: "primary", onclick: async () => {
        status.busy(M.t("auth_pages.saving"));
        errors = {};
        try {
          const saved = await M.stepUp.run(() => M.api.patch(URL, bodyOf(draft)), slot, M.t("auth_pages.step_up"));
          draft = { default_language: saved.default_language, pages: saved.pages };
          redrawAll();
          status.done();
          append(status.el, h("span", { class: "ok" }, M.t("auth_pages.saved")));
        } catch (err) {
          errors = (err.code === "invalid" && err.details && err.details.fields) || {};
          redrawAll();
          status.fail(M.t("auth_pages.not_saved"), { message: refusal(err) });
        }
      } }, M.t("auth_pages.save"));

      const json = M.jsonIo.part({
        id: id("json"),
        hint: M.t("auth_pages.json_hint"),
        body: () => bodyOf(draft).pages[page],
        load: async (data, io) => {
          if (!shapeOk(data)) { io.fail(M.t("jsonio.not_loaded"), { message: M.t("auth_pages.not_a_page") }); return false; }
          const next = { default_language: draft.default_language, pages: Object.assign({}, draft.pages, { [page]: data }) };
          io.busy(M.t("auth_pages.checking"));
          try { await M.api.post(URL + "/check", bodyOf(next)); }
          catch (err) { io.fail(M.t("jsonio.not_loaded"), { message: refusal(err) }); return false; }
          draft = next;
          errors = {};
          redrawAll();
          io.done();
          append(io.el, h("span", { class: "ok" }, M.t("auth_pages.loaded")));
          return true;
        },
      });
      append(root, h("p", { class: "hint" }, M.t("auth_pages.intro")), form, json.el, h("div", { class: "actions" }, save), slot, status.el);
    }
    return { section };
  }

  M.authPages = { editor, PAGES, LANGUAGES, shapeOk };
})(window.Maity);
