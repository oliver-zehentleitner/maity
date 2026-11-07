// The dashboard's words from a catalog, one per language (i18n/<lang>.json,
// loaded as js/i18n/<lang>.js, which tools/check.py builds from it, since
// file:// cannot fetch JSON). English is always loaded, as what a key without
// a translation reads in; the reader's language comes on top, as a script of
// its own (context/rendering.md). A translation fills a file, it touches no
// view; js/i18n/languages.js, built the same way, says which files there are.
//
// Which language (docs/api.md §6.2): the account's interface_language, which
// M.api gives M.i18n.follow with every GET /auth/session; without one, and
// before sign-in, the landing page's own choice, read from GET /site/chrome's
// `language` once per page (the hub chooses it from the raw ?lang=, the
// browser's Accept-Language, the landing page's languages and its
// default_language); a choice made on this page comes first, and without that
// read (fixture mode, the join host, an error, a late answer) ?lang=, the
// browser's, then en. Nothing is stored in the browser for it: the hub's own
// pages cannot read that (web/context/rendering.md).
//
// M.t(key, values): one key per sentence, never a sentence put together
// from pieces. `{name}` in the text takes values.name, a number formatted
// for the reader's locale. A text that depends on a number is an object of
// plural forms ({one, other, …}, Intl.PluralRules), chosen by values.count.
// M.tn(key, values): the same sentence as pieces, where a value may be a
// node (a link, a member) placed where the language puts it.
// M.fmt: dates and numbers through Intl, in the reader's locale.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const catalogs = window.MAITY_I18N || {};
  // The catalog's language, and the locale Intl formats in: undefined is
  // the browser's own, the reader's locale until the account sets one.
  const i18n = { language: "en", locale: undefined };
  // The languages with a catalog: a tag outside them is never loaded.
  const available = window.MAITY_I18N_LANGUAGES || ["en"];
  // Where an older version kept the visitor's choice: removed once, every other key left alone.
  const STORED = "maity.language";
  // js/i18n.js's own address: a route's path is deep, the bundles stay beside this file.
  const here = (window.document && window.document.currentScript && window.document.currentScript.src) || "js/i18n.js";

  // The catalog a browser's tag means: de-AT reads de, zh-CN zh-Hans, and
  // zh-TW nothing, since Traditional is another script and not a close second.
  function closestIn(tags, tag) {
    if (typeof tag !== "string" || !tag) return null;
    if (tags.includes(tag)) return tag;
    try {
      const l = new Intl.Locale(tag).maximize();
      return [l.language + "-" + l.script, l.language].find((c) => tags.includes(c)) || null;
    } catch { return null; }
  }
  const closest = (tag) => closestIn(available, tag);

  try { window.localStorage.removeItem(STORED); } catch { /* nothing kept, or no storage */ }
  // The visitor's choice while this page lives: a route without ?lang= keeps it, a new page
  // starts from its own address and the browser again, as the hub's pages do.
  let chosen = null;
  // A choice made on the page writes its tag into the address's ?lang=, so a reload, a copied
  // address and the hub's pages say the same. Nothing is drawn again: the page that asked
  // draws itself in the language (js/route.js, go with quiet).
  function carry(tag) {
    const route = M.route;
    if (!route) return;
    const at = route.current();
    if (at.query.get("lang") === tag) return;
    at.query.set("lang", tag);
    route.go(at.path + "?" + at.query.toString(), { quiet: true });
  }

  // The landing page's language for this visitor, from GET /site/chrome (docs/api.md §16.7.5),
  // once per page and per asked ?lang=: never in fixture mode, whose frame answers English
  // whatever is asked, and given `i18n.frameWait` ms, so a read that fails or answers late
  // leaves the rule below and never holds a view (the answer then counts for nothing).
  let picked = null;  // a choice made on this page (choose), while the address says no other
  const framed = {};  // the frame's language per address read
  let account = false;  // the session's interface_language decides
  const frameReads = {};
  // The address's ?lang= as written, for the hub to match exactly as the landing page does.
  // The last one this page saw, or a pick on it, stays its ?lang= across routes without one
  // (a link to /login from /register?lang=de), as `chosen` does for the rule below.
  let pageAsked = null;
  function askedRaw() {
    const raw = window.location ? new URLSearchParams(window.location.search).get("lang") : null;
    if (raw && raw.length <= 35) { pageAsked = raw; return raw; }
    return null;
  }
  const frameAddress = () => {
    const raw = askedRaw() || pageAsked;
    return "/site/chrome" + (raw ? "?lang=" + encodeURIComponent(raw) : "");
  };
  function readFrame() {
    const address = frameAddress();
    if (Object.hasOwn(frameReads, address)) return frameReads[address];
    if (!M.api || !window.location || window.location.protocol === "file:") return Promise.resolve(null);
    const stop = typeof AbortController === "function" ? new AbortController() : null;
    let late;
    const wait = new Promise((resolve) => {
      late = window.setTimeout(() => { if (stop) stop.abort(); resolve(null); }, i18n.frameWait);
    });
    const answer = M.api.get(address, stop ? { signal: stop.signal } : undefined)
      .then((model) => (model && typeof model.language === "string" ? closest(model.language) : null), () => null);
    frameReads[address] = Promise.race([answer, wait]).then((tag) => {
      window.clearTimeout(late);
      if (tag) framed[address] = tag;
      return tag;
    });
    return frameReads[address];
  }

  // Without an account's language: ?lang= (which then stays the choice for this page), the
  // choice made on this page, the browser's list, English.
  // What the person chose themselves, or null: only this may go on an account.
  function explicitChoice() {
    const asked = window.location ? closest(new URLSearchParams(window.location.search).get("lang")) : null;
    if (asked) { chosen = asked; return asked; }
    return closest(chosen);
  }
  // Without an account's language: a choice made on this page, the landing page's (the frame),
  // then the rule below.
  // A newer address with any other ?lang= value ends a pick: sv, xx, also de-AT after de (a
  // pick writes its own tag into the address, so the address the pick made never ends it).
  function releasePick() {
    const raw = askedRaw();
    if (raw && picked && raw !== picked) picked = null;
  }
  // What the person chose, for the account (js/register.js): a pick on the page, else ?lang= or
  // the choice kept for the page, unless the landing page's frame overrode that ?lang= (a reload
  // with ?lang=ko and no ko page): the page shows the frame's language then, and an address the
  // landing page ignores is no choice to store.
  function personChoice() {
    releasePick();
    const pick = closest(picked);
    if (pick) return pick;
    const asked = explicitChoice();
    const shown = framed[frameAddress()];
    return asked && shown && shown !== asked ? null : asked;
  }
  function visitorChoice() {
    releasePick();
    const pick = closest(picked);
    if (pick) return pick;
    return closest(framed[frameAddress()]) || browserChoice();
  }
  const browserList = () => (window.navigator && window.navigator.languages) || [];
  function browserChoice() {
    const chosen = explicitChoice();
    if (chosen) return chosen;
    for (const tag of browserList()) {
      const found = closest(tag);
      if (found) return found;
    }
    return "en";
  }

  // One script per language, however many ask while it loads; a failed one may be tried again.
  const loading = {};
  function load(tag) {
    if (catalogs[tag]) return Promise.resolve(true);
    if (!Object.hasOwn(loading, tag)) {
      loading[tag] = new Promise((resolve) => {
        const script = window.document.createElement("script");
        script.src = new URL("i18n/" + tag + ".js", new URL(here, window.document.baseURI)).href;
        script.onload = () => { delete loading[tag]; resolve(!!catalogs[tag]); };
        script.onerror = () => { delete loading[tag]; resolve(false); };
        window.document.head.appendChild(script);
      });
    }
    return loading[tag];
  }

  // Never rejects: a catalog that cannot be had leaves the page in the language it has.
  let asked = 0;
  async function use(tag) {
    const mine = ++asked;
    const loaded = await load(tag);
    if (!loaded || mine !== asked) return;  // the last one asked for wins
    i18n.language = tag;
    if (window.document && window.document.documentElement) window.document.documentElement.lang = tag;
    // The product line is outside every view: it follows the language itself, also when the
    // session's interface_language arrives after the view began (docs/api.md §16.13).
    if (M.productLine) M.productLine.draw();
  }

  // Own keys only: a key like "constructor" is no text of the catalog.
  const text = (key) => {
    const own = catalogs[i18n.language] || {};
    const en = catalogs.en || {};
    return Object.hasOwn(own, key) ? own[key] : Object.hasOwn(en, key) ? en[key] : undefined;
  };

  function fill(template, values) {
    return template.replace(/\{([a-z][a-z0-9_]*)\}/g, (whole, name) => {
      if (!values || !Object.hasOwn(values, name)) return whole;
      const v = values[name];
      return typeof v === "number" ? number(v) : String(v);
    });
  }

  // The text of a key for these values: its plural form chosen by count.
  function template(key, values) {
    const entry = text(key);
    if (entry === undefined || typeof entry === "string") return entry;
    const count = values && typeof values.count === "number" ? values.count : 0;
    // The forms the catalog's language has, whatever locale formats the numbers.
    const form = new Intl.PluralRules(i18n.language).select(count);
    return entry[form] !== undefined ? entry[form] : entry.other;
  }

  function t(key, values) {
    const said = template(key, values);
    // A key the catalog does not hold reads as itself: visible, never empty.
    return said === undefined ? key : fill(said, values);
  }

  // The text only where this language's own catalog has it, else undefined: for
  // js/errors.js, where the hub's English says more than the catalog's.
  function tOwn(key, values) {
    const own = catalogs[i18n.language];
    if (i18n.language === "en" || !own || !Object.hasOwn(own, key)) return undefined;
    return t(key, values);
  }

  // The same sentence as pieces for M.dom.h: a placeholder whose value is a
  // node (a link, a member) is that node, in the sentence where the
  // language puts it; strings and numbers fill in as with M.t.
  function tn(key, values) {
    const said = template(key, values);
    if (said === undefined) return [key];
    const out = [];
    let last = 0;
    said.replace(/\{([a-z][a-z0-9_]*)\}/g, (whole, name, at) => {
      if (at > last) out.push(said.slice(last, at));
      const v = values && Object.hasOwn(values, name) ? values[name] : undefined;
      out.push(v === undefined ? whole : typeof v === "number" ? number(v) : v);
      last = at + whole.length;
      return whole;
    });
    if (last < said.length) out.push(said.slice(last));
    return out;
  }

  function number(n, options) {
    return new Intl.NumberFormat(i18n.locale, options).format(n);
  }

  // A date and time, a date, or a time; `value` an ISO string or a Date.
  // An unreadable value is returned as given.
  function when(value, options) {
    const d = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return new Intl.DateTimeFormat(i18n.locale, options).format(d);
  }

  M.t = t;
  M.tOwn = tOwn;
  M.tn = tn;
  M.fmt = {
    number,
    // A list of names or facts as the catalog's language joins them, without
    // "and" or "or" ("a, b, c" in English): one place for every view.
    list: (items) => new Intl.ListFormat(i18n.language, { type: "unit" }).format(items),
    dateTime: (value) => when(value, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    date: (value) => when(value, { year: "numeric", month: "short", day: "numeric" }),
    time: (value) => when(value, { hour: "2-digit", minute: "2-digit" }),
    when,
  };
  i18n.available = available;
  i18n.explicit = personChoice;
  // The first of the browser's languages among these tags, or null.
  i18n.fromBrowser = (tags) => {
    for (const tag of browserList()) {
      const found = closestIn(tags, tag);
      if (found) return found;
    }
    return null;
  };
  // The first language, before the first view is drawn.
  i18n.ready = use(browserChoice());
  // How long the frame's language may take before the rule without it decides.
  i18n.frameWait = 1500;
  // The account's interface language, or null. Signed in without one (`signedIn`, the session
  // read answered 200): the browser's rule, as docs/api.md §6.2 says, and no frame read. Signed
  // out (the 401): the visitor's language, the frame read first.
  i18n.follow = (tag, signedIn) => {
    const own = closest(tag);
    account = !!own || !!signedIn;
    if (own) return use(own);
    if (signedIn) return use(browserChoice());
    return readFrame().then(() => (account ? undefined : use(visitorChoice())));
  };
  // A choice made on a page before sign-in.
  i18n.choose = (tag) => {
    chosen = closest(tag) || chosen;
    picked = closest(tag) || picked;
    if (closest(tag)) pageAsked = tag;
    carry(tag);
    return use(tag);
  };
  // The frame's own read (js/site-chrome.js) at the same address: its `language` counts as the
  // read above does. True when the page's language changed, so the page draws itself again once;
  // false when it agrees, under an account's language, or after a choice made on the page.
  i18n.frameAddress = frameAddress;
  i18n.frame = (tag) => {
    const found = closest(tag);
    if (!found) return Promise.resolve(false);
    framed[frameAddress()] = found;
    const next = visitorChoice();
    if (account || next === i18n.language) return Promise.resolve(false);
    return use(next).then(() => i18n.language === next);
  };
  // A key's English text, for a translation that may not be used (the product line's
  // sentence with a placeholder missing or twice, docs/api.md §16.13).
  i18n.english = (key) => {
    const en = catalogs.en || {};
    return Object.hasOwn(en, key) ? en[key] : undefined;
  };
  M.i18n = i18n;
})(window.Maity);
