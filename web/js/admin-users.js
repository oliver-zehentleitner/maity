// Users of this hub, the Users section of /admin (docs/api.md §16.1;
// js/instance-admin.js shows it to the instance admin only): the humans of the
// instance for its admin — counts and times, never content. Searchable by
// handle or name and filterable by disabled; paged by the hub's cursor.
// "Reset two-factor sign-in" (§2.8.3, §2.8.7) mails the person a link; only
// their press on its button changes anything.
// Being the instance admin opens no project: this view links nowhere into
// one.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const PAGE = 50;
  const SEARCH_MS = 300;
  const REASON_MAX = 1024; // the hub's limit (§2.8.3)

  // The hub's refusals of a reset, in words (§2.8.3).
  function resetSaid(err) {
    if (err.details && err.details.reason === "own_account") return { message: M.t("users.reset.refused.own") };
    if (err.code === "mail_not_configured") return { message: M.t("users.reset.refused.no_mail") };
    if (err.code === "address_unverified") return { message: M.t("users.reset.refused.no_address") };
    if (err.code === "conflict") return { message: M.t("users.reset.refused.not_enrolled") };
    if (err.code === "rate_limited") return { message: M.t("users.reset.refused.rate_limited") };
    if (err.code === "invalid") return { message: M.t("users.reset.refused.reason") };
    return err;
  }

  // The form under the list, for one person: the reason, what it does, and whom to ask first.
  function resetForm(user, opener, close) {
    const status = M.statusLine();
    const slot = h("div", { class: "step-up-slot" });
    const reason = h("textarea", { id: "user-reset-reason", rows: "3", maxlength: String(REASON_MAX), required: true });
    const send = h("button", { type: "submit", class: "primary" }, M.t("users.reset.send"));
    const leave = () => { close(); if (opener.isConnected !== false) opener.focus(); };
    const form = h("form", { class: "user-reset", "aria-labelledby": "user-reset-title", onsubmit: async (e) => {
      e.preventDefault();
      const said = reason.value.trim();
      if (!said) { status.fail(M.t("users.reset.not_sent"), { message: M.t("users.reset.reason_needed") }); return; }
      send.disabled = true;
      status.busy(M.t("users.reset.sending"));
      try {
        const answer = await M.stepUp.run(
          () => M.api.post("/admin/users/" + encodeURIComponent(user.id) + "/second-factor/reset", { reason: said }),
          slot, M.t("users.reset.what"));
        reason.value = "";
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("users.reset.sent", { name: user.display_name, when: formatTime(answer.expires_at) })));
      } catch (err) {
        if (err.code === "cancelled") status.done();
        else status.fail(M.t("users.reset.not_sent"), resetSaid(err));
      } finally {
        send.disabled = false;
      }
    } },
    h("h3", { id: "user-reset-title" }, M.t("users.reset.title", { name: user.display_name })),
    h("p", null, M.t("users.reset.explain")),
    h("p", { class: "flag" }, M.t("users.reset.confirm_first")),
    h("label", { for: "user-reset-reason" }, M.t("users.reset.reason")), reason,
    h("p", { class: "hint" }, M.t("users.reset.reason_hint")),
    h("div", { class: "actions" }, send, h("button", { type: "button", onclick: leave }, M.t("users.reset.close"))),
    slot, status.el);
    return { form, reason };
  }

  async function section(ctx, root) {
    const status = M.statusLine();
    const box = h("div", { class: "users-box" });
    const more = h("div", { class: "actions" });
    const q = h("input", { id: "users-q", type: "search", maxlength: "64", autocomplete: "off", spellcheck: "false" });
    const disabled = h("select", { id: "users-disabled" },
      [["", "All accounts"], ["false", "Active"], ["true", "Disabled"]].map(([v, l]) => h("option", { value: v }, l)));
    disabled.value = "";
    let rows = [];
    let next = null;
    let seq = 0;
    // A cursor belongs to the filter it was read with (docs/api.md §1.4):
    // the next page asks with that filter, never with what is typed since.
    let shownFilter = null;

    const filterNow = () => ({ q: q.value.trim(), disabled: disabled.value });
    const query = (filter, cursor) => {
      const p = new URLSearchParams();
      if (filter.q) p.set("q", filter.q);
      if (filter.disabled) p.set("disabled", filter.disabled);
      p.set("limit", String(PAGE));
      if (cursor) p.set("cursor", cursor);
      return "/admin/users?" + p.toString();
    };

    // One form at a time; it stays when the list below it is searched or paged.
    const resetBox = h("div");
    function openReset(user, opener) {
      const { form, reason } = resetForm(user, opener, () => clear(resetBox));
      append(clear(resetBox), form);
      reason.focus();
    }

    function resetButton(user) {
      const button = h("button", { type: "button", class: "small", "aria-label": M.t("users.reset.label", { name: user.display_name }),
        onclick: () => openReset(user, button) }, M.t("users.reset.button"));
      return button;
    }

    function draw() {
      const n = rows.length;
      append(clear(box),
        h("p", { class: "muted" }, n ? n + (next ? "+" : "") + (n === 1 ? " account" : " accounts") : "No account matches."),
        n ? h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Users" },
          h("table", { class: "users card-table", role: "table", "aria-label": "Users" },
            h("thead", { role: "rowgroup" }, h("tr", { role: "row" },
              ["Name", "Admin", "Status", "Created", "Last sign-in", "Last seen", "Projects", "Agents", M.t("users.reset.column")]
                .map((t) => h("th", { scope: "col", role: "columnheader" }, t)))),
            h("tbody", { role: "rowgroup" }, rows.map((u) => h("tr", { role: "row", class: u.disabled ? "disabled" : "" },
              h("th", { scope: "row", role: "rowheader", "data-label": "Name", tabindex: "-1" },
                h("span", { class: "user-name" }, u.display_name), h("span", { class: "muted" }, " @" + u.handle),
                u.id === ctx.me.id ? h("span", { class: "muted" }, " (you)") : null),
              h("td", { role: "cell", "data-label": "Admin" }, u.instance_admin ? "instance admin" : "—"),
              h("td", { role: "cell", "data-label": "Status" }, u.disabled ? "disabled" : "active"),
              h("td", { role: "cell", "data-label": "Created" }, formatTime(u.created_at)),
              h("td", { role: "cell", "data-label": "Last sign-in" }, u.last_login_at ? formatAgo(u.last_login_at) : "never"),
              h("td", { role: "cell", "data-label": "Last seen" }, u.last_seen_at ? formatAgo(u.last_seen_at) : "never"),
              h("td", { role: "cell", "data-label": "Projects" }, String(u.memberships)),
              h("td", { role: "cell", "data-label": "Agents" }, String(u.agents)),
              h("td", { role: "cell", "data-label": M.t("users.reset.column") }, u.id === ctx.me.id
                ? h("span", { class: "muted" }, M.t("users.reset.own"))
                : resetButton(u))))))) : null);
      clear(more);
      if (next) append(more, h("button", { type: "button", onclick: () => load(shownFilter, next) }, "Load more"));
    }

    // A newer search wins over an older answer still on its way.
    async function load(filter, cursor) {
      const mine = ++seq;
      status.busy(cursor ? "Loading more…" : "Loading…");
      try {
        const page = await M.api.get(query(filter, cursor));
        if (mine !== seq) return;
        const before = cursor ? rows.length : 0;
        rows = cursor ? rows.concat(page.items) : page.items;
        next = page.next_cursor || null;
        shownFilter = filter;
        draw();
        status.done();
        // Load more is gone or redrawn: the focus goes to the first new row.
        if (cursor && rows.length > before) {
          const first = box.querySelectorAll("tbody tr")[before];
          if (first) first.querySelector("th").focus();
        }
      } catch (err) {
        if (mine !== seq) return;
        status.fail("The users could not be read: ", err);
      }
    }

    // Any change of the filter ends paging of the old one at once.
    const changed = () => { next = null; clear(more); };
    let timer = null;
    q.addEventListener("input", () => {
      changed();
      window.clearTimeout(timer);
      timer = window.setTimeout(() => load(filterNow(), null), SEARCH_MS);
    });
    disabled.addEventListener("change", () => { changed(); load(filterNow(), null); });

    append(root, h("h2", null, "Users of this hub"),
      h("p", { class: "muted" }, "The people with an account here, for you as the instance admin: when they came, signed in and "
        + "were last seen, how many projects they are in and how many agents they own. Being the instance admin opens no project."),
      h("form", { class: "users-filter", role: "search", onsubmit: (e) => { e.preventDefault(); changed(); load(filterNow(), null); } },
        h("label", { for: "users-q" }, "Search by handle or name"), q,
        h("label", { for: "users-disabled" }, "Show"), disabled),
      status.el, box, more, resetBox);
    await load(filterNow(), null);
  }

  M.adminUsers = { section };
})(window.Maity);
