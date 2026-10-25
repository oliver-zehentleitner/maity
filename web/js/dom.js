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
        } else if (key === "href" && !isLocalRef(value) && !safeUrl(value) && !isOwnFile(value)) {
          throw new TypeError("h(): href is neither a route nor an https URL");
        } else if (key === "src" && !isLocalRef(value) && !isOwnImage(value) && !isOwnFile(value)) {
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
  // hub's own origin (docs/api.md §11.2, built by api.js), a member's
  // avatar there (§6.10, the path the hub gives as avatar_url), or an object
  // URL of an image chosen in this tab (fixture mode's upload). Never
  // another origin.
  function isOwnImage(value) {
    if (typeof value !== "string") return false;
    if (/^\/api\/v1\/projects\/[a-z0-9][a-z0-9-]{1,62}\/(logo|banner)\?v=[A-Za-z0-9%._-]*$/.test(value)) return true;
    if (/^\/api\/v1\/avatars\/[A-Za-z0-9_-]{1,64}\?v=[A-Za-z0-9%._-]*$/.test(value)) return true;
    // A project's README badge, served by the hub at its root (§6.20).
    if (/^\/badge\/[a-z0-9][a-z0-9-]{1,62}\.svg$/.test(value)) return true;
    // Object URLs exist only for an upload in fixture mode, a page opened from file://.
    return window.location.protocol === "file:" && /^blob:null\/[0-9a-f-]+$/.test(value);
  }

  // An attachment's bytes on the hub's own origin (docs/api.md §8.7), built
  // by api.js from the project and the attachment id, never from data; in
  // fixture mode an object URL of a file chosen in this tab.
  function isOwnFile(value) {
    if (typeof value !== "string") return false;
    if (/^\/api\/v1\/projects\/[a-z0-9][a-z0-9-]{1,62}\/attachments\/[A-Za-z0-9_-]{1,64}\/content(\?download=1)?$/.test(value)) return true;
    return window.location.protocol === "file:" && /^blob:null\/[0-9a-f-]+$/.test(value);
  }

  // A link target from data (a forge URL a member typed, say) is used only
  // when it is plain https; anything else, javascript: included, is no link.
  // Plain https only: no whitespace, no control, bidi or zero-width
  // characters (a link that reads one way and goes another), and no user
  // info before the host (https://bank.example@evil.example).
  const HIDDEN = /[\u0000-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]/;
  function safeUrl(url) {
    if (typeof url !== "string" || !/^https:\/\/[^\s]+$/i.test(url) || HIDDEN.test(url)) return null;
    return /^https:\/\/[^/?#]*@/i.test(url) ? null : url;
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

  // A scanned text with its stored mentions (docs/api.md §8.6) as text
  // nodes and member links. Offsets and lengths count code points; only the
  // stored ones for this field are links, and only where the text there is
  // "@" + the stored handle; nothing the writer typed becomes a link.
  function withMentions(text, mentions, field, hrefOf) {
    const chars = Array.from(String(text || ""));
    const marks = (mentions || [])
      .filter((x) => x && x.field === field && Number.isInteger(x.offset) && Number.isInteger(x.length) && x.length > 1)
      .sort((a, b) => a.offset - b.offset);
    const out = [];
    let at = 0;
    marks.forEach((x) => {
      if (x.offset < at || x.offset + x.length > chars.length) return;
      const said = chars.slice(x.offset, x.offset + x.length).join("");
      if (said !== "@" + x.handle) return;
      if (x.offset > at) out.push(chars.slice(at, x.offset).join(""));
      // No href: a mention named where its member cannot be opened.
      const href = hrefOf(x.member_id);
      out.push(href ? h("a", { class: "mention", href }, said) : h("span", { class: "mention" }, said));
      at = x.offset + x.length;
    });
    if (at < chars.length) out.push(chars.slice(at).join(""));
    return out;
  }

  // An image to upload as the hub reads it (§11.2, §6.10): its type from the
  // first bytes, at most 1 MiB; null when it is no PNG, JPEG or WebP.
  const IMAGE_MAX = 1024 * 1024;
  async function sniffImage(file) {
    const b = new Uint8Array(await file.slice(0, 12).arrayBuffer());
    const at = (i, bytes) => bytes.every((v, k) => b[i + k] === v);
    if (at(0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return "image/png";
    if (at(0, [0xff, 0xd8, 0xff])) return "image/jpeg";
    if (at(0, [0x52, 0x49, 0x46, 0x46]) && at(8, [0x57, 0x45, 0x42, 0x50])) return "image/webp";
    return null;
  }

  // Ctrl+Enter, or Cmd+Enter on a Mac, sends what a multi-line field is
  // for, as its submit button would; plain Enter stays a new line. The
  // field's form is submitted, or for a field outside one `act` is called;
  // never while `button` (the form's submit button by default) is
  // disabled, so a send on its way is not sent twice.
  const SEND_KEYS = /Mac|iPhone|iPad/.test((window.navigator && window.navigator.platform) || "") ? "⌘+Enter" : "Ctrl+Enter";
  function formOf(el) {
    for (let x = el.parentNode; x; x = x.parentNode) if (x.tagName === "FORM") return x;
    return null;
  }
  function sendOnCtrlEnter(field, act, button) {
    field.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey) || e.isComposing) return;
      e.preventDefault();
      const form = act ? null : formOf(field);
      const submit = button || (form && Array.from(form.querySelectorAll("button")).find((b) => b.getAttribute("type") === "submit"));
      if (submit && submit.disabled) return;
      if (act) act(e);
      else if (form) form.requestSubmit();
    });
    return field;
  }

  // What a view says where a feature of a newer hub would be: muted, not red.
  const notOnHub = (text) => h("p", { class: "muted not-on-hub" }, text);

  // A member as every view names them: always a way to their view in the
  // project (the maintainer's rule: a member is always clickable), the full
  // name as tooltip. `who` is a member id or a reference carrying
  // {member_id or id, display_name, handle}. opts.text: what it says (the
  // display name by default; "handle" for @handle); opts.avatar: a picture
  // of that size before it. A member the project does not list (removed,
  // outside), or a view read from outside the project, gets plain text.
  function memberRef(ctx, who, opts) {
    const o = opts || {};
    const id = typeof who === "string" ? who : who && (who.member_id || who.id);
    const m = id && ctx.memberById ? ctx.memberById[id] : null;
    const name = (m && m.display_name) || (who && who.display_name) || (id && ctx.nameOf ? ctx.nameOf(id) : id) || "—";
    const handle = (m && m.handle) || (who && who.handle);
    const label = o.text === "handle" ? (handle ? "@" + handle : name) : (o.text || name);
    const pic = o.avatar && m && M.avatar ? M.avatar(m, o.avatar) : null;
    if (!m || ctx.outsider || typeof ctx.link !== "function") return h("span", { class: "member-ref plain", title: name }, pic, label);
    return h("a", { class: "member-ref", href: ctx.link("members", id), title: name, "data-member": id }, pic, label);
  }

  const isSilentAgent = (member) => !!member && member.kind === "agent"
    && ["away", "offline", "paused", "revoked"].includes(member.presence);

  function silentSince(member, warn) {
    if (!isSilentAgent(member)) return null;
    const date = member.last_seen_at && new Date(member.last_seen_at);
    const known = date && !Number.isNaN(date.getTime());
    const text = known ? "silent since " + date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false })
      : "silent · last call unknown";
    return h("span", { class: "member-silence " + (warn ? "flag-inline" : "muted"),
      title: known ? "Last hub call: " + formatTime(member.last_seen_at) : "No last hub call is available" }, text);
  }

  M.dom = { isSilentAgent, silentSince, memberRef, notOnHub, h, append, clear, safeUrl, formatTime, formatAgo, NAME_RULES, withMentions, sniffImage, IMAGE_MAX, SEND_KEYS, sendOnCtrlEnter };
})(window.Maity);
