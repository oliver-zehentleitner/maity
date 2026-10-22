// (2) The board: cards by status, with claim holder, lease and
// dependencies. Releases are a card kind with their pull requests as the
// hub observed them; readiness and its reasons come from the hub and are
// shown, never computed here (docs/api.md §6.7).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, safeUrl, formatAgo, formatTime } = M.dom;

  const COLUMNS = [
    ["proposed", "Proposed"],
    ["open", "Open"],
    ["in_progress", "In progress"],
    ["blocked", "Blocked"],
    ["review", "Review"],
    ["done", "Done"],
    ["cancelled", "Cancelled"],
  ];

  // Closed cards older than this are left out (closed_after).
  const CLOSED_WINDOW_DAYS = 14;

  // The hub's bound on a pull request number (docs/api.md §6.7).
  const PR_MAX = 2 ** 31;

  // The roles holding releases:write (docs/api.md §2.3).
  const RELEASERS = new Set(["owner", "admin", "reviewer"]);

  const KIND_LABELS = { release: "Release", contract: "Contract", maintenance_round: "Context round" };

  const status = (s) => s.replace("_", " ");

  // The hub's reasons (docs/api.md §6.7), in words; any other reason is
  // shown as it comes, with its details.
  function blockingText(b, byId) {
    const card = (id) => id + (byId[id] ? " (" + byId[id].title + ")" : "");
    switch (b.reason) {
      case "probe_not_configured": return "the hub observes nothing for this project (no forge probe)";
      case "task_open": return card(b.task) + " is not done";
      case "pr_open": return "#" + b.pr + " is not merged";
      case "pr_unverified": return "#" + b.pr + " is not observed yet; what was typed or reported counts for nothing";
      case "pr_not_found": return "#" + b.pr + " is not on the forge (a mistyped number, or a moved repository)";
      case "pr_mismatch": return "#" + b.pr + ": the observed head differs from the reported one";
      case "group_incomplete": return "the group " + b.tasks.join(" + ") + " does not ship complete";
      case "checklist_open": return "checklist item " + b.item + " is open";
      default: {
        const details = Object.keys(b).filter((k) => k !== "reason").map((k) => k + " " + JSON.stringify(b[k]));
        return b.reason + (details.length ? " (" + details.join(", ") + ")" : "");
      }
    }
  }

  function claimLine(ctx, c) {
    const claim = c.claim;
    if (!claim) {
      return h("p", { class: "claim unclaimed" },
        c.assigned_to ? "Assigned to " + ctx.nameOf(c.assigned_to) + ", not claimed" : "Unclaimed");
    }
    return h("p", { class: "claim" },
      "Claimed by ", h("strong", null, ctx.nameOf(claim.holder)), " · " + formatAgo(claim.since),
      claim.expired
        ? h("span", { class: "expired" }, " · lease expired " + formatTime(claim.lease_until))
        : (claim.lease_until ? h("span", { class: "lease" }, " · lease until " + formatTime(claim.lease_until)) : null));
  }

  function edges(label, ids, byId, frozen) {
    if (!ids || !ids.length) return null;
    if (frozen) return h("div", { class: "deps" }, h("span", { class: "label" }, label), h("ul", null, ids.map((id) => h("li", null, id))));
    return h("div", { class: "deps" },
      h("span", { class: "label" }, label),
      h("ul", null, ids.map((id) => {
        const dep = byId[id];
        const closed = dep && (dep.status === "done" || dep.status === "cancelled");
        return h("li", { class: dep ? (closed ? "met" : "unmet") : "" },
          id + (dep ? " — " + dep.title + " (" + status(dep.status) + ")" : ""));
      })));
  }

  function checkpoint(c) {
    const cp = c.checkpoint;
    if (!cp) return null;
    return h("div", { class: "checkpoint" },
      h("span", { class: "label" }, "Checkpoint " + formatAgo(cp.updated_at) + " (" + cp.verification + ")"),
      h("p", { class: "pre" }, "Done: " + cp.last_step + "\nNext: " + cp.next_step),
      cp.branch ? h("p", { class: "muted" }, cp.branch + (cp.head ? " @ " + cp.head : "")) : null);
  }

  function report(c) {
    const r = c.report;
    if (!r) return null;
    const pr = r.pr ? "PR #" + r.pr.number : (r.pr_status === "none" ? "no PR" : "PR unknown: " + (r.pr_unknown_reason || "—"));
    const observed = r.observed
      ? "observed " + r.observed.pr_state + ", checks " + r.observed.checks + " · " + formatAgo(r.observed.observed_at)
      : "not observed by the hub";
    return h("div", { class: "report" + (r.mismatch ? " mismatch" : "") },
      h("span", { class: "label" }, "Report " + formatAgo(r.reported_at) + " (" + r.verification + ")"),
      h("p", { class: "pre" }, r.summary),
      h("p", { class: "muted" }, pr + " · " + observed),
      r.mismatch ? h("p", { class: "flag" }, "The observed head differs from the reported one.") : null);
  }

  // One pull request as the hub has it. Only what the forge probe observed
  // is a fact; a typed or reported state is shown as a claim beside
  // "unverified" (docs/api.md §6.7).
  function prState(pr) {
    if (pr.found === false) return h("td", { class: "pr-missing" }, "not on the forge");
    if (!pr.observed_at) {
      return h("td", { class: "pr-unverified" }, "unverified",
        pr.state ? h("span", { class: "muted" }, " · " + pr.source + " as " + pr.state) : null);
    }
    return h("td", { class: "pr-" + pr.state }, pr.state || "—");
  }

  function pullRequests(rel) {
    const prs = rel.pull_requests || [];
    if (!prs.length) return h("p", { class: "muted" }, "No pull requests yet: they come from the shipped cards' reports, or are typed in.");
    return h("table", { class: "prs" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col" }, "PR"), h("th", { scope: "col" }, "State"),
        h("th", { scope: "col" }, "Checks"), h("th", { scope: "col" }, "Observed"))),
      h("tbody", null, prs.map((pr) => h("tr", null,
        h("td", null, safeUrl(pr.url) ? h("a", { href: safeUrl(pr.url), rel: "noopener noreferrer" }, "#" + pr.number) : "#" + pr.number,
          " " + (pr.title || ""), h("span", { class: "muted" }, " · " + pr.source + (pr.task_id ? " by " + pr.task_id : ""))),
        prState(pr),
        h("td", { class: "checks-" + pr.checks }, pr.observed_at && pr.checks ? pr.checks : "—"),
        h("td", null, pr.observed_at ? formatAgo(pr.observed_at) + (pr.head_sha ? " @ " + pr.head_sha : "") : "never")))));
  }

  // The connected ships_with components: they ship together or not at all.
  // Complete only by the hub's word: green when the release is ready, amber
  // when the hub names the group incomplete, neither while it observes
  // nothing. A member outside the release's depends_on is said so; a live
  // status is shown only for an open release, never in a frozen record.
  function shipGroups(c, byId, closed) {
    const rel = c.release;
    const groups = rel.groups || [];
    if (!groups.length) return null;
    const r = rel.readiness || { ready: false, blocking: [] };
    const incomplete = new Set((r.blocking || [])
      .filter((b) => b.reason === "group_incomplete").map((b) => (b.tasks || []).join(" ")));
    const shipped = new Set(c.depends_on || []);
    const member = (id) => id
      + (shipped.has(id) ? "" : " (not in this release)")
      + (!closed && byId[id] ? " (" + status(byId[id].status) + ")" : "");
    return h("div", { class: "deps groups" },
      h("span", { class: "label" }, "Ship together"),
      h("ul", null, groups.map((g) => h("li", {
        class: r.ready ? "met" : (incomplete.has(g.join(" ")) ? "unmet" : "unknown"),
      }, g.map(member).join(" + ")))));
  }

  function tagLine(rel) {
    const name = rel.tag ? rel.tag.name : "v" + rel.version;
    if (!rel.tag || !rel.tag.observed_at) return h("p", { class: "muted" }, "Tag " + name + ": not observed");
    return h("p", { class: "muted" }, "Tag " + name + ": "
      + (rel.tag.found ? "on the forge" + (rel.tag.sha ? " @ " + rel.tag.sha : "") : "not on the forge")
      + " · " + formatAgo(rel.tag.observed_at));
  }

  function checklistView(ctx, rel) {
    if (!rel.checklist || !rel.checklist.length) return null;
    return h("ul", { class: "checklist" }, rel.checklist.map((item) =>
      h("li", { class: item.done ? "met" : "unmet" }, (item.done ? "✓ " : "○ ") + item.text, tickedBy(ctx, item))));
  }

  const tickedBy = (ctx, item) => (item.done && item.by
    ? h("span", { class: "muted" }, " · " + ctx.nameOf(item.by) + (item.at ? " " + formatAgo(item.at) : ""))
    : null);

  // The hub's refusals of a release edit (docs/api.md §6.7), in words.
  function editError(err) {
    if (err.code === "invalid_transition") return { message: "this release is closed; its record does not change" };
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) {
      return { message: Object.keys(fields).map((k) => {
        const why = String(fields[k]);
        if (why.startsWith("unknown_item:")) return "the checklist changed meanwhile (" + why.slice(13) + " is gone); reload";
        if (why === "duplicate_id") return "an item is listed twice";
        return k + ": " + why;
      }).join("; ") };
    }
    return err;
  }

  // Editing a release for members with releases:write (owner, admin,
  // reviewer; docs/api.md §2.3, §6.7): tick items, edit the checklist, and
  // the typed pull requests. The hub's answer redraws this card alone.
  function releaseEditor(ctx, c, redraw) {
    const rel = c.release;
    const path = ctx.base + "/tasks/" + encodeURIComponent(c.id);
    const status = M.statusLine();
    const patch = async (release, what, focusId) => {
      status.busy("Saving " + what + "…");
      try {
        redraw(await M.api.patch(path, { release }), focusId);
      } catch (err) {
        status.fail("Not saved: ", editError(err));
      }
    };

    function checklist() {
      const items = rel.checklist || [];
      const list = h("ul", { class: "checklist editable" }, items.map((item) => {
        const id = "chk-" + c.id + "-" + item.id;
        const box = h("input", { type: "checkbox", id });
        box.checked = !!item.done;
        box.addEventListener("change", async () => {
          box.disabled = true;
          status.busy(box.checked ? "Ticking…" : "Unticking…");
          try {
            redraw(await M.api.post(path + "/checklist/" + encodeURIComponent(item.id), { done: box.checked }), id);
          } catch (err) {
            box.checked = !box.checked;
            box.disabled = false;
            status.fail("Not saved: ", err.status === 404
              ? { message: "this item is gone (removed meanwhile); reload the board" } : editError(err));
          }
        });
        return h("li", { class: item.done ? "met" : "unmet" }, box, h("label", { for: id }, " " + item.text), tickedBy(ctx, item));
      }));
      const box = h("div", { class: "release-edit" });
      append(box,
        items.length ? list : h("p", { class: "muted" }, "No checklist items."),
        h("div", { class: "row" },
          h("button", { type: "button", class: "small", id: "edit-checklist-" + c.id, onclick: () => editChecklist(box) }, "Edit checklist"),
          h("button", { type: "button", class: "small", id: "edit-typed-" + c.id, onclick: () => editTyped(box) }, "Typed pull requests")),
        status.el);
      return box;
    }

    // A list editor: rows of inputs, add and remove, Save sends the list.
    // Each row's controls are labelled with their row number; after Save or
    // Cancel the focus goes back to the button that opened the editor.
    function rowsEditor(box, title, rows, makeRow, toBody, what, opener) {
      const list = h("ol", { class: "edit-rows" });
      let n = 0;
      const add = (row) => {
        n += 1;
        const li = h("li", null, makeRow(row, n),
          h("button", { type: "button", class: "small", "aria-label": "Remove row " + n, onclick: () => li.remove() }, "Remove"));
        append(list, li);
        return li;
      };
      rows.forEach(add);
      const form = h("form", {
        class: "rows-form",
        onsubmit: (e) => {
          e.preventDefault();
          const body = toBody(list);
          if (body) patch(body, what, opener);
        },
      },
      h("h4", null, title), list,
      h("div", { class: "row" },
        h("button", { type: "button", class: "small", onclick: () => {
          const li = add(null);
          const first = li.querySelector("input");
          if (first) first.focus();
        } }, "Add"),
        h("button", { type: "submit" }, "Save"),
        h("button", { type: "button", onclick: () => redraw(c, opener) }, "Cancel")),
      status.el);
      M.dom.clear(box);
      append(box, form);
      const first = list.querySelector("input");
      if (first) first.focus();
    }

    function editChecklist(box) {
      rowsEditor(box, "Checklist", rel.checklist || [], (item, n) => {
        const input = h("input", { class: "item-text", maxlength: "200", "aria-label": "Checklist item " + n });
        input.value = item ? item.text : "";
        if (item) input.setAttribute("data-id", item.id);
        return input;
      }, (list) => {
        const items = Array.from(list.querySelectorAll("input.item-text")).map((i) => ({ id: i.getAttribute("data-id") || undefined, text: i.value.trim() }))
          .filter((i) => i.text);
        // An item keeps its tick by its id; a new one gets the next id from the hub.
        return { checklist: items.map((i) => (i.id ? { id: i.id, text: i.text } : { text: i.text })) };
      }, "the checklist", "edit-checklist-" + c.id);
    }

    function editTyped(box) {
      rowsEditor(box, "Typed pull requests", rel.pull_requests_typed || [], (pr, n) => {
        const number = h("input", { class: "pr-number", type: "number", min: "1", max: String(PR_MAX), "aria-label": "Pull request number, row " + n });
        number.value = pr ? String(pr.number) : "";
        const state = h("select", { class: "pr-claim", "aria-label": "State you attest, row " + n },
          [["", "no state"], ["open", "open"], ["merged", "merged"], ["closed", "closed"]].map(([v, l]) => h("option", { value: v }, l)));
        state.value = pr && pr.state ? pr.state : "";
        return h("span", { class: "row" }, "#", number, state);
      }, (list) => {
        // A row with neither number nor state is dropped; anything else must
        // be a whole number from 1 to 2^31, each number once (docs/api.md §6.7).
        const rows = Array.from(list.querySelectorAll("li")).map((li) => ({
          raw: li.querySelector("input.pr-number").value.trim(),
          state: li.querySelector("select.pr-claim").value || null,
        })).filter((r) => r.raw || r.state);
        const bad = rows.find((r) => !/^[0-9]+$/.test(r.raw) || Number(r.raw) < 1 || Number(r.raw) > PR_MAX);
        if (bad) {
          status.fail("Not saved: ", { message: "a pull request number is a whole number from 1 to " + PR_MAX + (bad.raw ? " (not " + bad.raw + ")" : "") });
          return null;
        }
        const seen = new Set();
        const twice = rows.find((r) => seen.has(Number(r.raw)) || !seen.add(Number(r.raw)));
        if (twice) {
          status.fail("Not saved: ", { message: "#" + Number(twice.raw) + " is listed twice" });
          return null;
        }
        return { pull_requests_typed: rows.map((r) => ({ number: Number(r.raw), state: r.state })) };
      }, "the typed pull requests", "edit-typed-" + c.id);
    }

    return { checklist };
  }

  function release(ctx, c, byId, closed, redraw) {
    const editor = !closed && ctx.canRelease && redraw ? releaseEditor(ctx, c, redraw) : null;
    const rel = c.release;
    const r = rel.readiness || { ready: false, blocking: [] };
    const noProbe = r.blocking.some((b) => b.reason === "probe_not_configured");
    return [
      closed ? h("p", { class: "muted" }, "Closed: its pull requests, groups and readiness are the record frozen when it closed; "
        + "later changes do not alter them.") : null,
      pullRequests(rel),
      shipGroups(c, byId, closed),
      editor ? null : checklistView(ctx, rel),
      editor ? editor.checklist() : null,
      r.ready
        ? h("div", { class: "readiness ready" },
          c.status === "done"
            ? h("strong", null, "Shipped: it was ready when it closed.")
            : [h("strong", null, "Ready to tag"),
              h("span", null, " — every shipped card is done, every pull request observed merged, every group complete and the checklist done.")])
        : h("div", { class: "readiness not-ready" }, h("strong", null, "Not ready: "),
          h("ul", null, r.blocking.map((b) => h("li", null, blockingText(b, byId))))),
      noProbe && !closed
        ? h("p", { class: "flag" }, "Without a forge probe the hub cannot see this project's pull requests or tag, "
          + "so it never calls the release ready, and it can be cancelled but not marked done. The probe needs "
          + "the project's repository on a forge the hub has a token for.")
        : null,
      tagLine(rel),
    ];
  }

  // A contract's arbiter may be a role ("role:admin"): named in words.
  const arbiterName = (ctx, a) => (/^role:/.test(a || "") ? "the " + a.slice(5) + "s" : ctx.nameOf(a));

  function card(ctx, c, byId) {
    const frozen = c.kind === "release" && (c.status === "done" || c.status === "cancelled");
    // The hub's answer to an edit replaces this card in place.
    // focusId names the control to focus in the new card (the box just
    // ticked, the button that opened an editor), so the focus is not lost.
    const redraw = (updated, focusId) => {
      byId[updated.id] = updated;
      const fresh = card(ctx, updated, byId);
      el.parentNode.insertBefore(fresh, el);
      el.remove();
      const target = focusId && document.getElementById(focusId);
      if (target) target.focus();
    };
    const el = h("article", { class: "card card-" + c.kind, "aria-label": c.title },
      h("header", null,
        h("span", { class: "card-id" }, c.id),
        KIND_LABELS[c.kind]
          ? h("span", { class: "badge " + c.kind }, KIND_LABELS[c.kind] + (c.kind === "release" ? " " + c.release.version : ""))
          : null,
        c.label ? h("span", { class: "label-tag" }, c.label) : null,
        c.area ? h("span", { class: "area" }, c.area) : null),
      h("h3", null, c.title),
      claimLine(ctx, c),
      edges(c.kind === "release" ? "Ships" : "Depends on", c.depends_on, byId, frozen),
      edges("Ships with", c.ships_with, byId),
      c.blocked_by_request
        ? h("p", { class: "flag" }, "Waits for ", h("a", { href: ctx.link("inbox") }, "an answer"), " (",
          h("span", { class: "request-id" }, c.blocked_by_request), ")")
        : null,
      c.contract
        ? h("p", { class: "muted" }, "Contract " + c.contract.state + " · arbiter " + arbiterName(ctx, c.contract.arbiter)
          + ((c.contract.watchers || []).length ? " · watched by " + c.contract.watchers.map(ctx.nameOf).join(", ") : ""))
        : null,
      checkpoint(c),
      report(c),
      c.kind === "release" && c.release ? release(ctx, c, byId, frozen, redraw) : null);
    return el;
  }

  M.views.board = async function (ctx, root) {
    ctx.canRelease = RELEASERS.has(ctx.role);
    const since = new Date(Date.now() - CLOSED_WINDOW_DAYS * 86400000).toISOString().replace(/\.\d{3}Z$/, "Z");
    const tasks = await M.api.getAll(ctx.base + "/tasks?status=all&closed_after=" + encodeURIComponent(since));
    const byId = {};
    tasks.items.forEach((t) => { byId[t.id] = t; });
    const known = new Set(COLUMNS.map(([s]) => s));
    const other = tasks.items.filter((t) => !known.has(t.status));

    append(root, h("h2", null, "Board"),
      h("p", { class: "muted" }, "Every open card, and the done and cancelled ones of the last " + CLOSED_WINDOW_DAYS + " days."),
      tasks.items.length
        ? null
        : h("p", { class: "first-hint" }, "No cards yet. Your agents put the work here: they propose cards in their "
          + "areas, claim them and report when they are done. Ask an agent in its chat to propose what it will work on."),
      h("div", { class: "columns" },
        COLUMNS.map(([s, label]) => {
          const cards = tasks.items.filter((t) => t.status === s);
          return h("section", { class: "column", "aria-label": label },
            h("h3", { class: "column-head" }, label, h("span", { class: "count" }, String(cards.length))),
            cards.length ? cards.map((c) => card(ctx, c, byId)) : h("p", { class: "muted" }, "—"));
        }),
        other.length
          ? h("section", { class: "column", "aria-label": "Other" },
            h("h3", { class: "column-head" }, "Unknown status"),
            other.map((c) => card(ctx, c, byId)))
          : null));
  };
})(window.Maity);
