// (1) The inbox: what each agent wants from the human, one entry after the
// other. The first open entry in the chosen order is expanded; answering
// it expands the next. Runs in one project (#/p/<slug>/inbox) or across
// all of them (#/all), where every entry is labelled with its project.
// Requests carry everything an entry shows (docs/api.md §7): asker, card
// and context are inline, so no other call is made.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, formatAgo, formatTime } = M.dom;

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
  // only. req.slug is set on load; the API gives a cross-project item its
  // project as {slug, name, state} and a per-project item none.
  const keyOf = (req) => req.slug + "/" + req.id;

  // Who asked, from the request itself: asked_by and, where the request was
  // filed for someone else, on_behalf_of.
  function asker(req) {
    const by = req.asked_by ? req.asked_by.display_name : "—";
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
    if (to === ctx.me.id) return "you";
    if (to.startsWith("profile_owner:")) return "you, as the agent's owner";
    return ref(ctx, req, { member_id: to, display_name: ctx.nameOf ? ctx.nameOf(to) : to });
  }

  // In the cross-project view: the project's logo or monogram, its name
  // and state, a link to the project, before the entry it belongs to.
  function projectBadge(ctx, req, names) {
    const p = req.project || { slug: req.slug, name: names.project(req) };
    // A personal request (§7) is the human's, not the project's: no link to
    // a project inbox that never lists it, and maybe one is not a member of.
    if (req.personal) {
      return h("span", { class: "project-label personal" }, "Personal", h("span", { class: "muted" }, " · " + p.name));
    }
    return h("a", { class: "project-label", href: ctx.projectLink(p.slug, "inbox") },
      M.projectMark(p.slug, p.name, (ctx.projectViews || {})[p.slug], "small"),
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
    ctx.scope === "all" ? h("span", { class: "visually-hidden" }, (req.personal ? "Personal, " : "") + names.project(req) + ": ") : null,
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
  function ref(ctx, req, person) {
    const id = person && (person.member_id || person.id);
    const known = !req.personal && id && (ctx.scope !== "project" || (ctx.memberById || {})[id]);
    const view = { memberById: known ? { [id]: (ctx.memberById || {})[id] || Object.assign({ id }, person) } : {},
      link: (route, x) => ctx.projectLink(req.slug, route, x), nameOf: ctx.nameOf };
    return M.dom.memberRef(view, person);
  }

  function who(ctx, req, person) {
    return [ref(ctx, req, person), " · " + person.role + (person.session_id ? " · session " + person.session_id : "")];
  }

  function entryBody(ctx, req, names, onAnswer, onLater) {
    const body = h("div", { class: "entry-body" });

    append(body, h("dl", { class: "facts" },
      ctx.scope === "all" && req.personal
        ? [h("dt", null, "Project"), h("dd", null, names.project(req) + " — a personal request: for you as the owner of the agent, not for the project")]
        : null,
      ctx.scope === "all" && !req.personal
        ? [h("dt", null, "Project"), h("dd", null, h("a", { href: ctx.projectLink(req.slug, "inbox") }, names.project(req)))]
        : null,
      h("dt", null, "Asked by"), h("dd", null, req.asked_by ? who(ctx, req, req.asked_by) : "—"),
      req.on_behalf_of ? [h("dt", null, "On behalf of"), h("dd", null, who(ctx, req, req.on_behalf_of))] : null,
      req.to ? [h("dt", null, "To"), h("dd", null, addressee(ctx, req))] : null,
      h("dt", null, "Asked"), h("dd", null, formatTime(req.created_at)),
      req.task
        ? [h("dt", null, "Card"), h("dd", null, req.personal
          ? req.task.id + " — " + req.task.title + " (" + req.task.status.replace("_", " ") + ")"
          : h("a", { href: ctx.projectLink(req.slug, "board") },
            req.task.id + " — " + req.task.title + " (" + req.task.status.replace("_", " ") + ")"))]
        : null,
      h("dt", null, "Meanwhile"), h("dd", null, req.while_open === "proceed_provisionally"
        ? "the agent proceeds provisionally"
        : "the agent waits for the answer"),
      req.ktw_ref ? [h("dt", null, "Reasoning"), h("dd", null, h("code", null, req.ktw_ref))] : null));

    // Mentions link to the member in the request's own project (docs/api.md §8.6).
    // A personal request's project may be one the human is not in: no links there.
    const memberHref = (id) => (req.personal ? null : ctx.projectLink(req.slug, "members", id));
    const said = (field, text, mentions) => M.dom.withMentions(text, mentions, field, memberHref);
    if (req.summary) append(body, h("p", { class: "summary pre" }, said("summary", req.summary, req.mentions)));
    if (req.tried) append(body, h("h3", { class: "sub" }, "What it tried"), h("p", { class: "pre" }, said("tried", req.tried, req.mentions)));
    if (req.options && req.options.length) {
      append(body, h("h3", { class: "sub" }, "Options it sees"),
        h("ul", { class: "options" }, req.options.map((o) =>
          h("li", null, h("strong", null, o.label), o.detail ? " — " + o.detail : ""))));
    }
    const nis = req.needs_in_session;
    if (nis) {
      append(body, h("p", { class: "flag", role: "note" },
        h("strong", null, "Needs you in the session: "),
        nis.display_name + (nis.session_id ? " · " + nis.session_id : "") + (nis.harness ? " · " + nis.harness : "") + ". ",
        nis.reason));
    }

    if (req.status !== "open") {
      const a = req.answer;
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

    const textId = "reply-" + req.slug + "-" + req.id;
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
        [...(req.replies || []).filter((r) => replyClass(req, r) !== "reply primary"),
          ...(req.replies || []).filter((r) => replyClass(req, r) === "reply primary")].map((r) =>
          h("button", { type: "button", class: replyClass(req, r), onclick: () => send({ reply_id: r.id }) }, r.label))),
      h("div", { class: "free-text" },
        h("label", { for: textId }, "Free text (" + M.dom.SEND_KEYS + " sends)"),
        text,
        // @ offers this project's members; the hub links them, it pings nobody (§8.6).
        // Not for a personal request: its project may be one the human is not in.
        req.personal ? null : M.mentionPicker(text, () => M.api.getAll("/projects/" + encodeURIComponent(req.slug) + "/members").then((r) => r.items), ctx.me.id),
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

  async function load(ctx) {
    if (ctx.scope === "project") {
      const requests = await M.api.getAll(ctx.base + "/requests?status=all");
      requests.items.forEach((r) => { r.slug = ctx.slug; });
      return requests.items;
    }
    const requests = await M.api.getAll("/requests");
    requests.items.forEach((r) => { r.slug = r.project.slug; });
    return requests.items;
  }

  M.views.inbox = async function (ctx, root) {
    const items = await load(ctx);
    const names = {
      member: (id) => (ctx.nameOf ? ctx.nameOf(id) : id || "—"),
      project: (req) => (req.project && req.project.name)
        || (ctx.projects.find((x) => x.slug === req.slug) || { name: req.slug }).name,
    };
    const sorts = ctx.scope === "all" ? ["priority", "date", "agent", "project"] : ["priority", "date", "agent"];
    if (!sorts.includes(ui.sort)) ui.sort = "priority";
    // The cross-project view lists what is waiting, nothing else.
    const show = () => (ctx.scope === "all" ? "open" : ui.show);

    // The project filter is the cross-project view's only; a project no
    // longer in the switcher is no filter (it would empty the list for good).
    if (ui.project && !ctx.projects.some((p) => p.slug === ui.project)) ui.project = "";
    const projectFilter = () => (ctx.scope === "all" ? ui.project : "");
    const grouped = () => ctx.scope === "all" && ui.group;
    const list = h("div", { class: "entries-box" });
    const listStatus = M.statusLine();

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
      const at = (r) => { if (r.personal) return -1; const i = ctx.projects.findIndex((p) => p.slug === r.slug); return i < 0 ? ctx.projects.length : i; };
      return sorted.map((r, i) => [r, i]).sort((a, b) => at(a[0]) - at(b[0]) || a[1] - b[1]).map(([r]) => r);
    }

    function draw() {
      const shown = ordered();
      const open = shown.filter((r) => r.status === "open");
      if (!shown.some((r) => keyOf(r) === ui.current)) ui.current = open.length ? keyOf(open[0]) : null;
      M.dom.clear(list);
      if (!shown.length) {
        append(list, h("ol", { class: "entries" }, h("li", { class: "empty" }, "Nothing waits for you.",
          h("p", { class: "first-hint" }, ctx.scope === "all"
            ? "Requests from the agents of every project land here: a decision, a consent or a question only you can answer. Each one shows its project."
            : "Your agents ask here when they need you: a decision, a consent or a question only you can answer. "
              + "When an agent waits for the answer, its card on the board shows it."))));
        return;
      }
      const entry = (req) => {
        const expanded = keyOf(req) === ui.current;
        return h("li", { class: "entry" + (expanded ? " current" : "") + (req.status !== "open" ? " done" : "") },
          ctx.scope === "all"
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
          const id = "inbox-group-" + (slug || "personal");
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
      const path = (req.personal ? "" : "/projects/" + encodeURIComponent(req.slug))
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
      onchange: (e) => { ui.show = e.target.value; draw(); },
    },
    [["open", "open"], ["all", "all, answered too"]].map(([v, l]) => h("option", { value: v, selected: v === ui.show }, l)));

    // The cross-project view: a project filter and grouping by project.
    const projectSelect = ctx.scope === "all" ? h("select", {
      id: "inbox-project",
      onchange: (e) => { ui.project = e.target.value; ui.current = null; draw(); },
    }, h("option", { value: "" }, "every project"),
    // No counts in the options: the switcher beside it has them, kept current.
    ctx.projects.map((p) => h("option", { value: p.slug }, p.name))) : null;
    if (projectSelect) projectSelect.value = ui.project;
    const groupBox = ctx.scope === "all" ? h("input", { type: "checkbox", id: "inbox-group", onchange: (e) => { ui.group = e.target.checked; draw(); } }) : null;
    if (groupBox) groupBox.checked = ui.group;

    // The project's banner (docs/api.md §11.2) heads its landing page.
    const banner = ctx.scope === "project" && M.api.imageUrl(ctx.slug, "banner", ctx.project.banner);
    if (banner) append(root, h("img", { class: "project-banner", src: banner, alt: "" }));
    append(root,
      h("div", { class: "toolbar" },
        h("h2", null, ctx.scope === "all" ? "Waiting for you, all projects" : "Inbox"),
        ctx.scope === "project" ? h("a", { class: "button-link", href: ctx.link("message") }, "Message the project") : null,
        h("label", { for: "inbox-sort" }, "Sort by"), sortSelect,
        showSelect ? [h("label", { for: "inbox-show" }, "Show"), showSelect] : null,
        projectSelect ? [h("label", { for: "inbox-project" }, "Project"), projectSelect,
          h("label", { class: "check", for: "inbox-group" }, groupBox, " Group by project")] : null),
      listStatus.el,
      list);
    draw();
  };
})(window.Maity);
