// The public pages one decides on (docs/api.md §16.9, tsk-0vccw54gj8e6): a
// project's for its namespace owner, a person's for that person. Each form says
// what becomes public before it is switched on; the hub decides the rest.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // The namespace owner, a human (§16.9): the owner, or an owner of the
  // organisation that owns the project. Someone else's handle has no organisation
  // to read: not_found, and so no form.
  async function ownsNamespace(ctx) {
    if (ctx.me.kind !== "human") return false;
    const owner = ctx.project.owner || {};
    if (owner.id === ctx.me.id) return true;
    try {
      const org = await M.api.get("/orgs/" + encodeURIComponent(owner.handle));
      return !!org && org.my_role === "owner";
    } catch (err) {
      return false;
    }
  }

  // save: the Settings panel's, which draws it again from the hub's answer.
  function projectForm(ctx, save) {
    const p = ctx.project;
    const on = p.public_page === "on";
    const box = h("input", { type: "checkbox", id: "public-page" });
    box.checked = on;
    const about = h("textarea", { id: "public-about", rows: "6", "aria-describedby": "public-about-error" });
    about.value = p.public_about || "";
    const error = h("p", { class: "field-error", id: "public-about-error", role: "alert" });
    const served = on && p.state !== "archived" && !p.moderation;
    const atFields = (err) => {
      const said = err && err.details && err.details.fields && err.details.fields.public_about;
      if (!said) return false;
      error.textContent = said === "too_long" ? M.t("public_page.about.too_long") : M.t("public_page.about.refused", { reason: said });
      return true;
    };
    return h("form", {
      class: "inline-form public-page-form",
      onsubmit: (e) => {
        e.preventDefault();
        error.textContent = "";
        const body = {};
        if ((box.checked ? "on" : "off") !== (p.public_page || "off")) body.public_page = box.checked ? "on" : "off";
        if (about.value !== (p.public_about || "")) body.public_about = about.value || null;
        if (Object.keys(body).length) save(body, M.t("public_page.title"), atFields);
      },
    },
    h("h2", { class: "panel-title" }, M.t("public_page.title")),
    h("p", { class: "hint" }, M.t("public_page.hint")),
    h("p", { class: "hint" }, M.t("public_page.never")),
    p.policy && !p.policy.agent_owners ? h("p", { class: "hint public-page-owners" }, M.t("public_page.agent_owners")) : null,
    h("label", { class: "check", for: "public-page" }, box, " ", M.t("public_page.switch")),
    h("label", { for: "public-about" }, M.t("public_page.about")), about, error,
    h("button", { type: "submit" }, M.t("board.save")),
    served ? h("p", { class: "public-page-link" },
      h("a", { href: "/" + M.api.projectPath(p.full_name) + "?as=public", target: "_blank", rel: "noopener" }, M.t("public_page.view")),
      " ", h("span", { class: "muted" }, M.t("public_page.view_hint"))) : null);
  }

  // Beside a form that is always drawn: the slot fills when the owner is known.
  function projectPart(ctx, save) {
    const slot = h("div", { class: "public-page-slot" });
    ownsNamespace(ctx).then((yes) => { if (yes) append(slot, projectForm(ctx, save)); });
    return slot;
  }

  // Account: the person's page, and through it their agents' (§16.9).
  async function profileSection(ctx) {
    if (ctx.me.kind !== "human") return null;
    const status = M.statusLine();
    const box = h("input", { type: "checkbox", id: "public-profile" });
    const bio = h("textarea", { id: "public-bio", rows: "3", maxlength: "280", "aria-describedby": "public-bio-error" });
    const error = h("p", { class: "field-error", id: "public-bio-error", role: "alert" });
    const link = h("p", { class: "public-profile-link" });
    async function showLink() {
      clear(link);
      let person = null;
      try { person = await M.api.get("/people/" + encodeURIComponent(ctx.me.handle)); } catch (err) { person = null; }
      // page_served: the hub serves it now, with the instance's own switch counted.
      if (person && person.page_served) append(link, h("a", { href: "/" + encodeURIComponent(ctx.me.handle) + "?as=public", target: "_blank", rel: "noopener" }, M.t("public_page.view")));
    }
    function show() {
      box.checked = !!ctx.me.public_profile;
      bio.value = ctx.me.public_bio || "";
    }
    const form = h("form", {
      class: "inline-form public-profile-form",
      onsubmit: async (e) => {
        e.preventDefault();
        error.textContent = "";
        const body = {};
        if (box.checked !== !!ctx.me.public_profile) body.public_profile = box.checked;
        if (bio.value !== (ctx.me.public_bio || "")) body.public_bio = bio.value || null;
        if (!Object.keys(body).length) return;
        status.busy(M.t("meat.saving"));
        try {
          const answer = await M.api.patch("/me", body);
          const member = (answer && answer.member) || {};
          ["public_profile", "public_bio"].forEach((k) => { if (k in member) ctx.me[k] = member[k]; });
          show();
          await showLink();
          status.done();
          append(status.el, h("span", { class: "ok" }, M.t("public_profile.saved")));
        } catch (err) {
          const said = err && err.details && err.details.fields && err.details.fields.public_bio;
          if (said) error.textContent = M.t("public_profile.bio.refused", { reason: said });
          status.fail(M.t("meat.not_saved"), err);
        }
      },
    },
    h("h3", null, M.t("public_profile.title")),
    h("p", { class: "hint" }, M.t("public_profile.hint")),
    h("label", { class: "check", for: "public-profile" }, box, " ", M.t("public_profile.switch")),
    h("label", { for: "public-bio" }, M.t("public_profile.bio")), bio, error,
    h("button", { type: "submit" }, M.t("board.save")), status.el, link);
    show();
    await showLink();
    return { el: form };
  }

  M.publicPage = { projectPart, profileSection };
})(window.Maity);
