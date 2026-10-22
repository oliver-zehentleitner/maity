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
  const ui = { sort: "priority", show: "open", current: null, later: new Set() };

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

  function addressee(ctx, to) {
    if (!to) return null;
    if (to === "owner") return "the project's owner";
    if (to.startsWith("role:")) return "role " + to.slice(5);
    if (to === ctx.me.id) return "you";
    return ctx.nameOf ? ctx.nameOf(to) : to;
  }

  function entrySummary(ctx, req, names, expanded, onToggle) {
    return h("button", {
      class: "entry-head",
      type: "button",
      "aria-expanded": expanded ? "true" : "false",
      onclick: onToggle,
    },
    h("span", { class: "prio prio-" + req.priority }, req.priority),
    h("span", { class: "kind" }, CLASS_LABELS[req.class] || req.class),
    ctx.scope === "all" && req.project
      ? h("span", { class: "project-label" },
        M.projectMark(req.project.slug, req.project.name, (ctx.projectViews || {})[req.project.slug], "small"),
        req.project.name,
        h("span", { class: "state state-" + req.project.state }, ctx.stateLabel(req.project.state)))
      : null,
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

  function who(person) {
    return person.display_name + " · " + person.role + (person.session_id ? " · session " + person.session_id : "");
  }

  function entryBody(ctx, req, names, onAnswer, onLater) {
    const body = h("div", { class: "entry-body" });

    append(body, h("dl", { class: "facts" },
      ctx.scope === "all"
        ? [h("dt", null, "Project"), h("dd", null, h("a", { href: ctx.projectLink(req.slug, "inbox") }, names.project(req)))]
        : null,
      h("dt", null, "Asked by"), h("dd", null, req.asked_by ? who(req.asked_by) : "—"),
      req.on_behalf_of ? [h("dt", null, "On behalf of"), h("dd", null, who(req.on_behalf_of))] : null,
      req.to ? [h("dt", null, "To"), h("dd", null, addressee(ctx, req.to))] : null,
      h("dt", null, "Asked"), h("dd", null, formatTime(req.created_at)),
      req.task
        ? [h("dt", null, "Card"), h("dd", null, h("a", { href: ctx.projectLink(req.slug, "board") },
          req.task.id + " — " + req.task.title + " (" + req.task.status.replace("_", " ") + ")"))]
        : null,
      h("dt", null, "Meanwhile"), h("dd", null, req.while_open === "proceed_provisionally"
        ? "the agent proceeds provisionally"
        : "the agent waits for the answer"),
      req.ktw_ref ? [h("dt", null, "Reasoning"), h("dd", null, h("code", null, req.ktw_ref))] : null));

    // Mentions link to the member in the request's own project (docs/api.md §8.6).
    const memberHref = (id) => ctx.projectLink(req.slug, "members", id);
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
        a ? " · " + names.member(a.by) + (a.on_behalf_of ? " for " + names.member(a.on_behalf_of) : "") + " · " + formatTime(a.at) : null));
      return body;
    }

    const status = M.statusLine();
    const send = (payload) => {
      body.querySelectorAll("button, textarea").forEach((el) => { el.disabled = true; });
      status.busy("Sending…");
      onAnswer(req, payload).catch((err) => {
        body.querySelectorAll("button, textarea").forEach((el) => { el.disabled = false; });
        status.fail("Not sent: ", err);
      });
    };

    const textId = "reply-" + req.slug + "-" + req.id;
    const text = h("textarea", { id: textId, rows: "3", placeholder: "Reply in your own words" });
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
        // The primary reply last, the others in the hub's order before it.
        [...(req.replies || []).filter((r) => replyClass(req, r) !== "reply primary"),
          ...(req.replies || []).filter((r) => replyClass(req, r) === "reply primary")].map((r) =>
          h("button", { type: "button", class: replyClass(req, r), onclick: () => send({ reply_id: r.id }) }, r.label))),
      h("div", { class: "free-text" },
        h("label", { for: textId }, "Free text"),
        text,
        // @ offers this project's members; the hub links them, it pings nobody (§8.6).
        M.mentionPicker(text, () => M.api.getAll("/projects/" + encodeURIComponent(req.slug) + "/members").then((r) => r.items), ctx.me.id),
        h("button", {
          type: "button",
          onclick: () => {
            const value = text.value.trim();
            if (!value) { text.focus(); return; }
            send({ text: value });
          },
        }, "Send")),
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

    const list = h("ol", { class: "entries" });
    const listStatus = M.statusLine();

    // With no open entry on screen there is nothing being read or typed, so
    // a change of the counts reloads the list on its own (app.js, watch).
    ctx.quietReload = () => !visible().some((r) => r.status === "open");

    function draw() {
      const shown = items
        .filter((r) => show() === "all" || r.status === "open")
        .sort(comparator(names));
      const open = shown.filter((r) => r.status === "open");
      if (!shown.some((r) => keyOf(r) === ui.current)) ui.current = open.length ? keyOf(open[0]) : null;
      M.dom.clear(list);
      if (!shown.length) {
        append(list, h("li", { class: "empty" }, "Nothing waits for you.",
          h("p", { class: "first-hint" }, ctx.scope === "all"
            ? "Requests from the agents of every project land here: a decision, a consent or a question only you can answer. Each one shows its project."
            : "Your agents ask here when they need you: a decision, a consent or a question only you can answer. "
              + "When an agent waits for the answer, its card on the board shows it.")));
        return;
      }
      shown.forEach((req) => {
        const expanded = keyOf(req) === ui.current;
        append(list, h("li", { class: "entry" + (expanded ? " current" : "") + (req.status !== "open" ? " done" : "") },
          entrySummary(ctx, req, names, expanded, () => {
            ui.current = expanded ? null : keyOf(req);
            draw();
          }),
          expanded ? entryBody(ctx, req, names, answer, later) : null));
      });
    }

    // The open entry after `after` in the current order, wrapping round to
    // the first; the order is taken before the answer changed anything.
    function next(order, after) {
      const i = order.findIndex((r) => keyOf(r) === keyOf(after));
      const rest = order.slice(i + 1).concat(order.slice(0, i));
      const pick = rest.find((r) => r.status === "open" && keyOf(r) !== keyOf(after));
      ui.current = pick ? keyOf(pick) : null;
    }

    const visible = () => items
      .filter((r) => show() === "all" || r.status === "open")
      .sort(comparator(names));

    function later(req) {
      const order = visible();
      ui.later.add(keyOf(req));
      next(order, req);
      draw();
    }

    async function answer(req, payload) {
      const order = visible();
      const updated = await M.api.post("/projects/" + encodeURIComponent(req.slug)
        + "/requests/" + encodeURIComponent(req.id) + "/answer", payload);
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

    // The project's banner (docs/api.md §11.2) heads its landing page.
    const banner = ctx.scope === "project" && M.api.imageUrl(ctx.slug, "banner", ctx.project.banner);
    if (banner) append(root, h("img", { class: "project-banner", src: banner, alt: "" }));
    append(root,
      h("div", { class: "toolbar" },
        h("h2", null, ctx.scope === "all" ? "Waiting for you, all projects" : "Inbox"),
        ctx.scope === "project" ? h("a", { class: "button-link", href: ctx.link("message") }, "Message the project") : null,
        h("label", { for: "inbox-sort" }, "Sort by"), sortSelect,
        showSelect ? [h("label", { for: "inbox-show" }, "Show"), showSelect] : null),
      listStatus.el,
      list);
    draw();
  };
})(window.Maity);
