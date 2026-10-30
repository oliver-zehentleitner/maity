// Users of this hub, the Users section of /admin (docs/api.md §16.1;
// js/instance-admin.js shows it to the instance admin only): the humans of the
// instance for its admin — counts and times, never content. Searchable by
// handle or name and filterable by disabled; paged by the hub's cursor.
// Being the instance admin opens no project: this view links nowhere into
// one.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const PAGE = 50;
  const SEARCH_MS = 300;

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

    function draw() {
      const n = rows.length;
      append(clear(box),
        h("p", { class: "muted" }, n ? n + (next ? "+" : "") + (n === 1 ? " account" : " accounts") : "No account matches."),
        n ? h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Users" },
          h("table", { class: "users card-table", role: "table", "aria-label": "Users" },
            h("thead", { role: "rowgroup" }, h("tr", { role: "row" },
              ["Name", "Admin", "Status", "Created", "Last sign-in", "Last seen", "Projects", "Agents"]
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
              h("td", { role: "cell", "data-label": "Agents" }, String(u.agents))))))) : null);
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
        if (await M.api.missingRoute(err, "GET", "/admin/users")) {
          M.api.absent.note("GET", "/admin/users");
          if (root.classList.contains("admin-section")) { root.remove(); return; }
          clear(box);
          append(box, h("p", null, "This hub has no user list yet."));
          status.done();
        } else {
          status.fail("The users could not be read: ", err);
        }
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
      status.el, box, more);
    await load(filterNow(), null);
  }

  M.adminUsers = { section };
})(window.Maity);
