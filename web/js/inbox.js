// (1) The inbox: what each agent wants from the human, one entry after the
// other. The first open entry in the chosen order is expanded; answering
// it expands the next. Runs in one project (#/p/<slug>/inbox) or across
// all of them (#/all), where every entry is labelled with its project.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, formatAgo, formatTime } = M.dom;

  const PRIORITY_RANK = { high: 0, normal: 1, low: 2 };

  // Per tab only: which order and filter the human picked, and which entry
  // is open. Not persisted.
  const ui = { sort: "priority", show: "open", current: null };

  // An entry is addressed by project and id: ids are unique per project only.
  const keyOf = (req) => req.project + "/" + req.id;

  function comparator(names) {
    const priority = (a, b) => (PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority])
      || a.created_at.localeCompare(b.created_at);
    if (ui.sort === "date") return (a, b) => b.created_at.localeCompare(a.created_at);
    if (ui.sort === "agent") return (a, b) => names.agent(a).localeCompare(names.agent(b)) || priority(a, b);
    if (ui.sort === "project") return (a, b) => names.project(a).localeCompare(names.project(b)) || priority(a, b);
    // Highest priority first; within one priority the longest waiting first.
    return priority;
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

  function entrySummary(ctx, req, names, expanded, onToggle) {
    const project = ctx.scope === "all" ? ctx.projects.find((p) => p.slug === req.project) : null;
    return h("button", {
      class: "entry-head",
      type: "button",
      "aria-expanded": expanded ? "true" : "false",
      onclick: onToggle,
    },
    h("span", { class: "prio prio-" + req.priority }, req.priority),
    h("span", { class: "kind" }, req.kind),
    project
      ? h("span", { class: "project-label" }, project.name,
        h("span", { class: "state state-" + project.state }, ctx.stateLabel(project.state)))
      : null,
    h("span", { class: "title" }, req.title),
    h("span", { class: "meta" }, names.agent(req) + " · " + formatAgo(req.created_at)));
  }

  function entryBody(ctx, req, names, tasksById, onAnswer) {
    const c = req.context || {};
    const task = req.task_id ? tasksById[req.task_id] : null;
    const body = h("div", { class: "entry-body" });

    append(body, h("dl", { class: "facts" },
      ctx.scope === "all"
        ? [h("dt", null, "Project"), h("dd", null, h("a", { href: ctx.projectLink(req.project, "inbox") }, names.project(req)))]
        : null,
      h("dt", null, "Agent"), h("dd", null, names.agent(req)),
      h("dt", null, "Asked"), h("dd", null, formatTime(req.created_at)),
      req.task_id
        ? [h("dt", null, "Task"), h("dd", null, h("a", { href: ctx.projectLink(req.project, "board") },
          req.task_id + (task ? " — " + task.title : "")))]
        : null));

    if (c.summary) append(body, h("p", { class: "summary" }, c.summary));
    if (c.tried) append(body, h("h4", null, "What it tried"), h("p", { class: "pre" }, c.tried));
    if (c.options && c.options.length) {
      append(body, h("h4", null, "Options it sees"),
        h("ul", { class: "options" }, c.options.map((o) =>
          h("li", null, h("strong", null, o.label), o.detail ? " — " + o.detail : ""))));
    }
    if (req.harness_flag) {
      append(body, h("p", { class: "flag", role: "note" }, req.harness_flag));
    }

    if (req.status !== "open") {
      append(body, h("p", { class: "answered" },
        "Answered: " + answerLabel(req)
        + (req.answer && req.answer.text ? " — “" + req.answer.text + "”" : "")
        + (req.answer ? " · " + names.member(req.project, req.answer.by) + " · " + formatTime(req.answer.at) : "")));
      return body;
    }

    const status = h("p", { class: "send-status", role: "status" });
    const send = (payload) => {
      body.querySelectorAll("button, textarea").forEach((el) => { el.disabled = true; });
      status.textContent = "Sending…";
      onAnswer(req, payload).catch((err) => {
        body.querySelectorAll("button, textarea").forEach((el) => { el.disabled = false; });
        status.textContent = "Not sent: " + err.message;
        status.className = "send-status failed";
      });
    };

    const textId = "reply-" + req.project + "-" + req.id;
    const text = h("textarea", { id: textId, rows: "3", placeholder: "Reply in your own words" });
    append(body,
      h("div", { class: "replies" },
        (req.replies || []).map((r) =>
          h("button", { type: "button", class: "reply reply-" + r.id, onclick: () => send({ reply_id: r.id }) }, r.label)),
        h("button", { type: "button", class: "reply talk", onclick: () => send({ talk: true }) }, "Neither — let's talk")),
      h("div", { class: "free-text" },
        h("label", { for: textId }, "Free text"),
        text,
        h("button", {
          type: "button",
          onclick: () => {
            const value = text.value.trim();
            if (!value) { text.focus(); return; }
            send({ text: value });
          },
        }, "Send")),
      status);

    const agent = names.memberObj(req.project, req.agent_id);
    if (agent && agent.owner_id === ctx.me.id) {
      append(body, h("p", { class: "chat-link" },
        h("a", { href: ctx.projectLink(req.project, "chat", agent.id) }, "Chat with " + agent.display_name)));
    }
    return body;
  }

  // Requests, members per project and tasks for the scope being shown.
  async function load(ctx) {
    if (ctx.scope === "project") {
      const [requests, tasks] = await Promise.all([
        M.api.get(ctx.base + "/requests"),
        M.api.get(ctx.base + "/tasks"),
      ]);
      const tasksById = {};
      tasks.items.forEach((t) => { tasksById[t.id] = t; });
      requests.items.forEach((r) => { r.project = ctx.slug; });
      return { items: requests.items, members: { [ctx.slug]: ctx.memberById }, tasksById };
    }
    const requests = await M.api.get("/requests?scope=all");
    const slugs = [...new Set(requests.items.map((r) => r.project))];
    const lists = await Promise.all(slugs.map((s) => M.api.get("/projects/" + encodeURIComponent(s) + "/members")));
    const members = {};
    slugs.forEach((s, i) => {
      members[s] = {};
      lists[i].items.forEach((m) => { members[s][m.id] = m; });
    });
    return { items: requests.items, members, tasksById: {} };
  }

  M.views.inbox = async function (ctx, root) {
    const data = await load(ctx);
    const names = {
      memberObj: (slug, id) => (data.members[slug] || {})[id] || null,
      member: (slug, id) => { const m = names.memberObj(slug, id); return m ? m.display_name : id || "—"; },
      agent: (req) => names.member(req.project, req.agent_id),
      project: (req) => { const p = ctx.projects.find((x) => x.slug === req.project); return p ? p.name : req.project; },
    };
    const sorts = ctx.scope === "all" ? ["priority", "date", "agent", "project"] : ["priority", "date", "agent"];
    if (!sorts.includes(ui.sort)) ui.sort = "priority";
    // The cross-project view lists what is waiting, nothing else.
    const show = () => (ctx.scope === "all" ? "open" : ui.show);

    const list = h("ol", { class: "entries" });

    function draw() {
      const shown = data.items
        .filter((r) => show() === "all" || r.status === "open")
        .sort(comparator(names));
      const open = shown.filter((r) => r.status === "open");
      if (!shown.some((r) => keyOf(r) === ui.current)) ui.current = open.length ? keyOf(open[0]) : null;
      M.dom.clear(list);
      if (!shown.length) {
        append(list, h("li", { class: "empty" }, "Nothing waits for you."));
        return;
      }
      shown.forEach((req) => {
        const expanded = keyOf(req) === ui.current;
        append(list, h("li", { class: "entry" + (expanded ? " current" : "") + (req.status !== "open" ? " done" : "") },
          entrySummary(ctx, req, names, expanded, () => {
            ui.current = expanded ? null : keyOf(req);
            draw();
          }),
          expanded ? entryBody(ctx, req, names, data.tasksById, answer) : null));
      });
    }

    async function answer(req, payload) {
      const updated = await M.api.post("/projects/" + encodeURIComponent(req.project)
        + "/requests/" + encodeURIComponent(req.id) + "/answer", payload);
      updated.project = req.project;
      data.items[data.items.indexOf(req)] = updated;
      // Move on to the next open entry in the current order.
      const open = data.items.filter((r) => r.status === "open").sort(comparator(names));
      ui.current = open.length ? keyOf(open[0]) : null;
      ctx.adjustOpen(req.project, -1);
      draw();
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

    append(root,
      h("div", { class: "toolbar" },
        h("h2", null, ctx.scope === "all" ? "Waiting for you, all projects" : "Inbox"),
        h("label", { for: "inbox-sort" }, "Sort by"), sortSelect,
        showSelect ? [h("label", { for: "inbox-show" }, "Show"), showSelect] : null),
      list);
    draw();
  };
})(window.Maity);
