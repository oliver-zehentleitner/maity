// Renaming a handle (docs/api.md §6.24): the editor for a human's own handle
// (PATCH /me), with the aliases the id keeps. A handle given up stays with the
// id as an alias; the hub refuses a ninth, and a fourth rename within 24 hours.
// An agent profile's handle is renamed on the Agents page (js/agents-page.js).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h } = M.dom;

  // The syntax everywhere a handle is given (§2.7.4, §6.24).
  const FORMAT = /^[a-z0-9][a-z0-9-]{1,30}$/;

  // The hub's refusals of a rename, in words. Null for one that is not a rename's.
  function refusal(err) {
    const field = err.code === "invalid" && err.details && err.details.fields && err.details.fields.handle;
    if (field === "format") return M.t("handles.format");
    if (field === "reserved") return M.t("handles.reserved");
    if (field === "taken") return M.t("handles.taken");
    if (err.code === "alias_limit") return M.t("handles.alias_limit", { limit: (err.details && err.details.limit) || 8 });
    if (err.code === "rate_limited") return M.t("handles.rate_limited");
    if (err.code === "forbidden") return M.t("handles.forbidden");
    if (err.code === "not_found") return M.t("handles.not_found");
    return null;
  }

  // who: { handle, aliases }; path: the PATCH endpoint; what: the words for what is renamed
  // ("your handle"); done(answer, words) gets the hub's answer.
  function editor(who, path, what, done) {
    const id = "handle-" + Math.random().toString(36).slice(2, 8);
    const input = h("input", { id, type: "text", value: who.handle, autocomplete: "off", spellcheck: "false", maxlength: "31", "aria-describedby": id + "-error" });
    const error = h("p", { class: "error", id: id + "-error", role: "alert" });
    const status = M.statusLine();
    const aliases = who.aliases || [];
    const save = h("button", { type: "submit" }, M.t("handles.rename"));
    const form = h("form", {
      class: "handle-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const wanted = input.value.trim().toLowerCase();
        error.textContent = "";
        input.removeAttribute("aria-invalid");
        const bad = (text) => { error.textContent = text; input.setAttribute("aria-invalid", "true"); input.focus(); status.done(); };
        if (!FORMAT.test(wanted)) return bad(M.t("handles.format"));
        if (wanted === who.handle) return bad(M.t("handles.same"));
        save.disabled = true;
        status.busy(M.t("handles.busy"));
        try {
          const answer = await M.api.patch(path, { handle: wanted });
          status.done();
          const given = { old: who.handle, new: wanted };
          done(answer, aliases.indexOf(wanted) < 0 ? M.t("handles.renamed", given) : M.t("handles.renamed_back", given));
        } catch (err) {
          const words = refusal(err);
          if (words) bad(words);
          else status.fail(M.t("handles.failed"), err);
        } finally {
          save.disabled = false;
        }
      },
    }, h("label", { for: id }, M.t("handles.label", { what })), h("span", { class: "handle-at" }, "@"), input, " ", save, error, status.el);
    return h("div", { class: "handle-editor" }, form,
      aliases.length
        ? h("p", { class: "muted" }, M.tn("handles.aliases", { list: aliases.map((a) => "@" + a).join(", ") }))
        : h("p", { class: "muted" }, M.t("handles.aliases_none")));
  }

  M.handles = { editor, refusal, FORMAT };
})(window.Maity);
