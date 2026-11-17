// The project's roles (docs/api.md §2.3 "Project roles"): the built-in roles as the hub
// explains them, and the project's own roles, each a name on a built-in base whose scopes it
// grants and nothing else. A human with project:admin adds, changes and removes them with
// `PUT …/roles`, the whole list at once. A role's own briefing and guide are the project's
// briefings (§6.28), whose routes the hub does not serve yet; they are not edited here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // The bases a project role may stand on (§2.3), in the order of the role table.
  const BASES = ["coder", "reviewer", "tester", "designer", "writer", "ops"];
  const NAME = /^[a-z][a-z0-9-]{1,23}$/;
  // Names a project role may not take beside the built-in roles: trusts and tokens (§2.3).
  const RESERVED = ["owner", "admin", "member", "outside", "guest", "team", "all", "proxy", "lead", "null", "none"];
  const LIMIT = 12;
  const DESCRIPTION_MAX = 200;
  const length = (s) => [...s].length;

  // `details.fields` of an `invalid` PUT, by its reason (§2.3).
  const FIELD_WORDS = {
    format: () => M.t("roles.error.format"),
    reserved: () => M.t("roles.error.reserved"),
    duplicate: () => M.t("roles.error.duplicate"),
    unknown: () => M.t("roles.error.base"),
    outside_roles: () => M.t("roles.error.outside_roles"),
    too_long: () => M.t("roles.error.too_long"),
    too_many: () => M.t("roles.error.too_many"),
  };
  const fieldWords = (why) => (Object.hasOwn(FIELD_WORDS, why) ? FIELD_WORDS[why]() : why);
  // `details.uses` of a `role_in_use` refusal: what still names the role.
  const USE_WORDS = {
    membership: () => M.t("roles.use.membership"),
    join: () => M.t("roles.use.join"),
    invitation: () => M.t("roles.use.invitation"),
    card: () => M.t("roles.use.card"),
    request: () => M.t("roles.use.request"),
    placement: () => M.t("roles.use.placement"),
    check_in_with: () => M.t("roles.use.check_in_with"),
    substitutes: () => M.t("roles.use.substitutes"),
    memory: () => M.t("roles.use.memory"),
    outside_roles: () => M.t("roles.use.outside_roles"),
  };
  const useWords = (use) => (Object.hasOwn(USE_WORDS, use) ? USE_WORDS[use]() : use);

  // The section in Settings → Members and agents, for a human with project:admin (the PUT is
  // human only). `saved(words)` draws the settings again with what the save did.
  function settingsSection(ctx, saved) {
    const section = h("section", { class: "project-roles", id: "project-roles", "aria-labelledby": "project-roles-title" },
      h("h2", { class: "panel-title", id: "project-roles-title" }, M.t("roles.title")),
      h("p", { class: "hint" }, M.t("roles.hint")));
    const body = h("div", { class: "project-roles-body" });
    const status = M.statusLine();
    append(section, body, status.el);
    const load = () => {
      status.busy(M.t("roles.loading"));
      M.api.get(ctx.base + "/roles").then((answer) => {
        status.done();
        draw(ctx, body, answer || {}, saved, load);
      }).catch((err) => status.fail(M.t("roles.load_failed"), err));
    };
    load();
    return section;
  }

  function draw(ctx, body, answer, saved, reload) {
    const builtin = answer.builtin || [];
    const stored = (answer.custom || []).map((r) => ({ name: r.name, base: r.base, description: r.description || "", guide: r.guide || "" }));
    // The list's version as read (§2.3 "Version."): the save names it, and the hub refuses it
    // when someone else saved since.
    const version = answer.version;
    clear(body);

    // The built-in roles, read only: what each means and its guide as it applies here.
    append(body, h("h3", null, M.t("roles.builtin.title")),
      h("ul", { class: "project-roles-builtin" }, builtin.map((r) => h("li", null,
        h("strong", null, M.trust.roleLabel(r.name)), " ", h("code", null, r.name),
        r.description ? h("span", { class: "muted" }, " — " + r.description) : null,
        r.guide ? h("details", null, h("summary", null, M.t("roles.guide")), h("p", { class: "project-roles-guide" }, r.guide)) : null))));

    // The project's own roles: a row each, name fixed once saved (there is no rename, §2.3).
    const rows = stored.map((r) => ({ ...r, kept: true }));
    const table = h("tbody");
    const errors = h("ul", { class: "field-error project-roles-errors", role: "alert" });
    const confirmBox = h("div", { class: "project-roles-confirm", hidden: true });
    const status = M.statusLine();
    const save = h("button", { type: "submit" }, M.t("roles.save"));
    const add = h("button", { type: "button", class: "project-roles-add" }, M.t("roles.add"));

    // The draft is frozen while the confirmation is open and while the PUT runs, so what is
    // sent is what the page shows (A963 P2-2); Back or a refusal thaws it.
    const editors = () => [...table.querySelectorAll("input"), ...table.querySelectorAll("select"), ...table.querySelectorAll("button")];
    const freeze = (on) => {
      editors().forEach((el) => { el.disabled = on; });
      add.disabled = on || rows.length >= LIMIT;
      save.disabled = on;
    };

    function drawRows() {
      clear(table);
      rows.forEach((r, i) => {
        const name = h("input", { id: "project-role-name-" + i, class: "project-role-name", maxlength: 24, required: true,
          readonly: r.kept ? true : null, "aria-label": M.t("roles.name"), autocomplete: "off", spellcheck: "false" });
        name.value = r.name || "";
        name.addEventListener("input", () => { r.name = name.value.trim(); });
        const base = h("select", { id: "project-role-base-" + i, "aria-label": M.t("roles.base") },
          BASES.map((b) => h("option", { value: b }, M.trust.roleLabel(b))));
        base.value = r.base || BASES[0];
        r.base = base.value;
        base.addEventListener("change", () => { r.base = base.value; });
        const description = h("input", { id: "project-role-description-" + i, maxlength: DESCRIPTION_MAX, "aria-label": M.t("roles.description") });
        description.value = r.description || "";
        description.addEventListener("input", () => { r.description = description.value; });
        const remove = h("button", { type: "button", class: "project-roles-remove", "aria-label": M.t("roles.remove_named", { name: r.name || "" }),
          onclick: () => { rows.splice(i, 1); drawRows(); add.disabled = rows.length >= LIMIT; } }, M.t("roles.remove"));
        append(table, h("tr", { "data-role": r.name || "" },
          h("td", null, name), h("td", null, base), h("td", null, description), h("td", null, remove)));
      });
      if (!rows.length) append(table, h("tr", null, h("td", { colspan: 4, class: "muted" }, M.t("roles.none"))));
    }

    add.addEventListener("click", () => {
      if (rows.length >= LIMIT) return;
      rows.push({ name: "", base: BASES[0], description: "", kept: false });
      drawRows();
      add.disabled = rows.length >= LIMIT;
      const fields = table.querySelectorAll("input.project-role-name");
      if (fields.length) fields[fields.length - 1].focus();
    });
    add.disabled = rows.length >= LIMIT;
    drawRows();

    const list = () => rows.map((r) => ({ name: r.name, base: r.base, description: r.description || "" }));
    const unchanged = (next) => next.length === stored.length
      && next.every((r, i) => r.name === stored[i].name && r.base === stored[i].base && r.description === stored[i].description);
    // Who moves along when a role in use takes another base (§2.3, §6.4): the members the
    // page knows in that role. The hub moves them and drops the approvals the new base does not give.
    const movedBy = (next) => next.map((r) => {
      const before = stored.find((s) => s.name === r.name);
      if (!before || before.base === r.base) return null;
      const count = (ctx.members || []).filter((m) => m.role === r.name).length;
      return count ? { name: r.name, from: before.base, to: r.base, count } : null;
    }).filter(Boolean);

    // The page's own checks, the hub's rules (§2.3), so a typo is said before the call.
    function localErrors(next) {
      const said = [];
      const seen = new Set();
      next.forEach((r, i) => {
        const label = r.name || M.t("roles.row", { number: i + 1 });
        if (rows[i] && rows[i].kept) { seen.add(r.name); }
        else if (!NAME.test(r.name || "")) said.push(M.t("roles.error.at", { role: label, why: fieldWords("format") }));
        else if (M.trust.ROLES.includes(r.name) || RESERVED.includes(r.name)) said.push(M.t("roles.error.at", { role: label, why: fieldWords("reserved") }));
        else if (seen.has(r.name)) said.push(M.t("roles.error.at", { role: label, why: fieldWords("duplicate") }));
        seen.add(r.name);
        if (length(r.description || "") > DESCRIPTION_MAX) said.push(M.t("roles.error.at", { role: label, why: fieldWords("too_long") }));
      });
      return said;
    }

    // The save names the version this page read; when someone else saved since, the hub refuses
    // it (`conflict` without a `reason`, §2.3 "Version.") and changes nothing: the draft stays
    // until Reload (the lead's decision on A963 P2-1). No read before the PUT: the hub's check
    // covers a stale page and two saves in the same instant alike.
    function changedElsewhere() {
      clear(errors);
      status.done();
      append(errors, h("li", { class: "project-roles-stale" }, M.t("roles.stale"), " ",
        h("button", { type: "button", class: "project-roles-reload", onclick: () => reload() }, M.t("roles.reload"))));
      freeze(false);
    }

    async function send(next) {
      clear(errors);
      confirmBox.hidden = true;
      freeze(true);
      status.busy(M.t("settings.saving"));
      try {
        await M.api.put(ctx.base + "/roles", { custom: next, base_version: version });
        saved(M.t("roles.saved"));
      } catch (err) {
        freeze(false);
        if (err.code === "conflict" && err.details && err.details.current_version !== undefined) { changedElsewhere(); return; }
        if (err.code === "conflict" && err.details && err.details.reason === "role_in_use") {
          status.done();
          // The hub kept the role: it comes back into the draft as it was loaded, so the next
          // save does not try to remove it again (A964).
          const keptRole = stored.find((s) => s.name === err.details.role);
          if (keptRole && !rows.some((r) => r.name === keptRole.name)) {
            const at = stored.indexOf(keptRole);
            const before = rows.findIndex((r) => !r.kept || stored.findIndex((s) => s.name === r.name) > at);
            rows.splice(before < 0 ? rows.length : before, 0, { ...keptRole, kept: true });
            drawRows();
            freeze(false);
          }
          append(errors, h("li", null, M.t("roles.in_use", { role: err.details.role || "",
            uses: (err.details.uses || []).map(useWords).join(", ") })));
          return;
        }
        const fields = (err.code === "invalid" && err.details && err.details.fields) || {};
        const keys = Object.keys(fields);
        if (keys.length) {
          status.done();
          keys.forEach((k) => {
            const at = /^custom\[(\d+)\]/.exec(k);
            const row = at ? next[Number(at[1])] : null;
            append(errors, h("li", null, row ? M.t("roles.error.at", { role: row.name || M.t("roles.row", { number: Number(at[1]) + 1 }), why: fieldWords(fields[k]) })
              : fieldWords(fields[k])));
          });
          return;
        }
        status.fail(M.t("roles.not_saved"), err);
      }
    }

    // Before a base change of a role in use: how many members move along and that their
    // approvals from the old base expire; saved only once the human confirms.
    function askMove(next, moved) {
      clear(confirmBox);
      append(confirmBox,
        h("ul", { class: "project-roles-moved" }, moved.map((x) => h("li", null, M.t("roles.move.members", {
          count: x.count, role: x.name, from: M.trust.roleLabel(x.from), to: M.trust.roleLabel(x.to) })))),
        h("p", null, M.t("roles.move.approvals")),
        h("div", { class: "actions" },
          h("button", { type: "button", class: "project-roles-move-back", onclick: () => { confirmBox.hidden = true; freeze(false); save.focus(); } }, M.t("roles.move.back")),
          h("button", { type: "button", class: "project-roles-move-go", onclick: () => send(next) }, M.t("roles.move.go"))));
      confirmBox.hidden = false;
      freeze(true);
      confirmBox.querySelector("button.project-roles-move-go").focus();
    }

    append(body, h("h3", null, M.t("roles.custom.title")),
      h("p", { class: "hint" }, M.t("roles.custom.hint", { max: LIMIT })),
      h("form", {
        class: "project-roles-form",
        onsubmit: (e) => {
          e.preventDefault();
          clear(errors);
          status.done();
          const next = list();
          if (unchanged(next)) { append(status.el, h("span", null, M.t("roles.unchanged"))); return; }
          const said = localErrors(next);
          if (said.length) { said.forEach((s) => append(errors, h("li", null, s))); return; }
          const moved = movedBy(next);
          if (moved.length) { askMove(next, moved); return; }
          send(next);
        },
      },
      h("table", { class: "card-table project-roles-table" },
        h("thead", null, h("tr", null,
          h("th", { scope: "col" }, M.t("roles.name")), h("th", { scope: "col" }, M.t("roles.base")),
          h("th", { scope: "col" }, M.t("roles.description")), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, M.t("roles.actions"))))),
        table),
      h("div", { class: "actions" }, add, save),
      errors, confirmBox, status.el),
      h("p", { class: "muted project-roles-briefings" }, M.t("roles.briefings_later")));
  }

  M.projectRoles = { settingsSection, BASES };
})(window.Maity);
