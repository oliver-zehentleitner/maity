// The signed-in human's account (/account): who they are, their picture
// (/account/picture, docs/api.md §6.10; their agents' are on /agents), their
// preferences (/account/preferences, js/preferences.js), your data
// (/account/data, js/your-data.js), and
// changing the password (§2.1, POST /auth/password). A password change
// ends every other session of this human; this one stays signed in.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // The hub's minimum, counted in characters as the hub counts them.
  const MIN_LENGTH = 12;

  const { sniffImage, IMAGE_MAX } = M.dom;
  const SOURCE_WORDS = {
    uploaded: "Uploaded.",
    forge: "From the linked forge account.",
  };
  // The hub's refusals of an upload (§6.10), in words.
  const REFUSED = {
    unsupported_type: "not a PNG, JPEG or WebP image",
    too_large: "larger than 1 MiB",
    dimensions: "more than 4096 pixels on a side",
    undecodable: "the image could not be read",
  };
  function refusal(err, own) {
    const why = err.code === "invalid" && err.details && err.details.fields && err.details.fields.body;
    if (why) return { message: REFUSED[why] || why };
    if (err.code === "rate_limited") return { message: "too many changes of this picture in the last hour, or the hub is busy; try again later" };
    if (err.code === "not_found" && !own) return { message: "this profile is not yours" };
    return err;
  }

  // One picture and its controls: what shows now, where it comes from, an
  // upload and, for an upload, Remove. who: { id, display_name,
  // avatar_url, avatar_source }; path: the PUT/DELETE endpoint; changed
  // gets the hub's answer, { avatar_url, avatar_source }.
  function pictureEditor(who, path, own, changed) {
    const status = M.statusLine();
    const id = "avatar-file-" + who.id;
    const input = h("input", { id, type: "file", accept: "image/png,image/jpeg,image/webp" });
    const whose = own ? "your" : who.display_name + "'s";
    const done = (answer, words) => {
      who.avatar_url = answer.avatar_url;
      who.avatar_source = answer.avatar_source;
      changed(answer, words);
    };
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const stop = (message) => { status.fail("Not uploaded: ", { message }); input.value = ""; };
      if (file.size > IMAGE_MAX) { stop("larger than 1 MiB"); return; }
      const type = await sniffImage(file);
      if (!type) { stop("not a PNG, JPEG or WebP image"); return; }
      input.disabled = true;
      status.busy("Uploading " + whose + " picture…");
      try {
        done(await M.api.putImage(path, file, type), "Picture uploaded.");
      } catch (err) {
        status.fail("Not uploaded: ", refusal(err, own));
        input.value = "";
      } finally {
        input.disabled = false;
      }
    });
    const remove = who.avatar_source === "uploaded" ? h("button", {
      type: "button",
      onclick: async () => {
        remove.disabled = true;
        status.busy("Removing…");
        try {
          const answer = await M.api.del(path);
          done(answer, "Uploaded picture removed; " + (answer.avatar_source === "forge" ? "the forge's picture shows again." : "the generated one shows again."));
        } catch (err) {
          status.fail("Not removed: ", refusal(err, own));
          remove.disabled = false;
        }
      },
    }, "Remove the upload") : null;
    return h("div", { class: "picture" },
      h("div", { class: "picture-now" }, M.avatar(who, 64),
        h("p", { class: "muted" }, SOURCE_WORDS[who.avatar_source] || "Generated from the member id: the same in every client.")),
      h("div", { class: "picture-controls" },
        h("label", { for: id }, own ? "Upload a picture" : "Upload a picture for " + who.display_name),
        input,
        h("p", { class: "hint" }, "PNG, JPEG or WebP, at most 1 MiB and 4096 pixels on a side. The hub crops it to a square, "
          + "scales it to 256 pixels and drops everything but the pixels (a photo's location included)."),
        h("div", { class: "actions" }, remove),
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
    const go = h("button", { type: "submit", class: "danger" }, "Delete the profile");
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
        status.busy("Deleting…");
        try {
          const answer = await M.api.del("/agents/" + encodeURIComponent(who.id) + (where.length ? "?cascade=true" : ""));
          status.done();
          done(answer, "The profile @" + who.handle + " was deleted" + (where.length ? "; its memberships ended." : "."));
        } catch (err) {
          busy = false;
          typed.disabled = false;
          settle();
          const inUse = err.code === "profile_in_use" && err.details && err.details.memberships;
          status.fail("Not deleted: ", inUse ? { message: "it is still a member of " + err.details.memberships.map((x) => x.project).join(", ") + "; read the page again" } : err);
        }
      },
    },
    h("label", { for: id }, "Type @" + who.handle + " to delete it"), typed, go, status.el);
    return h("div", { class: "profile-delete-box" },
      h("h4", { class: "profile-delete-title" }, "Delete this profile"),
      h("p", { class: "hint" }, where.length
        ? "It is a member of " + where.join(", ") + ". Deleting it ends those memberships: their credentials are revoked, the cards it claimed are "
          + "released and its placements stop. The handle is free again at once. This cannot be undone."
        : "It is in no project. Deleting it frees the handle at once. This cannot be undone."),
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
  // once it is on — never a copy of the page's own; a hub that does not
  // send it shows none.
  const MEAT_PARTS = [
    ["meat_proxy_lead", "meat-proxy-lead", () => M.t("meat.part.lead")],
    ["meat_proxy_hands", "meat-proxy-hands", () => M.t("meat.part.hands")],
  ];
  async function meatProxySection(ctx) {
    if (ctx.me.kind !== "human") return null;
    const status = M.statusLine();
    const noteOf = (m) => (typeof m.meat_proxy_note === "string" && m.meat_proxy_note ? m.meat_proxy_note : null);
    const box = h("input", { type: "checkbox", id: "meat-proxy", "aria-describedby": "meat-proxy-hint" });
    const parts = MEAT_PARTS.map(([field, id]) => [field, h("input", { type: "checkbox", id })]);
    const hint = h("p", { class: "hint", id: "meat-proxy-hint" });
    const quote = h("div");
    const inputs = [box].concat(parts.map(([, input]) => input));
    // The switch, its parts and the note as the hub last said them.
    function show() {
      box.checked = !!ctx.me.meat_proxy;
      parts.forEach(([field, input]) => { input.checked = !!ctx.me[field]; });
      const note = noteOf(ctx.me);
      hint.textContent = !note ? M.t("meat.hint") : ctx.me.meat_proxy ? M.t("meat.hint.on") : M.t("meat.hint.off");
      append(clear(quote), note ? h("blockquote", { class: "meat-proxy-note", id: "meat-proxy-note" }, h("p", null, note)) : null);
      box.setAttribute("aria-describedby", note ? "meat-proxy-hint meat-proxy-note" : "meat-proxy-hint");
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
          ? (noteOf(ctx.me) ? M.t("meat.saved.on_note") : M.t("meat.saved.on"))
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

  M.views.account = async function (ctx, root, args) {
    // /account/sign-in-device (the profile menu's Sign in another device).
    if (args && args[0] === "sign-in-device" && M.deviceSignIn) { await M.deviceSignIn.anotherDevice(ctx, root); return; }
    const field = (id, label, autocomplete, hint) => {
      const input = h("input", { id, type: "password", autocomplete, required: true, "aria-describedby": id + "-error" });
      const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
      return { input, error, nodes: [h("label", { for: id }, label), input, hint ? h("p", { class: "hint" }, hint) : null, error] };
    };
    const current = field("password-current", "Current password", "current-password");
    const fresh = field("password-new", "New password", "new-password", "At least " + MIN_LENGTH + " characters.");
    const repeat = field("password-repeat", "New password again", "new-password");
    const all = [current, fresh, repeat];
    const status = M.statusLine();

    const showErrors = (errors) => {
      all.forEach((f) => { f.error.textContent = ""; f.input.removeAttribute("aria-invalid"); });
      errors.forEach(([f, text]) => { f.error.textContent = text; f.input.setAttribute("aria-invalid", "true"); });
      if (errors.length) errors[0][0].input.focus();
    };

    const submit = h("button", { type: "submit" }, "Change password");
    const form = h("form", {
      class: "project-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const errors = [];
        if (!current.input.value) errors.push([current, "Required."]);
        if ([...fresh.input.value].length < MIN_LENGTH) errors.push([fresh, "At least " + MIN_LENGTH + " characters."]);
        else if (fresh.input.value !== repeat.input.value) errors.push([repeat, "The two new passwords differ."]);
        showErrors(errors);
        if (errors.length) { status.done(); return; }
        submit.disabled = true;
        status.busy("Changing…");
        // The change ends every session but this one; the held long-poll goes
        // first, so that it never meets the change (§2.1, §18.2).
        M.notify.halt();
        try {
          await M.api.post("/auth/password", { current: current.input.value, new: fresh.input.value });
          all.forEach((f) => { f.input.value = ""; });
          status.done();
          append(status.el, h("span", { class: "ok" },
            "Password changed. Every other session of yours was signed out; this one stays signed in."));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields ? err.details.fields : null;
          if (fields && (fields.current || fields.new)) {
            showErrors([
              fields.current ? [current, fields.current === "mismatch" ? "This is not your current password." : String(fields.current)] : null,
              fields.new ? [fresh, fields.new === "too_short" ? "At least " + MIN_LENGTH + " characters." : String(fields.new)] : null,
            ].filter(Boolean));
            status.done();
          } else if (err.code === "rate_limited") {
            status.fail("Not changed: ", { message: "too many wrong passwords; wait a moment and try again" });
          } else {
            status.fail("Not changed: ", err);
          }
        } finally {
          // This session stays (or the change was refused): the stream goes on.
          M.notify.resume();
          submit.disabled = false;
        }
      },
    }, current.nodes, fresh.nodes, repeat.nodes, submit, status.el);

    // A changed picture redraws the whole page: the header's own picture
    // and /me come back with the hub's new avatar_url.
    const changed = (answer, words) => { pictureNote = words; ctx.refresh(); };
    const pictureHeading = h("h3", { class: "picture-heading", tabindex: "-1" }, "Your picture");
    const note = pictureNote ? h("p", { class: "ok", role: "status" }, pictureNote) : null;
    pictureNote = null;
    // The agents' pictures, names and deletion are on the Agents page
    // (/agents, js/agents-page.js): one place for one's agents.
    const meatProxy = await meatProxySection(ctx);
    const notify = M.notifySettings ? await M.notifySettings(ctx) : null;
    const sessions = M.sessions ? await M.sessions.section(ctx) : null;
    // Your data (§2.9): the export and the deletion of the account.
    const yourData = M.yourData ? await M.yourData.section(ctx) : null;
    const preferences = M.preferences ? await M.preferences.section(ctx) : null;
    // The theme (js/theme.js): signed in, it is chosen here, not in the
    // header (the maintainer's instruction). Per browser, as before: what
    // was picked while signed out stays until it is changed here.
    const themeHeading = h("h3", { id: "theme-heading", tabindex: "-1" }, "Theme");
    const themeBox = M.theme ? h("fieldset", { class: "theme-choice", "aria-labelledby": "theme-heading" },
      M.theme.THEMES.map((t) => {
        const input = h("input", { type: "radio", name: "theme", id: "theme-" + t, value: t });
        input.checked = t === M.theme.get();
        input.addEventListener("change", () => { if (input.checked) M.theme.set(t); });
        return h("label", { class: "check", for: "theme-" + t }, input, " " + ((M.THEME_WORDS || {})[t] || t));
      })) : null;
    append(root, h("h2", null, "Your account"),
      h("dl", { class: "facts" },
        h("dt", null, "Name"), h("dd", null, ctx.me.display_name),
        h("dt", null, "Handle"), h("dd", null, "@" + ctx.me.handle)),
      pictureHeading,
      h("p", { class: "muted" }, "Shown next to your name in every project, to everyone who shares one with you."),
      note,
      pictureEditor(ctx.me, "/me/avatar", true, changed),
      h("p", { class: "muted" }, "Your agents' pictures, names and handles are on ", h("a", { href: "/agents" }, "Your agents"), "."),
      meatProxy,
      themeBox ? [themeHeading, h("p", { class: "muted" }, "Kept in this browser only: another browser or device has its own. System follows the light or dark setting of your device."), themeBox] : null,
      preferences ? preferences.el : null,
      notify ? notify.el : null,
      sessions ? sessions.el : null,
      yourData ? yourData.el : null,
      h("h3", null, "Change password"),
      h("p", { class: "muted" }, "Changing it signs out every other browser and device where you are signed in."),
      form);
    // /account/picture (the profile menu's Picture) starts at the picture.
    if (args && args[0] === "picture") window.setTimeout(() => pictureHeading.focus(), 0);
    // /account/theme (the profile menu's Theme) starts there.
    if (themeBox && args && args[0] === "theme") window.setTimeout(() => themeHeading.focus(), 0);
    // /account/notifications (the bell's settings link) starts there.
    if (notify && args && args[0] === "notifications") window.setTimeout(() => notify.heading.focus(), 0);
    // /account/preferences (the profile menu's Preferences) starts there.
    if (preferences && args && args[0] === "preferences") window.setTimeout(() => preferences.heading.focus(), 0);
    // /account/sessions (a sign-in alert's link) starts at the sessions.
    if (sessions && args && args[0] === "sessions") window.setTimeout(() => sessions.heading.focus(), 0);
    // /account/data (the mail's link to the export, §2.9) starts at Your data.
    if (yourData && args && args[0] === "data") window.setTimeout(() => yourData.heading.focus(), 0);
  };
})(window.Maity);
