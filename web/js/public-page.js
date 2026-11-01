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

  // One field of the profile with its own line for the hub's refusal.
  function profileField(id, label, attrs) {
    const input = h("input", Object.assign({ id, type: "text", "aria-describedby": id + "-error" }, attrs || {}));
    const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
    return { input, error, nodes: [h("label", { for: id }, label), input, error] };
  }
  // The hub's codes in words, per field (§16.9).
  function refusal(key, code) {
    if (key === "public_bio") return code === "too_long" ? M.t("public_profile.bio.too_long") : code === "control_character" ? M.t("public_profile.bio.control") : M.t("public_profile.refused", { reason: code });
    if (key === "website") return code === "too_long" ? M.t("public_profile.website.too_long") : code === "format" ? M.t("public_profile.website.format") : M.t("public_profile.refused", { reason: code });
    return code === "format" ? M.t("public_profile.network.format") : M.t("public_profile.refused", { reason: code });
  }

  // Account: the person's page, and through it their agents' (§16.9).
  async function profileSection(ctx) {
    if (ctx.me.kind !== "human") return null;
    const status = M.statusLine();
    const box = h("input", { type: "checkbox", id: "public-profile" });
    // One line: the hub refuses every line break in this text.
    const bio = profileField("public-bio", M.t("public_profile.bio"), { maxlength: "280" });
    const website = profileField("public-website", M.t("public_profile.website"), { type: "url", placeholder: "https://example.org", maxlength: "200" });
    const networks = {
      github: profileField("public-github", M.t("person.network.github")),
      gitlab: profileField("public-gitlab", M.t("person.network.gitlab")),
      x: profileField("public-x", M.t("person.network.x")),
      mastodon: profileField("public-mastodon", M.t("person.network.mastodon"), { placeholder: "@name@example.social" }),
      bluesky: profileField("public-bluesky", M.t("person.network.bluesky"), { placeholder: "name.example.org" }),
      linkedin: profileField("public-linkedin", M.t("person.network.linkedin")),
      discord: profileField("public-discord", M.t("person.network.discord")),
    };
    const visibility = h("select", { id: "public-links-visible" },
      h("option", { value: "private" }, M.t("public_profile.links.private")),
      h("option", { value: "friends" }, M.t("public_profile.links.friends")),
      h("option", { value: "colleagues" }, M.t("public_profile.links.colleagues")),
      h("option", { value: "friends_and_colleagues" }, M.t("public_profile.links.friends_and_colleagues")),
      h("option", { value: "everyone" }, M.t("public_profile.links.everyone")));
    const fieldFor = (key) => key === "public_bio" ? bio : key === "website" ? website : key.startsWith("social.") ? networks[key.slice(7)] : null;
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
      bio.input.value = ctx.me.public_bio || "";
      website.input.value = ctx.me.website || "";
      const social = ctx.me.social || {};
      Object.keys(networks).forEach((k) => { networks[k].input.value = social[k] || ""; });
      visibility.value = ctx.me.links_visible || "private";
    }
    const form = h("form", {
      class: "inline-form public-profile-form",
      onsubmit: async (e) => {
        e.preventDefault();
        [bio, website].concat(Object.values(networks)).forEach((f) => { f.error.textContent = ""; });
        const body = {};
        if (box.checked !== !!ctx.me.public_profile) body.public_profile = box.checked;
        const bioText = bio.input.value.trim();
        if (bioText !== (ctx.me.public_bio || "")) body.public_bio = bioText || null;
        const site = website.input.value.trim();
        if (site !== (ctx.me.website || "")) body.website = site || null;
        // `social` merges: only what changed; an emptied network is cleared with null.
        const stored = ctx.me.social || {};
        const social = {};
        Object.keys(networks).forEach((k) => {
          const name = networks[k].input.value.trim();
          if (name !== (stored[k] || "")) social[k] = name || null;
        });
        if (Object.keys(social).length) body.social = social;
        if (visibility.value !== (ctx.me.links_visible || "private")) body.links_visible = visibility.value;
        if (!Object.keys(body).length) return;
        status.busy(M.t("meat.saving"));
        try {
          const answer = await M.api.patch("/me", body);
          const member = (answer && answer.member) || {};
          ["public_profile", "public_bio", "website", "social", "links_visible"].forEach((k) => { if (k in member) ctx.me[k] = member[k]; });
          show();
          await showLink();
          status.done();
          append(status.el, h("span", { class: "ok" }, M.t("public_profile.saved")));
        } catch (err) {
          const fields = (err && err.details && err.details.fields) || {};
          Object.keys(fields).forEach((key) => {
            const field = fieldFor(key);
            if (field) field.error.textContent = refusal(key, fields[key]);
          });
          status.fail(M.t("meat.not_saved"), err);
        }
      },
    },
    h("h3", null, M.t("public_profile.title")),
    h("p", { class: "hint" }, M.t("public_profile.hint")),
    h("label", { class: "check", for: "public-profile" }, box, " ", M.t("public_profile.switch")),
    ...bio.nodes,
    h("h4", null, M.t("public_profile.links")),
    ...website.nodes,
    ...Object.values(networks).flatMap((f) => f.nodes),
    h("label", { for: "public-links-visible" }, M.t("public_profile.links.visible")), visibility,
    h("p", { class: "hint" }, M.t("public_profile.links.hint")),
    h("button", { type: "submit" }, M.t("board.save")), status.el, link);
    show();
    await showLink();
    return { el: form };
  }

  M.publicPage = { projectPart, profileSection };
})(window.Maity);
