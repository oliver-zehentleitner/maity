// (11) Messages (/<owner>/<slug>/messages): the project's messages the reader
// may see (docs/api.md §8.4, every type but chat), newest first, by type:
// who wrote to whom, about which card, the text as Markdown, the members
// it mentions as links, and its files (§8.7). The uploader or an admin
// deletes a file; an admin removes a message (§8.5). The view pages through
// the hub's listing (§8.8): its newest page first, older ones by the
// listing's cursor, the type filter the hub's. The project's feed is only
// the signal, as on the Ticker: a new message there reads the listing
// forward from the newest one shown, following its cursor; removals and deleted files change
// the list in place. A removed message stays as the listing's tombstone,
// or leaves a list filtered by type, which shows what is still there.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  // The words are read when drawn, so a language set after the page loads applies.
  const TYPE_WORDS = {
    notice: () => M.t("messages.type.notice"), handover: () => M.t("messages.type.handover"),
    blocker: () => M.t("messages.type.blocker"), go_request: () => M.t("messages.type.go_request"),
    review_result: () => M.t("messages.type.review_result"), interface_change: () => M.t("messages.type.interface_change"),
  };
  const typeWord = (type) => (Object.hasOwn(TYPE_WORDS, type) ? TYPE_WORDS[type]() : type);
  const PAGE = 50;
  // How many pages of new messages one live round reads at most.
  const LIVE_PAGES = 20;

  // A project message on the feed (§8.3), as the listing has it: not a chat's.
  const isMessage = (e) => e.kind === "message" && !e.redacted && e.payload && e.payload.type !== "chat";

  function toWords(ctx, to) {
    if (to === "all") return M.t("messages.to.everyone");
    if (/^role:/.test(to || "")) return M.t("messages.to.role", { role: to.slice(5) });
    return M.dom.memberRef(ctx, to);
  }

  // A review result's facts (§8.4): the verdict, what was reviewed, the
  // commit at its short head, and the places the reviewer read, each with
  // its quote as written. Folded after five; all text as text.
  const VERDICTS = {
    approve: () => M.t("messages.verdict.approve"), changes: () => M.t("messages.verdict.changes"),
    comment: () => M.t("messages.verdict.comment"),
  };
  const CITES_SHOWN = 5;
  // A commit's page on the project's forge, GitHub and GitLab, whose path
  // shapes are known; anything else gets no link.
  function commitUrl(repo, head) {
    const base = repo && M.dom.safeUrl(repo.url) ? String(repo.url).replace(/\.git$/, "").replace(/\/+$/, "") : null;
    if (!base || !/^[0-9a-f]{40}$/.test(head)) return null;
    if (repo.forge === "github") return base + "/commit/" + head;
    if (repo.forge === "gitlab") return base + "/-/commit/" + head;
    return null;
  }
  function reviewBlock(ctx, r) {
    const head = String(r.head || "");
    const short = h("code", null, head.slice(0, 7));
    const url = commitUrl(ctx.project && ctx.project.repository, head);
    const cite = (c) => h("li", { class: "review-cite" },
      h("span", { class: "review-place" }, h("code", null, c.path + (c.line ? ":" + c.line : "")), c.line ? null : h("span", { class: "muted" }, " " + M.t("messages.review.removed"))),
      h("code", { class: "review-quote" }, c.quote));
    const cites = r.cites || [];
    const shown = cites.slice(0, CITES_SHOWN);
    const rest = cites.slice(CITES_SHOWN);
    return h("div", { class: "review" },
      h("p", { class: "review-head" },
        h("span", { class: "pill review-verdict verdict-" + r.verdict }, Object.hasOwn(VERDICTS, r.verdict) ? VERDICTS[r.verdict]() : String(r.verdict)),
        " ", M.tn("messages.review.subject_at", {
          subject: r.subject || "",
          commit: url ? h("a", { href: url, rel: "noopener noreferrer", target: "_blank", title: head }, short) : h("span", { title: head }, short),
        })),
      cites.length ? h("ul", { class: "review-cites", "aria-label": M.t("messages.review.places") }, shown.map(cite)) : null,
      rest.length ? h("details", { class: "review-more" }, h("summary", null, M.t("messages.review.more", { count: rest.length })),
        h("ul", { class: "review-cites" }, rest.map(cite))) : null);
  }

  // Opened for one message (`#seq-<n>`, js/event.js, docs/api.md §8.9): older pages are
  // read until it is shown, at most this many, as in a chat (js/chat.js reveal).
  const REVEAL_PAGES = 10;

  M.views.messages = async function (ctx, root) {
    const here = M.route.current().path;
    // The message an event's link opened the listing at, marked where it is drawn.
    const target = M.route.seqTarget();
    // Its tombstone too: a removed message is still where the link points (§8.9 keeps a redacted event readable).
    const marked = (x) => (target && String(x.seq) === target ? " seq-target" : "");
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    let filter = "";
    let cursor = null;
    // Each read belongs to one filter; an answer of an older one is dropped.
    let gen = 0;
    let busy = false;
    // A first page still on its way: a signal meanwhile waits for it (ticker.js).
    let resetting = true;
    let liveAgain = false;
    let loaded = false;
    // The newest seq shown; floor, where a live read starts while none is.
    let top = 0;
    let floor = 0;
    const shown = new Map();
    const list = h("ol", { class: "project-messages" });
    const more = h("div", { class: "actions" });
    const query = (extra) => ctx.base + "/messages?" + [filter ? "type=" + encodeURIComponent(filter) : null, "limit=" + PAGE, extra || null].filter(Boolean).join("&");
    const itemOf = (seq) => Array.from(list.querySelectorAll("li.pmsg")).find((li) => li.getAttribute("data-seq") === String(seq));
    // Nothing shown: "none" only at the end of the history (next_cursor
    // null, §8.8); a page the hub's scan budget cut short may be empty while
    // older messages are still unread.
    const empty = () => h("li", { class: "empty muted" },
      cursor ? M.t("messages.not_read_yet") : filter ? M.t("messages.none_of_type") : M.t("messages.none"));
    const fillEmpty = () => {
      const blank = list.querySelector("li.empty");
      if (blank) list.removeChild(blank);
      if (!list.querySelector("li.pmsg")) append(list, empty());
    };
    // Items of one answer not shown yet, each once, also within the answer.
    const fresh = (items) => items.filter((x, i) => !shown.has(x.seq) && items.findIndex((y) => y.seq === x.seq) === i);
    const mark = (x) => { shown.set(x.seq, x); if (x.seq > top) top = x.seq; };
    // One button for older pages, kept while a cursor remains, so it keeps
    // the focus across clicks; busy is aria-disabled, which keeps it too.
    const older = h("button", { type: "button", class: "small", onclick: () => load(false) }, M.t("messages.older"));
    function drawMore() {
      if (busy) older.setAttribute("aria-disabled", "true"); else older.removeAttribute("aria-disabled");
      if (cursor && older.parentNode !== more) append(more, older);
      if (!cursor && older.parentNode === more) more.removeChild(older);
    }

    // Removed, here or by someone else (§8.5): the tombstone in its place,
    // as the listing has it; a list filtered by type drops it.
    function removed(seq) {
      const li = itemOf(seq);
      if (!li) return;
      const x = shown.get(seq);
      if (!filter && x) {
        const gone = Object.assign({}, x, { type: null, to: null, task_id: null, body: null, mentions: [], attachments: [], review: null, redacted: true });
        shown.set(seq, gone);
        list.insertBefore(item(gone), li);
      }
      list.removeChild(li);
      fillEmpty();
    }

    async function remove(x) {
      const reason = M.chatParts.askReason(M.t("messages.remove.ask"));
      if (reason === null) return;
      status.busy(M.t("messages.remove.busy"));
      try {
        await M.api.post(ctx.base + "/events/" + encodeURIComponent(x.seq) + "/redact", { reason });
      } catch (err) {
        status.fail(M.t("messages.remove.failed"), err);
        return;
      }
      removed(x.seq);
      status.done();
      append(status.el, h("span", { class: "ok" }, M.t("messages.remove.done")));
      status.el.focus();
    }

    // A listing item (§8.8): from, from_instance, to, task_id, sent_at.
    function item(x) {
      const from = x.from;
      const who = () => M.dom.memberRef(ctx, from, { instance: x.from_instance });
      // An update sent without one has no addressee (§8.4).
      const head = (badge) => h("div", { class: "pmsg-head" }, badge,
        h("span", null, " ", x.to ? M.tn("messages.from_to", { from: who(), to: toWords(ctx, x.to) }) : who()),
        x.task_id ? [" · ", h("a", { href: ctx.link("tasks", x.task_id) }, x.task_id)] : null,
        " · ", h("span", { class: "muted" }, formatTime(x.sent_at)));
      if (x.redacted) {
        return h("li", { class: "pmsg removed" + marked(x), "data-seq": String(x.seq) }, head(null), h("p", { class: "muted msg-redacted" }, M.t("messages.removed")));
      }
      const review = x.type === "review_result" && x.review ? reviewBlock(ctx, x.review) : null;
      // The file's uploader is the message's sender; an admin deletes any (§8.7).
      const canDelete = () => from === ctx.me.id || ctx.canAdmin;
      return h("li", { class: "pmsg type-" + x.type + marked(x), "data-seq": String(x.seq) },
        head(h("span", { class: "badge" }, typeWord(x.type))),
        review,
        // Its mentions are links where they stand (the one renderer, js/markdown.js).
        x.body ? h("div", { class: "md" }, M.markdown(x.body, M.ids.where(ctx), { mentions: x.mentions, hrefOf: (id) => ctx.link("team", id), ctx })) : null,
        M.attachments ? M.attachments.render(ctx, { attachments: x.attachments, body: x.body || "" }, canDelete) : null,
        (() => {
          // Report someone else's message (§16.8, tsk-7ze5w6ymf7bw): its seq with the project.
          const reporting = M.report && from !== ctx.me.id && ctx.me.kind === "human"
            ? M.report.control({ type: "message", id: String(x.seq), project: ctx.slug }, "message") : null;
          if (!ctx.canAdmin && !reporting) return null;
          return [h("div", { class: "actions" },
            ctx.canAdmin ? h("button", { type: "button", class: "small", "aria-label": M.t("messages.remove.label"), onclick: () => remove(x) }, M.t("messages.remove")) : null,
            reporting ? [" ", reporting.button] : null), reporting ? reporting.slot : null];
        })());
    }

    // A page, newest first: the first one of a filter (reset), or the next
    // older one by the listing's cursor. given: a page already read.
    async function load(reset, given) {
      if (!reset && busy) return;
      const mine = reset ? ++gen : gen;
      if (reset) { clear(list); shown.clear(); top = 0; cursor = null; liveFrom = null; liveCursor = null; resetting = true; loaded = false; }
      busy = true;
      drawMore();
      const hadFocus = !reset && document.activeElement === older;
      let page = given;
      try {
        if (!page) page = await M.api.get(query(cursor ? "cursor=" + encodeURIComponent(cursor) : null));
      } catch (err) {
        if (mine !== gen) return;
        busy = false;
        resetting = false;
        drawMore();
        status.fail(M.t("messages.read_failed"), err);
        return;
      }
      if (mine !== gen) return;
      busy = false;
      const added = fresh(page.items);
      added.forEach((x) => { mark(x); append(list, item(x)); });
      cursor = page.next_cursor;
      fillEmpty();
      drawMore();
      // The last older page takes the button away: the focus goes to the
      // first message it added, not to the page's body.
      if (hadFocus && !cursor) {
        const to = added.length ? itemOf(added[0].seq) : null;
        if (to) { to.setAttribute("tabindex", "-1"); to.focus(); } else status.el.focus();
      }
      if (reset) {
        resetting = false;
        loaded = true;
        status.done();
        if (liveAgain) live();
      }
    }

    // New messages with the feed: the listing forward from the newest one
    // shown, oldest first (§8.8), in this filter. A round keeps its after=
    // and follows next_cursor, empty pages too, until it is null: a page
    // examines at most the hub's scan budget, so a short one is not the
    // end. A round out of pages leaves its cursor to the next one. A signal
    // while a read runs is kept: the read runs once more afterwards.
    let liveBusy = false;
    let liveFrom = null;
    let liveCursor = null;
    async function live() {
      if (liveBusy || resetting) { liveAgain = true; return; }
      if (!loaded) { load(true); return; }
      liveBusy = true;
      liveAgain = false;
      const mine = gen;
      let added = 0;
      const from = liveCursor ? liveFrom : top || floor;
      let next = liveCursor;
      try {
        for (let n = 0; n < LIVE_PAGES; n++) {
          const page = await M.api.get(query("after=" + from + (next ? "&cursor=" + encodeURIComponent(next) : "")));
          if (mine !== gen) return;
          fresh(page.items).forEach((x) => { mark(x); list.insertBefore(item(x), list.firstChild); added += 1; });
          next = page.next_cursor;
          if (!next) break;
        }
        liveFrom = next ? from : null;
        liveCursor = next;
      } catch (err) {
        if (mine === gen) status.fail(M.t("messages.new_failed"), err);
        return;
      } finally {
        liveBusy = false;
        if (liveAgain && !resetting) live();
      }
      if (!added) { status.done(); return; }
      fillEmpty();
      status.done();
      append(status.el, h("span", null, M.t("messages.new", { count: added })));
    }

    const first = await M.api.get(query());
    if (M.route.current().path !== here) return;

    ctx.onEvents((events) => {
      const arrived = events.filter((e) => isMessage(e) && !shown.has(e.seq)).map((e) => e.seq);
      events.forEach((e) => {
        if (e.kind === "event_redacted" && e.payload) removed(e.payload.seq);
        if (e.kind === "attachment_deleted" && e.payload) M.attachments.markDeleted(list, e.payload.attachment_id);
      });
      if (!arrived.length) return;
      // Nothing shown yet: the read starts just below the first that arrived.
      const below = Math.min(...arrived) - 1;
      floor = floor ? Math.min(floor, below) : below;
      live();
    });

    const pick = h("select", { id: "messages-type", onchange: (ev) => { filter = ev.target.value; load(true); } },
      h("option", { value: "" }, M.t("messages.filter.every_type")), Object.keys(TYPE_WORDS).map((v) => h("option", { value: v }, typeWord(v))));
    append(root,
      h("div", { class: "toolbar" }, h("h2", null, M.t("messages.title")), h("a", { class: "button small", href: ctx.link("message") }, M.t("messages.write"))),
      h("p", { class: "muted" }, M.t("messages.intro")),
      h("form", { class: "board-filter", role: "search", onsubmit: (ev) => ev.preventDefault() },
        h("label", { for: "messages-type" }, M.t("messages.filter.type")), pick),
      status.el, list, more);
    await load(true, first);
    if (!target) return;
    // Older pages while the message is not shown and the listing goes below it; a filter
    // chosen meanwhile ends the search.
    const filterAt = filter;
    for (let n = 0; !itemOf(target) && n < REVEAL_PAGES && cursor && filter === filterAt
      && (!shown.size || Number(target) < Math.min(...shown.keys())); n += 1) await load(false);
    const li = itemOf(target);
    if (!li) { list.parentNode.insertBefore(h("p", { class: "muted seq-missed", role: "status" }, M.t("event.not_reached", { seq: target })), list); return; }
    // Scrolled to once the view is in the page, which the router does after this returns.
    window.setTimeout(() => { if (li.scrollIntoView) li.scrollIntoView({ block: "center" }); }, 0);
  };
})(window.Maity);
