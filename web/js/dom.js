// DOM helpers. Every string goes through textContent, never through an
// HTML parser: see context/rendering.md.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  // h("div", {class: "card", onclick: fn}, child, "text", [more])
  function h(tag, attrs) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key.startsWith("on")) {
          // Handlers are functions; a string here would be inline script.
          if (typeof value !== "function") throw new TypeError("h(): " + key + " must be a function");
          el.addEventListener(key.slice(2), value);
        } else if ((key === "href" || key === "src") && !isLocalRef(value) && !safeUrl(value)) {
          throw new TypeError("h(): " + key + " is neither a route nor an https URL");
        } else if (key === "class") {
          el.className = value;
        } else if (value === true) {
          el.setAttribute(key, "");
        } else {
          el.setAttribute(key, String(value));
        }
      }
    }
    for (let i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }

  // append(el, child, ...): skips null, undefined and false, flattens
  // arrays, turns everything else into text. The native Element.append
  // would insert "null" and stringify arrays, so the views use this one.
  function append(el) {
    for (let i = 1; i < arguments.length; i++) {
      const child = arguments[i];
      if (child === null || child === undefined || child === false) continue;
      if (Array.isArray(child)) {
        child.forEach((c) => append(el, c));
      } else if (child instanceof Node) {
        el.appendChild(child);
      } else {
        el.appendChild(document.createTextNode(String(child)));
      }
    }
    return el;
  }

  // Routes ("#/..."), the page's own query and relative files are local.
  function isLocalRef(value) {
    return typeof value === "string" && /^(#|\?|[a-z0-9_-]+\/[a-z0-9_./-]+$)/i.test(value) && !/^[a-z]+:/i.test(value);
  }

  // A link target from data (a forge URL a member typed, say) is used only
  // when it is plain https; anything else, javascript: included, is no link.
  function safeUrl(url) {
    return typeof url === "string" && /^https:\/\/[^\s]+$/i.test(url) ? url : null;
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
    return el;
  }

  function formatTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  }

  // "3 min ago" relative to now; falls back to the absolute time after a day.
  function formatAgo(iso, now) {
    if (!iso) return "never";
    const then = new Date(iso).getTime();
    const diff = Math.round(((now || Date.now()) - then) / 1000);
    if (Number.isNaN(diff)) return iso;
    if (diff < 0) return formatTime(iso);
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + " min ago";
    if (diff < 86400) return Math.floor(diff / 3600) + " h ago";
    return formatTime(iso);
  }

  M.dom = { h, append, clear, safeUrl, formatTime, formatAgo };
})(window.Maity);
