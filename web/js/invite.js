// How a person comes into a project (docs/api.md §3.4): the invitation
// page /invite/<token>, and on the Members page the invitations a human
// with members:admin issues and revokes. Registration is js/register.js.
// The invitation page is the first a new person sees: who invites them to
// what, then the way in that this instance offers.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  // The bar of a page without a project: the lockup and the theme.
  function bar(header, extra) {
    append(clear(header), h("div", { class: "bar" }, M.brandTitle ? M.brandTitle() : null,
      M.api.source === "fixtures" ? h("span", { class: "source" }, "Fixtures") : null, extra || null,
      M.themeMenu ? M.themeMenu() : null));
  }

  // The project's logo only from this hub's own path (the hub names it with its public URL).
  function ownLogo(url) {
    if (typeof url !== "string") return false;
    const origin = window.location && window.location.origin && window.location.origin !== "null" ? window.location.origin : "";
    const path = origin && url.startsWith(origin + "/") ? url.slice(origin.length) : url;
    return /^\/api\/v1\/projects\/[^/?#]+\/logo(\?[^#]*)?$/.test(path);
  }

  async function signedIn() {
    try { await M.api.get("/auth/session"); } catch (err) { if (err.status === 401) return null; throw err; }
    return (await M.api.get("/me")).member;
  }

  // ---- the invitation page ------------------------------------------------

  async function page(main, header, token) {
    bar(header);
    document.title = "Invitation · Maity";
    // One centred card, as sign-in and register (the designer's pass part 2):
    // the three pages are one door.
    const box = h("article", { class: "invite door" });
    append(clear(main), box);
    let inv;
    try {
      inv = await M.api.get("/invitations/" + encodeURIComponent(token));
    } catch (err) {
      // Unknown, used, expired or revoked: one answer, never which (§3.4).
      append(box, h("span", { class: "door-mark", "aria-hidden": "true" }, "✉"),
        h("h2", null, "This invitation cannot be used"),
        h("p", null, err.status === 404 ? "It may have expired, been used or been withdrawn. Ask the person who invited you for a new one."
          : "It could not be read: " + (err.message || "an error") + "."),
        h("p", null, h("a", { href: "/login" }, "Sign in")));
      return;
    }
    const role = M.trust.words(inv);
    const here = "/invite/" + encodeURIComponent(token);
    document.title = "Join " + inv.project.name + " · Maity";
    append(box,
      h("div", { class: "invite-project" },
        ownLogo(inv.project.logo_url) ? h("img", { class: "invite-logo", src: inv.project.logo_url, alt: "", width: "48", height: "48" })
          : M.projectMark ? M.projectMark(inv.project.full_name || inv.project.name, inv.project.name, null, "invite-logo") : null,
        h("h2", null, "Join ", h("span", { class: "invite-name" }, inv.project.name))),
      h("p", { class: "invite-lead" }, inv.invited_by.display_name + " invites you to join " + inv.project.name + " as ", h("strong", null, role), "."),
      inv.note ? [h("blockquote", { class: "invite-note" }, h("p", null, inv.note)),
        h("p", { class: "muted invite-note-by" }, "— " + inv.invited_by.display_name)] : null,
      h("p", { class: "muted" }, "Valid until " + formatTime(inv.expires_at) + "."
        + (inv.address_bound ? " It is meant for the address it was sent to." : "")));
    const ways = h("div", { class: "invite-ways" });
    append(box, ways);
    let me = null;
    try { me = await signedIn(); } catch (err) { append(ways, h("p", { class: "send-status failed" }, "Could not tell whether you are signed in: " + err.message)); return; }
    if (!me) {
      append(ways,
        h("a", { class: "button primary door-action", href: M.withNext("/login", here) }, "Sign in to accept"),
        inv.registration === "sign_in_or_register"
          ? h("p", { class: "door-alt" }, "No account yet? ", h("a", { href: M.withNext("/register", here) }, "Create one"), " and you come back here.")
          : h("p", { class: "muted" }, "This hub does not create new accounts: sign in with an account you have, or ask " + inv.invited_by.display_name + " for another way in."));
      return;
    }
    // An account that waits for approval accepts nothing yet (§2.7.5, §3.4).
    if (me.account_status === "pending") {
      append(ways, h("p", null, "Your account waits for the operator's approval. The invitation waits for you: open this link again once you are approved."));
      return;
    }
    // Signed in: one button, the hub's refusal in its own words (§3.4).
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const accept = h("button", { type: "button", class: "primary door-action" }, "Join " + inv.project.name + " as " + me.display_name);
    accept.addEventListener("click", async () => {
      accept.disabled = true;
      status.busy("Joining…");
      try {
        await M.api.post("/invitations/" + encodeURIComponent(token) + "/accept", {});
      } catch (err) {
        accept.disabled = false;
        status.fail("Not joined: ", { message: err.message + (refusal(err) ? " (" + refusal(err) + ")" : "") });
        status.el.focus();
        return;
      }
      status.done();
      clear(ways);
      append(ways, h("p", { class: "ok" }, "You are a member of " + inv.project.name + " now."),
        h("p", null, h("a", { class: "button primary", href: "/" + M.api.projectPath(inv.project.full_name) + "/inbox" }, "Open " + inv.project.name)));
      const open = ways.querySelector("a");
      if (open) open.focus();
    });
    // Who is signed in, as a small row, with a way out when it is someone else.
    append(ways, h("p", { class: "door-who" }, M.avatar ? M.avatar(me, 24) : null,
      h("span", { class: "muted" }, "Signed in as " + me.display_name + " · @" + me.handle),
      M.logout ? h("button", { type: "button", class: "link-button", onclick: () => M.logout(here) }, "Not you? Sign out") : null), accept, status.el);
  }

  // The reason a refusal names, beside the hub's words.
  function refusal(err) {
    const d = err.details || {};
    return (d.fields && d.fields.token) || d.reason || (err.code !== "forbidden" && err.code !== "invalid" ? err.code : null);
  }

  // ---- Members: inviting a person -----------------------------------------

  const TTLS = [[3600, "1 hour"], [86400, "1 day"], [3 * 86400, "3 days"], [7 * 86400, "1 week"]];
  function stateOf(x) {
    if (x.used_at) return "used";
    if (x.revoked_at) return "revoked";
    if (x.voided_at) return "voided";
    if (Date.parse(x.expires_at) <= M.api.now()) return "expired";
    return "open";
  }

  // For a human with members:admin; null otherwise or on a hub without invitations.
  async function membersPanel(ctx) {
    if (!ctx.canAdmin || ctx.me.kind !== "human") return null;
    if (!(await M.api.hubHas("POST", "/projects/{owner}/{slug}/invitations").catch(() => true))) return null;
    const box = h("section", { class: "invitations", "aria-labelledby": "invitations-heading" });
    const listBox = h("div");
    const issued = h("div", { class: "invite-issued" });
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    // Trust owner or admin, and the role proxy, only from an owner (owner_only, §2.3);
    // proxy only with trust admin (§3.4).
    const trusts = ctx.isOwner ? M.trust.TRUSTS : ["member", "guest"];
    const trust = h("select", { id: "invite-trust" }, trusts.map((r) => h("option", { value: r }, r)));
    trust.value = "member";
    const role = h("select", { id: "invite-role" });
    const roles = () => {
      const wanted = role.value || "coder";
      const offered = M.trust.ROLES.filter((r) => r !== "proxy" || (ctx.isOwner && trust.value === "admin"));
      append(clear(role), offered.map((r) => h("option", { value: r }, r)));
      role.value = offered.includes(wanted) ? wanted : "coder";
    };
    trust.addEventListener("change", roles);
    roles();
    const address = h("input", { id: "invite-address", type: "email", autocomplete: "off", placeholder: "Optional: only this address may accept" });
    const ttl = h("select", { id: "invite-ttl" }, TTLS.map(([v, l]) => h("option", { value: String(v) }, l)));
    ttl.value = "86400";
    const note = h("textarea", { id: "invite-note", rows: "2", maxlength: "1024", placeholder: "Optional: shown on the invitation page (at most 1 KiB)" });
    const submit = h("button", { type: "submit" }, "Create the invitation");
    const form = h("form", {
      class: "invite-form inline-form",
      onsubmit: async (e) => {
        e.preventDefault();
        const body = { trust: trust.value, role: role.value, ttl_seconds: Number(ttl.value) };
        if (address.value.trim()) body.address = address.value.trim();
        if (note.value.trim()) body.note = note.value.trim();
        // The hub counts the note in UTF-8 bytes (§3.4, 1 KiB), not characters.
        if (body.note && encodeURIComponent(body.note).replace(/%[0-9A-F]{2}/g, "x").length > 1024) {
          status.fail("Not created: ", { message: "the note is longer than 1 KiB" });
          note.focus();
          return;
        }
        submit.disabled = true;
        status.busy("Creating…");
        let made;
        try {
          made = await M.api.post(ctx.base + "/invitations", body);
        } catch (err) {
          submit.disabled = false;
          status.fail("Not created: ", err.details && err.details.fields
            ? { message: Object.entries(err.details.fields).map(([f, r]) => f + ": " + r).join("; ") } : err);
          return;
        }
        submit.disabled = false;
        status.done();
        address.value = ""; note.value = "";
        showOnce(made);
        await list();
      },
    },
    h("label", { for: "invite-trust" }, "Trust"), trust,
    h("label", { for: "invite-role" }, "Role"), role,
    h("label", { for: "invite-address" }, "Address"), address,
    h("label", { for: "invite-ttl" }, "Valid for"), ttl,
    h("label", { for: "invite-note" }, "Note"), note,
    submit, status.el);

    // The link exists once, in this answer (§3.4): shown with a copy button
    // until the page is left; the list never shows it again.
    function showOnce(made) {
      const url = h("input", { id: "invite-url", readonly: true, value: made.url });
      url.value = made.url;
      const copy = h("button", { type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(made.url); copy.textContent = "Copied"; } catch (err) { url.select(); copy.textContent = "Copy failed: select the link"; }
      } }, "Copy");
      const title = h("h3", { tabindex: "-1" }, "Invitation created");
      append(clear(issued), title,
        h("p", null, "This link is shown only now. Copy it and pass it on" + (made.address ? " (the hub also mails it to " + made.address + " where it sends mail)." : ".")),
        h("label", { for: "invite-url" }, "The link"), h("div", { class: "invite-url-row" }, url, copy));
      window.setTimeout(() => title.focus(), 0);
    }

    async function list() {
      let items;
      try {
        items = (await M.api.getAll(ctx.base + "/invitations")).items;
      } catch (err) {
        append(clear(listBox), h("p", { class: "send-status failed" }, "Could not read the invitations: " + err.message));
        return;
      }
      append(clear(listBox), items.length
        ? h("ul", { class: "invite-list" }, items.map((x) => {
          const state = stateOf(x);
          return h("li", { class: "invite-item invite-" + state, "data-invitation": x.id },
            h("span", { class: "invite-state" }, state), " ",
            h("span", null, M.trust.words(x) + (x.address ? " for " + x.address : " for whoever has the link")),
            h("span", { class: "muted" }, " · by " + ctx.nameOf(x.created_by) + " · "
              + (state === "open" ? "until " + formatTime(x.expires_at) : formatTime(x.used_at || x.revoked_at || x.voided_at || x.expires_at))),
            state === "open" ? h("button", { type: "button", class: "small", "data-focus": "revoke:" + x.id, onclick: async (e) => {
              const b = e.target;
              b.disabled = true;
              try {
                await M.api.del(ctx.base + "/invitations/" + encodeURIComponent(x.id));
              } catch (err) {
                b.disabled = false;
                status.fail("Not revoked: ", err);
                return;
              }
              status.done();
              append(status.el, h("span", { class: "ok" }, "Revoked; the link no longer works."));
              await list();
              status.el.focus();
            } }, "Revoke") : null);
        }))
        : h("p", { class: "muted" }, "No invitations in the last 30 days."));
    }
    append(box, h("h3", { id: "invitations-heading" }, "Invite a person"),
      h("p", { class: "muted" }, "For one person, one role, used once. Without an address, whoever has the link may accept."),
      form, issued, h("h4", null, "Invitations"), listBox);
    await list();
    return box;
  }

  M.invite = { page, membersPanel, stateOf };
})(window.Maity);
