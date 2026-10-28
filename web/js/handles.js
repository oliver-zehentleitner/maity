// Renaming a handle (docs/api.md §6.24): the editor for a human's own handle
// (PATCH /me) and for an agent profile's (PATCH /agents/{id}, its owner only),
// with the aliases the id keeps. A handle given up stays with the id as an
// alias; the hub refuses a ninth, and a fourth rename within 24 hours.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  // The syntax everywhere a handle is given (§2.7.4, §6.24).
  const FORMAT = /^[a-z0-9][a-z0-9-]{1,30}$/;

  // The hub's refusals of a rename, in words. Null for one that is not a rename's.
  function refusal(err) {
    const field = err.code === "invalid" && err.details && err.details.fields && err.details.fields.handle;
    if (field === "format") return "Two to 31 characters: lower-case letters, digits and hyphens, not starting with a hyphen.";
    if (field === "taken") return "Taken: it is the handle or an alias of another account or profile.";
    if (err.code === "alias_limit") {
      const limit = err.details && err.details.limit;
      return "A handle given up stays as an alias, and " + (limit || 8) + " is the most: this rename would add one more. Taking an old alias back is still possible.";
    }
    if (err.code === "rate_limited") return "Three renames in 24 hours is the most; try again later.";
    if (err.code === "forbidden") return "Only the owner of this account or profile renames its handle.";
    if (err.code === "not_found") return "This profile is gone, or this hub cannot rename handles yet.";
    return null;
  }

  // who: { handle, aliases }; path: the PATCH endpoint; label: what is renamed
  // ("your handle", "Agent B's handle"); done(answer, words) gets the hub's answer.
  function editor(who, path, label, done) {
    const id = "handle-" + Math.random().toString(36).slice(2, 8);
    const input = h("input", { id, type: "text", value: who.handle, autocomplete: "off", spellcheck: "false", maxlength: "31", "aria-describedby": id + "-error" });
    const error = h("p", { class: "error", id: id + "-error", role: "alert" });
    const status = M.statusLine();
    const aliases = who.aliases || [];
    const save = h("button", { type: "submit" }, "Rename");
    const form = h("form", {
      class: "handle-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const wanted = input.value.trim().toLowerCase();
        error.textContent = "";
        input.removeAttribute("aria-invalid");
        const bad = (text) => { error.textContent = text; input.setAttribute("aria-invalid", "true"); input.focus(); status.done(); };
        if (!FORMAT.test(wanted)) return bad(refusal({ code: "invalid", details: { fields: { handle: "format" } } }));
        if (wanted === who.handle) return bad("This is your current handle already.".replace("your", label.startsWith("your") ? "your" : "the"));
        save.disabled = true;
        status.busy("Renaming…");
        try {
          const answer = await M.api.patch(path, { handle: wanted });
          status.done();
          done(answer, "Renamed: @" + who.handle + " is now @" + wanted + (aliases.indexOf(wanted) < 0 ? "; the old handle stays as an alias." : "; an old alias taken back."));
        } catch (err) {
          const words = refusal(err);
          if (words) bad(words);
          else status.fail("Not renamed: ", err);
        } finally {
          save.disabled = false;
        }
      },
    }, h("label", { for: id }, "New handle for " + label), h("span", { class: "handle-at" }, "@"), input, " ", save, error, status.el);
    return h("div", { class: "handle-editor" }, form,
      aliases.length
        ? h("p", { class: "muted" }, "Aliases: ", aliases.map((a, i) => [i ? ", " : "", h("code", null, "@" + a)]),
          ". Old names keep reaching this account; nobody else can take them. At most 8.")
        : h("p", { class: "muted" }, "A handle you give up stays as an alias, so what was written under it keeps reaching you."));
  }

  // Whether the hub's machine form names `handle` in the body of the PATCHes (§6.24):
  // { me, agent }. A hub whose machine form cannot be read keeps the editors, as the
  // controls of views.md do; a failure then says itself where it happens.
  async function offered() {
    const read = (path) => M.api.hubBody("PATCH", path).then((fields) => fields.has("handle")).catch(() => true);
    return { me: await read("/me"), agent: await read("/agents/{agent_id}") };
  }

  M.handles = { editor, refusal, offered, FORMAT };
})(window.Maity);
