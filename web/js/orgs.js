// Organisations (docs/api.md §6.26) under the account: /account/orgs lists
// the ones the human is a member of and creates one; /account/orgs/<handle>
// is one organisation: its members and their roles, the open invitations,
// its settings, picture and deletion. Every route is the humans' business
// alone; a caller who is not a member is told not_found, as for a handle
// that names nothing. Why under /account and not /orgs: web/context/views.md.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const ROLES = ["owner", "admin", "member"];
  // Getters: the words are the catalog's when shown.
  const ROLE_WORDS = {
    get owner() { return M.t("orgs.role.owner"); },
    get admin() { return M.t("orgs.role.admin"); },
    get member() { return M.t("orgs.role.member"); },
  };
  // Names in a sentence: "a, b, c" in English, in the catalog's language (KTW adaebd69).
  const names = (list) => M.fmt.list(list);
  const orgPath = (org) => "/orgs/" + encodeURIComponent(org);
  const orgLink = (org) => "/account/orgs/" + encodeURIComponent(org);

  // The hub's refusals (§6.26), in words.
  const FIELD_WORDS = {
    get format() { return M.t("orgs.field.format"); },
    get reserved() { return M.t("orgs.field.reserved"); },
    get taken() { return M.t("orgs.field.taken"); },
    get member() { return M.t("orgs.field.member"); },
    get invited() { return M.t("orgs.field.invited"); },
    get length() { return M.t("orgs.field.length"); },
    get mismatch() { return M.t("orgs.field.mismatch"); },
  };
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) {
      const [name, why] = Object.entries(fields)[0];
      return { message: M.t("orgs.refused.field", { field: name === "display_name" ? M.t("orgs.field.name") : name,
        why: Object.hasOwn(FIELD_WORDS, why) ? FIELD_WORDS[why] : why }) };
    }
    const reason = err.details && err.details.reason;
    if (err.code === "forbidden" && reason === "org_role") return { message: M.t("orgs.refused.org_role") };
    if (err.code === "forbidden" && reason === "moderation_hold") return { message: M.t("orgs.refused.held") };
    if (err.code === "forbidden" && reason === "humans_only") return { message: M.t("orgs.refused.humans_only") };
    if (err.code === "org_last_owner") return { message: M.t("orgs.refused.last_owner") };
    if (err.code === "org_limit") return { message: M.t("orgs.refused.limit") };
    if (err.code === "namespace_owner") {
      const projects = (err.details && err.details.projects) || [];
      return { message: projects.length ? M.t("orgs.refused.owns_named", { projects: names(projects) }) : M.t("orgs.refused.owns") };
    }
    if (err.code === "rate_limited") return { message: M.t("orgs.refused.rate") };
    if (err.code === "alias_limit") return { message: M.t("orgs.refused.aliases", { count: (err.details && err.details.limit) || 8 }) };
    return err;
  }

  // The list and the form for a new one.
  async function listPage(ctx, root) {
    const heading = h("h2", { id: "orgs-heading", tabindex: "-1" }, M.t("orgs.title"));
    append(root, heading, h("p", { class: "hint" }, M.t("orgs.intro")));
    const { items } = await M.api.get("/orgs");
    append(root, items.length
      ? h("ul", { class: "org-list" }, items.map((o) => h("li", { class: "org-item" },
        M.avatar(o, 32),
        h("a", { href: orgLink(o.handle) }, o.display_name),
        h("span", { class: "muted" }, " @" + o.handle + " · " + o.my_role))))
      : h("p", { class: "muted" }, M.t("orgs.none")));
    append(root, createForm());
  }

  function createForm() {
    const status = M.statusLine();
    const handle = h("input", { id: "org-new-handle", required: true, autocomplete: "off", spellcheck: "false", placeholder: M.t("orgs.new.handle_placeholder") });
    const name = h("input", { id: "org-new-name", required: true, maxlength: "64", placeholder: M.t("orgs.new.name_placeholder") });
    const go = h("button", { type: "submit" }, M.t("orgs.new.create"));
    const form = h("form", {
      class: "org-create project-form",
      onsubmit: async (e) => {
        e.preventDefault();
        go.disabled = true;
        status.busy(M.t("orgs.new.creating"));
        try {
          const org = await M.api.post("/orgs", { handle: handle.value.trim().replace(/^@/, ""), display_name: name.value.trim() });
          M.route.go(orgLink(org.handle));
        } catch (err) {
          status.fail(M.t("orgs.new.failed"), said(err));
          go.disabled = false;
        }
      },
    },
    h("h3", null, M.t("orgs.new.title")),
    h("label", { for: "org-new-handle" }, M.t("orgs.handle")), handle,
    h("p", { class: "hint" }, M.t("orgs.new.hint")),
    h("label", { for: "org-new-name" }, M.t("orgs.name")), name,
    go, status.el);
    return form;
  }

  // One member: their role and, where the caller may, its change and removal.
  function memberRow(ctx, org, m, owners, redraw) {
    const status = M.statusLine();
    const self = m.id === ctx.me.id;
    const mine = org.my_role;
    const mayChange = mine === "owner" || (mine === "admin" && m.role !== "owner");
    const mayRemove = self || mayChange;
    const lastOwner = m.role === "owner" && owners === 1;
    let control = h("span", { class: "org-role" }, m.role);
    if (mayChange) {
      const id = "org-role-" + m.id;
      const pick = h("select", { id, "aria-label": M.t("orgs.member.role_label", { handle: m.handle }) },
        ROLES.filter((r) => mine === "owner" || r !== "owner").map((r) => h("option", { value: r }, r)));
      pick.value = m.role;
      pick.addEventListener("change", async () => {
        pick.disabled = true;
        status.busy(M.t("orgs.member.changing"));
        try {
          await M.api.patch(orgPath(org.handle) + "/members/" + encodeURIComponent(m.id), { role: pick.value });
          redraw(M.t("orgs.member.changed", { handle: m.handle, role: pick.value }));
        } catch (err) {
          pick.value = m.role;
          pick.disabled = false;
          status.fail(M.t("orgs.member.change_failed"), said(err));
        }
      });
      control = pick;
    }
    const remove = mayRemove ? h("button", {
      type: "button",
      class: self ? null : "danger",
      title: lastOwner ? M.t("orgs.member.last_owner") : null,
      onclick: async () => {
        remove.disabled = true;
        status.busy(self ? M.t("orgs.member.leaving") : M.t("orgs.member.removing"));
        try {
          await M.api.del(orgPath(org.handle) + "/members/" + encodeURIComponent(m.id));
          if (self) M.route.go("/account/orgs");
          else redraw(M.t("orgs.member.removed", { handle: m.handle }));
        } catch (err) {
          remove.disabled = false;
          status.fail(self ? M.t("orgs.member.leave_failed") : M.t("orgs.member.remove_failed"), said(err));
        }
      },
    }, self ? M.t("orgs.member.leave") : M.t("orgs.member.remove")) : null;
    return h("li", { class: "org-member" },
      M.avatar(m, 24),
      h("span", { class: "org-member-name" }, m.display_name, h("span", { class: "muted" }, " " + (self ? M.t("orgs.member.handle_you", { handle: m.handle }) : "@" + m.handle))),
      control, remove, status.el);
  }

  function invitationsPart(org, invitations, redraw) {
    const status = M.statusLine();
    const handle = h("input", { id: "org-invite-handle", required: true, autocomplete: "off", spellcheck: "false", placeholder: "@handle" });
    const role = h("select", { id: "org-invite-role" },
      ROLES.filter((r) => org.my_role === "owner" || r !== "owner").map((r) => h("option", { value: r }, r)));
    role.value = "member";
    const go = h("button", { type: "submit" }, M.t("orgs.invite.submit"));
    const form = h("form", {
      class: "org-invite inline-form",
      onsubmit: async (e) => {
        e.preventDefault();
        go.disabled = true;
        status.busy(M.t("orgs.invite.busy"));
        try {
          const item = await M.api.post(orgPath(org.handle) + "/members/invitations", { handle: handle.value.trim().replace(/^@/, ""), role: role.value });
          redraw(M.t("orgs.invite.done", { handle: item.handle, role: item.role }));
        } catch (err) {
          go.disabled = false;
          status.fail(M.t("orgs.invite.failed"), said(err));
        }
      },
    },
    h("label", { for: "org-invite-handle" }, M.t("orgs.handle")), handle,
    h("label", { for: "org-invite-role" }, M.t("orgs.role")), role, go, status.el);
    const rows = invitations.map((x) => {
      const line = M.statusLine();
      // An invitation for the role owner is an owner's to withdraw (§6.26).
      const withdraw = x.role === "owner" && org.my_role !== "owner" ? null : h("button", {
        type: "button",
        onclick: async () => {
          withdraw.disabled = true;
          line.busy(M.t("orgs.invite.withdrawing"));
          try {
            await M.api.del(orgPath(org.handle) + "/members/invitations/" + encodeURIComponent(x.id));
            redraw(M.t("orgs.invite.withdrawn", { handle: x.handle }));
          } catch (err) {
            withdraw.disabled = false;
            line.fail(M.t("orgs.invite.withdraw_failed"), said(err));
          }
        },
      }, M.t("orgs.invite.withdraw"));
      return h("li", { class: "org-invitation" },
        h("span", null, M.t("orgs.invite.item", { handle: x.handle, role: x.role })),
        h("span", { class: "muted" }, " · " + M.t("orgs.invite.by", { handle: x.invited_by.handle, time: formatTime(x.expires_at) })),
        withdraw, line.el);
    });
    return h("section", { class: "org-invitations", "aria-labelledby": "org-invitations-heading" },
      h("h3", { id: "org-invitations-heading" }, M.t("orgs.invite.title")),
      h("p", { class: "hint" }, M.t("orgs.invite.hint", { count: 14 })),
      rows.length ? h("ul", { class: "org-invitation-list" }, rows) : h("p", { class: "muted" }, M.t("orgs.invite.none")),
      form);
  }

  function settingsPart(org, redraw) {
    const status = M.statusLine();
    const name = h("input", { id: "org-name", required: true, maxlength: "64" });
    name.value = org.display_name;
    const handle = h("input", { id: "org-handle", required: true, autocomplete: "off", spellcheck: "false" });
    handle.value = org.handle;
    const create = h("input", { id: "org-members-create", type: "checkbox" });
    create.checked = !!org.members_create_projects;
    const page = h("input", { id: "org-public-page", type: "checkbox" });
    page.checked = org.public_page === "on";
    // While suspended the hub refuses a rename and turning the page on (§6.26).
    const held = !!org.moderation;
    handle.disabled = held;
    page.disabled = held && !page.checked;
    const go = h("button", { type: "submit" }, M.t("orgs.settings.save"));
    const form = h("form", {
      class: "org-settings project-form",
      onsubmit: async (e) => {
        e.preventDefault();
        const body = {};
        const wanted = handle.value.trim().replace(/^@/, "");
        if (name.value.trim() !== org.display_name) body.display_name = name.value.trim();
        if (wanted !== org.handle) body.handle = wanted;
        if (create.checked !== !!org.members_create_projects) body.members_create_projects = create.checked;
        if ((page.checked ? "on" : "off") !== org.public_page) body.public_page = page.checked ? "on" : "off";
        if (!Object.keys(body).length) { status.busy(M.t("orgs.settings.unchanged")); return; }
        go.disabled = true;
        status.busy(M.t("orgs.settings.saving"));
        try {
          const now = await M.api.patch(orgPath(org.handle), body);
          if (now.handle !== org.handle) M.route.go(orgLink(now.handle));
          else redraw(M.t("orgs.settings.saved"));
        } catch (err) {
          go.disabled = false;
          status.fail(M.t("orgs.settings.failed"), said(err));
        }
      },
    },
    h("label", { for: "org-name" }, M.t("orgs.name")), name,
    h("label", { for: "org-handle" }, M.t("orgs.handle")), handle,
    h("p", { class: "hint" }, held ? M.t("orgs.settings.held") : M.t("orgs.settings.rename_hint")),
    h("p", { class: "check" }, create, h("label", { for: "org-members-create" }, " " + M.t("orgs.settings.members_create"))),
    h("p", { class: "check" }, page, h("label", { for: "org-public-page" }, " " + M.t("orgs.settings.public_page"))),
    go, status.el);
    return h("section", { class: "org-settings-part", "aria-labelledby": "org-settings-heading" },
      h("h3", { id: "org-settings-heading" }, M.t("orgs.settings.title")), form);
  }

  // Deleting it: an owner's sensitive call (§2.8.4), confirmed by typing the handle.
  function deletePart(org) {
    const status = M.statusLine();
    const ask = h("div", { class: "step-up-slot" });
    ask.hidden = true;
    const id = "org-delete-confirm";
    const typed = h("input", { id, autocomplete: "off", spellcheck: "false", placeholder: "@" + org.handle });
    const go = h("button", { type: "submit", class: "danger" }, M.t("orgs.delete.title"));
    let busy = false;
    const confirmed = () => typed.value.trim().replace(/^@/, "") === org.handle;
    const settle = () => { go.disabled = busy || !confirmed(); };
    settle();
    typed.addEventListener("input", settle);
    const form = h("form", {
      class: "org-delete inline-form",
      onsubmit: async (e) => {
        e.preventDefault();
        if (busy || !confirmed()) return;
        busy = true;
        typed.disabled = true;
        settle();
        status.busy(M.t("orgs.delete.busy"));
        try {
          await M.stepUp.run(() => M.api.del(orgPath(org.handle), { confirm: org.handle }), ask, M.t("orgs.delete.step_up", { handle: org.handle }));
          M.route.go("/account/orgs");
        } catch (err) {
          busy = false;
          typed.disabled = false;
          settle();
          if (err.code === "cancelled") status.done();
          else status.fail(M.t("orgs.delete.failed"), said(err));
        }
      },
    }, h("label", { for: id }, M.t("orgs.delete.type", { handle: org.handle })), typed, go, status.el);
    return h("section", { class: "org-delete-part", "aria-labelledby": "org-delete-heading" },
      h("h3", { id: "org-delete-heading" }, M.t("orgs.delete.title")),
      h("p", { class: "hint" }, M.t("orgs.delete.hint")),
      ask, form);
  }

  async function orgPage(ctx, root, handle) {
    const body = h("div", { class: "org-page" });
    append(root, h("p", null, h("a", { href: "/account/orgs" }, M.t("orgs.all"))), body);
    const draw = async (words) => {
      let org;
      try {
        org = await M.api.get(orgPath(handle));
      } catch (err) {
        if (err.code !== "not_found") throw err;
        append(clear(body), h("p", null, M.t("orgs.not_in", { handle })));
        return;
      }
      const leads = org.my_role === "owner" || org.my_role === "admin";
      const [members, invitations] = await Promise.all([
        M.api.get(orgPath(org.handle) + "/members"),
        leads ? M.api.get(orgPath(org.handle) + "/members/invitations") : Promise.resolve({ items: [] }),
      ]);
      const redraw = (said) => draw(said).catch((err) => append(clear(body), h("p", { class: "send-status failed" }, M.t("orgs.reread_failed", { reason: err.message }))));
      const owners = members.items.filter((m) => m.role === "owner").length;
      const who = Object.assign({}, org, { avatar_source: org.avatar_url ? "uploaded" : null });
      append(clear(body),
        h("div", { class: "org-head" }, M.avatar(org, 48),
          h("h2", { id: "org-heading", tabindex: "-1" }, org.display_name),
          h("p", { class: "muted" }, (org.aliases || []).length
            ? M.t("orgs.head.aliases", { handle: org.handle, role: org.my_role, aliases: names(org.aliases.map((a) => "@" + a)) })
            : M.t("orgs.head", { handle: org.handle, role: org.my_role }))),
        words ? h("p", { class: "ok", role: "status" }, words) : null,
        org.moderation ? h("p", { class: "flag", role: "status" }, M.t("orgs.suspended", { time: formatTime(org.moderation.at) })) : null,
        h("section", { class: "org-members", "aria-labelledby": "org-members-heading" },
          h("h3", { id: "org-members-heading" }, M.t("orgs.members")),
          h("ul", { class: "org-member-list" }, members.items.map((m) => memberRow(ctx, org, m, owners, redraw))),
          h("ul", { class: "hint org-role-words" }, ROLES.map((r) => h("li", null, ROLE_WORDS[r])))),
        leads ? invitationsPart(org, invitations.items, redraw) : null,
        org.my_role === "owner" ? settingsPart(org, redraw) : null,
        org.my_role === "owner" && M.pictureEditor
          ? h("section", { class: "org-picture", "aria-labelledby": "org-picture-heading" },
            h("h3", { id: "org-picture-heading" }, M.t("orgs.picture")),
            M.pictureEditor(who, orgPath(org.handle) + "/avatar", false, (answer, said) => redraw(said)))
          : null,
        org.my_role === "owner" ? deletePart(org) : null);
    };
    await draw();
  }

  // A handle from the address as a typed one is read (§6.24): decoded, without
  // a leading @, in lowercase.
  function handleOf(arg) {
    let text = String(arg || "");
    try { text = decodeURIComponent(text); } catch (ignored) { /* kept as it came */ }
    return text.trim().replace(/^@/, "").toLowerCase();
  }

  M.views.orgs = async function (ctx, root, args) {
    if (ctx.me.kind !== "human") {
      append(root, h("p", null, M.t("orgs.humans_only")));
      return;
    }
    if (args && args[0]) await orgPage(ctx, root, handleOf(args[0]));
    else await listPage(ctx, root);
  };
  M.orgs = { said, handleOf };
})(window.Maity);
