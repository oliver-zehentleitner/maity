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
        } else if (key === "href" && !isLocalRef(value) && !safeUrl(value)) {
          throw new TypeError("h(): href is neither a route nor an https URL");
        } else if (key === "src" && !isLocalRef(value) && !isOwnImage(value)) {
          // An image never comes from another origin, not even over https.
          throw new TypeError("h(): src is neither a local file nor the hub's own image");
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

  // An image the page itself points at: a project's logo or banner on the
  // hub's own origin (docs/api.md §11.2, built by api.js), or an object URL
  // of an image chosen in this tab (fixture mode's upload). Never from data.
  function isOwnImage(value) {
    if (typeof value !== "string") return false;
    if (/^\/api\/v1\/projects\/[a-z0-9][a-z0-9-]{1,62}\/(logo|banner)\?v=[A-Za-z0-9%._-]*$/.test(value)) return true;
    // Object URLs exist only for an upload in fixture mode, a page opened from file://.
    return window.location.protocol === "file:" && /^blob:null\/[0-9a-f-]+$/.test(value);
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

  // The hub's rules for a typed handle or slug (hub/src/maity_hub/models.py),
  // said up front where one is typed, and again when one breaks them.
  const NAME_RULES = {
    handle: { pattern: "[a-z0-9][a-z0-9\\-]{1,30}", test: /^[a-z0-9][a-z0-9-]{1,30}$/,
      text: "Lowercase letters, digits and -, 2–31 characters, starting with a letter or digit." },
    slug: { pattern: "[a-z0-9][a-z0-9\\-]{1,62}", test: /^[a-z0-9][a-z0-9-]{1,62}$/,
      text: "Lowercase letters, digits and -, 2–63 characters, starting with a letter or digit." },
  };

  M.dom = { h, append, clear, safeUrl, formatTime, formatAgo, NAME_RULES };
})(window.Maity);
