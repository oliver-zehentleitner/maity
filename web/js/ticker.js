// (12) Ticker (/<owner>/<slug>/ticker, docs/api.md §17): the project's change
// feed — merges, decisions, deploys, releases and notes — newest first,
// "For me" and "Everything" as two tabs, filtered by type and area, paged
// with the hub's cursor. An item is its text (plain, never Markdown), its
// link when it is https, and for the viewer why it is theirs, in words.
// The viewer's own follow and mute are edited here (§17.8); an owner or
// admin posts a note, a deploy or a release (§17.6). New items come with
// the project's feed.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl, formatTime } = M.dom;

  // Getters: the label is read from the catalog when it is shown.
  const TYPE_LABELS = {
    get merge() { return M.t("ticker.types.merge"); },
    get contract() { return M.t("ticker.types.contract"); },
    get decision() { return M.t("ticker.types.decision"); },
    get deploy() { return M.t("ticker.types.deploy"); },
    get release() { return M.t("ticker.types.release"); },
    get note() { return M.t("ticker.types.note"); },
  };
  const TYPES = Object.keys(TYPE_LABELS);
  // A rename (§6.25, "<old> is now <new>") is the hub's to write; no filter of its own (§17).
  // No "contract": a contract change is a merge with x.contract, its badge
  // ticker.badge.contract, chosen in item().
  const TYPE_WORD = {
    get merge() { return M.t("ticker.badge.merge"); },
    get decision() { return M.t("ticker.badge.decision"); },
    get deploy() { return M.t("ticker.badge.deploy"); },
    get release() { return M.t("ticker.badge.release"); },
    get rename() { return M.t("ticker.badge.rename"); },
    get note() { return M.t("ticker.badge.note"); },
  };
  // "You follow <type>", one sentence per type.
  const FOLLOW_TYPE = {
    get merge() { return M.t("ticker.why.follow_type.merge"); },
    get contract() { return M.t("ticker.why.follow_type.contract"); },
    get decision() { return M.t("ticker.why.follow_type.decision"); },
    get deploy() { return M.t("ticker.why.follow_type.deploy"); },
    get release() { return M.t("ticker.why.follow_type.release"); },
    get note() { return M.t("ticker.why.follow_type.note"); },
  };
  const PAGE = 50;
  // How many pages of new items one live round reads at most.
  const LIVE_PAGES = 20;

  // "You are a <role>" and "you are an <trust>": one sentence each, the article
  // being the language's; a value the hub adds later reads as a plain phrase.
  const ROLE_WHY = {
    get coder() { return M.t("ticker.why.role.coder"); },
    get reviewer() { return M.t("ticker.why.role.reviewer"); },
    get tester() { return M.t("ticker.why.role.tester"); },
    get designer() { return M.t("ticker.why.role.designer"); },
    get ops() { return M.t("ticker.why.role.ops"); },
    get writer() { return M.t("ticker.why.role.writer"); },
    get proxy() { return M.t("ticker.why.role.proxy"); },
    get manager() { return M.t("ticker.why.role.manager"); },
  };
  const TRUST_WHY = {
    get owner() { return M.t("ticker.why.trust.owner"); },
    get admin() { return M.t("ticker.why.trust.admin"); },
    get member() { return M.t("ticker.why.trust.member"); },
    get guest() { return M.t("ticker.why.trust.guest"); },
  };
  // A reason token (§17.3, §17.6, §17.8) as the viewer reads it.
  function whyWords(token) {
    const [kind, ...rest] = token.split(":");
    const arg = rest.join(":");
    switch (kind) {
      case "area_owner": return arg === "/" || arg === "*" ? M.t("ticker.why.area_owner_all") : M.t("ticker.why.area_owner", { area: arg });
      case "card_holder": return M.t("ticker.why.card_holder", { card: arg });
      case "card_assignee": return M.t("ticker.why.card_assignee", { card: arg });
      case "contract_implementer": return arg === "*" ? M.t("ticker.why.contract_implementer_all") : M.t("ticker.why.contract_implementer", { section: arg });
      case "role": return Object.hasOwn(ROLE_WHY, arg) ? ROLE_WHY[arg] : M.t("ticker.why.role", { role: arg });
      case "trust": return Object.hasOwn(TRUST_WHY, arg) ? TRUST_WHY[arg] : M.t("ticker.why.trust", { trust: arg });
      case "decision_asker": return M.t("ticker.why.decision_asker");
      case "decision_on_behalf_of": return M.t("ticker.why.decision_on_behalf_of");
      case "contract_watcher": return M.t("ticker.why.contract_watcher");
      case "all_members": return M.t("ticker.why.all_members");
      case "posted_to_all": return M.t("ticker.why.posted_to_all");
      case "addressed": return M.t("ticker.why.addressed");
      case "follow": return rest[0] === "type"
        ? (Object.hasOwn(FOLLOW_TYPE, rest[1]) ? FOLLOW_TYPE[rest[1]] : M.t("ticker.why.follow", { what: rest.slice(1).join(":") }))
        : M.t("ticker.why.follow", { what: arg });
      default: return token;
    }
  }

  // The hub's refusals, in words: which field, and why (§17.6, §17.8).
  const FIELD_NAMES = {
    get type() { return M.t("ticker.field.type"); },
    get text() { return M.t("ticker.field.text"); },
    get url() { return M.t("ticker.field.url"); },
    get to() { return M.t("ticker.field.to"); },
    get areas() { return M.t("ticker.field.areas"); },
    get release_task_id() { return M.t("ticker.field.release_task_id"); },
    get deploy() { return M.t("ticker.field.deploy"); },
    get "deploy.environment"() { return M.t("ticker.field.deploy_environment"); },
    get "deploy.log_url"() { return M.t("ticker.field.deploy_log_url"); },
    get "follow.areas"() { return M.t("ticker.field.follow_areas"); },
    get "follow.types"() { return M.t("ticker.field.follow_types"); },
    get "mute.areas"() { return M.t("ticker.field.mute_areas"); },
    get "mute.types"() { return M.t("ticker.field.mute_types"); },
  };
  const WHY_WORDS = {
    get not_for_type() { return M.t("ticker.refusal.not_for_type"); },
    get required() { return M.t("ticker.refusal.required"); },
    get not_done() { return M.t("ticker.refusal.not_done"); },
    get too_many() { return M.t("ticker.refusal.too_many"); },
    get invalid() { return M.t("ticker.refusal.invalid"); },
  };
  function said(err, what) {
    if (err.code === "ticker_duplicate") {
      // The item's number as the hub writes it, never grouped.
      return { message: err.details && err.details.seq ? M.t("ticker.said.duplicate_item", { seq: String(err.details.seq) }) : M.t("ticker.said.duplicate") };
    }
    if (err.code === "rate_limited") return { message: what === "post" ? M.t("ticker.said.rate_limited_post") : M.t("ticker.said.rate_limited_change") };
    if (err.code === "forbidden") return { message: what === "post" ? M.t("ticker.said.forbidden_post") : M.t("ticker.said.forbidden_change") };
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) {
      return { message: Object.entries(fields).map(([f, why]) => M.t("ticker.said.field", {
        field: Object.hasOwn(FIELD_NAMES, f) ? FIELD_NAMES[f] : M.t("ticker.field.other", { name: f }),
        why: Object.hasOwn(WHY_WORDS, why) ? WHY_WORDS[why] : M.t("ticker.refusal.other", { why }),
      })).join("; ") };
    }
    return err;
  }

  M.views.ticker = async function (ctx, root) {
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const toolbar = h("div", { class: "toolbar" }, h("h2", null, M.t("ticker.title")));
    let forMe = true;
    let type = "";
    let area = "";
    let cursor = null;
    // Each read belongs to one filter set; an answer of an older one is dropped.
    let gen = 0;
    let busy = false;
    // A first page of a filter set still on its way: no live read until it is
    // in, since `top` is not known yet; a signal meanwhile is kept for after.
    // True from the start: a signal before the first page is in waits for it.
    let resetting = true;
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
        ? (x.detail.reply_label ? M.t("ticker.decided", { reply: x.detail.reply_label, title: x.detail.request_title })
          : M.t("ticker.decided.in_writing", { title: x.detail.request_title })) : null;
      return h("li", { class: "ticker-item type-" + x.type + (x.for_me ? " for-me" : ""), "data-seq": String(x.seq) },
        h("div", { class: "ticker-head" },
          h("span", { class: "badge" }, x.type === "merge" && x.contract ? M.t("ticker.badge.contract") : Object.hasOwn(TYPE_WORD, x.type) ? TYPE_WORD[x.type] : x.type),
          " ", h("span", { class: "muted" }, formatTime(x.at), x.actor && x.actor.member_id ? [" · ", M.dom.memberRef(ctx, x.actor.member_id, { instance: x.actor })] : null)),
        x.redacted ? h("p", { class: "muted msg-redacted" }, M.t("ticker.removed"))
          // An item whose own link is a pull request or an issue links it
          // once: its numbers stay text.
          : h("p", { class: "ticker-text" }, M.ids.link(x.text, link && /\/(pull|issues)\/\d+/.test(link)
            ? Object.assign(M.ids.where(ctx), { repository: null }) : M.ids.where(ctx)), link ? [" ", h("a", { href: link, rel: "noopener noreferrer", target: "_blank" }, M.t("ticker.link"))] : null),
        decided && !x.redacted ? h("p", { class: "muted" }, M.ids.link(decided, M.ids.where(ctx))) : null,
        x.for_me ? h("p", { class: "ticker-why" }, x.muted ? M.t("ticker.for_you.muted", { why: reasons(x.why) }) : M.t("ticker.for_you", { why: reasons(x.why) })) : null);
    }
    // The reasons as a list, in the catalog's language: "a, b, c" in English.
    const reasons = (why) => M.fmt.list(why.map(whyWords));
    // Items of one answer not shown yet, each once, also within the answer.
    const fresh = (items) => items.filter((x, i) => !shown.has(x.seq) && items.findIndex((y) => y.seq === x.seq) === i);
    const mark = (x) => { shown.add(x.seq); if (x.seq > top) top = x.seq; };
    const fillEmpty = () => {
      const blank = list.querySelector("li.empty");
      if (list.querySelector("li.ticker-item")) { if (blank) list.removeChild(blank); return; }
      if (!blank) append(list, h("li", { class: "empty muted" }, forMe ? M.t("ticker.empty.for_me") : M.t("ticker.empty.all")));
    };
    function drawMore() {
      clear(more);
      if (cursor) append(more, h("button", { type: "button", class: "small", disabled: busy ? true : null, onclick: () => load(false) }, M.t("ticker.older")));
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
        status.fail(M.t("ticker.status.read_failed"), err);
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
        // The page is in: a failure said before is over.
        status.done();
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
        if (mine === gen) status.fail(M.t("ticker.status.new_failed"), err);
        return;
      } finally {
        liveBusy = false;
        if (liveAgain && !resetting) live();
      }
      // Nothing new: a failure said earlier is over.
      if (!added) { status.done(); return; }
      fillEmpty();
      status.done();
      append(status.el, h("span", null, M.t("ticker.new_items", { count: added })));
    }

    const first = await M.api.get(query());

    const tab = (mine, label) => h("button", { type: "button", class: "small", "aria-pressed": String(forMe === mine),
      onclick: (e) => { forMe = mine; Array.from(tabs.querySelectorAll("button")).forEach((b) => b.setAttribute("aria-pressed", String(b === e.target))); load(true); } }, label);
    const tabs = h("div", { class: "ticker-tabs", role: "group", "aria-label": M.t("ticker.tabs.label") }, tab(true, M.t("ticker.tabs.for_me")), tab(false, M.t("ticker.tabs.everything")));
    const typePick = h("select", { id: "ticker-type", onchange: (e) => { type = e.target.value; load(true); } },
      h("option", { value: "" }, M.t("ticker.filter.every_type")), TYPES.map((v) => h("option", { value: v }, TYPE_LABELS[v])));
    const areaField = h("input", { id: "ticker-area", placeholder: M.t("ticker.filter.area_placeholder"), autocomplete: "off" });
    const filter = h("form", { class: "board-filter", role: "search", onsubmit: (e) => { e.preventDefault(); area = areaField.value.trim(); load(true); } },
      h("label", { for: "ticker-type" }, M.t("ticker.filter.type")), typePick, h("label", { for: "ticker-area" }, M.t("ticker.filter.area")), areaField,
      h("button", { type: "submit", class: "small" }, M.t("ticker.filter.submit")));

    ctx.onEvents((events) => { if (events.some((e) => e.kind === "ticker" && !shown.has(e.seq))) live(); });

    append(root, toolbar,
      h("p", { class: "muted" }, M.t("ticker.intro")),
      tabs, filter, status.el, list, more,
      await subscription(ctx),
      ctx.canAdmin ? postForm(ctx, () => load(true)) : null);
    await load(true, first);
  };

  // §17.8: the viewer's own follow and mute, changed by what is added or removed.
  async function subscription(ctx) {
    const box = h("section", { class: "ticker-sub", "aria-labelledby": "ticker-sub-title" }, h("h3", { id: "ticker-sub-title" }, M.t("ticker.sub.title")));
    const status = M.statusLine();
    const body = h("div");
    let sub;
    try {
      sub = await M.api.get(ctx.base + "/ticker/subscription");
    } catch (err) {
      append(box, h("p", { class: "send-status failed" }, M.t("ticker.sub.read_failed", { reason: err.message })));
      return box;
    }
    async function change(patch, words) {
      status.busy(M.t("ticker.sub.saving"));
      try {
        sub = await M.api.patch(ctx.base + "/ticker/subscription", patch);
      } catch (err) {
        status.fail(M.t("ticker.sub.not_saved"), said(err, "change"));
        return false;
      }
      draw();
      status.done();
      append(status.el, h("span", { class: "ok" }, words));
      return true;
    }
    const typeWord = (v) => (Object.hasOwn(TYPE_LABELS, v) ? TYPE_LABELS[v] : v);
    function draw() {
      const following = (list) => list === "follow";
      const chips = (list, kind) => sub[list][kind].map((v) => h("li", null, kind === "types" ? typeWord(v) : v, " ",
        h("button", { type: "button", class: "small",
          "aria-label": following(list) ? M.t("ticker.sub.stop_following", { value: v }) : M.t("ticker.sub.stop_muting", { value: v }),
          onclick: () => change({ remove: { [list]: { [kind]: [v] } } },
            following(list) ? M.t("ticker.sub.no_longer_following", { value: v }) : M.t("ticker.sub.no_longer_muting", { value: v })) }, M.t("ticker.sub.remove"))));
      const part = (list, title, hint) => h("div", { class: "ticker-sub-part" }, h("h4", null, title), h("p", { class: "hint" }, hint),
        sub[list].areas.length || sub[list].types.length
          ? h("ul", { class: "ticker-chips" }, chips(list, "areas"), chips(list, "types"))
          : h("p", { class: "muted" }, M.t("ticker.sub.none")));
      append(clear(body),
        part("follow", M.t("ticker.sub.follow.title"), M.t("ticker.sub.follow.hint")),
        part("mute", M.t("ticker.sub.mute.title"), M.t("ticker.sub.mute.hint")));
    }
    const list = h("select", { id: "ticker-sub-list" }, h("option", { value: "follow" }, M.t("ticker.sub.follow")), h("option", { value: "mute" }, M.t("ticker.sub.mute")));
    const kind = h("select", { id: "ticker-sub-kind" }, h("option", { value: "areas" }, M.t("ticker.sub.kind.area")), h("option", { value: "types" }, M.t("ticker.sub.kind.type")));
    list.value = "follow";
    kind.value = "areas";
    const value = h("input", { id: "ticker-sub-value", placeholder: M.t("ticker.sub.value_placeholder"), autocomplete: "off", required: true });
    const form = h("form", { class: "inline-form", onsubmit: async (e) => {
      e.preventDefault();
      const v = value.value.trim();
      if (!v) return;
      // Kept until the hub took it, so a refusal loses nothing.
      if (await change({ add: { [list.value]: { [kind.value]: [v] } } }, list.value === "follow" ? M.t("ticker.sub.following", { value: v }) : M.t("ticker.sub.muting", { value: v }))) value.value = "";
    } }, h("label", { for: "ticker-sub-list", class: "visually-hidden" }, M.t("ticker.sub.list_label")), list,
    h("label", { for: "ticker-sub-kind", class: "visually-hidden" }, M.t("ticker.sub.kind_label")), kind,
    h("label", { for: "ticker-sub-value", class: "visually-hidden" }, M.t("ticker.sub.value_label")), value,
    h("button", { type: "submit", class: "small" }, M.t("ticker.sub.add")));
    draw();
    append(box, body, form, h("p", { class: "hint" }, M.t("ticker.sub.hint", { types: TYPES.join(", ") })), status.el);
    return box;
  }

  // §17.6: a note, a deploy or a release, by an owner or admin.
  function postForm(ctx, onPosted) {
    const status = M.statusLine();
    const type = h("select", { id: "ticker-post-type" }, h("option", { value: "note" }, TYPE_WORD.note), h("option", { value: "deploy" }, TYPE_WORD.deploy), h("option", { value: "release" }, TYPE_WORD.release));
    // 280 code points as the hub counts them, checked before sending.
    const text = M.dom.sendOnCtrlEnter(h("textarea", { id: "ticker-post-text", rows: "2", required: true }));
    const url = h("input", { id: "ticker-post-url", type: "url", placeholder: "https://…" });
    const to = h("select", { id: "ticker-post-to" }, h("option", { value: "computed" }, M.t("ticker.post.to.computed")), h("option", { value: "all" }, M.t("ticker.post.to.all")), h("option", { value: "list" }, M.t("ticker.post.to.list")));
    const tokens = h("input", { id: "ticker-post-tokens", placeholder: "member:agt-b trust:admin area:web/" });
    const areas = h("input", { id: "ticker-post-areas", placeholder: "hub/ web/" });
    const release = h("input", { id: "ticker-post-release", placeholder: "tsk-0050" });
    const env = h("input", { id: "ticker-post-env", placeholder: "staging" });
    const ver = h("input", { id: "ticker-post-version", placeholder: M.t("ticker.post.version_placeholder") });
    const log = h("input", { id: "ticker-post-log", type: "url", placeholder: "https://…" });
    const field = (id, label, input, cls) => h("div", { class: "field " + (cls || "") }, h("label", { for: id }, label), input);
    const forNote = field("ticker-post-areas", M.t("ticker.post.areas"), areas, "only-note");
    const forRelease = field("ticker-post-release", M.t("ticker.post.release"), release, "only-release");
    const forDeploy = [field("ticker-post-env", M.t("ticker.post.environment"), env, "only-deploy"), field("ticker-post-version", M.t("ticker.post.version"), ver, "only-deploy"),
      field("ticker-post-log", M.t("ticker.post.log"), log, "only-deploy")];
    const forList = field("ticker-post-tokens", M.t("ticker.post.tokens"), tokens, "only-list");
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
    const send = h("button", { type: "submit" }, M.t("ticker.post.submit"));
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
      if (Array.from(body.text).length > 280) { status.fail(M.t("ticker.post.not_posted"), { message: M.t("ticker.post.too_long", { max: 280 }) }); return; }
      if (to.value === "all" && !window.confirm(M.t("ticker.post.confirm_all"))) return;
      send.disabled = true;
      status.busy(M.t("ticker.post.posting"));
      try {
        await M.api.post(ctx.base + "/ticker", body);
      } catch (err) {
        status.fail(M.t("ticker.post.not_posted"), said(err, "post"));
        return;
      } finally {
        send.disabled = false;
      }
      text.value = "";
      status.done();
      append(status.el, h("span", { class: "ok" }, M.t("ticker.post.posted")));
      onPosted();
    } },
    field("ticker-post-type", M.t("ticker.post.type"), type), field("ticker-post-text", M.t("ticker.post.text", { max: 280, keys: M.dom.SEND_KEYS }), text),
    field("ticker-post-url", M.t("ticker.post.url"), url), field("ticker-post-to", M.t("ticker.post.to"), to), forList, forNote, forRelease, forDeploy, send, status.el);
    show();
    return h("section", { class: "ticker-post-box", "aria-labelledby": "ticker-post-title" },
      h("h3", { id: "ticker-post-title" }, M.t("ticker.post.title")),
      h("p", { class: "hint" }, M.t("ticker.post.hint")),
      form);
  }

  M.ticker = { whyWords, said };
})(window.Maity);
