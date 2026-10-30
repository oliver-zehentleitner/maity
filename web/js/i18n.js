// The dashboard's words from a catalog, one per language (i18n/<lang>.json,
// loaded as js/i18n/<lang>.js, which tools/check.py builds from it, since
// file:// cannot fetch JSON). English is the only language so far; a
// translation later fills a file, it touches no view (context/rendering.md).
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
    const form = new Intl.PluralRules(i18n.locale).select(count);
    return entry[form] !== undefined ? entry[form] : entry.other;
  }

  function t(key, values) {
    const said = template(key, values);
    // A key the catalog does not hold reads as itself: visible, never empty.
    return said === undefined ? key : fill(said, values);
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
  M.tn = tn;
  M.fmt = {
    number,
    dateTime: (value) => when(value, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    date: (value) => when(value, { year: "numeric", month: "short", day: "numeric" }),
    time: (value) => when(value, { hour: "2-digit", minute: "2-digit" }),
    when,
  };
  M.i18n = i18n;
})(window.Maity);
