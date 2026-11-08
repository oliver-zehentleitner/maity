// The signed-in human's account (/account), in tabs (tsk-3banvfzv3nvs): Profile (who they are,
// their picture, docs/api.md §6.10, the public profile, the meat proxy), Settings
// (/account/settings: preferences, js/preferences.js, the languages, the theme), Notifications
// (/account/notifications, js/notify-settings.js), Security (/account/security and its own tabs:
// the password, §2.1, and the second factor, sessions, another device, forge access, your data)
// and Organisations (/account/orgs, js/orgs.js). A password change ends every other session of
// this human; this one stays signed in.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // The hub's minimum, counted in characters as the hub counts them.
  const MIN_LENGTH = 12;

  const { sniffImage, IMAGE_MAX } = M.dom;
  // Getters: the words are the catalog's when shown.
  const SOURCE_WORDS = {
    get uploaded() { return M.t("picture.source.uploaded"); },
    get forge() { return M.t("picture.source.forge"); },
    get motif() { return M.t("picture.source.motif"); },
  };
  // A theme's heading (§6.10): the catalog's where it has one, else its name.
  const THEME_WORDS = {
    get classic() { return M.t("avatar.motif.theme.classic"); },
    get office() { return M.t("avatar.motif.theme.office"); },
  };
  // The hub's refusals of an upload (§6.10), in words.
  const REFUSED = {
    get unsupported_type() { return M.t("picture.refused.type"); },
    get too_large() { return M.t("picture.refused.too_large"); },
    get dimensions() { return M.t("picture.refused.dimensions"); },
    get undecodable() { return M.t("picture.refused.undecodable"); },
  };
  function refusal(err, own) {
    const why = err.code === "invalid" && err.details && err.details.fields && err.details.fields.body;
    if (why) return { message: Object.hasOwn(REFUSED, why) ? REFUSED[why] : why };
    if (err.code === "rate_limited") return { message: M.t("picture.refused.rate") };
    if (err.code === "not_found" && !own) return { message: M.t("picture.refused.not_yours") };
    return err;
  }

  // The motifs an agent may show (§6.10, "An agent's motif"), read once until the page reloads.
  let motifList = null;
  const motifs = () => {
    motifList = motifList || M.api.get("/avatars/motifs").then((r) => r.motifs || [], (err) => { motifList = null; throw err; });
    return motifList;
  };

  // An agent's motif: chosen by its owner with PATCH /agents/{id} (§6.3), or
  // cleared; it shows while the agent has no upload. who and done as in the
  // picture editor below.
  function motifPicker(who, path, status, done) {
    const id = "avatar-motif-" + who.id;
    const slot = h("div", { class: "picture-motif field-stack" },
      h("p", { class: "muted" }, M.t("picture.motif.reading")));
    motifs().then((list) => {
      if (!list.length) { append(clear(slot), h("p", { class: "muted" }, M.t("picture.motif.none_served"))); return; }
      const themes = [];
      list.forEach((x) => { if (!themes.includes(x.theme)) themes.push(x.theme); });
      const select = h("select", { id },
        h("option", { value: "" }, M.t("picture.motif.generated")),
        themes.map((theme) => h("optgroup", { label: Object.hasOwn(THEME_WORDS, theme) ? THEME_WORDS[theme] : theme },
          list.filter((x) => x.theme === theme).map((x) => h("option", { value: x.name }, x.label)))));
      select.value = list.some((x) => x.name === who.avatar_motif) ? who.avatar_motif : "";
      const preview = h("span", { class: "picture-motif-preview" });
      const show = () => {
        const motif = list.find((x) => x.name === select.value);
        clear(preview);
        if (!motif) return;
        try {
          append(preview, h("img", { class: "avatar-img", src: motif.url, alt: motif.alt, width: "64", height: "64" }));
        } catch (refused) {
          // not an address the page may load: no preview, the choice stays possible
        }
      };
      show();
      select.addEventListener("change", show);
      const save = h("button", { type: "button" }, M.t("picture.motif.save"));
      save.addEventListener("click", async () => {
        const name = select.value || null;
        if (name === (who.avatar_motif || null)) { status.done(); append(status.el, h("span", { class: "ok" }, M.t("picture.motif.unchanged"))); return; }
        save.disabled = true;
        status.busy(M.t("picture.motif.saving"));
        try {
          const answer = await M.api.patch(path, { avatar_motif: name });
          who.avatar_motif = answer.avatar_motif === undefined ? name : answer.avatar_motif;
          const words = !name ? M.t("picture.motif.cleared")
            : answer.avatar_source === "uploaded" ? M.t("picture.motif.chosen_behind_upload") : M.t("picture.motif.chosen");
          done({ avatar_url: answer.avatar_url, avatar_source: answer.avatar_source, avatar_motif: who.avatar_motif }, words);
        } catch (err) {
          status.fail(M.t("picture.motif.not_saved"), motifRefusal(err));
        } finally {
          save.disabled = false;
        }
      });
      append(clear(slot),
        h("label", { for: id }, M.t("picture.motif.label", { name: who.display_name })),
        h("div", { class: "picture-motif-choice" }, select, preview),
        h("p", { class: "hint" }, M.t("picture.motif.hint")),
        h("div", { class: "actions" }, save));
    }, (err) => append(clear(slot), h("p", { class: "send-status failed" }, M.t("picture.motif.unreadable", { reason: err.message }))));
    return slot;
  }
  // The hub's refusals of a motif (§6.10, §16.8), in words.
  function motifRefusal(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields && fields.avatar_motif === "unknown") return { message: M.t("picture.motif.refused.unknown") };
    if (err.code === "forbidden" && err.details && err.details.reason === "moderation_hold") return { message: M.t("picture.motif.refused.held") };
    if (err.code === "rate_limited") return { message: M.t("picture.refused.rate") };
    return err;
  }

  // Names in a sentence: "a, b, c" in English, in the catalog's language.
  const names = (list) => M.fmt.list(list);

  // One picture and its controls: what shows now, where it comes from, an
  // upload and, for an upload, Remove. who: { id, display_name,
  // avatar_url, avatar_source }; path: the PUT/DELETE endpoint; changed
  // gets the hub's answer, { avatar_url, avatar_source }.
  function pictureEditor(who, path, own, changed) {
    const status = M.statusLine();
    const id = "avatar-file-" + who.id;
    const input = h("input", { id, type: "file", accept: "image/png,image/jpeg,image/webp" });
    const done = (answer, words) => {
      who.avatar_url = answer.avatar_url;
      who.avatar_source = answer.avatar_source;
      if ("avatar_motif" in answer) who.avatar_motif = answer.avatar_motif;
      changed(answer, words);
    };
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const stop = (message) => { status.fail(M.t("picture.not_uploaded"), { message }); input.value = ""; };
      if (file.size > IMAGE_MAX) { stop(M.t("picture.refused.too_large")); return; }
      const type = await sniffImage(file);
      if (!type) { stop(M.t("picture.refused.type")); return; }
      input.disabled = true;
      status.busy(own ? M.t("picture.uploading_own") : M.t("picture.uploading", { name: who.display_name }));
      try {
        done(await M.api.putImage(path, file, type), M.t("picture.uploaded"));
      } catch (err) {
        status.fail(M.t("picture.not_uploaded"), refusal(err, own));
        input.value = "";
      } finally {
        input.disabled = false;
      }
    });
    const remove = who.avatar_source === "uploaded" ? h("button", {
      type: "button",
      onclick: async () => {
        remove.disabled = true;
        status.busy(M.t("picture.removing"));
        try {
          const answer = await M.api.del(path);
          done(answer, answer.avatar_source === "forge" ? M.t("picture.removed_forge")
            : answer.avatar_source === "motif" ? M.t("picture.removed_motif") : M.t("picture.removed_generated"));
        } catch (err) {
          status.fail(M.t("picture.not_removed"), refusal(err, own));
          remove.disabled = false;
        }
      },
    }, M.t("picture.remove")) : null;
    return h("div", { class: "picture" },
      h("div", { class: "picture-now" }, M.avatar(who, 64),
        h("p", { class: "muted" }, Object.hasOwn(SOURCE_WORDS, who.avatar_source) ? SOURCE_WORDS[who.avatar_source] : M.t("picture.source.generated"))),
      h("div", { class: "picture-controls field-stack" },
        h("label", { for: id }, own ? M.t("picture.upload_own") : M.t("picture.upload_for", { name: who.display_name })),
        input,
        h("p", { class: "hint" }, M.t("picture.hint")),
        h("div", { class: "actions" }, remove),
        // An agent's motif (§6.10): its owner's choice here; a human has none.
        !own && /^agt-/.test(who.id || "") ? motifPicker(who, "/agents/" + encodeURIComponent(who.id), status, done) : null,
        status.el));
  }

  // Members opens one's own agent with its picture (tsk-th1yq0jtk3yf).
  M.pictureEditor = pictureEditor;

  // Deleting one's own agent profile (docs/api.md §6.3), confirmed by typing
  // its handle. A profile that is still a member somewhere is deleted with
  // ?cascade=true, which ends those memberships; the projects are named first.
  // who: the profile as GET /agents has it; done(tombstone, words).
  function profileDelete(who, done) {
    const status = M.statusLine();
    const id = "profile-delete-" + who.id;
    const where = (who.memberships || []).map((x) => x.project);
    const typed = h("input", { id, autocomplete: "off", spellcheck: "false", placeholder: "@" + who.handle });
    const go = h("button", { type: "submit", class: "danger" }, M.t("profile_delete.submit"));
    // One deletion at a time, and only for the handle as it is typed now: the
    // field is locked while the call runs, and the button follows the field.
    let busy = false;
    const confirmed = () => typed.value.trim().replace(/^@/, "") === who.handle;
    const settle = () => { go.disabled = busy || !confirmed(); };
    settle();
    typed.addEventListener("input", settle);
    const form = h("form", {
      class: "profile-delete inline-form",
      onsubmit: async (e) => {
        e.preventDefault();
        if (busy || !confirmed()) return;
        busy = true;
        typed.disabled = true;
        settle();
        status.busy(M.t("profile_delete.busy"));
        try {
          const answer = await M.api.del("/agents/" + encodeURIComponent(who.id) + (where.length ? "?cascade=true" : ""));
          status.done();
          done(answer, where.length ? M.t("profile_delete.done_ended", { handle: who.handle }) : M.t("profile_delete.done", { handle: who.handle }));
        } catch (err) {
          busy = false;
          typed.disabled = false;
          settle();
          const inUse = err.code === "profile_in_use" && err.details && err.details.memberships;
          status.fail(M.t("profile_delete.failed"), inUse ? { message: M.t("profile_delete.in_use", { projects: names(err.details.memberships.map((x) => x.project)) }) } : err);
        }
      },
    },
    h("label", { for: id }, M.t("profile_delete.type", { handle: who.handle })), typed, go, status.el);
    return h("div", { class: "profile-delete-box" },
      h("h4", { class: "profile-delete-title" }, M.t("profile_delete.title")),
      h("p", { class: "hint" }, where.length ? M.t("profile_delete.hint_member", { projects: names(where) }) : M.t("profile_delete.hint_none")),
      form);
  }
  M.profileDelete = profileDelete;
  // §5.2 "Meat proxy": the human's own switch (PATCH /me) with its two
  // parts under it, each a sentence the person says about themselves. The
  // hub stores the parts; the switch is on while one of them is. Switching
  // on sends `meat_proxy: true`, which ticks both; off, `false`, which
  // clears both; a part alone sends only that part, so ticking one while
  // off turns the mode on with it, and clearing the last turns it off.
  // The hub's note (member.meat_proxy_note, §2) stands under the parts as
  // /me and each answer carry it — what agents read now, or would read
  // once it is on — never a copy of the page's own.
  const MEAT_PARTS = [
    ["meat_proxy_lead", "meat-proxy-lead", () => M.t("meat.part.lead")],
    ["meat_proxy_hands", "meat-proxy-hands", () => M.t("meat.part.hands")],
  ];
  async function meatProxySection(ctx) {
    if (ctx.me.kind !== "human") return null;
    const status = M.statusLine();
    const box = h("input", { type: "checkbox", id: "meat-proxy", "aria-describedby": "meat-proxy-hint" });
    const parts = MEAT_PARTS.map(([field, id]) => [field, h("input", { type: "checkbox", id })]);
    const hint = h("p", { class: "hint", id: "meat-proxy-hint" });
    const quote = h("div");
    const inputs = [box].concat(parts.map(([, input]) => input));
    // The switch, its parts and the note as the hub last said them.
    function show() {
      box.checked = !!ctx.me.meat_proxy;
      parts.forEach(([field, input]) => { input.checked = !!ctx.me[field]; });
      hint.textContent = ctx.me.meat_proxy ? M.t("meat.hint.on") : M.t("meat.hint.off");
      // GET /me carries the note always, off too: what switching on would send (§5.2).
      append(clear(quote), h("blockquote", { class: "meat-proxy-note", id: "meat-proxy-note" }, h("p", null, ctx.me.meat_proxy_note)));
      box.setAttribute("aria-describedby", "meat-proxy-hint meat-proxy-note");
    }
    async function send(body) {
      inputs.forEach((x) => { x.disabled = true; });
      status.busy(M.t("meat.saving"));
      try {
        // The answer is /me itself (§5.1), its member as GET /me has it.
        const answer = await M.api.patch("/me", body);
        const member = answer && answer.member;
        ["meat_proxy", "meat_proxy_note"].concat(MEAT_PARTS.map(([field]) => field)).forEach((k) => {
          if (member && k in member) ctx.me[k] = member[k];
        });
        show();
        status.done();
        append(status.el, h("span", { class: "ok" }, ctx.me.meat_proxy
          ? M.t("meat.saved.on_note")
          : M.t("meat.saved.off")));
      } catch (err) {
        show();
        status.fail(M.t("meat.not_saved"), err);
      } finally {
        inputs.forEach((x) => { x.disabled = false; });
      }
    }
    box.addEventListener("change", () => send({ meat_proxy: box.checked }));
    parts.forEach(([field, input]) => input.addEventListener("change", () => send({ [field]: input.checked })));
    show();
    return h("section", { class: "meat-proxy" },
      h("h3", null, M.t("meat.title")),
      h("label", { class: "check", for: "meat-proxy" }, box, " ", M.t("meat.switch")),
      h("fieldset", { class: "meat-proxy-parts" }, h("legend", { class: "visually-hidden" }, M.t("meat.parts")),
        MEAT_PARTS.map(([, id, sentence], i) => h("label", { class: "check", for: id }, parts[i][1], " ", sentence()))),
      hint, quote, status.el);
  }

  // Set by a change; the next drawing of the view says it.
  let pictureNote = null;

  // The account's tabs (tsk-3banvfzv3nvs): one settings page whose tabs are the profile menu's
  // entries, each at an address of its own; the menu is drawn from this list too. Security and
  // Organisations are a human's alone, as in the menu before; Linked accounts is to come, shown
  // without an address. Security has tabs of its own.
  const TABS = [
    { key: "profile", path: "/account", label: () => M.t("menu.profile") },
    { key: "settings", path: "/account/settings", label: () => M.t("menu.settings") },
    { key: "notifications", path: "/account/notifications", label: () => M.t("menu.notifications") },
    { key: "security", path: "/account/security", label: () => M.t("menu.security"), human: true },
    { key: "orgs", path: "/account/orgs", label: () => M.t("menu.orgs"), human: true },
    { key: "linked", label: () => M.t("menu.linked_accounts"), later: true },
  ];
  const SECURITY = [
    { key: "sign-in", path: "/account/security", label: () => M.t("account.security.sign_in") },
    { key: "sessions", path: "/account/security/sessions", label: () => M.t("account.security.sessions") },
    { key: "device", path: "/account/security/device", label: () => M.t("account.security.device") },
    { key: "forge", path: "/account/security/forge", label: () => M.t("account.security.forge") },
    { key: "data", path: "/account/security/data", label: () => M.t("account.security.data") },
  ];
  // The addresses of the one long page before the tabs, and the hub's (mails, the bell, the
  // forge's setup redirect, §11.4): each to its tab, the heading of its part focused there.
  // `/settings/forge` arrives here as ["forge"] too (js/app.js parseRoute), but is no old address:
  // the contract names it as the setup's return (§16.11), so it shows Forge access itself.
  const MOVED = {
    picture: ["/account", "picture"],
    preferences: ["/account/settings", "preferences"],
    theme: ["/account/settings", "theme"],
    password: ["/account/security", "password"],
    sessions: ["/account/security/sessions", "sessions"],
    "sign-in-device": ["/account/security/device", "device"],
    forge: ["/account/security/forge", "forge"],
    data: ["/account/security/data", "data"],
  };
  // The heading a moved address asked for, focused once its tab is drawn.
  let wantedHeading = null;

  const shownTabs = (ctx) => TABS.filter((t) => !t.human || ctx.me.kind === "human");
  // The profile menu's entries: the tabs, Linked accounts greyed (js/app.js).
  const menuItems = (ctx) => shownTabs(ctx).map((t) => (t.later
    ? { label: t.label(), disabled: true, why: M.t("menu.later") }
    : { label: t.label(), href: t.path, current: ctx.scope === "orgs" ? t.key === "orgs" : null }));

  // A row of tabs: links, the current one marked; one to come greyed, with no address. It scrolls
  // sideways where it is wider than the window, the current tab in sight: js/app.js sets that up
  // once the view is in the page (a row not yet in it has no width).
  function tabRow(list, chosen, label, extra) {
    const nav = h("nav", { class: "view-tabs account-tabs" + (extra ? " " + extra : ""), "aria-label": label },
      list.map((t) => (t.later
        ? h("span", { class: "view-tab later", "aria-disabled": "true", title: M.t("menu.later") }, t.label())
        : h("a", { href: t.path, class: "view-tab", "aria-current": t.key === chosen ? "page" : null }, t.label()))));
    return nav;
  }
  // What stands on every tab: the page's heading and the tab row.
  const head = (ctx, chosen) => [h("h2", null, M.t("account.title")), tabRow(shownTabs(ctx), chosen, M.t("account.tabs.label"))];

  // The password form (§2.1, POST /auth/password), on Security's Sign-in.
  function passwordPart() {
    const field = (id, label, autocomplete, hint) => {
      const input = h("input", { id, type: "password", autocomplete, required: true, "aria-describedby": id + "-error" });
      const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
      return { input, error, nodes: [h("label", { for: id }, label), input, hint ? h("p", { class: "hint" }, hint) : null, error] };
    };
    const atLeast = () => M.t("password.at_least", { count: MIN_LENGTH });
    const current = field("password-current", M.t("password.current"), "current-password");
    const fresh = field("password-new", M.t("password.new"), "new-password", atLeast());
    const repeat = field("password-repeat", M.t("password.repeat"), "new-password");
    const all = [current, fresh, repeat];
    const status = M.statusLine();

    const showErrors = (errors) => {
      all.forEach((f) => { f.error.textContent = ""; f.input.removeAttribute("aria-invalid"); });
      errors.forEach(([f, text]) => { f.error.textContent = text; f.input.setAttribute("aria-invalid", "true"); });
      if (errors.length) errors[0][0].input.focus();
    };

    const submit = h("button", { type: "submit" }, M.t("password.submit"));
    const form = h("form", {
      class: "project-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const errors = [];
        if (!current.input.value) errors.push([current, M.t("password.required")]);
        if ([...fresh.input.value].length < MIN_LENGTH) errors.push([fresh, atLeast()]);
        else if (fresh.input.value !== repeat.input.value) errors.push([repeat, M.t("password.differ")]);
        showErrors(errors);
        if (errors.length) { status.done(); return; }
        submit.disabled = true;
        status.busy(M.t("password.changing"));
        // The change ends every session but this one; the held long-poll goes
        // first, so that it never meets the change (§2.1, §18.2).
        M.notify.halt();
        try {
          await M.api.post("/auth/password", { current: current.input.value, new: fresh.input.value });
          all.forEach((f) => { f.input.value = ""; });
          status.done();
          append(status.el, h("span", { class: "ok" }, M.t("password.changed")));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields ? err.details.fields : null;
          if (fields && (fields.current || fields.new)) {
            showErrors([
              fields.current ? [current, fields.current === "mismatch" ? M.t("password.mismatch") : String(fields.current)] : null,
              fields.new ? [fresh, fields.new === "too_short" ? atLeast() : String(fields.new)] : null,
            ].filter(Boolean));
            status.done();
          } else if (err.code === "rate_limited") {
            status.fail(M.t("password.not_changed"), { message: M.t("password.rate") });
          } else {
            status.fail(M.t("password.not_changed"), err);
          }
        } finally {
          // This session stays (or the change was refused): the stream goes on.
          M.notify.resume();
          submit.disabled = false;
        }
      },
    }, current.nodes, fresh.nodes, repeat.nodes, submit, status.el);
    const heading = h("h3", { id: "password-heading", tabindex: "-1" }, M.t("password.title"));
    return { el: [heading, h("p", { class: "muted" }, M.t("password.hint")), form], heading };
  }

  // Profile: who one is, the picture, the public profile, the meat proxy.
  async function profileTab(ctx, root) {
    // A changed picture redraws the whole page: the header's own picture
    // and /me come back with the hub's new avatar_url.
    const changed = (answer, words) => { pictureNote = words; ctx.refresh(); };
    const pictureHeading = h("h3", { class: "picture-heading", tabindex: "-1" }, M.t("account.picture"));
    const note = pictureNote ? h("p", { class: "ok", role: "status" }, pictureNote) : null;
    pictureNote = null;
    const meatProxy = await meatProxySection(ctx);
    const publicProfile = M.publicPage ? await M.publicPage.profileSection(ctx) : null;
    append(root,
      h("dl", { class: "facts" },
        h("dt", null, M.t("account.name")), h("dd", null, ctx.me.display_name),
        h("dt", null, M.t("account.handle")), h("dd", null, "@" + ctx.me.handle)),
      // Directly under the name and handle: one's public page, while the hub serves it.
      publicProfile ? publicProfile.link : null,
      M.handles.editor(ctx.me, "/me", M.t("handles.what_own"), changed),
      pictureHeading,
      h("p", { class: "muted" }, M.t("account.picture_hint")),
      note,
      pictureEditor(ctx.me, "/me/avatar", true, changed),
      // The agents' pictures, names and deletion are on the Agents page
      // (/agents, js/agents-page.js): one place for one's agents.
      h("p", { class: "muted" }, M.tn("account.agents_hint", { link: h("a", { href: "/agents" }, M.t("account.agents_link")) })),
      meatProxy,
      publicProfile ? publicProfile.el : null);
    return { picture: pictureHeading };
  }

  // Settings: one's preferences, the languages, the theme.
  async function settingsTab(ctx, root) {
    const preferences = M.preferences ? await M.preferences.section(ctx) : null;
    const language = M.notifySettings ? await M.notifySettings(ctx, "language") : null;
    // The theme (js/theme.js): signed in, it is chosen here, not in the
    // header (the maintainer's instruction). Per browser, as before: what
    // was picked while signed out stays until it is changed here.
    const themeHeading = h("h3", { id: "theme-heading", tabindex: "-1" }, M.t("account.theme"));
    const themeBox = M.theme ? h("fieldset", { class: "theme-choice", "aria-labelledby": "theme-heading" },
      M.theme.THEMES.map((t) => {
        const input = h("input", { type: "radio", name: "theme", id: "theme-" + t, value: t });
        input.checked = t === M.theme.get();
        input.addEventListener("change", () => { if (input.checked) M.theme.set(t); });
        return h("label", { class: "check", for: "theme-" + t }, input, " " + ((M.THEME_WORDS || {})[t] || t));
      })) : null;
    append(root,
      preferences ? preferences.el : null,
      language ? language.el : null,
      themeBox ? [themeHeading, h("p", { class: "muted" }, M.t("account.theme_hint")), themeBox] : null);
    return { preferences: preferences && preferences.heading, theme: themeBox && themeHeading };
  }

  // Notifications: mail, when it goes out, agents that stop listening, the browser's.
  async function notificationsTab(ctx, root) {
    const notify = M.notifySettings ? await M.notifySettings(ctx, "notifications") : null;
    if (notify) append(root, notify.el);
    return { notifications: notify && notify.heading };
  }

  // Security, with tabs of its own: sign-in, sessions, another device, forge access, your data.
  async function securityTab(ctx, root, sub) {
    const chosen = SECURITY.find((t) => t.key === sub) || SECURITY[0];
    append(root, tabRow(SECURITY, chosen.key, M.t("account.security.tabs.label"), "security-tabs"));
    if (chosen.key === "device") {
      const device = M.deviceSignIn ? await M.deviceSignIn.anotherDevice(ctx, root) : null;
      return { device: device && device.heading };
    }
    if (chosen.key === "sessions") {
      const sessions = M.sessions ? await M.sessions.section(ctx) : null;
      if (sessions) append(root, sessions.el);
      return { sessions: sessions && sessions.heading };
    }
    if (chosen.key === "forge") {
      // Forge access (§11.4): the grants one's projects read their repositories with.
      const forge = M.forge ? await M.forge.section(ctx) : null;
      if (forge) append(root, forge.el);
      return { forge: forge && forge.heading };
    }
    if (chosen.key === "data") {
      // Your data (§2.9): the export and the deletion of the account.
      const yourData = M.yourData ? await M.yourData.section(ctx) : null;
      if (yourData) append(root, yourData.el);
      return { data: yourData && yourData.heading };
    }
    // The second factor first: the hub's mail and bell item about it link to /account/security
    // (hub notifications), so it is what that address shows at the top.
    const password = passwordPart();
    const security = M.security ? await M.security.section() : null;
    append(root, security ? security.el : null, password.el);
    return { password: password.heading, security: security && security.heading };
  }

  M.views.account = async function (ctx, root, args) {
    if (M.route.current().path === "/settings/forge") args = ["security", "forge"];
    const first = (args && args[0]) || "";
    // An address of the long page before the tabs, or the hub's: to its tab, in place of it in
    // the history; the view is drawn again there. One the page does not know: the profile.
    const moved = Object.hasOwn(MOVED, first) ? MOVED[first] : null;
    const tab = TABS.find((t) => !t.later && t.key !== "orgs" && t.path === "/account/" + first);
    const known = !first || (tab && (first === "security" ? !args[1] || SECURITY.some((t) => t.key === args[1] && t.key !== "sign-in") : !args[1]));
    if (moved || !known || (tab && tab.human && ctx.me.kind !== "human")) {
      // The query goes along: the forge's setup redirect says a failure in it (js/forge.js).
      const query = M.route.current().query.toString();
      // An unknown tab of Security leads to Security, any other unknown address to the profile.
      const back = first === "security" && ctx.me.kind === "human" ? "/account/security" : "/account";
      const to = (moved ? moved[0] : back) + (query ? "?" + query : "");
      wantedHeading = moved ? moved[1] : null;
      if (M.route.go(to, { replace: true })) return;
    }
    const chosen = first ? first : "profile";
    append(root, head(ctx, chosen));
    let headings = {};
    if (chosen === "profile") headings = await profileTab(ctx, root);
    else if (chosen === "settings") headings = await settingsTab(ctx, root);
    else if (chosen === "notifications") headings = await notificationsTab(ctx, root);
    else if (chosen === "security") headings = await securityTab(ctx, root, args[1]);
    // The part a moved address asked for starts in sight, its heading focused. The view is put in
    // the page when this returns (js/app.js), before the timeout runs, so the focus holds.
    const wanted = wantedHeading;
    wantedHeading = null;
    const heading = wanted && headings[wanted];
    if (heading) window.setTimeout(() => heading.focus(), 0);
  };
  M.accountTabs = { head, menuItems };
})(window.Maity);
