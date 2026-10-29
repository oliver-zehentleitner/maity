// A project's name (docs/api.md §6.25), in Project settings: its full name
// and the earlier ones, a rename of its slug by a human owner, and its
// transfer to another namespace owner by the namespace owner, which the
// receiver accepts in their inbox, or into an organisation (§6.26). Every name given up stays an alias, so
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
    if (err.code === "forbidden" && err.details && err.details.reason === "org_role") return { message: "only an owner or admin of that organisation can move a project into it" };
    if (err.code === "forbidden" && err.details && err.details.reason === "moderation_hold") return { message: "that organisation is suspended and takes no project now" };
    if (err.code === "invalid_transition" && err.details && err.details.reason === "transfer_stale") return { message: "the transfer no longer holds; ask again" };
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

  // The namespace owner — for an organisation's project, any of its owners —
  // hands the project to another human owner, who accepts in their inbox, or
  // into an organisation they own or administer (§6.26): an owner of it moves
  // the project at once, an admin asks its owners. A sensitive call (§2.8.4).
  function transferForm(ctx) {
    const p = ctx.project;
    const self = ctx.members.find((m) => m.id === ctx.me.id);
    const ofOrg = !!(p.owner && /^org-/.test(p.owner.id));
    if (!p.owner || (ofOrg ? !(self && self.org_owner) : p.owner.id !== ctx.me.id)) return null;
    const box = h("div", { class: "project-transfer" });
    const fill = (orgs) => {
      // Out of an organisation, an owner may take it into their own namespace.
      const owners = ctx.members.filter((m) => m.kind === "human" && M.trust.owner(m) && (ofOrg || m.id !== ctx.me.id));
      if (!owners.length && !orgs.length) {
        append(M.dom.clear(box), h("h3", null, "Transfer"),
          h("p", { class: "muted" }, "To move this project into another person's namespace, make them an owner of it first (Members)."));
        return;
      }
      append(M.dom.clear(box), form(owners, orgs));
    };
    const form = (owners, orgs) => {
      const status = M.statusLine();
      const ask = h("div", { class: "step-up-slot" });
      ask.hidden = true;
      const targets = owners.map((m) => ({ id: m.id, handle: M.dom.handleOf(ctx, m), name: m.id === ctx.me.id ? "yourself" : m.display_name, org: null }))
        .concat(orgs.map((o) => ({ id: o.id, handle: o.handle, name: o.display_name, org: o })));
      const select = h("select", { id: "project-transfer-to" },
        targets.map((t) => h("option", { value: t.id }, t.org ? "@" + t.handle + " · " + t.name + " (organisation)" : t.name + " (@" + t.handle + ")")));
      select.value = targets[0].id;
      const button = h("button", { type: "submit" }, "Transfer");
      const result = h("div", { class: "transfer-result" });
      return h("form", {
        class: "inline-form project-transfer",
        onsubmit: async (e) => {
          e.preventDefault();
          if (button.disabled) return;
          const to = targets.find((t) => t.id === select.value);
          if (!to) { select.focus(); return; }
          const at = once(to);
          if (!window.confirm((at ? "Move " + p.full_name + " to " : "Ask " + to.name + " to take over " + p.full_name + " as ")
            + to.handle + "/" + p.slug + "?" + (at ? "" : " It moves when they accept;") + " The old name stays an earlier name.")) return;
          button.disabled = true;
          status.busy(at ? "Moving…" : "Asking…");
          try {
            const answer = await M.stepUp.run(() => M.api.post(ctx.base + "/transfer", { to: to.id }), ask, "Transferring " + p.full_name);
            status.done();
            // Moved in the call: the project answers under its new name.
            if (answer && answer.full_name) { window.location.hash = ctx.projectLink(answer.full_name, "settings"); return; }
            append(M.dom.clear(result), h("p", { class: "ok" }, (to.org ? "Asked the owners of @" + to.handle + ". The project moves when one of them accepts"
              : "Asked " + to.name + ". The project moves when they accept") + " in their inbox; a rename or another transfer withdraws this one."),
            // Into an organisation the owners' requests are personal (§6.26): withdrawn on /requests.
            answer && answer.id ? withdrawButton(ctx, answer.id, result, !!to.org) : null);
          } catch (err) {
            if (err.code === "cancelled") status.done();
            else status.fail("Not transferred: ", said(err, to.handle));
          } finally {
            button.disabled = false;
          }
        },
      },
      h("h3", null, "Transfer"),
      h("label", { for: "project-transfer-to" }, "To"), select,
      h("p", { class: "hint" }, "A person must be an owner of this project, and accepts in their inbox. An organisation you own takes it at once; "
        + "one you administer asks its owners."),
      ask, button, status.el, result);
    };
    // Without a direct word: to oneself, or into an organisation one owns.
    const once = (to) => (to.org ? to.org.my_role === "owner" : to.id === ctx.me.id);
    fill([]);
    if (ctx.me.kind === "human") {
      M.api.hubHas("GET", "/orgs")
        .then((yes) => (yes ? M.api.get("/orgs") : { items: [] }))
        .then((r) => {
          // A suspended organisation takes no transfer in (§6.26).
          const orgs = r.items.filter((o) => ["owner", "admin"].includes(o.my_role) && o.id !== p.owner.id && !o.moderation);
          if (orgs.length) fill(orgs);
        }, () => {});
    }
    return box;
  }

  function withdrawButton(ctx, id, result, personal) {
    const status = M.statusLine();
    const button = h("button", { type: "button", class: "small", onclick: async () => {
      button.disabled = true;
      status.busy("Withdrawing…");
      try {
        await M.api.post((personal ? "" : ctx.base) + "/requests/" + encodeURIComponent(id) + "/withdraw", {});
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
