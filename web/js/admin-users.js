// Users of this hub (#/admin/users, docs/api.md §16.1): the humans of the
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

  M.views.adminUsers = async function (ctx, root) {
    if (!ctx.me.instance_admin) {
      append(root, h("h2", null, "Users of this hub"), h("p", null, "Only the instance admin sees the users of this hub."));
      return;
    }
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

    const query = (cursor) => {
      const p = new URLSearchParams();
      if (q.value.trim()) p.set("q", q.value.trim());
      if (disabled.value) p.set("disabled", disabled.value);
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
              h("th", { scope: "row", role: "rowheader", "data-label": "Name" },
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
      if (next) append(more, h("button", { type: "button", onclick: () => load(next) }, "Load more"));
    }

    // A newer search wins over an older answer still on its way.
    async function load(cursor) {
      const mine = ++seq;
      status.busy(cursor ? "Loading more…" : "Loading…");
      try {
        const page = await M.api.get(query(cursor));
        if (mine !== seq) return;
        rows = cursor ? rows.concat(page.items) : page.items;
        next = page.next_cursor || null;
        draw();
        status.done();
      } catch (err) {
        if (mine !== seq) return;
        if (err.status === 404 && err.code === "not_found" && !cursor && !rows.length) {
          clear(box);
          append(box, h("p", null, "This hub has no user list yet."));
          status.done();
        } else {
          status.fail("The users could not be read: ", err);
        }
      }
    }

    let timer = null;
    q.addEventListener("input", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => load(null), SEARCH_MS);
    });
    disabled.addEventListener("change", () => load(null));

    append(root, h("h2", null, "Users of this hub"),
      h("p", { class: "muted" }, "The people with an account here, for you as the instance admin: when they came, signed in and "
        + "were last seen, how many projects they are in and how many agents they own. Being the instance admin opens no project."),
      h("form", { class: "users-filter", role: "search", onsubmit: (e) => { e.preventDefault(); load(null); } },
        h("label", { for: "users-q" }, "Search by handle or name"), q,
        h("label", { for: "users-disabled" }, "Show"), disabled),
      status.el, box, more);
    await load(null);
  };
})(window.Maity);
