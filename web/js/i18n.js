// The dashboard's words from a catalog, one per language (i18n/<lang>.json,
// loaded as js/i18n/<lang>.js, which tools/check.py builds from it, since
// file:// cannot fetch JSON). English is always loaded, as what a key without
// a translation reads in; the reader's language comes on top, as a script of
// its own (context/rendering.md). A translation fills a file, it touches no
// view; js/i18n/languages.js, built the same way, says which files there are.
//
// Which language (docs/api.md §6.2): the account's interface_language, which
// M.api gives M.i18n.follow with every GET /auth/session; without one, and
// before sign-in, the explicit choice or ?lang=, then the browser's, then en.
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
  const STORED = "maity.language";
  // js/i18n.js's own address: a route's path is deep, the bundles stay beside this file.
  const here = (window.document && window.document.currentScript && window.document.currentScript.src) || "js/i18n.js";

  // The catalog a browser's tag means: de-AT reads de, zh-CN zh-Hans, and
  // zh-TW nothing, since Traditional is another script and not a close second.
  function closest(tag) {
    if (typeof tag !== "string" || !tag) return null;
    if (available.includes(tag)) return tag;
    try {
      const l = new Intl.Locale(tag).maximize();
      return [l.language + "-" + l.script, l.language].find((c) => available.includes(c)) || null;
    } catch { return null; }
  }

  function stored() {
    try { return window.localStorage.getItem(STORED); } catch { return null; }
  }
  function remember(tag) {
    try { window.localStorage.setItem(STORED, tag); } catch { /* the page still follows it */ }
  }

  // Without an account's language: ?lang= (which then stays the choice), the
  // explicit choice, the browser's list, English.
  function browserChoice() {
    const asked = window.location ? closest(new URLSearchParams(window.location.search).get("lang")) : null;
    if (asked) { remember(asked); return asked; }
    const candidates = [stored(), ...((window.navigator && window.navigator.languages) || [])];
    for (const tag of candidates) {
      const found = closest(tag);
      if (found) return found;
    }
    return "en";
  }

  function load(tag) {
    if (catalogs[tag]) return Promise.resolve(true);
    return new Promise((resolve) => {
      const script = window.document.createElement("script");
      script.src = new URL("i18n/" + tag + ".js", new URL(here, window.location.href)).href;
      script.onload = () => resolve(!!catalogs[tag]);
      script.onerror = () => resolve(false);
      window.document.head.appendChild(script);
    });
  }

  // Never rejects: a catalog that cannot be had leaves the page in the language it has.
  let asked = 0;
  async function use(tag) {
    const mine = ++asked;
    if (tag !== i18n.language && !(await load(tag))) return;
    if (mine !== asked) return;
    i18n.language = tag;
    if (window.document && window.document.documentElement) window.document.documentElement.lang = tag;
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
  // The first language, before the first view is drawn.
  i18n.ready = use(browserChoice());
  // The account's interface language, or null: the rule without an account.
  i18n.follow = (tag) => use(closest(tag) || browserChoice());
  // A choice made on a page before sign-in.
  i18n.choose = (tag) => { remember(tag); return use(tag); };
  M.i18n = i18n;
})(window.Maity);
