// The signed-in human's account (#/account): who they are, their picture
// and the pictures of their agents no project of theirs shows
// (#/account/picture, docs/api.md §6.10), their
// preferences (#/account/preferences, js/preferences.js), and
// changing the password (§2.1, POST /auth/password). A password change
// ends every other session of this human; this one stays signed in.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

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
    // /me/avatar is not_found only on a hub that has no pictures yet.
    if (err.code === "not_found") return { message: own ? "this hub does not take pictures yet" : "this profile is not yours, or this hub does not take pictures yet" };
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

  // Set by a change; the next drawing of the view says it.
  let pictureNote = null;

  M.views.account = async function (ctx, root, args) {
    // #/account/sign-in-device (the profile menu's Sign in another device).
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
    const wantedAgent = args && args[0] === "picture" ? args[1] || null : null;
    const note = pictureNote ? h("p", { class: "ok", role: "status" }, pictureNote) : null;
    pictureNote = null;
    // An agent's picture is set on Members, in its row (tsk-th1yq0jtk3yf);
    // here only the agents in no project one can open, which no other page
    // reaches. Without memberships in the profile, every agent counts as such.
    const opened = new Set((ctx.projects || []).map((p) => p.full_name));
    const reachable = (a) => (Array.isArray(a.memberships) ? a.memberships : []).find((x) => opened.has(x.project)) || null;
    const mine = await M.api.getAll("/agents").then((r) => r.items.filter((a) => a.owner_id === ctx.me.id && !a.deleted_at)).catch(() => null);
    // A link to an agent's picture that Members reaches goes there.
    const wantedThere = wantedAgent && mine && mine.find((a) => a.id === wantedAgent && reachable(a));
    if (wantedThere) {
      window.location.replace("#/" + M.api.projectPath(reachable(wantedThere).project) + "/members/" + encodeURIComponent(wantedThere.id) + "/picture");
      return;
    }
    const agents = mine && mine.filter((a) => !reachable(a));
    const notify = M.notifySettings ? await M.notifySettings(ctx) : null;
    const sessions = M.sessions ? await M.sessions.section(ctx) : null;
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
      agents && agents.length ? [h("h3", null, "Agents in other projects"),
        h("p", { class: "muted" }, "Your agents' pictures are set on Members, in each agent's row. These agents are in no project you are a member of, "
          + "so their pictures are set here. Each agent can also set its own; the last change wins."),
        // #/account/picture/<agent id> (a Keep the Why notice about an agent
        // in a project one is not in) marks that agent and starts there.
        h("ul", { class: "picture-list" }, agents.map((a) => h("li", { class: wantedAgent === a.id ? "wanted" : null, "data-agent": a.id },
          h("h4", { class: "picture-name", tabindex: wantedAgent === a.id ? "-1" : null }, a.display_name, h("span", { class: "muted" }, " @" + (a.name || a.handle))),
          pictureEditor(a, "/agents/" + encodeURIComponent(a.id) + "/avatar", false, changed))))] : null,
      themeBox ? [themeHeading, h("p", { class: "muted" }, "Kept in this browser only: another browser or device has its own. System follows the light or dark setting of your device."), themeBox] : null,
      preferences ? preferences.el : null,
      notify ? notify.el : null,
      sessions ? sessions.el : null,
      h("h3", null, "Change password"),
      h("p", { class: "muted" }, "Changing it signs out every other browser and device where you are signed in."),
      form);
    // #/account/picture (the profile menu's Picture) starts at the picture.
    if (args && args[0] === "picture") {
      const marked = wantedAgent && Array.from(root.querySelectorAll("li.wanted")).find((li) => li.getAttribute("data-agent") === wantedAgent);
      window.setTimeout(() => (marked ? marked.querySelector(".picture-name") : pictureHeading).focus(), 0);
    }
    // #/account/theme (the profile menu's Theme) starts there.
    if (themeBox && args && args[0] === "theme") window.setTimeout(() => themeHeading.focus(), 0);
    // #/account/notifications (the bell's settings link) starts there.
    if (notify && args && args[0] === "notifications") window.setTimeout(() => notify.heading.focus(), 0);
    // #/account/preferences (the profile menu's Preferences) starts there.
    if (preferences && args && args[0] === "preferences") window.setTimeout(() => preferences.heading.focus(), 0);
    // #/account/sessions (a sign-in alert's link) starts at the sessions.
    if (sessions && args && args[0] === "sessions") window.setTimeout(() => sessions.heading.focus(), 0);
  };
})(window.Maity);
