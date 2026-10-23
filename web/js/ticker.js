// (12) Ticker (#/p/<slug>/ticker, docs/api.md §17): the project's change
// feed — merges, decisions, deploys, releases and notes — newest first,
// "For me" and "Everything" as two tabs, filtered by type and area, paged
// with the hub's cursor. An item is its text (plain, never Markdown), its
// link when it is https, and for the viewer why it is theirs, in words.
// The viewer's own follow and mute are edited here (§17.8); an owner or
// admin posts a note, a deploy or a release (§17.6). New items come with
// the project's feed. A hub without the ticker says so, asked once per
// page load.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl, formatTime } = M.dom;

  const TYPES = [["merge", "Merges"], ["contract", "Contract changes"], ["decision", "Decisions"], ["deploy", "Deploys"], ["release", "Releases"], ["note", "Notes"]];
  const TYPE_WORD = { merge: "Merge", decision: "Decision", deploy: "Deploy", release: "Release", note: "Note" };
  const TYPE_PLURAL = { merge: "merges", contract: "contract changes", decision: "decisions", deploy: "deploys", release: "releases", note: "notes" };
  const PAGE = 50;
  // How many pages of new items one live round reads at most.
  const LIVE_PAGES = 20;
  // Whether this hub has the ticker, from its machine form (§17.6), never
  // from a 404 alone. A hub without it is not asked again until the page is
  // loaded anew; a hub with it is asked again on the next unexplained 404.
  let hubHas = null;

  const article = (word) => (/^[aeiou]/.test(word) ? "an " : "a ") + word;
  // A reason token (§17.3, §17.6, §17.8) as the viewer reads it.
  function whyWords(token) {
    const [kind, ...rest] = token.split(":");
    const arg = rest.join(":");
    switch (kind) {
      case "area_owner": return arg === "/" || arg === "*" ? "you own the whole repository" : "you own " + arg;
      case "card_holder": return "you hold " + arg;
      case "card_assignee": return "you are assigned " + arg;
      case "contract_implementer": return arg === "*" ? "you implement the contract" : "you implement §" + arg;
      case "role": return "you are " + article(arg);
      case "decision_asker": return "you asked";
      case "decision_on_behalf_of": return "it was asked for you";
      case "contract_watcher": return "you watch the contract";
      case "all_members": return "it is for everyone";
      case "posted_to_all": return "it was posted to everyone";
      case "addressed": return "it was addressed to you";
      case "follow": return rest[0] === "type" ? "you follow " + (TYPE_PLURAL[rest[1]] || rest.slice(1).join(":")) : "you follow " + arg;
      default: return token;
    }
  }

  // The hub's refusals, in words: which field, and why (§17.6, §17.8).
  const FIELD_NAMES = {
    type: "The type", text: "The text", url: "The link", to: "Whom it goes to", areas: "The areas", release_task_id: "The release card",
    deploy: "The deploy's environment and version or sha", "deploy.environment": "The environment", "deploy.log_url": "The log URL",
    "follow.areas": "The areas you follow", "follow.types": "The types you follow", "mute.areas": "The areas you mute", "mute.types": "The types you mute",
  };
  const WHY_WORDS = {
    not_for_type: "does not go with this type", required: "is missing", not_done: "must name a release card that is done",
    too_many: "may hold at most 20", invalid: "is not valid",
  };
  function said(err, what) {
    if (err.code === "ticker_duplicate") return { message: "this was posted already" + (err.details && err.details.seq ? " (item " + err.details.seq + ")" : "") };
    if (err.code === "rate_limited") return { message: what === "post" ? "too many posts in the last hour; try again later" : "too many changes in a short time; try again later" };
    if (err.code === "forbidden") return { message: what === "post" ? "only an owner or admin may post to the ticker" : "you may change only your own follow and mute" };
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) {
      return { message: Object.entries(fields).map(([f, why]) => (FIELD_NAMES[f] || "The field " + f) + " "
        + (WHY_WORDS[why] || "was refused (" + why + ")")).join("; ") };
    }
    return err;
  }

  // Whether the hub lists the ticker in its machine form (§17.6: a 404 on
  // the listing alone may be a mistyped project).
  async function hubHasTicker() {
    if (hubHas === false) return false;
    const doc = await M.api.get("/openapi.json");
    // The hub lists its paths under its prefix (/api/v1/…); either form counts, as in the CLI.
    const paths = (doc && doc.paths) || {};
    hubHas = !!(paths["/projects/{slug}/ticker"] || paths["/api/v1/projects/{slug}/ticker"]);
    return hubHas;
  }

  M.views.ticker = async function (ctx, root) {
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const toolbar = h("div", { class: "toolbar" }, h("h2", null, "Ticker"));
    const none = () => append(root, toolbar, h("p", { class: "muted" }, "This hub has no ticker yet."));
    if (hubHas === false) { none(); return; }
    let forMe = true;
    let type = "";
    let area = "";
    let cursor = null;
    // Each read belongs to one filter set; an answer of an older one is dropped.
    let gen = 0;
    let busy = false;
    // A first page of a filter set still on its way: no live read until it is
    // in, since `top` is not known yet; a signal meanwhile is kept for after.
    let resetting = false;
    let liveAgain = false;
    // Whether the first page of this filter set is in; after a failed one a
    // signal reads that page again rather than everything from the start.
    let loaded = false;
    const shown = new Set();
    let top = 0;
    const list = h("ol", { class: "ticker-list" });
    const more = h("div", { class: "actions" });
    const query = (extra) => ctx.base + "/ticker?" + [forMe ? "for=me" : "for=all", type ? "type=" + encodeURIComponent(type) : null,
      area ? "area=" + encodeURIComponent(area) : null, "limit=" + PAGE, extra || null].filter(Boolean).join("&");

    function item(x) {
      const link = safeUrl(x.url);
      const decided = x.type === "decision" && x.detail
        ? "Decided: " + (x.detail.reply_label ? x.detail.reply_label : "answered in writing") + " — " + x.detail.request_title : null;
      return h("li", { class: "ticker-item type-" + x.type + (x.for_me ? " for-me" : ""), "data-seq": String(x.seq) },
        h("div", { class: "ticker-head" },
          h("span", { class: "badge" }, x.type === "merge" && x.contract ? "Contract change" : TYPE_WORD[x.type] || x.type),
          " ", h("span", { class: "muted" }, formatTime(x.at) + (x.actor && x.actor.member_id ? " · " + ctx.nameOf(x.actor.member_id) : ""))),
        x.redacted ? h("p", { class: "muted msg-redacted" }, "This item was removed.")
          : h("p", { class: "ticker-text" }, x.text, link ? [" ", h("a", { href: link, rel: "noopener noreferrer", target: "_blank" }, "link")] : null),
        decided && !x.redacted ? h("p", { class: "muted" }, decided) : null,
        x.for_me ? h("p", { class: "ticker-why" }, "For you: " + x.why.map(whyWords).join(", ") + (x.muted ? " (muted: it woke no one here)" : "") + ".") : null);
    }
    // Items of one answer not shown yet, each once, also within the answer.
    const fresh = (items) => items.filter((x, i) => !shown.has(x.seq) && items.findIndex((y) => y.seq === x.seq) === i);
    const mark = (x) => { shown.add(x.seq); if (x.seq > top) top = x.seq; };
    const fillEmpty = () => {
      const blank = list.querySelector("li.empty");
      if (list.querySelector("li.ticker-item")) { if (blank) list.removeChild(blank); return; }
      if (!blank) append(list, h("li", { class: "empty muted" }, forMe ? "Nothing for you yet." : "Nothing in the ticker yet."));
    };
    function drawMore() {
      clear(more);
      if (cursor) append(more, h("button", { type: "button", class: "small", disabled: busy ? true : null, onclick: () => load(false) }, "Older"));
    }

    // A page, newest first: the first one of a filter set (reset), or the
    // next older one by the hub's cursor. given: a page already read.
    async function load(reset, given) {
      if (!reset && busy) return;
      const mine = reset ? ++gen : gen;
      if (reset) { clear(list); clear(more); shown.clear(); top = 0; cursor = null; resetting = true; loaded = false; }
      busy = true;
      drawMore();
      let page = given;
      try {
        if (!page) page = await M.api.get(query(cursor ? "cursor=" + encodeURIComponent(cursor) : null));
      } catch (err) {
        if (mine !== gen) return;
        busy = false;
        resetting = false;
        drawMore();
        status.fail("Could not read the ticker: ", err);
        return;
      }
      if (mine !== gen) return;
      busy = false;
      fresh(page.items).forEach((x) => { mark(x); append(list, item(x)); });
      cursor = page.next_cursor;
      fillEmpty();
      drawMore();
      if (reset) {
        resetting = false;
        loaded = true;
        if (liveAgain) live();
      }
    }

    // New items with the feed: read from the newest one shown, oldest first,
    // page by page with after= (§17.9), in this view's filters.
    // A signal while a read runs (or while a first page is on its way) is
    // kept: the read runs once more afterwards, so nothing waits for the
    // next event.
    let liveBusy = false;
    async function live() {
      if (liveBusy || resetting) { liveAgain = true; return; }
      if (!loaded) { load(true); return; }
      liveBusy = true;
      liveAgain = false;
      const mine = gen;
      let added = 0;
      try {
        for (let n = 0; n < LIVE_PAGES; n++) {
          const page = await M.api.get(query("after=" + top));
          if (mine !== gen) return;
          fresh(page.items).forEach((x) => { mark(x); list.insertBefore(item(x), list.firstChild); added += 1; });
          if (page.items.length < PAGE) break;
        }
      } catch (err) {
        if (mine === gen) status.fail("Could not read the new items: ", err);
        return;
      } finally {
        liveBusy = false;
        if (liveAgain && !resetting) live();
      }
      // Nothing new: a failure said earlier is over.
      if (!added) { status.done(); return; }
      fillEmpty();
      status.done();
      append(status.el, h("span", null, added === 1 ? "1 new item." : added + " new items."));
    }

    // The first read; a 404 is the hub's lack of a ticker only when its machine form says so.
    let first;
    try {
      first = await M.api.get(query());
    } catch (err) {
      if (err.status !== 404) throw err;
      if (!(await hubHasTicker())) { none(); return; }
      throw err;
    }

    const tab = (mine, label) => h("button", { type: "button", class: "small", "aria-pressed": String(forMe === mine),
      onclick: (e) => { forMe = mine; Array.from(tabs.querySelectorAll("button")).forEach((b) => b.setAttribute("aria-pressed", String(b === e.target))); load(true); } }, label);
    const tabs = h("div", { class: "ticker-tabs", role: "group", "aria-label": "Which items" }, tab(true, "For me"), tab(false, "Everything"));
    const typePick = h("select", { id: "ticker-type", onchange: (e) => { type = e.target.value; load(true); } },
      h("option", { value: "" }, "every type"), TYPES.map(([v, l]) => h("option", { value: v }, l)));
    const areaField = h("input", { id: "ticker-area", placeholder: "e.g. web/", autocomplete: "off" });
    const filter = h("form", { class: "board-filter", role: "search", onsubmit: (e) => { e.preventDefault(); area = areaField.value.trim(); load(true); } },
      h("label", { for: "ticker-type" }, "Type"), typePick, h("label", { for: "ticker-area" }, "Area"), areaField,
      h("button", { type: "submit", class: "small" }, "Filter"));

    ctx.onEvents((events) => { if (events.some((e) => e.kind === "ticker" && !shown.has(e.seq))) live(); });

    append(root, toolbar,
      h("p", { class: "muted" }, "What changed in the project: merges, decisions, deploys, releases and notes. Texts are as the hub or the poster wrote them."),
      tabs, filter, status.el, list, more,
      await subscription(ctx),
      ctx.canAdmin ? postForm(ctx, () => load(true)) : null);
    await load(true, first);
  };

  // §17.8: the viewer's own follow and mute, changed by what is added or removed.
  async function subscription(ctx) {
    const box = h("section", { class: "ticker-sub", "aria-labelledby": "ticker-sub-title" }, h("h3", { id: "ticker-sub-title" }, "Follow and mute"));
    const status = M.statusLine();
    const body = h("div");
    let sub;
    try {
      sub = await M.api.get(ctx.base + "/ticker/subscription");
    } catch (err) {
      append(box, h("p", { class: "send-status failed" }, "Could not read your subscription: " + err.message));
      return box;
    }
    async function change(patch, words) {
      status.busy("Saving…");
      try {
        sub = await M.api.patch(ctx.base + "/ticker/subscription", patch);
      } catch (err) {
        status.fail("Not saved: ", said(err, "change"));
        return false;
      }
      draw();
      status.done();
      append(status.el, h("span", { class: "ok" }, words));
      return true;
    }
    const typeWord = (v) => (TYPES.find(([k]) => k === v) || [v, v])[1];
    function draw() {
      const chips = (list, kind) => sub[list][kind].map((v) => h("li", null, kind === "types" ? typeWord(v) : v, " ",
        h("button", { type: "button", class: "small", "aria-label": "Stop " + (list === "follow" ? "following " : "muting ") + v,
          onclick: () => change({ remove: { [list]: { [kind]: [v] } } }, (list === "follow" ? "No longer following " : "No longer muting ") + v + ".") }, "Remove")));
      const part = (list, title, hint) => h("div", { class: "ticker-sub-part" }, h("h4", null, title), h("p", { class: "hint" }, hint),
        sub[list].areas.length || sub[list].types.length
          ? h("ul", { class: "ticker-chips" }, chips(list, "areas"), chips(list, "types"))
          : h("p", { class: "muted" }, "None."));
      append(clear(body),
        part("follow", "You follow", "Items of these areas or types are for you, and wake you."),
        part("mute", "You mute", "Items of these never wake you; one you also follow is still listed for you, marked muted."));
    }
    const list = h("select", { id: "ticker-sub-list" }, h("option", { value: "follow" }, "Follow"), h("option", { value: "mute" }, "Mute"));
    const kind = h("select", { id: "ticker-sub-kind" }, h("option", { value: "areas" }, "an area"), h("option", { value: "types" }, "a type"));
    list.value = "follow";
    kind.value = "areas";
    const value = h("input", { id: "ticker-sub-value", placeholder: "web/ or release", autocomplete: "off", required: true });
    const form = h("form", { class: "inline-form", onsubmit: async (e) => {
      e.preventDefault();
      const v = value.value.trim();
      if (!v) return;
      // Kept until the hub took it, so a refusal loses nothing.
      if (await change({ add: { [list.value]: { [kind.value]: [v] } } }, (list.value === "follow" ? "Following " : "Muting ") + v + ".")) value.value = "";
    } }, h("label", { for: "ticker-sub-list", class: "visually-hidden" }, "Follow or mute"), list,
    h("label", { for: "ticker-sub-kind", class: "visually-hidden" }, "Area or type"), kind,
    h("label", { for: "ticker-sub-value", class: "visually-hidden" }, "The area or type"), value,
    h("button", { type: "submit", class: "small" }, "Add"));
    draw();
    append(box, body, form, h("p", { class: "hint" }, "Types: merge, contract, decision, deploy, release, note. Changes apply to items written from now on."), status.el);
    return box;
  }

  // §17.6: a note, a deploy or a release, by an owner or admin.
  function postForm(ctx, onPosted) {
    const status = M.statusLine();
    const type = h("select", { id: "ticker-post-type" }, h("option", { value: "note" }, "Note"), h("option", { value: "deploy" }, "Deploy"), h("option", { value: "release" }, "Release"));
    // 280 code points as the hub counts them, checked before sending.
    const text = h("textarea", { id: "ticker-post-text", rows: "2", required: true });
    const url = h("input", { id: "ticker-post-url", type: "url", placeholder: "https://…" });
    const to = h("select", { id: "ticker-post-to" }, h("option", { value: "computed" }, "whom it concerns"), h("option", { value: "all" }, "everyone (wakes all)"), h("option", { value: "list" }, "these members, roles, areas"));
    const tokens = h("input", { id: "ticker-post-tokens", placeholder: "member:agt-b role:admin area:web/" });
    const areas = h("input", { id: "ticker-post-areas", placeholder: "hub/ web/" });
    const release = h("input", { id: "ticker-post-release", placeholder: "tsk-0050" });
    const env = h("input", { id: "ticker-post-env", placeholder: "staging" });
    const ver = h("input", { id: "ticker-post-version", placeholder: "0.3.0 or a sha" });
    const log = h("input", { id: "ticker-post-log", type: "url", placeholder: "https://…" });
    const field = (id, label, input, cls) => h("div", { class: "field " + (cls || "") }, h("label", { for: id }, label), input);
    const forNote = field("ticker-post-areas", "Areas (for whom it concerns)", areas, "only-note");
    const forRelease = field("ticker-post-release", "Release card (done)", release, "only-release");
    const forDeploy = [field("ticker-post-env", "Environment", env, "only-deploy"), field("ticker-post-version", "Version or sha", ver, "only-deploy"), field("ticker-post-log", "Log URL", log, "only-deploy")];
    const forList = field("ticker-post-tokens", "Members, roles, areas", tokens, "only-list");
    const show = () => {
      forNote.hidden = type.value !== "note";
      forRelease.hidden = type.value !== "release";
      forDeploy.forEach((f) => { f.hidden = type.value !== "deploy"; });
      forList.hidden = to.value !== "list";
    };
    type.value = "note";
    to.value = "computed";
    type.addEventListener("change", show);
    to.addEventListener("change", show);
    const send = h("button", { type: "submit" }, "Post");
    const words = (s) => s.split(/\s+/).filter(Boolean);
    const form = h("form", { class: "project-form ticker-post", onsubmit: async (e) => {
      e.preventDefault();
      const body = { type: type.value, text: text.value.trim() };
      if (url.value.trim()) body.url = url.value.trim();
      if (to.value === "all") body.to = "all";
      if (to.value === "list") body.to = words(tokens.value);
      if (type.value === "note" && words(areas.value).length) body.areas = words(areas.value);
      if (type.value === "release") body.release_task_id = release.value.trim();
      if (type.value === "deploy") {
        // A commit sha is 7 to 40 hex digits with a letter among them; anything else is a version.
        const v = ver.value.trim();
        const sha = /^[0-9a-f]{7,40}$/i.test(v) && /[a-f]/i.test(v);
        body.deploy = Object.assign({ environment: env.value.trim() }, sha ? { sha: v.toLowerCase() } : { version: v }, log.value.trim() ? { log_url: log.value.trim() } : {});
      }
      if (Array.from(body.text).length > 280) { status.fail("Not posted: ", { message: "the text is longer than 280 characters" }); return; }
      if (to.value === "all" && !window.confirm("Post to everyone? It wakes every member who has not muted it.")) return;
      send.disabled = true;
      status.busy("Posting…");
      try {
        await M.api.post(ctx.base + "/ticker", body);
      } catch (err) {
        status.fail("Not posted: ", said(err, "post"));
        return;
      } finally {
        send.disabled = false;
      }
      text.value = "";
      status.done();
      append(status.el, h("span", { class: "ok" }, "Posted."));
      onPosted();
    } },
    field("ticker-post-type", "Type", type), field("ticker-post-text", "Text (at most 280 characters, plain)", text), field("ticker-post-url", "Link (https, optional)", url),
    field("ticker-post-to", "To", to), forList, forNote, forRelease, forDeploy, send, status.el);
    show();
    return h("section", { class: "ticker-post-box", "aria-labelledby": "ticker-post-title" },
      h("h3", { id: "ticker-post-title" }, "Post to the ticker"),
      h("p", { class: "hint" }, "For what the hub cannot see: a deploy without a webhook, a release, a note the team must know. Merges and decisions are written by the hub."),
      form);
  }

  M.ticker = { whyWords, said };
})(window.Maity);
