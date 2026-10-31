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
      M.api.source === "fixtures" ? h("span", { class: "source" }, M.t("header.fixtures")) : null, extra || null,
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
    document.title = M.t("invite.page_title") + " · Maity";
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
        h("h2", null, M.t("invite.unusable")),
        h("p", null, err.status === 404 ? M.t("invite.unusable.hint") : M.t("invite.read_failed", { reason: err.message || M.t("invite.an_error") })),
        h("p", null, h("a", { href: "/login" }, M.t("invite.sign_in"))));
      return;
    }
    const role = M.trust.words(inv);
    const here = "/invite/" + encodeURIComponent(token);
    document.title = M.t("invite.join_title", { project: inv.project.name }) + " · Maity";
    append(box,
      h("div", { class: "invite-project" },
        ownLogo(inv.project.logo_url) ? h("img", { class: "invite-logo", src: inv.project.logo_url, alt: "", width: "48", height: "48" })
          : M.projectMark ? M.projectMark(inv.project.full_name || inv.project.name, inv.project.name, null, "invite-logo") : null,
        h("h2", null, M.tn("invite.join_heading", { project: h("span", { class: "invite-name" }, inv.project.name) }))),
      h("p", { class: "invite-lead" }, M.tn("invite.lead", { who: inv.invited_by.display_name, project: inv.project.name, role: h("strong", null, role) })),
      inv.note ? [h("blockquote", { class: "invite-note" }, h("p", null, inv.note)),
        h("p", { class: "muted invite-note-by" }, "— " + inv.invited_by.display_name)] : null,
      h("p", { class: "muted" }, inv.address_bound ? M.t("invite.valid_until.bound", { when: formatTime(inv.expires_at) }) : M.t("invite.valid_until", { when: formatTime(inv.expires_at) })));
    const ways = h("div", { class: "invite-ways" });
    append(box, ways);
    let me = null;
    try { me = await signedIn(); } catch (err) { append(ways, h("p", { class: "send-status failed" }, M.t("invite.session_failed", { reason: err.message }))); return; }
    if (!me) {
      append(ways,
        h("a", { class: "button primary door-action", href: M.withNext("/login", here) }, M.t("invite.sign_in_to_accept")),
        inv.registration === "sign_in_or_register"
          ? h("p", { class: "door-alt" }, M.tn("invite.register", { create: h("a", { href: M.withNext("/register", here) }, M.t("invite.register.link")) }))
          : h("p", { class: "muted" }, M.t("invite.no_registration", { who: inv.invited_by.display_name })));
      return;
    }
    // An account that waits for approval accepts nothing yet (§2.7.5, §3.4).
    if (me.account_status === "pending") {
      append(ways, h("p", null, M.t("invite.pending")));
      return;
    }
    // Signed in: one button, the hub's refusal in its own words (§3.4).
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const accept = h("button", { type: "button", class: "primary door-action" }, M.t("invite.accept", { project: inv.project.name, name: me.display_name }));
    accept.addEventListener("click", async () => {
      accept.disabled = true;
      status.busy(M.t("invite.joining"));
      try {
        await M.api.post("/invitations/" + encodeURIComponent(token) + "/accept", {});
      } catch (err) {
        accept.disabled = false;
        status.fail(M.t("invite.not_joined"), { message: refusal(err) ? M.t("invite.refusal", { reason: err.message, code: refusal(err) }) : err.message });
        status.el.focus();
        return;
      }
      status.done();
      clear(ways);
      append(ways, h("p", { class: "ok" }, M.t("invite.joined", { project: inv.project.name })),
        h("p", null, h("a", { class: "button primary", href: "/" + M.api.projectPath(inv.project.full_name) + "/inbox" }, M.t("invite.open", { project: inv.project.name }))));
      const open = ways.querySelector("a");
      if (open) open.focus();
    });
    // Who is signed in, as a small row, with a way out when it is someone else.
    append(ways, h("p", { class: "door-who" }, M.avatar ? M.avatar(me, 24) : null,
      h("span", { class: "muted" }, M.t("invite.signed_in_as", { name: me.display_name }), " · @" + me.handle),
      M.logout ? h("button", { type: "button", class: "link-button", onclick: () => M.logout(here) }, M.t("invite.not_you")) : null), accept, status.el);
  }

  // The reason a refusal names, beside the hub's words.
  function refusal(err) {
    const d = err.details || {};
    return (d.fields && d.fields.token) || d.reason || (err.code !== "forbidden" && err.code !== "invalid" ? err.code : null);
  }

  // ---- Members: inviting a person -----------------------------------------

  const TTLS = [[3600, () => M.t("invite.ttl.hour")], [86400, () => M.t("invite.ttl.day")], [3 * 86400, () => M.t("invite.ttl.days3")], [7 * 86400, () => M.t("invite.ttl.week")]];
  // An invitation's state in words; the class keeps the hub's value.
  const STATE_WORDS = {
    open: () => M.t("invite.state.open"), used: () => M.t("invite.state.used"), revoked: () => M.t("invite.state.revoked"),
    voided: () => M.t("invite.state.voided"), expired: () => M.t("invite.state.expired"),
  };
  function stateOf(x) {
    if (x.used_at) return "used";
    if (x.revoked_at) return "revoked";
    if (x.voided_at) return "voided";
    if (Date.parse(x.expires_at) <= M.api.now()) return "expired";
    return "open";
  }

  // A join URL's host, as the person sees it in the link ("join.maity.team").
  const hostOf = (url) => { try { return new URL(url).host; } catch (err) { return String(url); } };

  // For a human with members:admin; null otherwise. opts.heading: the
  // section's title instead of the usual one (the /invite page names the
  // project); opts.listOnly: the invitations without the form (another
  // project's on /invite).
  async function membersPanel(ctx, opts) {
    const o = opts || {};
    if (!ctx.canAdmin || ctx.me.kind !== "human") return null;
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
      M.trust.fillRoles(role, offered, wanted, "coder");
    };
    const roleHelp = M.trust.roleHint(role);
    trust.addEventListener("change", roles);
    roles();
    const address = h("input", { id: "invite-address", type: "email", autocomplete: "off", placeholder: M.t("invite.address.placeholder") });
    const ttl = h("select", { id: "invite-ttl" }, TTLS.map(([v, l]) => h("option", { value: String(v) }, l())));
    ttl.value = "86400";
    const note = h("textarea", { id: "invite-note", rows: "2", maxlength: "1024", placeholder: M.t("invite.note.placeholder") });
    // The link on the join host (§3.4 `via`, §1.1): offered, on by default, only
    // where the hub names a join host (`join_url` of GET /auth/session): the
    // session the page has read already, asked again only where there is none.
    const session = M.api.session() || await M.api.get("/auth/session").catch(() => ({}));
    const joinHost = session.join_url ? hostOf(session.join_url) : null;
    const viaJoin = joinHost ? h("input", { type: "checkbox", id: "invite-via-join" }) : null;
    if (viaJoin) viaJoin.checked = true;
    const submit = h("button", { type: "submit" }, M.t("invite.create"));
    const form = h("form", {
      class: "invite-form inline-form",
      onsubmit: async (e) => {
        e.preventDefault();
        const body = { trust: trust.value, role: role.value, ttl_seconds: Number(ttl.value) };
        if (address.value.trim()) body.address = address.value.trim();
        if (note.value.trim()) body.note = note.value.trim();
        if (viaJoin) body.via = viaJoin.checked ? "join" : "public";
        // The hub counts the note in UTF-8 bytes (§3.4, 1 KiB), not characters.
        if (body.note && encodeURIComponent(body.note).replace(/%[0-9A-F]{2}/g, "x").length > 1024) {
          status.fail(M.t("invite.not_created"), { message: M.t("invite.note.too_long") });
          note.focus();
          return;
        }
        submit.disabled = true;
        status.busy(M.t("invite.creating"));
        let made;
        try {
          made = await M.api.post(ctx.base + "/invitations", body);
        } catch (err) {
          submit.disabled = false;
          status.fail(M.t("invite.not_created"), err.details && err.details.fields
            ? { message: Object.entries(err.details.fields).map(([f, r]) => (f === "via" && r === "no_join_host" ? M.t("invite.no_join_host") : f + ": " + r)).join("; ") } : err);
          return;
        }
        submit.disabled = false;
        status.done();
        address.value = ""; note.value = "";
        showOnce(made);
        await list();
      },
    },
    h("label", { for: "invite-trust" }, M.t("invite.trust")), trust,
    h("label", { for: "invite-role" }, M.t("invite.role")), role, roleHelp,
    h("label", { for: "invite-address" }, M.t("invite.address")), address,
    h("label", { for: "invite-ttl" }, M.t("invite.ttl")), ttl,
    h("label", { for: "invite-note" }, M.t("invite.note")), note,
    viaJoin ? h("label", { class: "check", for: "invite-via-join" }, viaJoin, " ", M.t("invite.via_join", { host: joinHost })) : null,
    viaJoin ? h("p", { class: "hint" }, M.t("invite.via_join.hint")) : null,
    submit, status.el);

    // The link exists once, in this answer (§3.4): shown with a copy button
    // until the page is left; the list never shows it again.
    function showOnce(made) {
      const url = h("input", { id: "invite-url", readonly: true, value: made.url });
      url.value = made.url;
      const copy = h("button", { type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(made.url); copy.textContent = M.t("invite.copied"); } catch (err) { url.select(); copy.textContent = M.t("invite.copy_failed"); }
      } }, M.t("invite.copy"));
      const title = h("h3", { tabindex: "-1" }, M.t("invite.created"));
      append(clear(issued), title,
        h("p", null, made.address ? M.t("invite.shown_once.mailed", { address: made.address }) : M.t("invite.shown_once")),
        h("label", { for: "invite-url" }, M.t("invite.link")), h("div", { class: "invite-url-row" }, url, copy));
      window.setTimeout(() => title.focus(), 0);
    }

    async function list() {
      let items;
      try {
        items = (await M.api.getAll(ctx.base + "/invitations")).items;
      } catch (err) {
        append(clear(listBox), h("p", { class: "send-status failed" }, M.t("invite.list_failed", { reason: err.message })));
        return;
      }
      append(clear(listBox), items.length
        ? h("ul", { class: "invite-list" }, items.map((x) => {
          const state = stateOf(x);
          return h("li", { class: "invite-item invite-" + state, "data-invitation": x.id },
            h("span", { class: "invite-state" }, Object.hasOwn(STATE_WORDS, state) ? STATE_WORDS[state]() : state), " ",
            h("span", null, x.address ? M.t("invite.for_address", { what: M.trust.words(x), address: x.address }) : M.t("invite.for_link", { what: M.trust.words(x) })),
            // Which link went out (§3.4), where the hub lists it.
            x.via === "join" && joinHost ? h("span", { class: "muted" }, " · ", M.t("invite.via", { host: joinHost }))
              : x.via === "public" && joinHost ? h("span", { class: "muted" }, " · ", M.t("invite.via_public")) : null,
            h("span", { class: "muted" }, " · ", M.t("invite.by", { who: ctx.nameOf(x.created_by) }), " · ",
              state === "open" ? M.t("invite.until", { when: formatTime(x.expires_at) }) : formatTime(x.used_at || x.revoked_at || x.voided_at || x.expires_at)),
            state === "open" ? h("button", { type: "button", class: "small", "data-focus": "revoke:" + x.id, onclick: async (e) => {
              const b = e.target;
              b.disabled = true;
              try {
                await M.api.del(ctx.base + "/invitations/" + encodeURIComponent(x.id));
              } catch (err) {
                b.disabled = false;
                status.fail(M.t("invite.not_revoked"), err);
                return;
              }
              status.done();
              append(status.el, h("span", { class: "ok" }, M.t("invite.revoked")));
              await list();
              status.el.focus();
            } }, M.t("invite.revoke")) : null);
        }))
        : h("p", { class: "muted" }, M.t("invite.none")));
    }
    // Ids per project, so that several panels share a page.
    const headingId = "invitations-heading" + (o.heading ? "-" + ctx.slug.replace(/[^a-z0-9]+/gi, "-") : "");
    box.setAttribute("aria-labelledby", headingId);
    append(box, h("h3", { id: headingId }, o.heading || M.t("invite.title")),
      // Without the form its status line stands here: a revoke in the list says what happened.
      o.listOnly ? status.el : [h("p", { class: "muted" }, M.t("invite.hint")), form, issued],
      h("h4", null, M.t("invite.list")), listBox);
    await list();
    return box;
  }

  M.invite = { page, membersPanel, stateOf };
})(window.Maity);
