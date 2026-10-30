// (1) The inbox: what each agent wants from the human, one entry after the
// other. The first open entry in the chosen order is expanded; answering
// it expands the next. Runs in one project (/<owner>/<slug>/inbox) or across
// all of them (/all), where every entry is labelled with its project.
// Requests carry everything an entry shows (docs/api.md §7): asker, card
// and context are inline, so no other call is made.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const PRIORITY_RANK = { urgent: 0, high: 1, normal: 2, low: 3 };

  const CLASS_LABELS = { decision: "decision", consent: "consent", contract: "contract", info: "info" };

  // Per tab only: which order and filter the human picked, which entry is
  // open, and which were put off with "Later". Not persisted, never sent:
  // there is no deferred state in the hub, a request stays open until it
  // is answered.
  // project: the cross-project view's filter ("" for every project);
  // group: whether it shows one section per project.
  const ui = { sort: "priority", show: "open", current: null, later: new Set(), project: "", group: false };

  // An entry is addressed by project and id: ids are unique per project
  // only. req.slug is set on load to the project's full name (§6.25); the
  // API gives a cross-project item its project as {slug, full_name, name,
  // state} and a per-project item none.
  const keyOf = (req) => req.slug + "/" + req.id;

  // Who asked, from the request itself: asked_by and, where the request was
  // filed for someone else, on_behalf_of.
  // A request the hub files itself (asked_by null, filed_by "hub": an
  // outage, an unconfirmed commitment, the not-listening digest, §5.3, §7).
  const byHub = (req) => !req.asked_by && req.filed_by === "hub";
  // The not-listening digest (§5.3): the hub's, personal, about no project
  // and no organisation; it leads to one's agents.
  const digest = (req) => byHub(req) && req.personal && !req.project && !req.org;

  function asker(req) {
    const by = req.asked_by ? req.asked_by.display_name : byHub(req) ? "Maity" : "—";
    return req.on_behalf_of ? by + " for " + req.on_behalf_of.display_name : by;
  }

  function comparator(names) {
    const priority = (a, b) => (PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority])
      || a.created_at.localeCompare(b.created_at);
    let cmp = priority;
    if (ui.sort === "date") cmp = (a, b) => b.created_at.localeCompare(a.created_at);
    if (ui.sort === "agent") cmp = (a, b) => asker(a).localeCompare(asker(b)) || priority(a, b);
    if (ui.sort === "project") cmp = (a, b) => names.project(a).localeCompare(names.project(b)) || priority(a, b);
    // Entries put off with "Later" go to the end, in the same order.
    return (a, b) => (ui.later.has(keyOf(a)) - ui.later.has(keyOf(b))) || cmp(a, b);
  }

  function answerLabel(req) {
    const a = req.answer;
    if (!a) return req.status;
    if (a.talk) return "Neither — let's talk";
    if (a.reply_id) {
      const reply = (req.replies || []).find((r) => r.id === a.reply_id);
      return reply ? reply.label : a.reply_id;
    }
    return "Free text";
  }

  function addressee(ctx, req) {
    const to = req.to;
    if (!to) return null;
    if (to === "owner") return "the project's owner";
    if (to.startsWith("role:")) return "role " + to.slice(5);
    if (to.startsWith("trust:")) return "trust " + to.slice(6);
    if (to === ctx.me.id) return "you";
    if (to.startsWith("profile_owner:")) return "you, as the agent's owner";
    return ref(ctx, req, { member_id: to, display_name: ctx.nameOf ? ctx.nameOf(to) : to });
  }

  // In the cross-project view: the project's logo or monogram, its name
  // and state, a link to the project, before the entry it belongs to.
  function projectBadge(ctx, req, names) {
    const p = req.project || { full_name: req.slug, name: names.project(req) };
    // A personal request (§7) is the human's, not the project's: no link to
    // a project inbox that never lists it, and maybe one is not a member of.
    // One with a project (a transfer into an organisation, §6.26) names the
    // project; one without (an organisation's invitation) the organisation
    // where the request carries it, otherwise nothing more.
    if (req.personal) {
      const of = p.name || (req.org ? "@" + req.org.handle : "");
      return h("span", { class: "project-label personal" }, "Personal", of ? h("span", { class: "muted" }, " · " + of) : null);
    }
    return h("a", { class: "project-label", href: ctx.projectLink(p.full_name, "inbox") },
      M.projectMark(p.full_name, p.name, (ctx.projectViews || {})[p.full_name], "small"),
      p.name,
      p.state ? h("span", { class: "state state-" + p.state }, ctx.stateLabel(p.state)) : null);
  }

  function entrySummary(ctx, req, names, expanded, onToggle) {
    return h("button", {
      class: "entry-head",
      type: "button",
      "aria-expanded": expanded ? "true" : "false",
      onclick: onToggle,
    },
    // The project's badge stands before the entry, as a link; its name is
    // also the start of this button's name, for whom the badge is not seen.
    ctx.scope === "all" || req.personal ? h("span", { class: "visually-hidden" }, (req.personal ? "Personal, " : "") + (names.project(req) || (req.org ? "@" + req.org.handle : "")) + (req.project && req.org ? ", into @" + req.org.handle : "") + ": ") : null,
    h("span", { class: "prio prio-" + req.priority }, req.priority),
    h("span", { class: "kind" }, CLASS_LABELS[req.class] || req.class),
    h("span", { class: "title" }, req.title),
    ui.later.has(keyOf(req)) ? h("span", { class: "muted" }, "later") : null,
    h("span", { class: "meta" }, asker(req) + " · " + formatAgo(req.created_at)));
  }

  // A reply id is chosen by the asking agent, so it never becomes a class:
  // only the hub's own "go" of a consent without options is styled as the
  // primary answer.
  function replyClass(req, reply) {
    const computedGo = req.class === "consent" && !(req.options && req.options.length) && reply.id === "go";
    return computedGo ? "reply primary" : "reply";
  }

  // A member named in an entry, as a link to them in the request's own
  // project; a personal request's project may be one the human is not in,
  // so there they stay text.
  // A link only to someone this page knows is a member of the request's
  // project: its own project's member list. Across projects that list is
  // not read, so there, and for a personal request, they stay text.
  function ref(ctx, req, person) {
    const id = person && (person.member_id || person.id);
    const known = ctx.scope === "project" && !req.personal && id && (ctx.memberById || {})[id];
    const view = { memberById: known ? { [id]: known } : {}, link: ctx.link, nameOf: ctx.nameOf };
    return M.dom.memberRef(view, person, { instance: person && person.instance });
  }

  function who(ctx, req, person) {
    return [ref(ctx, req, person), " · " + M.trust.words(person) + (person.session_id ? " · session " + person.session_id : "")];
  }

  // The project a request's text belongs to, for its ids as links
  // (js/ids.js): none for a personal request from a project the human is
  // not in, whose pages would not open.
  function textAt(ctx, req) {
    const p = ctx.projects.find((x) => x.full_name === req.slug);
    const slug = req.personal && !p ? null : req.slug;
    return { slug, repository: (p && p.repository && p.repository.url) || (ctx.slug === req.slug ? M.ids.where(ctx).repository : null),
      // Across projects (/all) a card or request reads with its project (§6.25).
      outside: ctx.scope !== "project" };
  }

  function entryBody(ctx, req, names, onAnswer, onLater) {
    const body = h("div", { class: "entry-body" });
    const at = textAt(ctx, req);
    // The title is inside the entry's button, where a link cannot be: its
    // ids are offered here.
    const titleRefs = M.ids.refs(req.title, at);

    append(body, h("dl", { class: "facts" },
      req.personal && req.org && !req.project
        ? [h("dt", null, "Organisation"), h("dd", null, "@" + req.org.handle + " — a personal request: for you, not for a project")]
        : null,
      // A transfer into an organisation: the project, and the organisation it would move into.
      req.personal && req.org && req.project
        ? [h("dt", null, "Project"), h("dd", null, names.project(req) + " — a personal request: for you as an owner of @" + req.org.handle),
          h("dt", null, "Into"), h("dd", null, "@" + req.org.handle)]
        : null,
      req.personal && !req.org && names.project(req)
        ? [h("dt", null, "Project"), h("dd", null, names.project(req) + " — a personal request: for you as the owner of the agent, not for the project")]
        : null,
      ctx.scope === "all" && !req.personal
        ? [h("dt", null, "Project"), h("dd", null, h("a", { href: ctx.projectLink(req.slug, "inbox") }, names.project(req)))]
        : null,
      titleRefs.length ? [h("dt", null, "In the title"), h("dd", { class: "title-refs" }, titleRefs.map((a, i) => [i ? ", " : null, a]))] : null,
      h("dt", null, "Asked by"), h("dd", null, req.asked_by ? who(ctx, req, req.asked_by) : byHub(req) ? "Maity, on its own" : "—"),
      req.on_behalf_of ? [h("dt", null, "On behalf of"), h("dd", null, who(ctx, req, req.on_behalf_of))] : null,
      req.to ? [h("dt", null, "To"), h("dd", null, addressee(ctx, req))] : null,
      h("dt", null, "Asked"), h("dd", null, formatTime(req.created_at)),
      req.task
        ? [h("dt", null, "Card"), h("dd", null, req.personal
          ? M.ids.ref(req.project && req.project.full_name, req.task.id, true) + " — " + req.task.title + " (" + req.task.status.replace("_", " ") + ")"
          : h("a", { href: ctx.projectLink(req.slug, "tasks", req.task.id) },
            M.ids.ref(req.slug, req.task.id, ctx.scope !== "project") + " — " + req.task.title + " (" + req.task.status.replace("_", " ") + ")"))]
        : null,
      digest(req) ? [h("dt", null, "Your agents"), h("dd", null, h("a", { class: "digest-agents", href: "/agents" }, "See them and their memberships"))] : null,
      // Nobody waits on one the hub filed itself.
      byHub(req) ? null : [h("dt", null, "Meanwhile"), h("dd", null, req.while_open === "proceed_provisionally"
        ? "the agent proceeds provisionally"
        : "the agent waits for the answer")],
      req.ktw_ref ? [h("dt", null, "Reasoning"), h("dd", null, h("code", null, req.ktw_ref))] : null));

    // Mentions link to the member in the request's own project (docs/api.md §8.6).
    // A personal request's project may be one the human is not in: no links there.
    const memberHref = (id) => (req.personal ? null : ctx.projectLink(req.slug, "members", id));
    const said = (field, text, mentions) => M.dom.withMentions(text, mentions, field, memberHref, at);
    if (req.summary) append(body, h("p", { class: "summary pre" }, said("summary", req.summary, req.mentions)));
    if (req.tried) append(body, h("h3", { class: "sub" }, "What it tried"), h("p", { class: "pre" }, said("tried", req.tried, req.mentions)));
    if (req.options && req.options.length) {
      append(body, h("h3", { class: "sub" }, "Options it sees"),
        h("ul", { class: "options" }, req.options.map((o) =>
          h("li", null, h("strong", null, M.ids.link(o.label, at)), o.detail ? [" — ", M.ids.link(o.detail, at)] : ""))));
    }
    const nis = req.needs_in_session;
    if (nis) {
      append(body, h("p", { class: "flag", role: "note" },
        h("strong", null, "Needs you in the session: "),
        ref(ctx, req, nis), (nis.session_id ? " · " + nis.session_id : "") + (nis.harness ? " · " + nis.harness : "") + ". ",
        nis.reason));
    }

    const preference = M.preferences && M.preferences.isProposal(req);
    // Not read in full: no reply that could apply a proposal unseen.
    const unread = req.personal && req.status === "open" && req.unreadable;
    if (req.status !== "open") {
      const a = req.answer;
      if (preference) append(body, M.preferences.outcome(req));
      append(body, h("p", { class: "answered" },
        (req.status === "withdrawn" ? "Withdrawn" : "Answered: " + answerLabel(req)),
        a && a.text ? [" — “", said("text", a.text, a.mentions), "”"] : null,
        a ? [" · ", ref(ctx, req, { member_id: a.by, display_name: names.member(a.by) }),
          a.on_behalf_of ? [" for ", ref(ctx, req, { member_id: a.on_behalf_of, display_name: names.member(a.on_behalf_of) })] : null,
          " · " + formatTime(a.at)] : null));
      return body;
    }

    const status = M.statusLine();
    const send = (payload, verb) => {
      body.querySelectorAll("button, textarea").forEach((el) => { el.disabled = true; });
      status.busy("Sending…");
      onAnswer(req, payload, verb).catch((err) => {
        body.querySelectorAll("button, textarea").forEach((el) => { el.disabled = false; });
        status.fail("Not sent: ", err);
      });
    };

    if (unread) {
      const again = h("button", { type: "button", onclick: async () => {
        again.disabled = true;
        await readInFull(req);
        const fresh = entryBody(ctx, req, names, onAnswer, onLater);
        append(clear(body), Array.from(fresh.childNodes));
      } }, "Try again");
      append(body, h("div", { class: "error", role: "alert" },
        h("p", null, "This request could not be read in full, so it is not offered for an answer yet: it may be a proposal whose texts you should see first. "
          + (req.unreadable.message || req.unreadable.code || "")),
        again));
    }
    // A preference proposal (§19.4) is answered in its review: accept,
    // accept an edit, decline; Later, talk and Withdraw stay below.
    if (preference) append(body, M.preferences.review(ctx, req, (payload) => onAnswer(req, payload)));

    const textId = "reply-" + String(req.slug).replace("/", "-") + "-" + req.id;
    const text = h("textarea", { id: textId, rows: "3", placeholder: "Reply in your own words" });
    const sendWords = () => {
      const value = text.value.trim();
      if (!value) { text.focus(); return; }
      send({ text: value });
    };
    const sendText = h("button", { type: "button", onclick: sendWords }, "Send");
    M.dom.sendOnCtrlEnter(text, sendWords, sendText);
    append(body,
      // Right-aligned, the secondary ones first: Later, talk, then the replies.
      h("div", { class: "replies" },
        h("button", {
          type: "button",
          class: "reply later",
          title: "Moves it down this list in this tab; it stays open and nothing is sent",
          onclick: () => onLater(req),
        }, "Later"),
        h("button", { type: "button", class: "reply talk", onclick: () => send({ talk: true }) }, "Neither — let's talk"),
        // Its human may withdraw a personal request, as nobody else can (§7).
        req.personal ? h("button", {
          type: "button",
          class: "reply withdraw",
          onclick: () => {
            if (!window.confirm("Withdraw this request? It is closed without an answer.")) return;
            const reason = text.value.trim();
            send(reason ? { reason } : {}, "withdraw");
          },
        }, "Withdraw") : null,
        // The primary reply last, the others in the hub's order before it.
        (preference || unread ? [] : [...(req.replies || []).filter((r) => replyClass(req, r) !== "reply primary"),
          ...(req.replies || []).filter((r) => replyClass(req, r) === "reply primary")]).map((r) =>
          h("button", { type: "button", class: replyClass(req, r), onclick: () => send({ reply_id: r.id }) }, r.label))),
      // A preference proposal's words go with its Decline, in the review.
      preference || unread ? null : h("div", { class: "free-text" },
        h("label", { for: textId }, "Free text (" + M.dom.SEND_KEYS + " sends)"),
        text,
        // @ offers this project's members; the hub links them, it pings nobody (§8.6).
        // Not for a personal request: its project may be one the human is not in.
        req.personal ? null : M.mentionPicker(text, () => M.api.getAll("/projects/" + M.api.projectPath(req.slug) + "/members").then((r) => r.items), ctx.me.id),
        sendText),
      status.el);

    // Ownership is known inside a project only; across projects the link to
    // the project's inbox leads there.
    const agent = ctx.scope === "project" && req.asked_by ? ctx.memberById[req.asked_by.member_id] : null;
    if (agent && agent.kind === "agent" && agent.owner_id === ctx.me.id) {
      append(body, h("p", { class: "chat-link" },
        h("a", { href: ctx.link("chat", agent.id) }, "Chat with " + agent.display_name)));
    }
    return body;
  }

  // A personal request as GET /requests/{id} has it: a proposal with its
  // texts (§19.4), or the error that kept it from being read.
  function readInFull(r) {
    return M.api.get("/requests/" + encodeURIComponent(r.id)).then((full) => {
      delete r.unreadable;
      if (full.memory_proposal) r.memory_proposal = full.memory_proposal;
    }, (err) => { r.unreadable = err; });
  }

  async function load(ctx) {
    if (ctx.scope === "project") {
      // The project's own requests, and the open personal requests about it
      // (§7: a project's list never holds them, the tab's count does, §18.2):
      // the list shows what the tab counts.
      // A failed read of them is said in the list's status line (load's
      // personalError), never an empty list short of the tab.
      let personalError = null;
      const [requests, personal] = await Promise.all([M.api.getAll(ctx.base + "/requests?status=all"),
        M.api.getAll("/requests").then((r) => r.items.filter((x) => x.personal && x.status === "open" && x.project && x.project.full_name === ctx.slug),
          (err) => { personalError = err; return []; })]);
      requests.items.forEach((r) => { r.slug = ctx.slug; });
      personal.forEach((r) => { r.slug = ctx.slug; });
      await Promise.all(personal.map(readInFull));
      const all = requests.items.concat(personal);
      all.personalError = personalError;
      return all;
    }
    const requests = await M.api.getAll("/requests");
    // A personal request may have no project (an organisation's invitation, §6.26).
    requests.items.forEach((r) => { r.slug = r.project ? r.project.full_name : null; });
    // A list shows no proposal (§7): an open personal request is read on its
    // own, so a preference proposal (§19.4) comes with its review's texts.
    // One that cannot be read is offered no reply until it is: it may be a
    // proposal whose texts the human has to see first.
    await Promise.all(requests.items.filter((r) => r.personal && r.status === "open").map(readInFull));
    return requests.items;
  }

  // args[0]: a request to show (/<owner>/<slug>/inbox/<id>, an id's link,
  // js/ids.js): opened, and listed among the answered when it is one; an id
  // the project's inbox does not hold is said.
  M.views.inbox = async function (ctx, root, args) {
    const items = await load(ctx);
    const wanted = ctx.scope === "project" && args && args[0] ? args[0] : null;
    const wantedReq = wanted ? items.find((r) => r.id === wanted) : null;
    let showAll = false;
    if (wantedReq) {
      ui.current = keyOf(wantedReq);
      // An answered one is shown among the answered for this view only;
      // the inbox's own choice stays as it was.
      if (wantedReq.status !== "open") showAll = true;
    }
    const names = {
      member: (id) => (ctx.nameOf ? ctx.nameOf(id) : id || "—"),
      project: (req) => (req.project && req.project.name)
        || (req.slug ? (ctx.projects.find((x) => x.full_name === req.slug) || { name: req.slug }).name : ""),
    };
    const sorts = ctx.scope === "all" ? ["priority", "date", "agent", "project"] : ["priority", "date", "agent"];
    if (!sorts.includes(ui.sort)) ui.sort = "priority";
    // The cross-project view lists what is waiting, nothing else.
    const show = () => (ctx.scope === "all" ? "open" : showAll ? "all" : ui.show);

    // The project filter is the cross-project view's only; a project no
    // longer in the switcher is no filter (it would empty the list for good).
    if (ui.project && !ctx.projects.some((p) => p.full_name === ui.project)) ui.project = "";
    const projectFilter = () => (ctx.scope === "all" ? ui.project : "");
    const grouped = () => ctx.scope === "all" && ui.group;
    const list = h("div", { class: "entries-box" });
    const listStatus = M.statusLine();
    if (items.personalError) listStatus.fail("Your personal requests about this project could not be read: ", items.personalError);

    // With no open entry on screen there is nothing being read or typed, so
    // a change of the counts reloads the list on its own (app.js, watch).
    ctx.quietReload = () => !ordered().some((r) => r.status === "open");

    // The entries in the order they are on screen: shown, filtered, sorted,
    // and grouped by project in the switcher's order. draw(), the next
    // entry after an answer, and the quiet reload all use this one order.
    function ordered() {
      const sorted = items
        .filter((r) => show() === "all" || r.status === "open")
        .filter((r) => !projectFilter() || r.slug === projectFilter())
        .sort(comparator(names));
      if (!grouped()) return sorted;
      // Personal requests first, in a group of their own; then by project.
      const at = (r) => { if (r.personal) return -1; const i = ctx.projects.findIndex((p) => p.full_name === r.slug); return i < 0 ? ctx.projects.length : i; };
      return sorted.map((r, i) => [r, i]).sort((a, b) => at(a[0]) - at(b[0]) || a[1] - b[1]).map(([r]) => r);
    }

    function draw() {
      const shown = ordered();
      const open = shown.filter((r) => r.status === "open");
      if (!shown.some((r) => keyOf(r) === ui.current)) ui.current = open.length ? keyOf(open[0]) : null;
      M.dom.clear(list);
      if (!shown.length) {
        append(list, h("ol", { class: "entries" }, h("li", { class: "empty" }, "No open requests.",
          h("p", { class: "first-hint" }, ctx.scope === "all"
            ? "Requests from the agents of every project land here: a decision, a consent or a question only you can answer. Each one shows its project."
            : "Your agents ask here when they need you: a decision, a consent or a question only you can answer. "
              + "When an agent waits for the answer, its card on the board shows it."))));
        return;
      }
      const entry = (req) => {
        const expanded = keyOf(req) === ui.current;
        return h("li", { class: "entry" + (expanded ? " current" : "") + (req.status !== "open" ? " done" : ""), "data-request": req.id },
          // A personal request carries its label in a project's inbox too (§18.2).
          ctx.scope === "all" || req.personal
            ? h("div", { class: "entry-row" }, projectBadge(ctx, req, names), entrySummary(ctx, req, names, expanded, () => {
              ui.current = expanded ? null : keyOf(req);
              draw();
            }))
            : entrySummary(ctx, req, names, expanded, () => {
              ui.current = expanded ? null : keyOf(req);
              draw();
            }),
          expanded ? entryBody(ctx, req, names, answer, later) : null);
      };
      if (grouped()) {
        // One section per project, its heading and its own list, so that a
        // list's items are its entries only.
        const groupOf = (r) => (r.personal ? "" : r.slug);
        const slugs = [...new Set(shown.map(groupOf))];
        slugs.forEach((slug) => {
          const own = shown.filter((r) => groupOf(r) === slug);
          const id = "inbox-group-" + (slug ? slug.replace("/", "-") : "personal");
          append(list, h("section", { class: "entry-group", "aria-labelledby": id },
            h("h3", { id }, slug ? names.project(own[0]) : "Personal", h("span", { class: "count" }, String(own.length))),
            h("ol", { class: "entries" }, own.map(entry))));
        });
      } else {
        append(list, h("ol", { class: "entries" }, shown.map(entry)));
      }
    }

    // The open entry after `after` in the current order, wrapping round to
    // the first; the order is taken before the answer changed anything.
    function next(order, after) {
      const i = order.findIndex((r) => keyOf(r) === keyOf(after));
      const rest = order.slice(i + 1).concat(order.slice(0, i));
      const pick = rest.find((r) => r.status === "open" && keyOf(r) !== keyOf(after));
      ui.current = pick ? keyOf(pick) : null;
    }

    function later(req) {
      const order = ordered();
      ui.later.add(keyOf(req));
      next(order, req);
      draw();
    }

    // A personal request is answered and withdrawn on /requests/{id} (§7):
    // the project's routes answer not_found for it.
    async function answer(req, payload, verb) {
      const order = ordered();
      const path = (req.personal ? "" : "/projects/" + M.api.projectPath(req.slug))
        + "/requests/" + encodeURIComponent(req.id) + "/" + (verb || "answer");
      const updated = await M.api.post(path, payload);
      updated.slug = req.slug;
      if (req.project) updated.project = req.project;
      items[items.indexOf(req)] = updated;
      ui.later.delete(keyOf(req));
      // Move on to the open entry after this one in the current order.
      next(order, req);
      draw();
      // The counts come from the hub (docs/api.md §5.1).
      try {
        await ctx.refreshCounts();
        ctx.markSeen();
        listStatus.done();
      } catch (err) {
        listStatus.fail("Answer sent; the counts could not be refreshed: ", err);
      }
    }

    const sortSelect = h("select", {
      id: "inbox-sort",
      onchange: (e) => { ui.sort = e.target.value; ui.current = null; draw(); },
    },
    sorts.map((s) => h("option", { value: s, selected: s === ui.sort }, s)));
    const showSelect = ctx.scope === "all" ? null : h("select", {
      id: "inbox-show",
      onchange: (e) => { ui.show = e.target.value; showAll = false; draw(); },
    },
    [["open", "open"], ["all", "all, answered too"]].map(([v, l]) => h("option", { value: v, selected: v === show() }, l)));

    // The cross-project view: a project filter and grouping by project.
    const projectSelect = ctx.scope === "all" ? h("select", {
      id: "inbox-project",
      onchange: (e) => { ui.project = e.target.value; ui.current = null; draw(); },
    }, h("option", { value: "" }, "every project"),
    // No counts in the options: the switcher beside it has them, kept current.
    ctx.projects.map((p) => h("option", { value: p.full_name }, p.name))) : null;
    if (projectSelect) projectSelect.value = ui.project;
    const groupBox = ctx.scope === "all" ? h("input", { type: "checkbox", id: "inbox-group", onchange: (e) => { ui.group = e.target.checked; draw(); } }) : null;
    if (groupBox) groupBox.checked = ui.group;

    // The project's banner (docs/api.md §11.2) heads its landing page.
    const banner = ctx.scope === "project" && M.api.imageUrl(ctx.slug, "banner", ctx.project.banner);
    if (banner) append(root, h("img", { class: "project-banner", src: banner, alt: "" }));
    append(root,
      h("div", { class: "toolbar" },
        h("h2", null, ctx.scope === "all" ? "Waiting for you, all projects" : "Inbox"),
        h("label", { for: "inbox-sort" }, "Sort by"), sortSelect,
        showSelect ? [h("label", { for: "inbox-show" }, "Show"), showSelect] : null,
        projectSelect ? [h("label", { for: "inbox-project" }, "Project"), projectSelect,
          h("label", { class: "check", for: "inbox-group" }, groupBox, " Group by project")] : null),
      listStatus.el,
      wanted && !wantedReq ? h("p", { class: "muted wanted-note", role: "status" }, "No request " + wanted + " in this project's inbox.") : null,
      list);
    draw();
    if (wantedReq) {
      const head = Array.from(list.querySelectorAll("li.entry")).filter((li) => li.getAttribute("data-request") === wanted)
        .map((li) => li.querySelector("button.entry-head"))[0];
      if (head) window.setTimeout(() => head.focus(), 0);
    }
  };
})(window.Maity);
