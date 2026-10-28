// A project's name (docs/api.md §6.25), in Project settings: its full name
// and the earlier ones, a rename of its slug by a human owner, and its
// transfer to another namespace owner by the namespace owner, which the
// receiver accepts in their inbox. Every name given up stays an alias, so
// an old link never leads elsewhere.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  // The hub's refusals of a rename or a transfer, in words.
  function said(err, receiver) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields && fields.slug === "taken") {
      return { message: receiver ? "@" + receiver + " has a project of that name already, or had one" : "that name is taken in this namespace, now or as an earlier name" };
    }
    if (fields && fields.slug === "reserved") return { message: "that word is part of the dashboard's addresses; choose another slug" };
    if (fields && fields.to === "not_an_owner") return { message: "the receiver has to be an owner of the project first" };
    if (err.code === "alias_limit") return { message: "the project has kept " + ((err.details && err.details.limit) || 8) + " earlier names, the most it may" };
    if (err.code === "rate_limited") return { message: "at most 3 renames and transfers a day; try again tomorrow" };
    if (err.code === "forbidden" && err.details && err.details.reason === "step_up_required") {
      return { message: "the hub asks for your second factor first; sign in again with it and try once more" };
    }
    return err;
  }

  // The section, for a human owner, where the hub knows names (its project
  // view carries `aliases`); none otherwise.
  function section(ctx) {
    const p = ctx.project;
    if (ctx.me.kind !== "human" || !ctx.isOwner || !("aliases" in p)) return null;
    const box = h("div", { class: "project-names" }, h("h2", { class: "panel-title", id: "names-heading" }, "Project name"),
      h("p", null, "This project is ", h("code", null, p.full_name), "."),
      p.aliases.length
        ? h("p", { class: "muted project-aliases" }, "Earlier names, still leading here: ", p.aliases.join(", "), ".")
        : null,
      renameForm(ctx));
    const transfer = transferForm(ctx);
    if (transfer) append(box, transfer);
    return box;
  }

  function renameForm(ctx) {
    const p = ctx.project;
    const owner = p.full_name.split("/")[0];
    const status = M.statusLine();
    const rule = M.dom.NAME_RULES.slug;
    const input = h("input", { id: "project-rename", pattern: rule.pattern, maxlength: "63", autocomplete: "off", spellcheck: "false",
      "aria-describedby": "project-rename-hint project-rename-error" });
    input.value = p.slug;
    const error = h("p", { class: "field-error", id: "project-rename-error", role: "alert" });
    const fail = (text) => { error.textContent = text; input.setAttribute("aria-invalid", "true"); input.focus(); };
    const button = h("button", { type: "submit" }, "Rename");
    return h("form", {
      class: "inline-form project-rename",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        if (button.disabled) return;
        error.textContent = "";
        input.removeAttribute("aria-invalid");
        const slug = input.value.trim();
        if (slug === p.slug) { status.done(); append(status.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
        if (!rule.test.test(slug)) { fail(rule.text); return; }
        if (!window.confirm("Rename " + p.full_name + " to " + owner + "/" + slug + "? The old name stays an earlier name that leads here.")) return;
        button.disabled = true;
        status.busy("Renaming…");
        try {
          const updated = await M.api.patch(ctx.base, { slug });
          window.location.hash = ctx.projectLink((updated && updated.full_name) || owner + "/" + slug, "settings");
        } catch (err) {
          const why = said(err);
          if (err.code === "invalid" && err.details && err.details.fields && err.details.fields.slug) { status.done(); fail(why.message); }
          else status.fail("Not renamed: ", why);
        } finally {
          button.disabled = false;
        }
      },
    },
    h("label", { for: "project-rename" }, "Slug"), input,
    h("p", { class: "hint", id: "project-rename-hint" }, rule.text + " Links to the old name keep working; at most 8 earlier names, and 3 renames or transfers a day."),
    error, button, status.el);
  }

  // The namespace owner hands the project to another human owner; nothing
  // moves until that person accepts in their inbox (a consent request).
  function transferForm(ctx) {
    const p = ctx.project;
    if (!p.owner || p.owner.id !== ctx.me.id) return null;
    const owners = ctx.members.filter((m) => m.kind === "human" && M.trust.owner(m) && m.id !== ctx.me.id);
    const status = M.statusLine();
    if (!owners.length) {
      return h("div", { class: "project-transfer" }, h("h3", null, "Transfer"),
        h("p", { class: "muted" }, "To move this project into another person's namespace, make them an owner of it first (Members)."));
    }
    const select = h("select", { id: "project-transfer-to" },
      owners.map((m) => h("option", { value: m.id }, m.display_name + " (@" + M.dom.handleOf(ctx, m) + ")")));
    select.value = owners[0].id;
    const button = h("button", { type: "submit" }, "Ask to take it over");
    const result = h("div", { class: "transfer-result" });
    return h("form", {
      class: "inline-form project-transfer",
      onsubmit: async (e) => {
        e.preventDefault();
        if (button.disabled) return;
        const to = owners.find((m) => m.id === select.value);
        if (!to) { select.focus(); return; }
        const handle = M.dom.handleOf(ctx, to);
        if (!window.confirm("Ask " + to.display_name + " to take over " + p.full_name + " as " + handle + "/" + p.slug + "? It moves when they accept; the old name stays an earlier name.")) return;
        button.disabled = true;
        status.busy("Asking…");
        try {
          const req = await M.api.post(ctx.base + "/transfer", { to: to.id });
          status.done();
          append(M.dom.clear(result), h("p", { class: "ok" }, "Asked " + to.display_name + ". The project moves when they accept in their inbox; a rename or another transfer withdraws this one."),
            req && req.id ? withdrawButton(ctx, req.id, result) : null);
        } catch (err) {
          status.fail("Not asked: ", said(err, handle));
        } finally {
          button.disabled = false;
        }
      },
    },
    h("h3", null, "Transfer"),
    h("label", { for: "project-transfer-to" }, "To"), select,
    h("p", { class: "hint" }, "Only an owner of this project can receive it; they accept in their inbox."),
    button, status.el, result);
  }

  function withdrawButton(ctx, id, result) {
    const status = M.statusLine();
    const button = h("button", { type: "button", class: "small", onclick: async () => {
      button.disabled = true;
      status.busy("Withdrawing…");
      try {
        await M.api.post(ctx.base + "/requests/" + encodeURIComponent(id) + "/withdraw", {});
        append(M.dom.clear(result), h("p", { class: "ok" }, "Withdrawn."));
      } catch (err) {
        button.disabled = false;
        status.fail("Not withdrawn: ", err);
      }
    } }, "Withdraw the request");
    return [button, status.el];
  }

  M.projectNames = { section, said };
})(window.Maity);
