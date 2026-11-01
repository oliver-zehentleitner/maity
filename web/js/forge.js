// Forge access (docs/api.md §11.4) on the account, also at /settings/forge,
// where the hub sends the browser back after a GitHub App installation:
// the human's links of the instance's GitHub App and their own token, the
// grants every project they own reads its repository with. Starting a link
// and storing a token ask for the password or a code (§2.8.4); an unlink and
// a token's removal do not. A token is never shown, only whether one is set.
// On a project's settings, which grant reads its repository and the namespace
// owner's confirmation that lets their grants serve it.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  // GitHub's own page for the installations: an unlink here does not uninstall (§11.4).
  const INSTALLATIONS = "https://github.com/settings/installations";

  // The reasons the hub's setup redirect names in ?error= (§11.4).
  const BACK = {
    link_state: () => M.t("forge.back.link_state"),
    installation_not_yours: () => M.t("forge.back.installation_not_yours"),
    organisation_installation: () => M.t("forge.back.organisation_installation"),
    installation_linked: () => M.t("forge.back.installation_linked"),
    forge_app_missing: () => M.t("forge.back.forge_app_missing"),
    forge_unavailable: () => M.t("forge.back.forge_unavailable"),
  };
  const STATUS = {
    active: () => M.t("forge.status.active"),
    suspended: () => M.t("forge.status.suspended"),
    removed: () => M.t("forge.status.removed"),
    rejected: () => M.t("forge.status.rejected"),
  };
  // The hub's ?error= as words, kept across the redraw that drops it from the address.
  let carried = null;
  const statusOf = (s) => (Object.hasOwn(STATUS, s) ? STATUS[s]() : String(s || ""));

  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields && fields.token === "classic_token") return { message: M.t("forge.token.classic") };
    if (fields && fields.token === "rejected") return { message: M.t("forge.token.rejected") };
    if (err.code === "secret_key_missing") return { message: M.t("forge.token.no_key") };
    if (err.code === "forge_app_missing") return { message: M.t("forge.back.forge_app_missing") };
    if (err.code === "forge_unavailable") return { message: M.t("forge.back.forge_unavailable") };
    return err;
  }

  function linkItem(link, act) {
    const shown = link.repositories_shown || [];
    return h("li", { class: "forge-link forge-" + link.status, "data-link": link.id },
      h("p", null, h("strong", null, link.account && link.account.login ? "@" + link.account.login : String(link.installation_id)),
        " · ", statusOf(link.status),
        " · ", link.repository_selection === "all" ? M.t("forge.link.all") : M.t("forge.link.selected"),
        link.linked_at ? " · " + M.t("forge.link.linked", { at: formatTime(link.linked_at) }) : "",
        link.checked_at ? " · " + M.t("forge.checked", { at: formatTime(link.checked_at) }) : ""),
      shown.length ? h("details", null, h("summary", null, M.t("forge.link.repositories", { count: shown.length })),
        h("ul", { class: "forge-repos" }, shown.map((r) => h("li", { class: "mono" }, r)))) : null,
      h("button", { type: "button", onclick: () => act(M.t("forge.unlink.busy"), M.t("forge.unlink.done"),
        () => M.api.del("/me/forge/github/links/" + encodeURIComponent(link.id))) }, M.t("forge.unlink")),
      h("p", { class: "hint" }, M.tn("forge.unlink.hint", { link: h("a", { href: INSTALLATIONS, target: "_blank", rel: "noopener" }, M.t("forge.unlink.github")) })));
  }

  async function section(ctx) {
    if (ctx.me.kind !== "human") return null;
    const heading = h("h3", { id: "forge-heading", tabindex: "-1" }, M.t("forge.title"));
    const ask = h("div", { class: "step-up-slot" });
    ask.hidden = true;
    const status = M.statusLine();
    const body = h("div");
    const box = h("section", { class: "forge-access", "aria-labelledby": "forge-heading" },
      heading, h("p", { class: "muted" }, M.t("forge.intro")), status.el, ask, body);
    // Back from the forge (§11.4): the reason in words, then the address
    // without it; dropping the query draws the page again, which says it.
    const where = M.route.current();
    const back = where.query.get("error");
    let note = carried || (back ? { error: Object.hasOwn(BACK, back) ? BACK[back]() : back } : null);
    carried = null;
    if (where.path === "/settings/forge" && back) { carried = note; M.route.go("/settings/forge", { replace: true }); }

    async function act(busy, done, call) {
      status.busy(busy + "…");
      try {
        await call();
      } catch (err) {
        if (err.code === "cancelled") { status.done(); return; }
        status.fail(M.t("forge.failed", { what: busy }), said(err));
        return;
      }
      note = { ok: done };
      await load();
    }

    async function load() {
      let state;
      try {
        state = await M.api.get("/me/forge");
      } catch (err) {
        status.fail(M.t("forge.unread"), err);
        return;
      }
      status.done();
      const links = state.links || [];
      const own = state.token || { configured: false };
      const linkButton = h("button", { type: "button" }, M.t("forge.link"));
      linkButton.addEventListener("click", async () => {
        linkButton.disabled = true;
        status.busy(M.t("forge.link.busy"));
        try {
          const answer = await M.stepUp.run(() => M.api.post("/me/forge/github/link", {}), ask, M.t("forge.link.what"));
          const url = M.dom.safeUrl(answer.url);
          if (!url || !/^https:\/\//.test(url)) throw new M.api.ApiError(M.t("forge.link.bad_url"), 0, "/me/forge/github/link", "bad_url");
          window.location.assign(url);
        } catch (err) {
          linkButton.disabled = false;
          if (err.code === "cancelled") status.done();
          else status.fail(M.t("forge.failed", { what: M.t("forge.link.busy") }), said(err));
        }
      });
      const tokenId = "forge-token";
      // new-password: a browser's password manager would otherwise offer to keep the token as this site's password.
      const token = h("input", { id: tokenId, type: "password", autocomplete: "new-password", spellcheck: "false", "aria-describedby": tokenId + "-hint " + tokenId + "-error" });
      const tokenError = h("p", { class: "field-error", id: tokenId + "-error", role: "alert" });
      const tokenForm = h("form", {
        class: "inline-form forge-token-form",
        onsubmit: async (e) => {
          e.preventDefault();
          tokenError.textContent = "";
          const value = token.value.trim();
          if (!value) { token.focus(); return; }
          status.busy(M.t("forge.token.busy") + "…");
          try {
            await M.stepUp.run(() => M.api.put("/me/forge/github/token", { token: value }), ask, M.t("forge.token.what"));
          } catch (err) {
            if (err.code === "cancelled") { status.done(); return; }
            const fields = err.code === "invalid" && err.details && err.details.fields;
            if (fields && fields.token) {
              status.done();
              tokenError.textContent = said(err).message;
              token.setAttribute("aria-invalid", "true");
              token.focus();
              return;
            }
            status.fail(M.t("forge.failed", { what: M.t("forge.token.busy") }), said(err));
            return;
          }
          token.value = "";
          note = { ok: M.t("forge.token.done") };
          await load();
        },
      }, h("label", { for: tokenId }, own.configured ? M.t("forge.token.replace") : M.t("forge.token.label")), token,
      h("button", { type: "submit" }, own.configured ? M.t("forge.token.replace_button") : M.t("forge.token.save")),
      h("p", { class: "hint", id: tokenId + "-hint" }, M.t("forge.token.hint")), tokenError);
      append(clear(body),
        note && note.ok ? h("p", { class: "ok", role: "status" }, note.ok) : null,
        note && note.error ? h("p", { class: "error", role: "alert" }, note.error) : null,
        h("h4", null, M.t("forge.app.title")),
        state.app_configured
          ? [h("p", { class: "hint" }, M.t("forge.app.hint")),
            links.length ? h("ul", { class: "forge-links" }, links.map((l) => linkItem(l, act))) : h("p", { class: "muted" }, M.t("forge.app.none")),
            linkButton]
          : h("p", { class: "muted" }, M.t("forge.app.missing")),
        h("h4", null, M.t("forge.token.title")),
        own.configured
          ? h("p", { class: "forge-token-state" }, own.login ? M.t("forge.token.set_for", { login: "@" + own.login }) : M.t("forge.token.set"), " · ", statusOf(own.status),
            own.checked_at ? " · " + M.t("forge.checked", { at: formatTime(own.checked_at) }) : "", " ",
            h("button", { type: "button", onclick: () => act(M.t("forge.token.remove.busy"), M.t("forge.token.remove.done"),
              () => M.api.del("/me/forge/github/token")) }, M.t("forge.token.remove")))
          : h("p", { class: "muted" }, M.t("forge.token.none")),
        tokenForm);
      note = null;
    }
    await load();
    return { el: box, heading };
  }

  // A project's repository as the hub reads it (§6.1, §11.4): with which
  // grant, and whether the namespace owner confirmed it for their grants.
  const VIA = {
    app: () => M.t("forge.via.app"),
    owner_token: () => M.t("forge.via.owner_token"),
    instance: () => M.t("forge.via.instance"),
  };
  function repositoryPart(ctx) {
    const repo = ctx.project.repository;
    if (!repo || !repo.url) return null;
    const ask = h("div", { class: "step-up-slot" });
    ask.hidden = true;
    const status = M.statusLine();
    const by = repo.confirmed_by;
    // Only the namespace owner confirms — for an organisation's project any of
    // its owners (§11.4, §6.26) — as js/project-names.js decides a transfer.
    const self = (ctx.members || []).find((m) => m.id === ctx.me.id);
    const ofOrg = !!(ctx.project.owner && /^org-/.test(ctx.project.owner.id));
    const namespaceOwner = !!ctx.project.owner && (ofOrg ? !!(self && self.org_owner) : ctx.project.owner.id === ctx.me.id);
    // Confirmed already: by me, or for a human's project, nothing to offer; another
    // owner of the organisation may confirm with their own grants instead (§11.4).
    const settled = repo.owner_confirmed && (!ofOrg || (by && by.id === ctx.me.id));
    const confirm = settled || !namespaceOwner || ctx.me.kind !== "human" ? null : h("button", {
      type: "button",
      onclick: async (e) => {
        e.target.disabled = true;
        status.busy(M.t("forge.confirm.busy") + "…");
        try {
          await M.stepUp.run(() => M.api.post(ctx.base + "/repository/confirm", { url: repo.url }), ask, M.t("forge.confirm.what"));
        } catch (err) {
          e.target.disabled = false;
          if (err.code === "cancelled") { status.done(); return; }
          if (err.code === "conflict" && err.details && err.details.reason === "repository_changed") {
            status.fail(M.t("forge.failed", { what: M.t("forge.confirm.busy") }), { message: M.t("forge.confirm.changed", { url: String(err.details.url || "") }) });
            return;
          }
          status.fail(M.t("forge.failed", { what: M.t("forge.confirm.busy") }), err);
          return;
        }
        ctx.refresh();
      },
    }, M.t("forge.confirm"));
    return h("div", { class: "forge-repository" },
      h("p", null, repo.probe_via && Object.hasOwn(VIA, repo.probe_via) ? VIA[repo.probe_via]() : M.t("forge.via.none")),
      h("p", { class: repo.owner_confirmed ? "muted" : "hint" }, repo.owner_confirmed
        ? M.t("forge.confirmed", { handle: by && by.handle ? "@" + by.handle : "" })
        : M.t("forge.unconfirmed")),
      confirm, ask, status.el,
      h("p", { class: "hint" }, M.tn("forge.settings_hint", { link: h("a", { href: "/settings/forge" }, M.t("forge.settings_link")) })));
  }

  M.forge = { section, repositoryPart };
})(window.Maity);
