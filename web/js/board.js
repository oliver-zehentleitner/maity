// (2) The board: cards by status, with claim holder, lease and
// dependencies. Releases are a card kind with their pull requests as the
// hub observed them; readiness and its reasons come from the hub and are
// shown, never computed here (docs/api.md §6.7).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl, formatAgo, formatTime } = M.dom;

  const COLUMNS = M.boardEdit.COLUMNS;

  // Closed cards older than this are left out (closed_after).
  const CLOSED_WINDOW_DAYS = 14;
  // A closed column draws the cards closed last up to this, the rest on "Show more" (tsk-a5pxwgkgr73e):
  // 783 closed cards cost a full redraw about 640 ms in Chromium, 100 of them about 100 ms.
  const CLOSED_SHOWN = 50;
  // The open column groups the board reads side by side; the closed one, with its window, after them.
  const LIST_GROUPS = ["proposed", "open", "in_progress", "blocked,review"];
  // The read of the cards changed while the groups were read (below): a page of the newest, and how
  // far before the reads began it looks.
  const RECENT_PAGE = 50;
  const RECONCILE_MARGIN_MS = 60000;
  const RECONCILE_PASSES = 3;
  // The overview counts closed cards over the same window (js/overview.js).
  M.boardWindowDays = CLOSED_WINDOW_DAYS;

  // The hub's bound on a pull request number (docs/api.md §6.7).
  const PR_MAX = 2 ** 31;

  const KIND_LABELS = {
    get release() { return M.t("board.kind.release"); },
    get contract() { return M.t("board.kind.contract"); },
    get maintenance_round() { return M.t("board.kind.maintenance_round"); },
    get setup() { return M.t("board.kind.setup"); },
  };

  // A pull request's checks as the forge reports them (§6.11), in words.
  const CHECK_WORDS = {
    success: () => M.t("board.checks.success"), failure: () => M.t("board.checks.failure"), pending: () => M.t("board.checks.pending"),
    none: () => M.t("board.checks.none"), unknown: () => M.t("board.checks.unknown"),
    // A required check's status (§6.6) has two words of its own.
    cancelled: () => M.t("board.checks.cancelled"), missing: () => M.t("board.checks.missing"),
  };
  const VERIFICATION_WORDS = { signed: () => M.t("board.verification.signed"), bearer: () => M.t("board.verification.bearer") };
  const word = (words, value) => (Object.hasOwn(words, value) ? words[value]() : value);
  // A card's status inside a sentence, lowercase; a status the hub adds later reads as its own word.
  const statusWord = (s) => M.dom.word("status", s).replace("_", " ");

  const PRESENCE_WORDS = {
    online: () => M.t("chat.presence.online"), away: () => M.t("chat.presence.away"),
    offline: () => M.t("chat.presence.offline"), paused: () => M.t("chat.presence.paused"),
  };
  const presenceWord = (p) => (!p ? M.t("chat.presence.unknown") : Object.hasOwn(PRESENCE_WORDS, p) ? PRESENCE_WORDS[p]() : p);

  // The hub's reasons (docs/api.md §6.7), in words; any other reason is
  // shown as it comes, with its details.
  function blockingText(b, byId) {
    const card = (id) => id + (byId[id] ? " (" + byId[id].title + ")" : "");
    switch (b.reason) {
      case "probe_not_configured": return M.t("board.blocking.probe_not_configured");
      case "task_open": return M.t("board.blocking.task_open", { card: card(b.task) });
      case "pr_open": return M.t("board.blocking.pr_open", { pr: "#" + b.pr });
      case "pr_unverified": return M.t("board.blocking.pr_unverified", { pr: "#" + b.pr });
      case "pr_not_found": return M.t("board.blocking.pr_not_found", { pr: "#" + b.pr });
      case "pr_mismatch": return M.t("board.blocking.pr_mismatch", { pr: "#" + b.pr });
      case "group_incomplete": return M.t("board.blocking.group_incomplete", { tasks: b.tasks.join(" + ") });
      case "checklist_open": return M.t("board.blocking.checklist_open", { item: b.item });
      default: {
        const details = Object.keys(b).filter((k) => k !== "reason").map((k) => k + " " + JSON.stringify(b[k]));
        return b.reason + (details.length ? " (" + details.join(", ") + ")" : "");
      }
    }
  }

  // A member as the board names them: @handle, the full name as tooltip.
  const handleOf = (ctx, id) => {
    const m = (ctx.memberById || {})[id];
    return m && m.handle ? "@" + M.dom.handleOf(ctx, m) : ctx.nameOf(id);
  };

  // Who works on it, led by a dot: claimed (live), the lease run out, or
  // nobody yet. The dot is decoration; the words say it.
  function holderPresence(ctx, holder) {
    const member = (ctx.memberById || {})[holder];
    return h("span", { class: "holder-presence", "data-holder": holder }, member
      ? [" · ", h("span", { class: "dot " + (member.presence || "offline"), "aria-hidden": "true" }),
        " " + presenceWord(member.presence), M.dom.isSilentAgent(member) ? [" · ", M.dom.silentSince(member, ctx.canAdmin)] : null]
      : " · " + M.t("board.presence_unknown"));
  }

  function claimLine(ctx, c) {
    const claim = c.claim;
    const dot = (kind) => h("span", { class: "claim-dot " + kind, "aria-hidden": "true" });
    if (!claim) {
      return h("p", { class: "claim unclaimed" }, dot("none"), c.assigned_to ? M.t("board.claim.assigned_unclaimed") : M.t("board.claim.unclaimed"));
    }
    const who = h("strong", { title: ctx.nameOf(claim.holder) }, M.dom.memberRef(ctx, claim.holder, { text: "handle" }));
    if (claim.expired) {
      return h("p", { class: "claim expired" }, dot("expired"), who, holderPresence(ctx, claim.holder), " · ", M.t("board.claim.lease_expired", { time: formatTime(claim.lease_until) }));
    }
    return h("p", { class: "claim live" }, dot("live"), M.tn("board.claim.claimed_by", { who }), holderPresence(ctx, claim.holder), " · " + formatAgo(claim.since),
      claim.lease_until ? h("span", { class: "lease" }, " · ", M.t("board.claim.lease_until", { time: formatTime(claim.lease_until) })) : null);
  }

  // Whose card it is, in its header: a small picture and the handle, the
  // full name as tooltip and as what a screen reader says.
  function assignee(ctx, c) {
    if (!c.assigned_to) return null;
    const m = (ctx.memberById || {})[c.assigned_to];
    const name = ctx.nameOf(c.assigned_to);
    return h("a", { class: "card-assignee kind-" + (m && m.kind === "human" ? "human" : "agent"), href: ctx.link("team", c.assigned_to),
      title: name, "aria-label": M.t("board.assigned_to", { name }) },
      m ? M.avatar(m, 16) : null, h("span", { "aria-hidden": "true" }, handleOf(ctx, c.assigned_to)));
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
          id + (dep ? " — " + dep.title + " (" + statusWord(dep.status) + ")" : ""));
      })));
  }

  // Subtasks (docs/api.md §6.4). A child stands under its parent, folded,
  // the hub's open/total beside the toggle; one whose parent is not on the
  // board shows on its own with the parent's id. Which parents are unfolded
  // is kept per project while the page lives.
  const unfolded = new Set();
  const cardLink = (ctx, id, words) => h("a", { class: "card-ref", href: ctx.link("tasks", id) }, words || id);
  function childRow(ctx, t) {
    return h("li", { class: "subtask" + (t.status === "done" || t.status === "cancelled" ? " met" : ""), "data-card": t.id },
      h("span", { class: "subtask-status" }, statusWord(t.status)), " ", cardLink(ctx, t.id), " ", cardLink(ctx, t.id, t.title));
  }
  function subtasks(ctx, c, byId, inPanel) {
    const counts = c.children || { open: 0, total: 0 };
    if (!counts.total) return null;
    const kids = Object.values(byId).filter((t) => t.parent === c.id).sort(M.boardEdit.byOrder);
    const away = counts.total - kids.length;
    const list = h("ul", { class: "subtask-list" }, kids.map((t) => childRow(ctx, t)),
      away > 0 ? h("li", { class: "muted" }, M.t("board.subtasks.not_loaded", { count: away })) : null);
    const words = M.t("board.subtasks.words", { open: counts.open, total: counts.total });
    if (inPanel) return h("div", { class: "subtasks" }, h("span", { class: "label" }, words), list);
    const key = ctx.slug + "/" + c.id;
    const listId = "subtasks-" + c.id;
    list.id = listId;
    list.hidden = !unfolded.has(key);
    const toggle = h("button", { type: "button", class: "small subtask-toggle", "aria-expanded": String(!list.hidden), "aria-controls": listId,
      onclick: () => {
        list.hidden = !list.hidden;
        if (list.hidden) unfolded.delete(key); else unfolded.add(key);
        toggle.setAttribute("aria-expanded", String(!list.hidden));
      } }, words);
    return h("div", { class: "subtasks" }, toggle, list);
  }
  // The parent and the related cards, as links (navigation only).
  function family(ctx, c, inPanel) {
    return [
      c.parent ? h("p", { class: "card-parent muted" }, M.tn("board.subtask_of", { card: cardLink(ctx, c.parent) })) : null,
      inPanel && (c.related || []).length
        ? h("div", { class: "deps related" }, h("span", { class: "label" }, M.t("board.related")), h("ul", null, c.related.map((id) => h("li", null, cardLink(ctx, id)))))
        : null,
    ];
  }

  // A refused subtask edit in the hub's own words with every reason it
  // names (subtasks_proposed, too_deep, has_children, parent_closed, cycle,
  // …); null for any other refusal, which the form says as it says every
  // other (an ambiguous mention with its long forms, a closed project).
  function hubWords(err) {
    const fields = (err.details && err.details.fields) || {};
    const edge = Object.keys(fields).filter((f) => f === "parent" || f === "related");
    if (edge.length) return { message: err.message + " (" + edge.map((f) => f + ": " + fields[f]).join("; ") + ")" };
    if (err.details && err.details.reason === "subtasks_proposed") return { message: err.message + " (subtasks_proposed)" };
    if (err.code === "unknown_task") return { message: err.message + " (unknown_task)" };
    return null;
  }

  // In the opened card: its parent and related cards for whoever may edit
  // it, and a subtask to start under it for every member.
  function familyEditor(ctx, c, byId, manage) {
    if (!manage || !manage.reload) return null;
    const closed = (t) => t.status === "done" || t.status === "cancelled";
    const others = Object.values(byId).filter((t) => t.id !== c.id && !t._searchClosed);
    const parts = [];
    if (M.boardEdit.editable(ctx, c)) {
      const path = ctx.base + "/tasks/" + encodeURIComponent(c.id);
      const said = M.statusLine();
      const hasKids = !!(c.children && c.children.total);
      // A parent: no release, not a subtask itself, not closed (unless it is the current one).
      const parentSel = c.kind === "release" || hasKids ? null
        : h("select", { id: "card-parent-" + c.id, "data-focus": "parent:" + c.id }, h("option", { value: "" }, M.t("board.family.no_parent")),
          others.filter((t) => t.kind !== "release" && !t.parent && (t.id === c.parent || !closed(t))).map((t) => h("option", { value: t.id }, t.id + " · " + t.title)));
      // A parent or related card the board did not load (closed before its
      // window) stays chosen as it is: a save never drops what it cannot show.
      const notLoaded = (id) => h("option", { value: id }, M.t("board.family.not_loaded", { id }));
      if (parentSel && c.parent && !others.some((t) => t.id === c.parent)) parentSel.appendChild(notLoaded(c.parent));
      if (parentSel) parentSel.value = c.parent || "";
      const relatedSel = h("select", { id: "card-related-" + c.id, multiple: true, size: "4" },
        others.map((t) => { const o = h("option", { value: t.id }, t.id + " · " + t.title); o.selected = (c.related || []).includes(t.id); return o; }),
        (c.related || []).filter((id) => !others.some((t) => t.id === id)).map((id) => { const o = notLoaded(id); o.selected = true; return o; }));
      const needsSel = M.boardEdit.needsSelect(ctx, "card-needs-" + c.id, c.needs);
      const save = h("button", { type: "submit", "data-focus": "family:" + c.id }, M.t("board.save"));
      parts.push(h("form", {
        class: "card-family-form",
        onsubmit: async (e) => {
          e.preventDefault();
          const body = {};
          if (parentSel && parentSel.value !== (c.parent || "")) body.parent = parentSel.value || null;
          if (needsSel.value !== (c.needs || "")) body.needs = needsSel.value || null;
          const chosen = Array.from(relatedSel.querySelectorAll("option")).filter((o) => o.selected).map((o) => o.getAttribute("value"));
          if (chosen.slice().sort().join() !== (c.related || []).slice().sort().join()) body.related = chosen;
          if (!Object.keys(body).length) return;
          save.disabled = true;
          said.busy(M.t("board.saving"));
          try {
            await M.api.patch(path, body);
          } catch (err) {
            save.disabled = false;
            said.fail(M.t("board.not_saved"), hubWords(err) || M.boardEdit.said(err));
            return;
          }
          await manage.reload("family:" + c.id);
        },
      },
      h("h4", null, M.t("board.family.title")),
      parentSel ? [h("label", { for: parentSel.id }, M.t("board.family.parent")), parentSel]
        : h("p", { class: "hint" }, hasKids ? M.t("board.family.has_kids") : M.t("board.family.release")),
      h("label", { for: relatedSel.id }, M.t("board.family.related")), relatedSel,
      h("label", { for: needsSel.id }, M.t("cards.new.field.needs")), needsSel,
      save, said.el));
    }
    // A subtask under it: not under a subtask, a release or a closed card (§6.4).
    if (!c.parent && c.kind !== "release" && !closed(c)) {
      const box = h("div", { class: "new-subtask-box" });
      const start = h("button", { type: "button", class: "small", "aria-expanded": "false", "data-focus": "subtask:" + c.id,
        onclick: () => {
          if (start.getAttribute("aria-expanded") === "true") { clear(box); start.setAttribute("aria-expanded", "false"); return; }
          const f = M.boardEdit.newCardForm(ctx, others, async (body) => {
            try {
              await M.api.post(ctx.base + "/tasks", body);
            } catch (err) {
              throw hubWords(err) || err;
            }
            await manage.reload("subtask:" + c.id);
          }, () => { clear(box); start.setAttribute("aria-expanded", "false"); start.focus(); }, c);
          append(clear(box), f.form);
          start.setAttribute("aria-expanded", "true");
          f.focus();
        } }, M.t("board.new_subtask"));
      parts.push(h("div", { class: "card-new-subtask" }, start, box));
    }
    return parts.length ? h("div", { class: "card-family" }, parts) : null;
  }

  function checkpoint(ctx, c) {
    const cp = c.checkpoint;
    if (!cp) return null;
    // Two lines at most on the card; the whole text as its tooltip.
    const said = M.t("board.checkpoint.text", { done: cp.last_step, next: cp.next_step });
    return h("div", { class: "checkpoint" },
      h("span", { class: "label" }, M.t("board.checkpoint.label", { ago: formatAgo(cp.updated_at), verification: word(VERIFICATION_WORDS, cp.verification) })),
      h("p", { class: "pre clamp", title: said }, M.ids.link(said, M.ids.where(ctx))),
      cp.branch ? h("p", { class: "muted" }, cp.branch + (cp.head ? " @ " + cp.head : "")) : null);
  }

  // The two signatures under reviewer_and_tester (§6.4), while the card waits for them.
  function approvals(ctx, c) {
    if (c.status !== "review" || (ctx.project.policy || {}).done_authority !== "reviewer_and_tester") return null;
    const a = c.approvals || {};
    const signed = (m) => ({ name: ctx.nameOf(m.by), ago: formatAgo(m.at), revision: m.revision });
    return h("ul", { class: "card-approvals" },
      h("li", null, a.review ? M.t("board.approvals.review.signed", signed(a.review)) : M.t("board.approvals.review.none")),
      h("li", null, a.test ? M.t("board.approvals.test.signed", signed(a.test)) : M.t("board.approvals.test.none")));
  }

  function report(ctx, c) {
    const r = c.report;
    if (!r) return null;
    const pr = r.pr ? M.t("board.report.pr", { number: "#" + r.pr.number }) : (r.pr_status === "none" ? M.t("board.report.no_pr") : M.t("board.report.pr_unknown", { reason: r.pr_unknown_reason || "—" }));
    let observed = r.observed
      ? M.t("board.report.observed", { state: M.dom.word("pr", r.observed.pr_state), checks: word(CHECK_WORDS, r.observed.checks), ago: formatAgo(r.observed.observed_at) })
      : M.t("board.report.not_observed");
    // The project's required check on the head (§6.6), when the project names one.
    const rc = r.observed && r.observed.required_check;
    if (rc) observed = M.t("board.report.required_check", { text: observed, name: rc.name, status: word(CHECK_WORDS, rc.status) });
    return h("div", { class: "report" + (r.mismatch ? " mismatch" : "") },
      h("span", { class: "label" }, M.t("board.report.label", { ago: formatAgo(r.reported_at), verification: word(VERIFICATION_WORDS, r.verification) })),
      h("div", { class: "md report-summary" }, M.markdown(r.summary, M.ids.where(ctx), { mentions: r.mentions, field: "summary", hrefOf: (id) => ctx.link("team", id), ctx })),
      h("p", { class: "muted" }, pr + " · " + observed),
      r.mismatch ? h("p", { class: "flag" }, M.t("board.report.mismatch")) : null,
      whyLine(ctx, r));
  }

  // The why of a code report (docs/api.md §6.23): the entry that keeps it,
  // as a link to its file at the report's head on the forge, the entry's id
  // beside it; or the reason there is none, for the reviewer to judge.
  function whyLine(ctx, r) {
    const w = r.why;
    if (!w) return null;
    if (typeof w.none === "string") return h("p", { class: "report-why" }, M.t("board.why.none", { reason: w.none }));
    if (typeof w.ref !== "string") return null;
    const cut = w.ref.indexOf("#");
    const path = cut < 0 ? w.ref : w.ref.slice(0, cut);
    const id = cut < 0 ? "" : w.ref.slice(cut + 1);
    const repo = M.ids.where(ctx).repository;
    const safe = typeof repo === "string" && /^https:\/\//.test(repo) && /^[0-9a-f]{40}$/.test(r.head || "")
      && /^[A-Za-z0-9._\/-]+\.md$/.test(path) && !path.startsWith("/") && !path.split("/").includes("..");
    const href = safe ? repo.replace(/\/+$/, "").replace(/\.git$/, "") + "/blob/" + r.head + "/" + path : null;
    return h("p", { class: "report-why" }, M.tn("board.why.ref", { file: href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, path) : h("code", null, path) }),
      id ? h("span", { class: "muted" }, " #" + id) : null);
  }

  // One pull request as the hub has it. Only what the forge probe observed
  // is a fact; a typed or reported state is shown as a claim beside
  // "unverified" (docs/api.md §6.7).
  function prState(pr) {
    if (pr.found === false) return h("td", { class: "pr-missing" }, M.t("board.pr.not_found"));
    if (!pr.observed_at) {
      return h("td", { class: "pr-unverified" }, M.t("board.pr.unverified"),
        pr.state ? h("span", { class: "muted" }, " · ", M.t("board.pr.claimed_state", { source: pr.source, state: M.dom.word("pr", pr.state) })) : null);
    }
    return h("td", { class: "pr-" + pr.state }, pr.state ? M.dom.word("pr", pr.state) : "—");
  }

  function pullRequests(rel) {
    const prs = rel.pull_requests || [];
    if (!prs.length) return h("p", { class: "muted" }, M.t("board.prs.none"));
    // The table scrolls sideways in a narrow card; a keyboard reaches it.
    return h("table", { class: "prs", tabindex: "0", "aria-label": M.t("board.prs.label", { version: rel.version }) },
      h("thead", null, h("tr", null,
        h("th", { scope: "col" }, M.t("board.prs.pr")), h("th", { scope: "col" }, M.t("board.prs.state")),
        h("th", { scope: "col" }, M.t("board.prs.checks")), h("th", { scope: "col" }, M.t("board.prs.observed")))),
      h("tbody", null, prs.map((pr) => h("tr", null,
        h("td", null, safeUrl(pr.url) ? h("a", { href: safeUrl(pr.url), rel: "noopener noreferrer" }, "#" + pr.number) : "#" + pr.number,
          " " + (pr.title || ""), h("span", { class: "muted" }, " · " + (pr.task_id ? M.t("board.prs.source_by", { source: pr.source, card: pr.task_id }) : pr.source))),
        prState(pr),
        h("td", { class: "checks-" + pr.checks }, pr.observed_at && pr.checks ? word(CHECK_WORDS, pr.checks) : "—"),
        h("td", null, pr.observed_at ? formatAgo(pr.observed_at) + (pr.head_sha ? " @ " + pr.head_sha : "") : M.t("board.pr.never"))))));
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
      + (shipped.has(id) ? "" : " " + M.t("board.group.not_in_release"))
      + (!closed && byId[id] ? " (" + statusWord(byId[id].status) + ")" : "");
    return h("div", { class: "deps groups" },
      h("span", { class: "label" }, M.t("board.group.ship_together")),
      h("ul", null, groups.map((g) => h("li", {
        class: r.ready ? "met" : (incomplete.has(g.join(" ")) ? "unmet" : "unknown"),
      }, g.map(member).join(" + ")))));
  }

  function tagLine(rel) {
    const name = rel.tag ? rel.tag.name : "v" + rel.version;
    if (!rel.tag || !rel.tag.observed_at) return h("p", { class: "muted" }, M.t("board.tag.not_observed", { name }));
    const ago = formatAgo(rel.tag.observed_at);
    if (!rel.tag.found) return h("p", { class: "muted" }, M.t("board.tag.not_found", { name, ago }));
    return h("p", { class: "muted" }, rel.tag.sha ? M.t("board.tag.found_at", { name, sha: rel.tag.sha, ago }) : M.t("board.tag.found", { name, ago }));
  }

  function checklistView(ctx, rel) {
    if (!rel.checklist || !rel.checklist.length) return null;
    return h("ul", { class: "checklist" }, rel.checklist.map((item) =>
      h("li", { class: item.done ? "met" : "unmet" }, (item.done ? "✓ " : "○ ") + item.text, tickedBy(ctx, item))));
  }

  const tickedBy = (ctx, item) => (item.done && item.by
    ? h("span", { class: "muted" }, " · ", M.dom.memberRef(ctx, item.by), item.at ? " " + formatAgo(item.at) : "")
    : null);

  // The hub's refusals of a release edit (docs/api.md §6.7), in words.
  function editError(err) {
    if (err.code === "invalid_transition") return { message: M.t("board.release.closed_record") };
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) {
      return { message: Object.keys(fields).map((k) => {
        const why = String(fields[k]);
        if (why.startsWith("unknown_item:")) return M.t("board.release.checklist_changed", { item: why.slice(13) });
        if (why === "duplicate_id") return M.t("board.release.item_twice");
        return k + ": " + why;
      }).join("; ") };
    }
    return err;
  }

  // Editing a release for members with releases:write (owner, admin,
  // reviewer; docs/api.md §2.3, §6.7): tick items, edit the checklist, and
  // the typed pull requests. The hub's answer redraws this card alone.
  // idp: a prefix for its ids, so the panel's copy (js/card-panel.js) has
  // its own and a label never reaches the board's.
  function releaseEditor(ctx, c, redraw, idp) {
    const rel = c.release;
    const path = ctx.base + "/tasks/" + encodeURIComponent(c.id);
    const status = M.statusLine();
    const patch = async (release, busy, focusId) => {
      status.busy(busy);
      try {
        redraw(await M.api.patch(path, { release }), focusId);
      } catch (err) {
        status.fail(M.t("board.not_saved"), editError(err));
      }
    };

    function checklist() {
      const items = rel.checklist || [];
      const list = h("ul", { class: "checklist editable" }, items.map((item) => {
        const id = idp + "chk-" + c.id + "-" + item.id;
        const box = h("input", { type: "checkbox", id });
        box.checked = !!item.done;
        box.addEventListener("change", async () => {
          box.disabled = true;
          status.busy(box.checked ? M.t("board.release.ticking") : M.t("board.release.unticking"));
          try {
            redraw(await M.api.post(path + "/checklist/" + encodeURIComponent(item.id), { done: box.checked }), id);
          } catch (err) {
            box.checked = !box.checked;
            box.disabled = false;
            status.fail(M.t("board.not_saved"), err.status === 404
              ? { message: M.t("board.release.item_gone") } : editError(err));
          }
        });
        return h("li", { class: item.done ? "met" : "unmet" }, box, h("label", { for: id }, " " + item.text), tickedBy(ctx, item));
      }));
      const box = h("div", { class: "release-edit" });
      append(box,
        items.length ? list : h("p", { class: "muted" }, M.t("board.release.no_items")),
        h("div", { class: "row" },
          h("button", { type: "button", class: "small", id: idp + "edit-checklist-" + c.id, onclick: () => editChecklist(box) }, M.t("board.release.edit_checklist")),
          h("button", { type: "button", class: "small", id: idp + "edit-typed-" + c.id, onclick: () => editTyped(box) }, M.t("board.release.typed"))),
        status.el);
      return box;
    }

    // A list editor: rows of inputs, add and remove, Save sends the list.
    // Each row's controls are labelled with their row number; after Save or
    // Cancel the focus goes back to the button that opened the editor.
    function rowsEditor(box, title, rows, makeRow, toBody, busy, opener) {
      const list = h("ol", { class: "edit-rows" });
      let n = 0;
      const add = (row) => {
        n += 1;
        const li = h("li", null, makeRow(row, n),
          h("button", { type: "button", class: "small", "aria-label": M.t("board.rows.remove_row", { row: String(n) }), onclick: () => li.remove() }, M.t("board.rows.remove")));
        append(list, li);
        return li;
      };
      rows.forEach(add);
      const form = h("form", {
        class: "rows-form",
        onsubmit: (e) => {
          e.preventDefault();
          const body = toBody(list);
          if (body) patch(body, busy, opener);
        },
      },
      h("h4", null, title), list,
      h("div", { class: "row" },
        h("button", { type: "button", class: "small", onclick: () => {
          const li = add(null);
          const first = li.querySelector("input");
          if (first) first.focus();
        } }, M.t("board.rows.add")),
        h("button", { type: "button", onclick: () => redraw(c, opener) }, M.t("board.rows.cancel")),
        h("button", { type: "submit" }, M.t("board.save"))),
      status.el);
      M.dom.clear(box);
      append(box, form);
      const first = list.querySelector("input");
      if (first) first.focus();
    }

    function editChecklist(box) {
      rowsEditor(box, M.t("board.release.checklist"), rel.checklist || [], (item, n) => {
        const input = h("input", { class: "item-text", maxlength: "200", "aria-label": M.t("board.release.checklist_item", { row: String(n) }) });
        input.value = item ? item.text : "";
        if (item) input.setAttribute("data-id", item.id);
        return input;
      }, (list) => {
        const items = Array.from(list.querySelectorAll("input.item-text")).map((i) => ({ id: i.getAttribute("data-id") || undefined, text: i.value.trim() }))
          .filter((i) => i.text);
        // An item keeps its tick by its id; a new one gets the next id from the hub.
        return { checklist: items.map((i) => (i.id ? { id: i.id, text: i.text } : { text: i.text })) };
      }, M.t("board.release.saving_checklist"), idp + "edit-checklist-" + c.id);
    }

    function editTyped(box) {
      rowsEditor(box, M.t("board.release.typed"), rel.pull_requests_typed || [], (pr, n) => {
        const number = h("input", { class: "pr-number", type: "number", min: "1", max: String(PR_MAX), "aria-label": M.t("board.release.typed.number", { row: String(n) }) });
        number.value = pr ? String(pr.number) : "";
        const state = h("select", { class: "pr-claim", "aria-label": M.t("board.release.typed.state", { row: String(n) }) },
          [["", M.t("board.release.typed.no_state")], ["open", M.t("board.release.typed.open")], ["merged", M.t("board.release.typed.merged")], ["closed", M.t("board.release.typed.closed")]].map(([v, l]) => h("option", { value: v }, l)));
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
          status.fail(M.t("board.not_saved"), { message: bad.raw
            ? M.t("board.release.typed.bad_number_was", { max: String(PR_MAX), raw: bad.raw })
            : M.t("board.release.typed.bad_number", { max: String(PR_MAX) }) });
          return null;
        }
        const seen = new Set();
        const twice = rows.find((r) => seen.has(Number(r.raw)) || !seen.add(Number(r.raw)));
        if (twice) {
          status.fail(M.t("board.not_saved"), { message: M.t("board.release.typed.twice", { pr: "#" + Number(twice.raw) }) });
          return null;
        }
        return { pull_requests_typed: rows.map((r) => ({ number: Number(r.raw), state: r.state })) };
      }, M.t("board.release.saving_typed"), idp + "edit-typed-" + c.id);
    }

    return { checklist };
  }

  function release(ctx, c, byId, closed, redraw, idp) {
    const editor = !closed && ctx.canRelease && redraw ? releaseEditor(ctx, c, redraw, idp || "") : null;
    const rel = c.release;
    const r = rel.readiness || { ready: false, blocking: [] };
    const noProbe = r.blocking.some((b) => b.reason === "probe_not_configured");
    return [
      closed ? h("p", { class: "muted" }, M.t("board.release.frozen")) : null,
      pullRequests(rel),
      shipGroups(c, byId, closed),
      editor ? null : checklistView(ctx, rel),
      editor ? editor.checklist() : null,
      r.ready
        ? h("div", { class: "readiness ready" },
          c.status === "done"
            ? h("strong", null, M.t("board.release.shipped"))
            : M.tn("board.release.ready", { ready: h("strong", null, M.t("board.release.ready_words")) }))
        : h("div", { class: "readiness not-ready" }, M.tn("board.release.not_ready", { reasons: h("ul", null, r.blocking.map((b) => h("li", null, blockingText(b, byId)))) })
          .map((p) => (typeof p === "string" ? h("strong", null, p) : p))),
      noProbe && !closed
        ? h("p", { class: "flag" }, M.t("board.release.no_probe"))
        : null,
      tagLine(rel),
    ];
  }

  // A contract's arbiter may be a token ("trust:admin", "role:reviewer"): named in words.
  const arbiterName = (ctx, a) => {
    if (a === "trust:admin") return M.t("board.contract.arbiter_admins");
    if (/^role:/.test(a || "")) return M.t("board.contract.arbiter_role", { role: M.trust.roleLabel(a.slice(5)) });
    return M.dom.memberRef(ctx, a);
  };

  // manage: { move, assign, place, columnOf, drag } from the board, or null (read only).
  function actions(...controls) {
    const shown = controls.filter(Boolean);
    return shown.length ? h("div", { class: "card-actions" }, shown) : null;
  }

  // inPanel: drawn in the opened card's panel (js/card-panel.js): the
  // title is no link to itself and the card is not dragged from there.
  function card(ctx, c, byId, manage, inPanel) {
    const frozen = c.kind === "release" && (c.status === "done" || c.status === "cancelled");
    // The hub's answer to an edit replaces this card in place.
    // focusId names the control to focus in the new card (the box just
    // ticked, the button that opened an editor), so the focus is not lost.
    const redraw = (updated, focusId) => {
      // Into every copy the board holds too: a card opened or closed on the board draws from them
      // without reading the list again (review of #1527).
      if (manage && manage.keep) manage.keep(updated);
      byId[updated.id] = updated;
      const fresh = card(ctx, updated, byId, manage, inPanel);
      el.parentNode.insertBefore(fresh, el);
      el.remove();
      const target = focusId && Array.from(fresh.querySelectorAll("button, input, select")).find((x) => x.getAttribute("id") === focusId);
      if (target) target.focus();
    };
    const E = M.boardEdit;
    const controls = manage ? actions(E.moveControl(ctx, c, manage.move), E.assignControl(ctx, c, manage.assign),
      E.orderControl(ctx, c, manage.columnOf(c), manage.place)) : null;
    // Movable to another column, or within its own by tasks:admin.
    const movable = manage && (E.targets(ctx, c).length > 0 || E.orderable(ctx, c));
    const draggable = movable && !inPanel;
    const el = h("article", {
      class: "card card-" + c.kind + (draggable ? " movable" : ""),
      "aria-label": c.title,
      "data-card": c.id,
      // A pointer may drag it to a column it may move to; the Move menu
      // below does the same for the keyboard and on a phone.
      draggable: draggable ? "true" : null,
      ondragstart: draggable ? (e) => manage.drag.start(e, c) : null,
      ondragend: draggable ? () => manage.drag.end() : null,
    },
      h("header", null,
        h("span", { class: "card-id" }, c.id),
        KIND_LABELS[c.kind]
          ? h("span", { class: "badge " + c.kind }, KIND_LABELS[c.kind] + (c.kind === "release" ? " " + c.release.version : ""))
          : null,
        c._searchClosed ? h("span", { class: "badge" }, M.t("board.search.closed_outside")) : null,
        c.watching ? h("span", { class: "card-watching" }, M.t("cards.watching")) : null,
        Array.isArray(c.match) && c.match.length
          ? h("span", { class: "label-tag" }, M.t("board.search.matched", { fields: M.fmt.list(c.match) })) : null,
        c.label ? h("span", { class: "label-tag" }, M.dom.word("label", c.label)) : null,
        c.needs ? h("span", { class: "label-tag card-needs" }, M.t("cards.needs.tag", { role: M.trust.roleLabel(c.needs) })) : null,
        c.area ? h("span", { class: "area" }, c.area) : null,
        assignee(ctx, c)),
      // The title opens the card; ids in it are links in the panel's text.
      h("h3", null, inPanel ? M.ids.link(c.title, M.ids.where(ctx))
        : h("a", { class: "card-open", href: ctx.link("tasks", c.id), onclick: manage && manage.remember ? () => manage.remember(c.id) : null }, c.title)),
      claimLine(ctx, c),
      approvals(ctx, c),
      // In the panel the row of controls comes right under the claim (the
      // designer's pass part 2): on a phone it was far down.
      inPanel ? controls : null,
      family(ctx, c, inPanel),
      edges(c.kind === "release" ? M.t("board.edges.ships") : M.t("board.edges.depends_on"), c.depends_on, byId, frozen),
      edges(M.t("board.edges.ships_with"), c.ships_with, byId),
      c.blocked_by_request
        ? h("p", { class: "flag" }, M.tn("board.waits", {
          answer: h("a", { href: ctx.link("inbox") }, M.t("board.waits.answer")),
          request: h("span", { class: "request-id" }, c.blocked_by_request),
        }))
        : null,
      c.contract
        ? h("p", { class: "muted" }, (c.contract.watchers || []).length
          ? M.tn("board.contract.line_watched", { state: M.dom.word("contract", c.contract.state), arbiter: arbiterName(ctx, c.contract.arbiter),
            watchers: c.contract.watchers.map((w, i) => [i ? ", " : null, M.dom.memberRef(ctx, w)]) })
          : M.tn("board.contract.line", { state: M.dom.word("contract", c.contract.state), arbiter: arbiterName(ctx, c.contract.arbiter) }))
        : null,
      // Its section from the repository (§6.8).
      c.contract && M.contractPanel ? M.contractPanel.panel(ctx, c, redraw) : null,
      checkpoint(ctx, c),
      subtasks(ctx, c, byId, inPanel),
      inPanel ? familyEditor(ctx, c, byId, manage) : null,
      report(ctx, c),
      c.kind === "release" && c.release ? release(ctx, c, byId, frozen, redraw, inPanel ? "panel-" : "") : null,
      // One row of controls: the column, the assignee, the place in the column.
      inPanel ? null : controls);
    return el;
  }

  // The board a card was opened from, or whose panel was open last: the
  // card, whether its title opened it, and the board's filters, search and
  // scroll as they are when the next board view asks (snapshot). Going back
  // (Close, Escape, Back) marks the card, focuses its title and restores
  // them; a title opening its card keeps them too.
  let lastBoard = null;

  // args[0]: a card to open (/<owner>/<slug>/tasks/<id>, a title's or an id's
  // link, js/ids.js): its panel, and the card marked on the board; one the
  // board does not hold is read by itself, and said when there is none.
  M.views.board = async function (ctx, root, args) {
    const wanted = (args && args[0]) || null;
    const prior = lastBoard && lastBoard.slug === ctx.slug ? lastBoard : null;
    lastBoard = null;
    const returning = !wanted && prior ? prior.id : null;
    // A link from elsewhere (an id in a text, the URL) reveals its card
    // whatever the filters said; the board's own title keeps them.
    const kept = prior && (returning || (prior.fromTitle && prior.id === wanted)) ? prior.snapshot() : null;
    let marked = wanted || returning;
    // releases:write (docs/api.md §2.3): reviewer, ops, or trust owner or admin.
    ctx.canRelease = M.trust.releases(ctx);
    const E = M.boardEdit;
    const since = new Date(Date.now() - CLOSED_WINDOW_DAYS * 86400000).toISOString().replace(/\.\d{3}Z$/, "Z");
    // The cards in column groups read side by side, each following its own pages, instead of one
    // list of every status paged one after the other (tsk-d61rvjm6gteh: six pages in a row on a
    // project of 1,135 cards). The closed window applies to the closed group alone. Each column is
    // ordered by the board itself (byOrder), so the groups may answer in any order. The statuses are
    // the contract's seven (§6.4).
    // The groups are five snapshots, not one: a card moved from a group not yet answered into one
    // already answered would be in neither (review of #1536). So, once they have all answered, the
    // cards changed since the reads began are read again, newest first (`order=updated`, §6), until
    // the first one older than that; each replaces or adds its card. The start is taken on the hub's
    // clock (M.api.now) with a margin, so a skew of the clocks reads a little more, never less.
    // That read pages by an updated_at keyset: a card changed again between two of its pages moves
    // ahead of the cursor, and no later page returns it (review of #1536, delta 1). A pass that
    // followed a cursor is therefore followed by another from the first page, taking every card at
    // least as new as the newest the pass before saw; a pass of one page has no gap and ends it.
    // After RECONCILE_PASSES passes that all paged (the board changing faster than it can be read),
    // one list of every status in the window is read instead and replaces the cards.
    const listPaths = LIST_GROUPS.map((g) => ctx.base + "/tasks?status=" + g)
      .concat([ctx.base + "/tasks?status=done,cancelled&closed_after=" + encodeURIComponent(since)]);
    const windowPath = ctx.base + "/tasks?status=all&closed_after=" + encodeURIComponent(since);
    const recentPath = windowPath + "&order=updated&limit=" + RECENT_PAGE;
    // One pass: from the first page, every card updated at or after `from`; whether it followed a
    // cursor, and the newest updated_at it saw.
    const recentPass = async (cards, from) => {
      let newest = from;
      let paged = false;
      for (let cursor = null; ;) {
        const page = await M.api.get(recentPath + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
        let older = false;
        page.items.forEach((t) => {
          const at = Date.parse(t.updated_at) || 0;
          if (at >= from) { cards.set(t.id, t); if (at > newest) newest = at; } else older = true;
        });
        if (older || !page.next_cursor) break;
        cursor = page.next_cursor;
        paged = true;
      }
      return { paged, newest };
    };
    // shown(cards), where given, is called once the four open groups have answered, with their cards,
    // before the closed group's pages (tsk-a5pxwgkgr73e): on the maintainer's project that group was
    // 783 cards in four pages one after the other, about 0.9 s after the other groups had answered.
    const readList = async (shown) => {
      const began = M.api.now() - RECONCILE_MARGIN_MS;
      const groups = listPaths.map((path) => M.api.getAll(path));
      // A closed group failing while the open ones are awaited is handled by Promise.all below.
      groups.forEach((read) => read.catch(() => {}));
      if (shown) {
        const open = new Map();
        (await Promise.all(groups.slice(0, LIST_GROUPS.length))).forEach((r) => r.items.forEach((t) => { if (!open.has(t.id)) open.set(t.id, t); }));
        shown([...open.values()]);
      }
      const parts = await Promise.all(groups);
      const cards = new Map();
      parts.forEach((r) => r.items.forEach((t) => { if (!cards.has(t.id)) cards.set(t.id, t); }));
      // The groups have answered; a failure from here on is the read again of the cards changed
      // meanwhile, said as such (recheck), not as a failed read of the closed cards.
      try {
        let from = began;
        for (let pass = 0; pass < RECONCILE_PASSES; pass++) {
          const { paged, newest } = await recentPass(cards, from);
          if (!paged) return [...cards.values()];
          from = newest;
        }
        return (await M.api.getAll(windowPath)).items;
      } catch (err) {
        throw Object.assign(err instanceof Error ? err : new Error(String(err)), { recheck: true });
      }
    };
    // The first draw takes the open groups' cards; the closed columns say they are being read until
    // the whole read is in (closedPending), or why it failed (closedError). Each read has a number
    // (reads); an answer is drawn only when no later read's has been (applied), so a slow first read
    // never replaces a reload's cards, and a failed reload leaves the first read to fill the columns.
    let closedPending = true;
    let closedError = null;
    let reads = 1;
    let applied = 0;
    const apply = (read) => { if (read < applied) return false; applied = read; return true; };
    let openShown;
    const openRead = new Promise((resolve) => { openShown = resolve; });
    const firstRead = readList((open) => openShown(open));
    firstRead.catch(() => {});
    let items = await Promise.race([openRead, firstRead]);
    let boardItems = items;
    let searchVersion = 0;
    let hubResults = false;
    const normalize = (value) => String(value || "").normalize("NFKC").toLowerCase();
    const searchInput = h("input", { id: "board-search", type: "search", placeholder: M.t("board.search.placeholder") });
    const searchStatus = h("p", { class: "muted", role: "status", "aria-live": "polite" });
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const columnsBox = h("div", { class: "columns" });
    const formBox = h("div", { class: "new-card-box" });
    const intro = h("div");
    const wantedNote = h("p", { class: "muted wanted-note", role: "status" });
    // The column filter (the maintainer's request): one column, or the
    // closed ones together; remembered per viewer and project in this
    // browser. A card asked for by the URL is shown whatever it says.
    const COLUMN_GROUPS = [["", M.t("board.filter.every_column")], ["proposed", M.t("cards.column.proposed")], ["open", M.t("cards.column.open")], ["in_progress", M.t("cards.column.in_progress")],
      ["blocked", M.t("cards.column.blocked")], ["review", M.t("cards.column.review")], ["closed", M.t("board.filter.closed")]];
    const inGroup = (group, status) => !group || (group === "closed" ? status === "done" || status === "cancelled" : status === group);
    const columnKey = "maity.board.column." + ctx.slug;
    let rememberedColumn = "";
    try { rememberedColumn = window.localStorage.getItem(columnKey) || ""; } catch (err) { rememberedColumn = ""; }
    if (!COLUMN_GROUPS.some(([v]) => v === rememberedColumn)) rememberedColumn = "";
    const filter = kept ? { member: kept.member, area: kept.area, needs: kept.needs, silent: kept.silent, column: kept.column }
      : { member: "", area: "", needs: "", silent: false, column: marked ? "" : rememberedColumn };

    // Focus survives a redraw by key (data-focus), as on the Members view.
    // A card that left the view (closed and moved out, or filtered away)
    // takes no focus with it: the status line that says what happened does.
    // A Place arrow the new spot disables (to the top, then at the top) hands
    // the focus to the card's next arrow that still works.
    // inPanel: the action came from the opened card's panel; the focus
    // stays there, on its redrawn card.
    function refocus(key, inPanel) {
      if (!key) return;
      const all = Array.from((inPanel && panel ? panel.el : columnsBox).querySelectorAll("select, button"));
      const usable = (e) => !e.disabled && e.getAttribute("disabled") == null;
      let again = all.find((e) => e.getAttribute("data-focus") === key);
      if (again && !usable(again) && key.startsWith("order:")) {
        const card = key.split(":").slice(0, 2).join(":") + ":";
        again = all.find((e) => (e.getAttribute("data-focus") || "").startsWith(card) && usable(e)) || again;
      }
      // A control gone from the panel (a card moved to done has no menu
      // left) hands the focus to the panel's heading, never out of it.
      if (again) again.focus();
      else if (inPanel && panel) panel.focus();
      else status.el.focus();
    }

    async function reload(focusKey, inPanel) {
      const read = ++reads;
      const fresh = await readList();
      if (!apply(read)) return;
      boardItems = fresh;
      closedPending = false;
      closedError = null;
      sayClosed();
      items = boardItems;
      hubResults = false;
      if (searchInput.value) await search();
      else draw();
      refocus(focusKey, inPanel);
    }

    // A write, then the board read again; a failed re-read is no failed write.
    // stale(err), where given, tells a refusal that only a fresh read can
    // settle (a neighbour that moved meanwhile): the board is read again, and
    // what it returns is called with the fresh cards for the words to say.
    // words: what the status line says while it runs and when it fails.
    async function write(words, done, call, focusKey, stale) {
      const fromPanel = !!(panel && panel.el.contains(document.activeElement));
      let answer;
      status.busy(words.busy);
      try {
        answer = await call();
      } catch (err) {
        const said = stale && stale(err);
        if (said) {
          try { await reload(focusKey, fromPanel); } catch (ignored) { /* the refusal below is what matters */ }
          status.fail(words.failed, { message: said(items) });
          return false;
        }
        status.fail(words.failed, E.said(err));
        return false;
      }
      // Said once the board shows it: the words and the board never disagree.
      if (typeof done === "function") done = done(answer);
      try {
        await reload(focusKey, fromPanel);
      } catch (err) {
        status.fail((reason) => M.t("board.could_not_refresh", { done, reason }), err);
        return true;
      }
      status.done();
      append(status.el, h("span", { class: "ok" }, done));
      return true;
    }

    const cardPath = (c) => ctx.base + "/tasks/" + encodeURIComponent(c.id);
    const move = (c, to, focusKey, slot) => {
      // Under two signatures (§6.4) done is a signature, and the card may stay in review.
      const approve = slot || (to === "done" && E.signSlots(ctx, c)[0]);
      if (approve) {
        return write({ busy: M.t("board.sign.busy"), failed: M.t("board.sign.failed") },
          (card) => (card && card.status === "done" ? M.t("board.move.done", { id: c.id, status: statusWord("done") }) : M.t("board.sign.saved", { id: c.id })),
          () => M.api.patch(cardPath(c), { status: "done", approve }), focusKey || "move:" + c.id);
      }
      return write({ busy: M.t("board.move.busy"), failed: M.t("board.move.failed") }, M.t("board.move.done", { id: c.id, status: statusWord(to) }),
        () => M.api.patch(cardPath(c), { status: to }), focusKey || "move:" + c.id);
    };
    // Within a column (§6.4): the order changes once the hub has answered,
    // never before; a neighbour gone or moved to another column meanwhile
    // re-reads the board.
    const placed = (id, how) => {
      if (how.before) return M.t("board.place.above", { id, other: how.before });
      if (how.after) return M.t("board.place.below", { id, other: how.after });
      return how.to === "top" ? M.t("board.place.top", { id }) : M.t("board.place.bottom", { id });
    };
    const place = (c, how, focusKey) => write({ busy: M.t("board.place.busy"), failed: M.t("board.place.failed") }, placed(c.id, how),
      () => M.api.post(cardPath(c) + "/move", how), focusKey || "order:" + c.id,
      (err) => (err.code === "not_found" || err.code === "invalid"
        ? () => M.t("board.place.stale")
        : null));
    const assign = (c, who, focusKey) => write({ busy: M.t("board.assign.busy"), failed: M.t("board.assign.failed") }, M.t("board.assign.done", { id: c.id, name: ctx.nameOf(who) }),
      () => M.api.post(cardPath(c) + "/assign", { assignee: who }), focusKey);

    // Dragging: the columns the card may go to are marked, the others refused.
    // A browser fires drop only where dragover allowed it, so a card let go
    // over a refused column ends with dragend alone: the column it was last
    // over says what was refused.
    let dragging = null;
    let over = null;
    let dropped = false;
    const drag = {
      start(e, c) {
        dragging = c;
        over = null;
        dropped = false;
        if (e.dataTransfer) { e.dataTransfer.setData("text/plain", c.id); e.dataTransfer.effectAllowed = "move"; }
        const ok = new Set(E.targets(ctx, c));
        if (E.orderable(ctx, c)) ok.add(c.status);
        columnsBox.querySelectorAll("section.column").forEach((col) => {
          const s = col.getAttribute("data-status");
          col.classList.toggle("drop-ok", ok.has(s));
          col.classList.toggle("drop-refused", s !== c.status && !ok.has(s));
        });
      },
      // Over a card of its own column: above or below it, by the pointer's
      // half of that card; anywhere else in the column: to the bottom.
      spot(e) {
        let el = e.target;
        while (el && !(el.getAttribute && el.getAttribute("data-card"))) el = el.parentNode;
        const id = el ? el.getAttribute("data-card") : null;
        if (!id || id === dragging.id) return id ? null : { to: "bottom" };
        const box = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
        const above = !box || typeof e.clientY !== "number" || e.clientY < box.top + box.height / 2;
        return { [above ? "before" : "after"]: id, el };
      },
      mark(spot) {
        columnsBox.querySelectorAll("article.card").forEach((a) => { a.classList.toggle("drop-before", false); a.classList.toggle("drop-after", false); });
        if (spot && spot.el) spot.el.classList.toggle(spot.before ? "drop-before" : "drop-after", true);
      },
      end() {
        const c = dragging;
        if (c && !dropped && over && over.s !== c.status && !E.targets(ctx, c).includes(over.s)) {
          status.fail(M.t("board.move.not_moved"), { message: M.t("board.move.refused", { id: c.id, column: over.label }) });
        }
        dragging = null;
        over = null;
        columnsBox.querySelectorAll("section.column").forEach((col) => {
          col.classList.toggle("drop-ok", false);
          col.classList.toggle("drop-refused", false);
          col.classList.toggle("drop-over", false);
        });
        drag.mark(null);
      },
    };
    // The cards of each column as drawn, in order: the neighbours a place names.
    let columns = {};
    const columnOf = (c) => columns[c.status] || [];
    // What the board is showing, read when the next board view asks.
    const snapshot = () => ({ column: filter.column, member: filter.member, area: filter.area, needs: filter.needs, silent: filter.silent,
      search: searchInput.value, hub: hubResults, scroll: window.scrollY || 0 });
    const remember = (id) => { lastBoard = { slug: ctx.slug, id, fromTitle: true, snapshot }; };
    // The hub's answer to an edit, written into every copy of that card the board holds: the list,
    // the list a search replaced, the opened card. Matched by id, so an answer that comes after
    // another card was opened changes its own card only (review of #1527).
    const keep = (updated) => {
      [panelCard, byId[updated.id], items.find((t) => t.id === updated.id), boardItems.find((t) => t.id === updated.id)]
        .forEach((t) => { if (t && t !== updated && t.id === updated.id) Object.assign(t, updated); });
    };
    const manage = { move, assign, place, columnOf, drag, remember, keep, reload: (key) => reload(key, true) };

    function column(s, label, cards) {
      const may = () => dragging && E.targets(ctx, dragging).includes(s);
      const within = () => dragging && dragging.status === s && E.orderable(ctx, dragging);
      const col = h("section", {
        class: "column",
        "aria-label": label,
        "data-status": s,
        ondragenter: () => { if (dragging) over = { s, label }; },
        ondragover: (e) => {
          if (dragging) over = { s, label };
          if (may()) { e.preventDefault(); col.classList.toggle("drop-over", true); }
          if (within()) { const spot = drag.spot(e); if (spot) e.preventDefault(); drag.mark(spot); }
        },
        ondragleave: () => col.classList.toggle("drop-over", false),
        ondrop: (e) => {
          e.preventDefault();
          const c = dragging;
          if (within()) {
            const spot = drag.spot(e);
            dropped = true;
            drag.end();
            if (spot) { delete spot.el; place(c, spot); }
            return;
          }
          if (c && E.targets(ctx, c).includes(s)) {
            dropped = true;
            drag.end();
            move(c, s);
          }
        },
      },
      h("h3", { class: "column-head" }, label, closedWaiting(s) ? null : h("span", { class: "count" }, String(cards.length))),
      closedWaiting(s) && !cards.length
        ? h("p", { class: closedError ? "send-status failed closed-read" : "muted closed-read" }, closedWords())
        : cards.length ? shownOf(s, cards).drawn.map((c) => card(ctx, c, byId, manage)) : h("p", { class: "muted" }, "—"),
      moreButton(s, cards));
      if (closedWaiting(s) && !closedError) col.setAttribute("aria-busy", "true");
      return col;
    }

    // The cards a column draws: a closed one the CLOSED_SHOWN closed last (by closed_at, newest first)
    // until Show more opened it for this view, and the marked card wherever it stands, so a link to it
    // still finds it on the board, folded under a parent or not. They keep the column's order; only which
    // of them are drawn changes.
    const shownWhole = new Set();
    const closedLater = (a, b) => ((a.closed_at || "") < (b.closed_at || "") ? 1 : (a.closed_at || "") > (b.closed_at || "") ? -1
      : a.id < b.id ? 1 : a.id > b.id ? -1 : 0);
    function shownOf(s, cards) {
      if (!(s === "done" || s === "cancelled") || shownWhole.has(s) || cards.length <= CLOSED_SHOWN) return { drawn: cards, rest: 0 };
      const kept = new Set(cards.slice().sort(closedLater).slice(0, CLOSED_SHOWN).map((c) => c.id));
      // The marked card, and the card it is folded under: a folded child is found under its parent only
      // where that parent is drawn (review of #1645). The walk up stops after three ids, whatever the data.
      for (let id = marked, depth = 0; id && depth < 3; id = byId[id] && byId[id].parent, depth++) kept.add(id);
      const drawn = cards.filter((c) => kept.has(c.id));
      return { drawn, rest: cards.length - drawn.length };
    }
    // Show more draws the column whole; the first card it adds takes the focus, the button being gone.
    function moreButton(s, cards) {
      const { drawn, rest } = shownOf(s, cards);
      if (!rest) return null;
      const first = cards.find((c) => !drawn.includes(c));
      return h("button", { type: "button", class: "small show-more", "data-focus": "more:" + s, onclick: () => {
        shownWhole.add(s);
        draw();
        const el = Array.from(columnsBox.querySelectorAll("article.card")).find((a) => a.getAttribute("data-card") === first.id);
        const title = el && el.querySelector("a.card-open");
        if (title || el) (title || el).focus();
      } }, M.t("board.closed.show_more", { count: rest }));
    }

    // A closed column while the closed group is still read, or failed: a hub search lists its own cards.
    const closedWaiting = (s) => (closedPending || !!closedError) && !hubResults && (s === "done" || s === "cancelled");
    const closedWords = () => (closedError
      ? (closedError.recheck
        ? M.t("board.closed.recheck_failed", { reason: closedError.message || String(closedError) })
        : M.t("board.closed.failed", { reason: closedError.message || String(closedError) }))
      : M.t("board.closed.loading"));
    // What the closed read is doing, said once for a screen reader: the columns are drawn anew, so
    // the live region stands outside them and keeps its place from pending to done or failed.
    const closedStatus = h("p", { class: "visually-hidden", role: "status", "aria-live": "polite" });
    const sayClosed = () => { closedStatus.textContent = closedPending || closedError ? closedWords() : ""; };
    // The focused element in the columns, so that the next draw can find it again: its data-focus
    // key, or its card and its place among that card's controls and links (a card's title link has
    // no key). Returns what puts the focus back after the draw, or null when it was elsewhere.
    const FOCUSABLE = "a, button, select, input, textarea";
    // A control of the opened card's panel, by its data-focus key, its id, or its place among the
    // panel's focusable elements.
    const controlKey = (el, all) => el.getAttribute("data-focus") || el.getAttribute("id") || "#" + all.indexOf(el);
    const controlIn = (root, key) => {
      const all = Array.from(root.querySelectorAll(FOCUSABLE));
      return all.find((e) => controlKey(e, all) === key) || null;
    };
    // The late draw, the one redraw no action of the reader starts, draws the panel's card part
    // anew, since its subtask list and dependency lines read the closed cards that came with it
    // (review of #1622). What the reader chose or typed in its controls and has not saved, each
    // control's state against how it was drawn (panelDrawn), is carried onto the controls drawn
    // anew, and an open New subtask form is moved into the new part as it is, its draft and the
    // focus in it included, where the new part offers one.
    let panelDrawn = null;
    let panelPart = null;
    const CONTROLS = "input, select, textarea";
    const controlsOf = (root) => {
      const all = Array.from(root.querySelectorAll(CONTROLS));
      return all.map((e) => [controlKey(e, all), e]);
    };
    const choiceBox = (el) => el.getAttribute("type") === "checkbox" || el.getAttribute("type") === "radio";
    const stateOf = (el) => (el.tagName === "SELECT" && el.multiple
      ? Array.from(el.querySelectorAll("option")).filter((o) => o.selected).map((o) => o.getAttribute("value")).join("\n")
      : choiceBox(el) ? String(!!el.checked) : String(el.value == null ? "" : el.value));
    const setState = (el, state) => {
      if (el.tagName === "SELECT" && el.multiple) {
        const chosen = state.split("\n");
        Array.from(el.querySelectorAll("option")).forEach((o) => { o.selected = chosen.includes(o.getAttribute("value")); });
      } else if (choiceBox(el)) el.checked = state === "true";
      else if (el.tagName !== "SELECT" || Array.from(el.querySelectorAll("option")).some((o) => o.getAttribute("value") === state)) el.value = state;
    };
    const drawnState = (part) => new Map(controlsOf(part).map(([k, e]) => [k, stateOf(e)]));
    // The open New subtask form of a part (its button and box), found by the button's key.
    const openEditor = (part, id) => {
      const start = Array.from(part.querySelectorAll("button")).find((b) => b.getAttribute("data-focus") === "subtask:" + id);
      return start ? { start, open: start.getAttribute("aria-expanded") === "true" } : null;
    };
    function showPanelPart(part, keepTyped, data) {
      const typed = keepTyped && panelPart && panelDrawn
        ? controlsOf(panelPart).filter(([k, e]) => panelDrawn.has(k) && panelDrawn.get(k) !== stateOf(e)).map(([k, e]) => [k, stateOf(e)])
        : [];
      const was = keepTyped && panelPart ? openEditor(panelPart, data.id) : null;
      const spot = was && was.open ? openEditor(part, data.id) : null;
      if (spot) spot.start.parentNode.parentNode.replaceChild(was.start.parentNode, spot.start.parentNode);
      if (panelPart) panel.update(part);
      panelPart = part;
      panelDrawn = drawnState(part);
      const fresh = new Map(controlsOf(part));
      typed.forEach(([k, state]) => { if (fresh.has(k)) setState(fresh.get(k), state); });
    }
    // A card's open menu (status, assign) and its focused item, for a redraw that no action of the
    // reader starts: the draw builds every card anew, each with its menus closed, so a menu opened
    // just before would close under the reader's click (tsk-wp8hsgvha3n6). The old menu is closed
    // here, without moving the focus, so that its listener for clicks elsewhere goes with it. The
    // item is found again by what it says, not by its place: a refresh that changed who may be
    // assigned shifts the places, and Enter must not land on another member. Returns what opens the
    // same menu of the redrawn card on that item, or null when no item of an open menu had the focus.
    // An item gone meanwhile leaves the menu closed and the focus on its button (review of #1654).
    function openMenuSpot() {
      const open = Array.from(columnsBox.querySelectorAll(".menu-button"))
        .find((b) => b.getAttribute("aria-expanded") === "true" && b.getAttribute("data-focus"));
      if (!open) return null;
      const key = open.getAttribute("data-focus");
      const focused = Array.from(open.parentNode.querySelectorAll(".menu-item")).find((e) => e === document.activeElement);
      const was = M.menuOf(open);
      if (was) was.close(false);
      if (!focused) return null;
      const label = focused.textContent;
      return () => {
        const again = Array.from(columnsBox.querySelectorAll(".menu-button")).find((b) => b.getAttribute("data-focus") === key);
        const menu = again && M.menuOf(again);
        if (!menu || again.getAttribute("aria-expanded") === "true") return;
        menu.open("first");
        const item = Array.from(again.parentNode.querySelectorAll(".menu-item")).find((e) => e.textContent === label);
        if (item) item.focus();
        else menu.close(true);
      };
    }
    function focusSpot() {
      const at = document.activeElement;
      if (at && panel && panel.el.contains(at)) {
        const key = controlKey(at, Array.from(panel.el.querySelectorAll(FOCUSABLE)));
        const opened = panel;
        return () => {
          if (panel !== opened) return;
          const again = controlIn(panel.el, key);
          if (again) again.focus(); else panel.focus();
        };
      }
      if (!at || !columnsBox.contains(at)) return null;
      const key = at.getAttribute("data-focus");
      let article = at;
      while (article && article !== columnsBox && !(article.tagName === "ARTICLE" && article.getAttribute("data-card"))) article = article.parentNode;
      const id = article && article !== columnsBox ? article.getAttribute("data-card") : null;
      const place = id ? Array.from(article.querySelectorAll(FOCUSABLE)).indexOf(at) : -1;
      return () => {
        if (key) { refocus(key); if (columnsBox.contains(document.activeElement)) return; }
        const again = id ? Array.from(columnsBox.querySelectorAll("article.card")).find((a) => a.getAttribute("data-card") === id) : null;
        const target = again && place >= 0 ? Array.from(again.querySelectorAll(FOCUSABLE))[place] : null;
        if (target) target.focus();
        else status.el.focus();
      };
    }

    let byId = {};
    // The opened card's panel (js/card-panel.js), beside or above the columns.
    let panel = null;
    // The opened card as read: one closed outside the board's window is in no list.
    let panelCard = null;
    const boardBody = h("div", { class: "board-body" }, columnsBox);
    function openPanel(c) {
      lastBoard = { slug: ctx.slug, id: c.id, fromTitle: false, snapshot };
      panelCard = c;
      const part = card(ctx, c, byId, manage, true);
      panelPart = null;
      panel = M.cardPanel.render(ctx, c, part, () => M.route.go(ctx.link("board"), { replace: true }),
        (updated) => {
          // Every copy, the list a search replaced included, which comes back when it ends; and the card
          // this panel was opened for, whichever panel is open by now.
          keep(updated);
          if (c.id === updated.id && c !== updated) Object.assign(c, updated);
          draw();
        });
      showPanelPart(part, false, c);
      boardBody.className = "board-body has-panel";
      append(boardBody, panel.el);
      // Closed, or another card opened, before the timer: the focus stays where that left it.
      const opened = panel;
      window.setTimeout(() => { if (panel === opened) opened.focus(); }, 0);
    }

    // Closed on the board itself (the route follows, below): the panel goes, the card keeps its mark.
    function closePanel() {
      if (!panel) return;
      if (panel.el.parentNode) panel.el.parentNode.removeChild(panel.el);
      boardBody.className = "board-body";
      panel = null;
      panelCard = null;
      panelPart = null;
      panelDrawn = null;
    }

    function shown(c) {
      if (!inGroup(filter.column, c.status)) return false;
      if (filter.member && !(c.assigned_to === filter.member || (c.claim && c.claim.holder === filter.member))) return false;
      if (filter.area && c.area !== filter.area) return false;
      if (filter.needs && c.needs !== filter.needs) return false;
      if (filter.silent && !(c.claim && M.dom.isSilentAgent(ctx.memberById[c.claim.holder]))) return false;
      if (searchInput.value && !hubResults) {
        const query = normalize(searchInput.value);
        return [c.id, c.title, c.body].some((value) => normalize(value).includes(query));
      }
      return true;
    }

    // keepTyped: the late draw, which keeps what the reader typed in the opened card's panel.
    function draw(keepTyped) {
      areaOptions();
      needsOptions();
      byId = {};
      items.forEach((t) => { byId[t.id] = t; });
      const known = new Set(COLUMNS.map(([s]) => s));
      const visible = items.filter(shown);
      // A child whose parent is shown stands folded under it, not in a column.
      const shownIds = new Set(visible.map((t) => t.id));
      const standing = visible.filter((t) => !(t.parent && shownIds.has(t.parent)));
      const other = standing.filter((t) => !known.has(t.status));
      columns = {};
      COLUMNS.forEach(([s]) => { columns[s] = standing.filter((t) => t.status === s).sort(E.byOrder); });
      clear(intro);
      if (!items.length && !searchInput.value && !closedPending && !closedError) {
        append(intro, h("p", { class: "first-hint" }, M.t("board.empty")));
      } else if (!visible.length && !(closedWaiting("done") && inGroup(filter.column, "done"))) {
        // No verdict while the closed cards the filter would show are still unknown.
        append(intro, h("p", { class: "muted" }, M.t("board.no_match")));
      }
      append(clear(columnsBox),
        COLUMNS.filter(([s]) => inGroup(filter.column, s)).map(([s, label]) => column(s, label, columns[s])),
        other.length && !filter.column
          ? h("section", { class: "column", "aria-label": M.t("board.column.other") },
            h("h3", { class: "column-head" }, M.t("board.column.unknown")),
            other.map((c) => card(ctx, c, byId, manage)))
          : null);
      if (panel) {
        const data = byId[panel.id] || panelCard;
        showPanelPart(card(ctx, data, byId, manage, true), !!keepTyped, data);
      }
      if (marked) {
        let el = Array.from(columnsBox.querySelectorAll("article.card")).find((a) => a.getAttribute("data-card") === marked);
        // A folded child: its parent unfolds, and the child's row is marked.
        if (!el) {
          el = Array.from(columnsBox.querySelectorAll("li.subtask")).find((li) => li.getAttribute("data-card") === marked) || null;
          const list = el && el.parentNode;
          if (list) {
            list.hidden = false;
            unfolded.add(ctx.slug + "/" + byId[marked].parent);
            const toggle = Array.from(columnsBox.querySelectorAll("button.subtask-toggle")).find((b) => b.getAttribute("aria-controls") === list.id);
            if (toggle) toggle.setAttribute("aria-expanded", "true");
          }
        }
        if (el) { el.className += " wanted"; el.setAttribute("tabindex", "-1"); }
        return el || null;
      }
      return null;
    }

    function localSearch() {
      searchVersion++; // an older response must never replace a newer query or Clear
      items = boardItems;
      hubResults = false;
      searchStatus.textContent = searchInput.value
        ? M.t("board.search.filtering") : "";
      draw();
    }

    async function search() {
      const query = searchInput.value;
      if (!query) { localSearch(); return; }
      const version = ++searchVersion;
      if ([...query].length > 200) {
        searchStatus.textContent = M.t("board.search.too_long", { max: 200 });
        return;
      }
      items = boardItems;
      hubResults = false;
      draw();
      searchStatus.textContent = M.t("board.search.searching");
      try {
        const result = await M.api.getAll(ctx.base + "/tasks?status=all&q=" + encodeURIComponent(query));
        if (version !== searchVersion) return;
        // Outside the window by its closed_at, not by the loaded cards: while the closed group is
        // still read, those are the open groups' alone (review of #1622).
        const loaded = new Set(boardItems.map((c) => c.id));
        // closed_after is strict (§6, docs/api.md): a card closed at the cutoff is outside.
        const inWindow = (c) => !!c.closed_at && Date.parse(c.closed_at) > Date.parse(since);
        items = result.items.map((c) => ({ ...c,
          _searchClosed: ["done", "cancelled"].includes(c.status) && !loaded.has(c.id) && !inWindow(c) }));
        hubResults = true;
        searchStatus.textContent = M.t("board.search.found", { count: items.length });
        draw();
      } catch (err) {
        if (version !== searchVersion) return;
        searchStatus.textContent = M.t("board.search.failed", { error: err.message || String(err) });
      }
    }
    searchInput.addEventListener("input", localSearch);
    const clearSearch = h("button", { type: "button", onclick: () => {
      searchInput.value = "";
      localSearch();
      searchInput.focus();
    } }, M.t("board.search.clear"));

    // Filters, from what is on the board.
    const memberSel = h("select", { id: "board-member" }, h("option", { value: "" }, M.t("board.filter.everyone")),
      ctx.members.map((m) => h("option", { value: m.id }, m.display_name)));
    memberSel.value = filter.member;
    const areaSel = h("select", { id: "board-area" });
    // The areas on the board now; a chosen one stays offered while filtered.
    function areaOptions() {
      const areas = new Set(items.map((t) => t.area).filter(Boolean));
      if (filter.area) areas.add(filter.area);
      append(clear(areaSel), h("option", { value: "" }, M.t("board.filter.every_area")), [...areas].sort().map((a) => h("option", { value: a }, a)));
      areaSel.value = filter.area;
    }
    const needsFilter = h("select", { id: "board-needs" });
    // As with the areas: the roles the board's cards name now.
    function needsOptions() {
      const roles = new Set(items.map((t) => t.needs).filter(Boolean));
      if (filter.needs) roles.add(filter.needs);
      append(clear(needsFilter), h("option", { value: "" }, M.t("board.filter.every_role")), [...roles].sort().map((r) => h("option", { value: r }, M.trust.roleLabel(r))));
      needsFilter.value = filter.needs;
    }
    const columnSel = h("select", { id: "board-column" }, COLUMN_GROUPS.map(([v, l]) => h("option", { value: v, selected: v === filter.column }, l)));
    columnSel.value = filter.column;
    columnSel.addEventListener("change", () => {
      filter.column = columnSel.value;
      try { if (filter.column) window.localStorage.setItem(columnKey, filter.column); else window.localStorage.removeItem(columnKey); } catch (err) { /* this browser keeps nothing */ }
      draw();
    });
    memberSel.addEventListener("change", () => { filter.member = memberSel.value; draw(); });
    areaSel.addEventListener("change", () => { filter.area = areaSel.value; draw(); });
    needsFilter.addEventListener("change", () => { filter.needs = needsFilter.value; draw(); });

    const silentOnly = ctx.canAdmin ? h("input", { id: "board-silent", type: "checkbox" }) : null;
    if (silentOnly) {
      silentOnly.checked = filter.silent;
      silentOnly.addEventListener("change", () => { filter.silent = silentOnly.checked; draw(); });
    }

    const newButton = h("button", { type: "button", "aria-expanded": "false", "aria-controls": "new-card-box" }, M.t("board.new_card"));
    formBox.id = "new-card-box";
    const closeForm = () => { clear(formBox); newButton.setAttribute("aria-expanded", "false"); newButton.focus(); };
    newButton.addEventListener("click", () => {
      if (newButton.getAttribute("aria-expanded") === "true") { closeForm(); return; }
      const f = E.newCardForm(ctx, items, async (body) => {
        const created = await M.api.post(ctx.base + "/tasks", body);
        // Created: the form is done, whatever the re-read says.
        clear(formBox);
        newButton.setAttribute("aria-expanded", "false");
        const done = M.t("board.created", { id: created.id, status: statusWord(created.status) });
        status.done();
        append(status.el, h("span", { class: "ok" }, done));
        try {
          await reload("move:" + created.id);
        } catch (err) {
          status.fail((reason) => M.t("board.could_not_refresh", { done, reason }), err);
        }
      }, closeForm);
      append(clear(formBox), f.form);
      newButton.setAttribute("aria-expanded", "true");
      f.focus();
    });

    append(root,
      h("div", { class: "toolbar" }, h("h2", null, M.t("board.title")), newButton),
      h("p", { class: "muted" }, M.t("board.intro", { days: CLOSED_WINDOW_DAYS })),
      h("form", { class: "board-filter", role: "search", onsubmit: (e) => { e.preventDefault(); search(); } },
        h("label", { for: "board-search" }, M.t("board.search")), searchInput,
        h("button", { type: "submit" }, M.t("board.search.all")), clearSearch,
        h("label", { for: "board-column" }, M.t("board.filter.column")), columnSel,
        h("label", { for: "board-member" }, M.t("board.filter.member")), memberSel,
        h("label", { for: "board-area" }, M.t("board.filter.area")), areaSel,
        h("label", { for: "board-needs" }, M.t("cards.new.field.needs")), needsFilter,
        silentOnly ? h("label", { class: "check", for: "board-silent" }, silentOnly, " ", M.t("board.filter.silent")) : null),
      searchStatus, formBox, status.el, intro, wantedNote, closedStatus, boardBody);
    sayClosed();
    let markedCard = draw();
    // The closed group in, while the rest of the view goes on: the board drawn again with it (a local
    // search filters it too; a hub search keeps its own results), and the focus put back on the
    // element in the columns that had it (focusSpot), after a failed read too, where that element
    // still stands in a column. One whose card is now folded under a parent that came with the closed
    // cards, or is gone from the columns, hands the focus to the status line. A board left from a
    // closed card finds that card only now, and its title takes the focus if nothing else took it
    // meanwhile. A reload drawn meanwhile supersedes it.
    const markedFirst = !!markedCard;
    firstRead.then((all) => {
      if (!apply(1)) return;
      const at = document.activeElement;
      const back = focusSpot();
      const menuBack = openMenuSpot();
      boardItems = all;
      closedPending = false;
      sayClosed();
      if (!hubResults) items = boardItems;
      else {
        // A hub search drawn meanwhile: a card it found that the board has now loaded is in the window.
        const loaded = new Set(boardItems.map((c) => c.id));
        items = items.map((c) => (c._searchClosed && loaded.has(c.id) ? { ...c, _searchClosed: false } : c));
      }
      const found = draw(true);
      if (back) back();
      else if (found && !markedFirst && returning && (!at || at === document.body)) {
        const title = found.querySelector("a.card-open");
        window.setTimeout(() => (title || found).focus(), 0);
      }
      // After the focus is back: an open menu's item takes it again (null when no item had it).
      if (menuBack) menuBack();
    }, (err) => {
      if (applied > 1) return;
      const back = focusSpot();
      const menuBack = openMenuSpot();
      closedPending = false;
      closedError = err;
      sayClosed();
      draw(true);
      if (back) back();
      if (menuBack) menuBack();
    });
    // The board as it was left: its search too, the hub's one asked again.
    if (kept && kept.search) {
      searchInput.value = kept.search;
      if (kept.hub) await search(); else localSearch();
      markedCard = Array.from(columnsBox.querySelectorAll("article.card")).find((a) => a.getAttribute("data-card") === marked) || null;
    }
    if (kept && returning && window.scrollTo) window.scrollTo(0, kept.scroll);
    const opened = wanted ? byId[wanted] || await M.api.get(cardPath({ id: wanted })).catch(() => null) : null;
    if (opened) openPanel(opened);
    else if (markedCard && returning) {
      const title = markedCard.querySelector("a.card-open");
      window.setTimeout(() => (title || markedCard).focus(), 0);
    } else if (markedCard) window.setTimeout(() => markedCard.focus(), 0);
    else if (wanted) {
      wantedNote.textContent = M.t("board.wanted_missing", { id: wanted, days: CLOSED_WINDOW_DAYS });
    }
    ctx.every(30000, async () => {
      try {
        const fresh = (await M.api.getAll(ctx.base + "/members")).items;
        M.withMembers(ctx, fresh);
        if (filter.silent) {
          const menuBack = openMenuSpot();
          draw();
          if (menuBack) menuBack();
        }
        else columnsBox.querySelectorAll(".holder-presence").forEach((node) => {
          node.parentNode.replaceChild(holderPresence(ctx, node.getAttribute("data-holder")), node);
        });
      } catch (err) { status.fail(M.t("board.presence_failed"), err); }
    });
    // A card opened or closed on this board is followed here: the panel changes and that card is
    // read, never the list, the members or the project again (tsk-d61rvjm6gteh: a full render per
    // card read all of them, so clicking through cards read the members every second). Any other
    // address, another project's included, renders as before.
    ctx.followRoute((where) => {
      if (where.scope !== "project" || where.slug !== ctx.slug || (where.route !== "tasks" && where.route !== "board")) return false;
      // A card the filters hide, or one outside the board's window, is a link from elsewhere: drawn
      // afresh as before (the check just below), which shows it whatever the filters say.
      const id = where.args[0] || null;
      if (id && !(panel && panel.id === id) && (!byId[id] || !shown(byId[id]))) return false;
      // A missing card's note stood for the address before this one.
      wantedNote.textContent = "";
      if (!id) {
        const left = panel ? panel.id : null;
        closePanel();
        lastBoard = null;
        marked = left;
        const el = draw();
        const title = el && el.querySelector("a.card-open");
        if (el) window.setTimeout(() => (title || el).focus(), 0);
        return true;
      }
      if (panel && panel.id === id) return true;
      closePanel();
      marked = id;
      draw();
      openPanel(byId[id]);
      return true;
    });
  };
})(window.Maity);
