// Import and export of an admin setting as JSON (tsk-knb9me77f32t), for the
// legal pages and registration, as the landing editor has it (js/landing.js,
// tsk-36d575f5yybz): the editor's state as text, or text loaded into the
// editor after a confirmation. Loading saves nothing; the editor's own Save
// does. What the field holds and was not loaded is said before a preview,
// which would otherwise show the editor's state instead.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  const isObject = (v) => !!v && typeof v === "object" && !Array.isArray(v);

  // opts: id (the element ids' prefix), hint (what the body is), loadLabel (the load button's
  // words where loading does more than fill an editor), body() (the
  // editor's state as the hub takes it, or a promise of it), load(data, io) (checks the parsed
  // value and loads it into the editor: true when it did, else it has said
  // why in io).
  function part(opts) {
    const io = M.statusLine();
    const area = h("textarea", { id: opts.id, rows: "8", spellcheck: "false", "aria-describedby": opts.id + "-hint" });
    const file = h("input", { type: "file", id: opts.id + "-file", accept: ".json,application/json" });
    // The text last exported or loaded: anything else in the field is not in the editor.
    let settled = "";
    file.addEventListener("change", async () => {
      const chosen = file.files && file.files[0];
      if (!chosen) return;
      try { area.value = await chosen.text(); io.done(); } catch (err) { io.fail(M.t("jsonio.file_failed"), err); }
    });
    const exportIt = async () => {
      let body;
      try { body = await opts.body(); } catch (err) { io.fail(M.t("jsonio.export_failed"), err); return; }
      area.value = settled = JSON.stringify(body, null, 2);
      io.done();
      append(io.el, h("span", { class: "ok" }, M.t("jsonio.exported")));
      area.focus();
    };
    const copy = async () => {
      try { await navigator.clipboard.writeText(area.value); io.done(); append(io.el, h("span", { class: "ok" }, M.t("jsonio.copied"))); }
      catch (err) { io.fail(M.t("jsonio.copy_failed"), err); }
    };
    async function loadIt() {
      let data;
      try { data = JSON.parse(area.value); } catch (err) {
        io.fail(M.t("jsonio.not_loaded"), { message: M.t("jsonio.not_json", { reason: err.message }) });
        area.focus();
        return;
      }
      if (await opts.load(data, io)) settled = area.value;
    }
    const el = h("details", { class: "json-io field-stack" }, h("summary", null, M.t("jsonio.title")),
      h("p", { class: "hint", id: opts.id + "-hint" }, opts.hint),
      h("label", { for: opts.id }, M.t("jsonio.label")), area,
      h("div", { class: "inline-form" }, h("label", { for: opts.id + "-file" }, M.t("jsonio.file")), file),
      h("div", { class: "actions" },
        h("button", { type: "button", onclick: loadIt }, opts.loadLabel || M.t("jsonio.load")),
        h("button", { type: "button", onclick: exportIt }, M.t("jsonio.export")),
        h("button", { type: "button", onclick: copy }, M.t("jsonio.copy"))),
      io.el);
    // Text in the field that is not in the editor (pasted or chosen, not loaded).
    const pending = () => area.value.trim() !== "" && area.value !== settled;
    return { el, pending, focus: () => { el.open = true; area.focus(); } };
  }

  M.jsonIo = { part, isObject };
})(window.Maity);
