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
      return { message: receiver ? M.t("names.refused.taken_receiver", { handle: receiver }) : M.t("names.refused.taken") };
    }
    if (fields && fields.slug === "reserved") return { message: M.t("names.refused.reserved") };
    if (fields && fields.to === "not_an_owner") return { message: M.t("names.refused.not_an_owner") };
    if (err.code === "forbidden" && err.details && err.details.reason === "org_role") return { message: M.t("names.refused.org_role") };
    if (err.code === "forbidden" && err.details && err.details.reason === "moderation_hold") return { message: M.t("names.refused.moderation_hold") };
    if (err.code === "invalid_transition" && err.details && err.details.reason === "transfer_stale") return { message: M.t("names.refused.transfer_stale") };
    if (err.code === "alias_limit") return { message: M.t("names.refused.alias_limit", { count: (err.details && err.details.limit) || 8 }) };
    if (err.code === "rate_limited") return { message: M.t("names.refused.rate_limited") };
    if (err.code === "forbidden" && err.details && err.details.reason === "step_up_required") {
      return { message: M.t("names.refused.step_up") };
    }
    return err;
  }

  // The section, for a human owner; none otherwise.
  function section(ctx) {
    const p = ctx.project;
    if (ctx.me.kind !== "human" || !ctx.isOwner) return null;
    const box = h("div", { class: "project-names" }, h("h2", { class: "panel-title", id: "names-heading" }, M.t("names.title")),
      h("p", null, M.tn("names.current", { name: h("code", null, p.full_name) })),
      p.aliases.length
        ? h("p", { class: "muted project-aliases" }, M.t("names.aliases", { names: M.fmt.list(p.aliases) }))
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
    const button = h("button", { type: "submit" }, M.t("names.rename"));
    return h("form", {
      class: "inline-form project-rename",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        if (button.disabled) return;
        error.textContent = "";
        input.removeAttribute("aria-invalid");
        const slug = input.value.trim();
        if (slug === p.slug) { status.done(); append(status.el, h("span", { class: "ok" }, M.t("names.unchanged"))); return; }
        if (!rule.test.test(slug)) { fail(rule.text); return; }
        if (!window.confirm(M.t("names.rename.confirm", { from: p.full_name, to: owner + "/" + slug }))) return;
        button.disabled = true;
        status.busy(M.t("names.renaming"));
        try {
          const updated = await M.api.patch(ctx.base, { slug });
          M.route.go(ctx.projectLink((updated && updated.full_name) || owner + "/" + slug, "settings"));
        } catch (err) {
          const why = said(err);
          if (err.code === "invalid" && err.details && err.details.fields && err.details.fields.slug) { status.done(); fail(why.message); }
          else status.fail(M.t("names.not_renamed"), why);
        } finally {
          button.disabled = false;
        }
      },
    },
    h("label", { for: "project-rename" }, M.t("names.slug")), input,
    h("p", { class: "hint", id: "project-rename-hint" }, rule.text, " ", M.t("names.rename.hint")),
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
        append(M.dom.clear(box), h("h3", null, M.t("names.transfer")),
          h("p", { class: "muted" }, M.t("names.transfer.none")));
        return;
      }
      append(M.dom.clear(box), form(owners, orgs));
    };
    const form = (owners, orgs) => {
      const status = M.statusLine();
      const ask = h("div", { class: "step-up-slot" });
      ask.hidden = true;
      const targets = owners.map((m) => ({ id: m.id, handle: M.dom.handleOf(ctx, m), name: m.id === ctx.me.id ? M.t("names.transfer.yourself") : m.display_name, org: null }))
        .concat(orgs.map((o) => ({ id: o.id, handle: o.handle, name: o.display_name, org: o })));
      const select = h("select", { id: "project-transfer-to" },
        targets.map((t) => h("option", { value: t.id }, t.org ? M.t("names.transfer.org_option", { handle: t.handle, name: t.name }) : M.t("names.transfer.person_option", { handle: t.handle, name: t.name }))));
      select.value = targets[0].id;
      const button = h("button", { type: "submit" }, M.t("names.transfer"));
      const result = h("div", { class: "transfer-result" });
      return h("form", {
        class: "inline-form project-transfer",
        onsubmit: async (e) => {
          e.preventDefault();
          if (button.disabled) return;
          const to = targets.find((t) => t.id === select.value);
          if (!to) { select.focus(); return; }
          const at = once(to);
          const o = { project: p.full_name, name: to.name, to: to.handle + "/" + p.slug };
          if (!window.confirm(at ? M.t("names.transfer.confirm_move", o) : M.t("names.transfer.confirm_ask", o))) return;
          button.disabled = true;
          status.busy(at ? M.t("names.transfer.moving") : M.t("names.transfer.asking"));
          try {
            const answer = await M.stepUp.run(() => M.api.post(ctx.base + "/transfer", { to: to.id }), ask, M.t("names.transfer.step_up", { project: p.full_name }));
            status.done();
            // Moved in the call: the project answers under its new name.
            if (answer && answer.full_name) { M.route.go(ctx.projectLink(answer.full_name, "settings")); return; }
            append(M.dom.clear(result), h("p", { class: "ok" }, to.org ? M.t("names.transfer.asked_org", { handle: to.handle }) : M.t("names.transfer.asked_person", { name: to.name })),
            // Into an organisation the owners' requests are personal (§6.26): withdrawn on /requests.
            answer && answer.id ? withdrawButton(ctx, answer.id, result, !!to.org) : null);
          } catch (err) {
            if (err.code === "cancelled") status.done();
            else status.fail(M.t("names.transfer.failed"), said(err, to.handle));
          } finally {
            button.disabled = false;
          }
        },
      },
      h("h3", null, M.t("names.transfer")),
      h("label", { for: "project-transfer-to" }, M.t("names.transfer.to")), select,
      h("p", { class: "hint" }, M.t("names.transfer.hint")),
      ask, button, status.el, result);
    };
    // Without a direct word: to oneself, or into an organisation one owns.
    const once = (to) => (to.org ? to.org.my_role === "owner" : to.id === ctx.me.id);
    fill([]);
    if (ctx.me.kind === "human") {
      M.api.get("/orgs")
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
      status.busy(M.t("names.withdrawing"));
      try {
        await M.api.post((personal ? "" : ctx.base) + "/requests/" + encodeURIComponent(id) + "/withdraw", {});
        append(M.dom.clear(result), h("p", { class: "ok" }, M.t("names.withdrawn")));
      } catch (err) {
        button.disabled = false;
        status.fail(M.t("names.not_withdrawn"), err);
      }
    } }, M.t("names.withdraw"));
    return [button, status.el];
  }

  M.projectNames = { section, said };
})(window.Maity);
