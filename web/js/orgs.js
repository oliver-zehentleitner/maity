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
  const ROLE_WORDS = {
    owner: "Owner: everything, its handle and deletion included; trust owner in every project of the organisation",
    admin: "Admin: adds and removes members and admins, creates projects in it",
    member: "Member: creates projects in it only where the owners allow it",
  };
  const orgPath = (org) => "/orgs/" + encodeURIComponent(org);
  const orgLink = (org) => "/account/orgs/" + encodeURIComponent(org);

  // The hub's refusals (§6.26), in words.
  const FIELD_WORDS = {
    format: "2 to 31 lowercase letters, digits and dashes, starting with a letter or digit",
    reserved: "a word the dashboard uses itself",
    taken: "taken by a person or another organisation",
    member: "already a member",
    invited: "invited already",
    length: "1 to 64 characters",
    mismatch: "not the organisation's handle; read the page again",
  };
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) {
      const [name, why] = Object.entries(fields)[0];
      return { message: (name === "display_name" ? "name" : name) + ": " + (FIELD_WORDS[why] || why) };
    }
    const reason = err.details && err.details.reason;
    if (err.code === "forbidden" && reason === "org_role") return { message: "your role in this organisation does not allow that" };
    if (err.code === "forbidden" && reason === "moderation_hold") return { message: "the organisation is suspended: no new invitation, no rename and no public page meanwhile" };
    if (err.code === "forbidden" && reason === "humans_only") return { message: "organisations are for humans only" };
    if (err.code === "org_last_owner") return { message: "the organisation would have no owner left: make someone else an owner first" };
    if (err.code === "org_limit") return { message: "you are in as many organisations as this hub allows" };
    if (err.code === "namespace_owner") {
      const projects = (err.details && err.details.projects) || [];
      return { message: "it still owns projects that are not archived" + (projects.length ? ": " + projects.join(", ") : "") + "; archive or transfer them first" };
    }
    if (err.code === "rate_limited") return { message: "too many at once; try again later" };
    if (err.code === "alias_limit") return { message: "the organisation has kept " + ((err.details && err.details.limit) || 8) + " earlier handles, the most it may" };
    return err;
  }

  // The list and the form for a new one.
  async function listPage(ctx, root) {
    const heading = h("h2", { id: "orgs-heading", tabindex: "-1" }, "Organisations");
    append(root, heading,
      h("p", { class: "hint" }, "An organisation owns projects under its own handle, so that a team's projects do not hang on one person's account. "
        + "Its owners hold trust owner in every project it owns."));
    const { items } = await M.api.get("/orgs");
    append(root, items.length
      ? h("ul", { class: "org-list" }, items.map((o) => h("li", { class: "org-item" },
        M.avatar(o, 32),
        h("a", { href: orgLink(o.handle) }, o.display_name),
        h("span", { class: "muted" }, " @" + o.handle + " · " + o.my_role))))
      : h("p", { class: "muted" }, "You are in no organisation yet."));
    append(root, createForm());
  }

  function createForm() {
    const status = M.statusLine();
    const handle = h("input", { id: "org-new-handle", required: true, autocomplete: "off", spellcheck: "false", placeholder: "oz-team" });
    const name = h("input", { id: "org-new-name", required: true, maxlength: "64", placeholder: "OZ Team" });
    const go = h("button", { type: "submit" }, "Create the organisation");
    const form = h("form", {
      class: "org-create project-form",
      onsubmit: async (e) => {
        e.preventDefault();
        go.disabled = true;
        status.busy("Creating…");
        try {
          const org = await M.api.post("/orgs", { handle: handle.value.trim().replace(/^@/, ""), display_name: name.value.trim() });
          M.route.go(orgLink(org.handle));
        } catch (err) {
          status.fail("Not created: ", said(err));
          go.disabled = false;
        }
      },
    },
    h("h3", null, "New organisation"),
    h("label", { for: "org-new-handle" }, "Handle"), handle,
    h("p", { class: "hint" }, "Its projects are addressed as <handle>/<project>. You become its first owner."),
    h("label", { for: "org-new-name" }, "Name"), name,
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
      const pick = h("select", { id, "aria-label": "Role of @" + m.handle },
        ROLES.filter((r) => mine === "owner" || r !== "owner").map((r) => h("option", { value: r }, r)));
      pick.value = m.role;
      pick.addEventListener("change", async () => {
        pick.disabled = true;
        status.busy("Changing…");
        try {
          await M.api.patch(orgPath(org.handle) + "/members/" + encodeURIComponent(m.id), { role: pick.value });
          redraw("@" + m.handle + " is " + pick.value + " now.");
        } catch (err) {
          pick.value = m.role;
          pick.disabled = false;
          status.fail("Not changed: ", said(err));
        }
      });
      control = pick;
    }
    const remove = mayRemove ? h("button", {
      type: "button",
      class: self ? null : "danger",
      title: lastOwner ? "The last owner: make someone else an owner first." : null,
      onclick: async () => {
        remove.disabled = true;
        status.busy(self ? "Leaving…" : "Removing…");
        try {
          await M.api.del(orgPath(org.handle) + "/members/" + encodeURIComponent(m.id));
          if (self) M.route.go("/account/orgs");
          else redraw("@" + m.handle + " was removed.");
        } catch (err) {
          remove.disabled = false;
          status.fail(self ? "Not left: " : "Not removed: ", said(err));
        }
      },
    }, self ? "Leave" : "Remove") : null;
    return h("li", { class: "org-member" },
      M.avatar(m, 24),
      h("span", { class: "org-member-name" }, m.display_name, h("span", { class: "muted" }, " @" + m.handle + (self ? " (you)" : ""))),
      control, remove, status.el);
  }

  function invitationsPart(org, invitations, redraw) {
    const status = M.statusLine();
    const handle = h("input", { id: "org-invite-handle", required: true, autocomplete: "off", spellcheck: "false", placeholder: "@handle" });
    const role = h("select", { id: "org-invite-role" },
      ROLES.filter((r) => org.my_role === "owner" || r !== "owner").map((r) => h("option", { value: r }, r)));
    role.value = "member";
    const go = h("button", { type: "submit" }, "Invite");
    const form = h("form", {
      class: "org-invite inline-form",
      onsubmit: async (e) => {
        e.preventDefault();
        go.disabled = true;
        status.busy("Inviting…");
        try {
          const item = await M.api.post(orgPath(org.handle) + "/members/invitations", { handle: handle.value.trim().replace(/^@/, ""), role: role.value });
          redraw("Invited @" + item.handle + " as " + item.role + ".");
        } catch (err) {
          go.disabled = false;
          status.fail("Not invited: ", said(err));
        }
      },
    },
    h("label", { for: "org-invite-handle" }, "Handle"), handle,
    h("label", { for: "org-invite-role" }, "Role"), role, go, status.el);
    const rows = invitations.map((x) => {
      const line = M.statusLine();
      // An invitation for the role owner is an owner's to withdraw (§6.26).
      const withdraw = x.role === "owner" && org.my_role !== "owner" ? null : h("button", {
        type: "button",
        onclick: async () => {
          withdraw.disabled = true;
          line.busy("Withdrawing…");
          try {
            await M.api.del(orgPath(org.handle) + "/members/invitations/" + encodeURIComponent(x.id));
            redraw("The invitation of @" + x.handle + " was withdrawn.");
          } catch (err) {
            withdraw.disabled = false;
            line.fail("Not withdrawn: ", said(err));
          }
        },
      }, "Withdraw");
      return h("li", { class: "org-invitation" },
        h("span", null, "@" + x.handle + " as " + x.role),
        h("span", { class: "muted" }, " · by @" + x.invited_by.handle + ", open until " + formatTime(x.expires_at)),
        withdraw, line.el);
    });
    return h("section", { class: "org-invitations", "aria-labelledby": "org-invitations-heading" },
      h("h3", { id: "org-invitations-heading" }, "Invitations"),
      h("p", { class: "hint" }, "Nobody joins without saying so: the person gets a request in their inbox and answers it. "
        + "An invitation is open 14 days. The page says the same whether or not the handle names someone who can be invited."),
      rows.length ? h("ul", { class: "org-invitation-list" }, rows) : h("p", { class: "muted" }, "No open invitations."),
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
    const go = h("button", { type: "submit" }, "Save");
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
        if (!Object.keys(body).length) { status.busy("Nothing changed."); return; }
        go.disabled = true;
        status.busy("Saving…");
        try {
          const now = await M.api.patch(orgPath(org.handle), body);
          if (now.handle !== org.handle) M.route.go(orgLink(now.handle));
          else redraw("Saved.");
        } catch (err) {
          go.disabled = false;
          status.fail("Not saved: ", said(err));
        }
      },
    },
    h("label", { for: "org-name" }, "Name"), name,
    h("label", { for: "org-handle" }, "Handle"), handle,
    h("p", { class: "hint" }, held ? "While the organisation is suspended its handle cannot change and its public page cannot be turned on."
      : "A new handle renames every project address of the organisation; the old one keeps leading here as an alias."),
    h("p", { class: "check" }, create, h("label", { for: "org-members-create" }, " Members may create projects in it")),
    h("p", { class: "check" }, page, h("label", { for: "org-public-page" }, " A public page")),
    go, status.el);
    return h("section", { class: "org-settings-part", "aria-labelledby": "org-settings-heading" },
      h("h3", { id: "org-settings-heading" }, "Settings"), form);
  }

  // Deleting it: an owner's sensitive call (§2.8.4), confirmed by typing the handle.
  function deletePart(org) {
    const status = M.statusLine();
    const ask = h("div", { class: "step-up-slot" });
    ask.hidden = true;
    const id = "org-delete-confirm";
    const typed = h("input", { id, autocomplete: "off", spellcheck: "false", placeholder: "@" + org.handle });
    const go = h("button", { type: "submit", class: "danger" }, "Delete the organisation");
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
        status.busy("Deleting…");
        try {
          await M.stepUp.run(() => M.api.del(orgPath(org.handle), { confirm: org.handle }), ask, "Deleting @" + org.handle);
          M.route.go("/account/orgs");
        } catch (err) {
          busy = false;
          typed.disabled = false;
          settle();
          if (err.code === "cancelled") status.done();
          else status.fail("Not deleted: ", said(err));
        }
      },
    }, h("label", { for: id }, "Type @" + org.handle + " to delete it"), typed, go, status.el);
    return h("section", { class: "org-delete-part", "aria-labelledby": "org-delete-heading" },
      h("h3", { id: "org-delete-heading" }, "Delete the organisation"),
      h("p", { class: "hint" }, "Only while it owns no project that is not archived. Its open invitations are withdrawn. This cannot be undone."),
      ask, form);
  }

  async function orgPage(ctx, root, handle) {
    const body = h("div", { class: "org-page" });
    append(root, h("p", null, h("a", { href: "/account/orgs" }, "All your organisations")), body);
    const draw = async (words) => {
      let org;
      try {
        org = await M.api.get(orgPath(handle));
      } catch (err) {
        if (err.code !== "not_found") throw err;
        append(clear(body), h("p", null, "You are in no organisation @" + handle + "."));
        return;
      }
      const leads = org.my_role === "owner" || org.my_role === "admin";
      const [members, invitations] = await Promise.all([
        M.api.get(orgPath(org.handle) + "/members"),
        leads ? M.api.get(orgPath(org.handle) + "/members/invitations") : Promise.resolve({ items: [] }),
      ]);
      const redraw = (said) => draw(said).catch((err) => append(clear(body), h("p", { class: "send-status failed" }, "This page could not be read again: " + err.message)));
      const owners = members.items.filter((m) => m.role === "owner").length;
      const who = Object.assign({}, org, { avatar_source: org.avatar_url ? "uploaded" : null });
      append(clear(body),
        h("div", { class: "org-head" }, M.avatar(org, 48),
          h("h2", { id: "org-heading", tabindex: "-1" }, org.display_name),
          h("p", { class: "muted" }, "@" + org.handle + " · you are " + org.my_role
            + ((org.aliases || []).length ? " · also known as " + org.aliases.map((a) => "@" + a).join(", ") : ""))),
        words ? h("p", { class: "ok", role: "status" }, words) : null,
        org.moderation ? h("p", { class: "flag", role: "status" }, "Suspended since " + formatTime(org.moderation.at)
          + ": no new project, no invitation, no rename and no public page meanwhile.") : null,
        h("section", { class: "org-members", "aria-labelledby": "org-members-heading" },
          h("h3", { id: "org-members-heading" }, "Members"),
          h("ul", { class: "org-member-list" }, members.items.map((m) => memberRow(ctx, org, m, owners, redraw))),
          h("ul", { class: "hint org-role-words" }, ROLES.map((r) => h("li", null, ROLE_WORDS[r])))),
        leads ? invitationsPart(org, invitations.items, redraw) : null,
        org.my_role === "owner" ? settingsPart(org, redraw) : null,
        org.my_role === "owner" && M.pictureEditor
          ? h("section", { class: "org-picture", "aria-labelledby": "org-picture-heading" },
            h("h3", { id: "org-picture-heading" }, "Picture"),
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
      append(root, h("p", null, "Organisations are for humans only."));
      return;
    }
    if (args && args[0]) await orgPage(ctx, root, handleOf(args[0]));
    else await listPage(ctx, root);
  };
  M.orgs = { said, handleOf };
})(window.Maity);
