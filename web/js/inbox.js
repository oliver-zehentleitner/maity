// (1) The inbox: what each agent wants from the human, one entry after the
// other. The first open entry in the chosen order is expanded; answering
// it expands the next.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, formatAgo, formatTime } = M.dom;

  const PRIORITY_RANK = { high: 0, normal: 1, low: 2 };

  const SORTS = {
    // Highest priority first; within one priority the longest waiting first.
    priority: (a, b) => (PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority])
      || a.created_at.localeCompare(b.created_at),
    date: (a, b) => b.created_at.localeCompare(a.created_at),
    agent: (ctx) => (a, b) => ctx.nameOf(a.agent_id).localeCompare(ctx.nameOf(b.agent_id))
      || SORTS.priority(a, b),
  };

  // Per tab only: which order and filter the human picked, and which entry
  // is open. Not persisted.
  const ui = { sort: "priority", show: "open", current: null };

  function sorted(ctx, items) {
    const cmp = ui.sort === "agent" ? SORTS.agent(ctx) : SORTS[ui.sort];
    return items.slice().sort(cmp);
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

  function entrySummary(ctx, req, expanded, onToggle) {
    return h("button", {
      class: "entry-head",
      type: "button",
      "aria-expanded": expanded ? "true" : "false",
      onclick: onToggle,
    },
    h("span", { class: "prio prio-" + req.priority }, req.priority),
    h("span", { class: "kind" }, req.kind),
    h("span", { class: "title" }, req.title),
    h("span", { class: "meta" }, ctx.nameOf(req.agent_id) + " · " + formatAgo(req.created_at)));
  }

  function entryBody(ctx, req, tasksById, onAnswer) {
    const c = req.context || {};
    const task = req.task_id ? tasksById[req.task_id] : null;
    const body = h("div", { class: "entry-body" });

    body.append(h("dl", { class: "facts" },
      h("dt", null, "Agent"), h("dd", null, ctx.nameOf(req.agent_id)),
      h("dt", null, "Asked"), h("dd", null, formatTime(req.created_at)),
      task ? [h("dt", null, "Task"), h("dd", null, h("a", { href: "#/board" }, task.id + " — " + task.title))] : null));

    if (c.summary) body.append(h("p", { class: "summary" }, c.summary));
    if (c.tried) body.append(h("h4", null, "What it tried"), h("p", { class: "pre" }, c.tried));
    if (c.options && c.options.length) {
      body.append(h("h4", null, "Options it sees"),
        h("ul", { class: "options" }, c.options.map((o) =>
          h("li", null, h("strong", null, o.label), o.detail ? " — " + o.detail : ""))));
    }
    if (req.harness_flag) {
      body.append(h("p", { class: "flag", role: "note" }, req.harness_flag));
    }

    if (req.status !== "open") {
      body.append(h("p", { class: "answered" },
        "Answered: " + answerLabel(req)
        + (req.answer && req.answer.text ? " — “" + req.answer.text + "”" : "")
        + (req.answer ? " · " + ctx.nameOf(req.answer.by) + " · " + formatTime(req.answer.at) : "")));
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

    const textId = "reply-" + req.id;
    const text = h("textarea", { id: textId, rows: "3", placeholder: "Reply in your own words" });
    body.append(
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

    const agent = ctx.memberById[req.agent_id];
    if (agent && agent.owner_id === ctx.me.id) {
      body.append(h("p", { class: "chat-link" },
        h("a", { href: "#/chat/" + encodeURIComponent(agent.id) }, "Chat with " + agent.display_name)));
    }
    return body;
  }

  M.views.inbox = async function (ctx, root) {
    const [requests, tasks] = await Promise.all([
      M.api.get(ctx.base + "/requests"),
      M.api.get(ctx.base + "/tasks"),
    ]);
    const tasksById = {};
    tasks.items.forEach((t) => { tasksById[t.id] = t; });

    const list = h("ol", { class: "entries" });

    function draw() {
      const shown = sorted(ctx, requests.items.filter((r) => ui.show === "all" || r.status === "open"));
      const open = shown.filter((r) => r.status === "open");
      if (!shown.some((r) => r.id === ui.current)) ui.current = open.length ? open[0].id : null;
      M.dom.clear(list);
      if (!shown.length) {
        list.append(h("li", { class: "empty" }, "Nothing waits for you."));
        return;
      }
      shown.forEach((req) => {
        const expanded = req.id === ui.current;
        list.append(h("li", { class: "entry" + (expanded ? " current" : "") + (req.status !== "open" ? " done" : "") },
          entrySummary(ctx, req, expanded, () => {
            ui.current = expanded ? null : req.id;
            draw();
          }),
          expanded ? entryBody(ctx, req, tasksById, answer) : null));
      });
    }

    async function answer(req, payload) {
      const updated = await M.api.post(ctx.base + "/requests/" + encodeURIComponent(req.id) + "/answer", payload);
      const i = requests.items.findIndex((r) => r.id === req.id);
      requests.items[i] = updated;
      // Move on to the next open entry in the current order.
      const open = sorted(ctx, requests.items.filter((r) => r.status === "open"));
      ui.current = open.length ? open[0].id : null;
      ctx.openRequests = requests.items.filter((r) => r.status === "open").length;
      const count = document.querySelector('nav a[href="#/inbox"] .count');
      if (count) {
        if (ctx.openRequests) count.textContent = String(ctx.openRequests);
        else count.remove();
      }
      draw();
    }

    const sortSelect = h("select", {
      id: "inbox-sort",
      onchange: (e) => { ui.sort = e.target.value; ui.current = null; draw(); },
    },
    ["priority", "date", "agent"].map((s) => h("option", { value: s, selected: s === ui.sort }, s)));
    const showSelect = h("select", {
      id: "inbox-show",
      onchange: (e) => { ui.show = e.target.value; draw(); },
    },
    [["open", "open"], ["all", "all, answered too"]].map(([v, l]) => h("option", { value: v, selected: v === ui.show }, l)));

    root.append(
      h("div", { class: "toolbar" },
        h("h2", null, "Inbox"),
        h("label", { for: "inbox-sort" }, "Sort by"), sortSelect,
        h("label", { for: "inbox-show" }, "Show"), showSelect),
      list);
    draw();
  };
})(window.Maity);
