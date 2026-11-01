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
        } else if (key === "href" && M.route.isRoute(value)) {
          // A path of the dashboard, as the address bar holds it (js/route.js).
          el.setAttribute("href", M.route.href(value));
        } else if (key === "href" && M.route.isHubPage(value)) {
          // A page the hub serves itself (a legal page): a plain page load.
          el.setAttribute("href", value);
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

  // A relative file of the dashboard (brand/…) is local. No anchor and no
  // bare query: under the shell's <base href="/assets/"> (§16.11) they would
  // lead into /assets/. A route is a path (js/route.js), never a fragment.
  function isLocalRef(value) {
    return typeof value === "string" && /^[a-z0-9_-]+\/[a-z0-9_./-]+$/i.test(value) && !/^[a-z]+:/i.test(value);
  }

  // An image the page itself points at: a project's logo or banner on the
  // hub's own origin (docs/api.md §11.2, built by api.js), a member's
  // avatar there (§6.10, the path the hub gives as avatar_url), or an object
  // URL of an image chosen in this tab (fixture mode's upload). Never
  // another origin.
  function isOwnImage(value) {
    if (typeof value !== "string") return false;
    if (/^\/api\/v1\/projects\/[a-z0-9][a-z0-9-]{1,30}\/[a-z0-9][a-z0-9-]{1,62}\/(logo|banner)\?v=[A-Za-z0-9%._-]*$/.test(value)) return true;
    if (/^\/api\/v1\/avatars\/[A-Za-z0-9_-]{1,64}\?v=[A-Za-z0-9%._-]*$/.test(value)) return true;
    // A project's README badge, served by the hub at its root (§6.20).
    if (/^\/badge\/[a-z0-9][a-z0-9-]{1,30}\/[a-z0-9][a-z0-9-]{1,62}\.svg(\?v=[A-Za-z0-9%._-]*)?$/.test(value)) return true;
    // Object URLs exist only for an upload in fixture mode, a page opened from file://.
    return window.location.protocol === "file:" && /^blob:null\/[0-9a-f-]+$/.test(value);
  }

  // An attachment's bytes on the hub's own origin (docs/api.md §8.7), built
  // by api.js from the project and the attachment id, never from data; in
  // fixture mode an object URL of a file chosen in this tab.
  function isOwnFile(value) {
    if (typeof value !== "string") return false;
    if (/^\/api\/v1\/projects\/[a-z0-9][a-z0-9-]{1,30}\/[a-z0-9][a-z0-9-]{1,62}\/attachments\/[A-Za-z0-9_-]{1,64}\/content(\?download=1)?$/.test(value)) return true;
    // The campaign counts as a download (§16.7.2), which fixtures have no address for: smoke tests it here.
    if (/^\/api\/v1\/admin\/statistics\/campaigns\?days=[0-9]{1,3}&format=csv$/.test(value)) return true;
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

  // A date and time in the reader's locale, through Intl (js/i18n.js).
  function formatTime(iso) {
    if (!iso) return "—";
    return M.fmt.dateTime(iso);
  }

  // "3 min ago" relative to now; falls back to the absolute time after a day.
  function formatAgo(iso, now) {
    if (!iso) return M.t("time.never");
    const then = new Date(iso).getTime();
    const diff = Math.round(((now || Date.now()) - then) / 1000);
    if (Number.isNaN(diff)) return iso;
    if (diff < 0) return formatTime(iso);
    if (diff < 60) return M.t("time.just_now");
    if (diff < 3600) return M.t("time.minutes_ago", { count: Math.floor(diff / 60) });
    if (diff < 86400) return M.t("time.hours_ago", { count: Math.floor(diff / 3600) });
    return formatTime(iso);
  }

  // The hub's rules for a typed handle or slug (hub/src/maity_hub/models.py),
  // said up front where one is typed, and again when one breaks them.
  const NAME_RULES = {
    handle: { pattern: "[a-z0-9][a-z0-9\\-]{1,30}", test: /^[a-z0-9][a-z0-9-]{1,30}$/,
      get text() { return M.t("name_rules.handle"); } },
    slug: { pattern: "[a-z0-9][a-z0-9\\-]{1,62}", test: /^[a-z0-9][a-z0-9-]{1,62}$/,
      get text() { return M.t("name_rules.slug"); } },
  };

  // Whether `said` is "@" + one of the member's aliases (§6.24), or the long form
  // "@<owner>/<handle>" where the handle part is the member's handle or an alias and
  // the owner part is the owner's current handle (the first half of the member's global
  // name) or one of the owner's aliases, when the owner is among the member views the
  // context knows. The stored mention says who is meant; this only says that the typed
  // name was one of theirs.
  function aliasSaid(ctx, x, said, suffix) {
    const m = ctx && ctx.memberById ? ctx.memberById[x.member_id] : null;
    if (!m || !said.startsWith("@") || (suffix && !said.endsWith(suffix))) return false;
    const typed = said.slice(1, suffix ? said.length - suffix.length : said.length);
    const slash = typed.indexOf("/");
    if (slash < 0) return (m.aliases || []).indexOf(typed) >= 0;
    if ([m.handle].concat(m.aliases || []).indexOf(typed.slice(slash + 1)) < 0) return false;
    const owner = typed.slice(0, slash);
    const named = ctx.memberById[m.owner_id];
    if (!owner) return false;  // "@/handle" names no owner
    return owner === String(m.name || "").split("/")[0] || (!!named && (named.aliases || []).indexOf(owner) >= 0);
  }

  // The stored mentions of a text (docs/api.md §8.6) that stand where they
  // say: offsets and lengths count code points; only the stored ones for
  // this field count, and only where the text there is "@" + the stored
  // handle (or the long @owner/handle, or an alias the members in `ctx` know,
  // §6.24), with an instance's #id after it; nothing the writer typed becomes
  // a member link. js/markdown.js draws them as links.
  function mentionSpans(text, mentions, field, ctx) {
    const chars = Array.from(String(text || ""));
    const out = [];
    let from = 0;
    (mentions || [])
      .filter((x) => x && x.field === field && Number.isInteger(x.offset) && Number.isInteger(x.length) && x.length > 1)
      .sort((a, b) => a.offset - b.offset)
      .forEach((x) => {
        if (x.offset < from || x.offset + x.length > chars.length) return;
        const said = chars.slice(x.offset, x.offset + x.length).join("");
        const suffix = x.instance ? "#" + x.instance : "";
        if (said !== "@" + x.handle + suffix && !(x.name && said === "@" + x.name + suffix) && !aliasSaid(ctx, x, said, suffix)) return;
        out.push({ offset: x.offset, length: x.length, said, member_id: x.member_id, instance: x.instance || null });
        from = x.offset + x.length;
      });
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
  //
  // The keys are named as the keyboard prints them (tsk-00q3ddrh7a1q):
  // ⌘ on an Apple device, Strg where the page or the browser speaks German,
  // Ctrl elsewhere.
  function sendKeysFor(lang, platform, ua) {
    if (/Mac|iPhone|iPad|iPod/.test(String(platform || "")) || /Macintosh|iPhone|iPad|iPod/.test(String(ua || ""))) return "⌘+Enter";
    return /^de\b/i.test(String(lang || "")) ? "Strg+Enter" : "Ctrl+Enter";
  }
  const nav = window.navigator || {};
  // dom.js also loads where there is no document (web/tools/starter-configs.js).
  const root = typeof document !== "undefined" ? document.documentElement : null;
  const pageLang = (root && root.getAttribute && root.getAttribute("lang")) || "";
  const SEND_KEYS = sendKeysFor(/^de\b/i.test(pageLang) ? pageLang : nav.language, nav.platform, nav.userAgent);
  // A device with no keyboard to press them on: touch alone, no hover.
  const touchOnly = () => !!(window.matchMedia && window.matchMedia("(hover: none) and (pointer: coarse)").matches);
  function formOf(el) {
    for (let x = el.parentNode; x; x = x.parentNode) if (x.tagName === "FORM") return x;
    return null;
  }
  const submitOf = (form) => form && Array.from(form.querySelectorAll("button")).find((b) => b.getAttribute("type") === "submit");
  // The keys right before the button that sends, muted, the two one group
  // (span.send-with-keys, in the button's place), and in the button's
  // tooltip, so whoever looks at the button learns them; the label keeps
  // saying them for a screen reader. Once per button; none on a touch-only
  // device. The designer's pass on #431: the hint reads as Send's label.
  function showSendKeys(button) {
    if (!button || button.getAttribute("data-send-keys") || touchOnly() || !button.parentNode) return;
    button.setAttribute("data-send-keys", SEND_KEYS);
    button.setAttribute("aria-keyshortcuts", "Control+Enter Meta+Enter");
    const said = button.getAttribute("title");
    button.setAttribute("title", (said ? said + " " : (button.textContent || "").trim() + " ") + "(" + SEND_KEYS + ")");
    const group = h("span", { class: "send-with-keys" });
    button.parentNode.insertBefore(group, button);
    append(group, h("span", { class: "send-keys muted", "aria-hidden": "true" }, SEND_KEYS), button);
  }
  function sendOnCtrlEnter(field, act, button) {
    field.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey) || e.isComposing) return;
      e.preventDefault();
      const form = act ? null : formOf(field);
      const submit = button || submitOf(form);
      if (submit && submit.disabled) return;
      if (act) act(e);
      else if (form) form.requestSubmit();
    });
    // The view puts the field and its button on the page after this call.
    window.setTimeout(() => showSendKeys(button || submitOf(formOf(field))), 0);
    return field;
  }

  // The handle a member goes by in a project (docs/api.md §6.3): the short
  // one, or an agent's global name (owner/handle) where two members of the
  // project share the short one. A human has no long form and keeps the
  // short one ("a human comes first", §8.6). `members`: the project's list.
  const sharedOf = new WeakMap();
  function sharedHandles(members) {
    const list = members || [];
    if (!sharedOf.has(list)) {
      const count = {};
      list.forEach((m) => { if (m && m.handle) count[m.handle] = (count[m.handle] || 0) + 1; });
      sharedOf.set(list, new Set(Object.keys(count).filter((k) => count[k] > 1)));
    }
    return sharedOf.get(list);
  }
  function handleIn(members, m) {
    if (!m || !m.handle) return null;
    return m.kind === "agent" && m.name && sharedHandles(members).has(m.handle) ? m.name : m.handle;
  }
  const handleOf = (ctx, m) => handleIn(ctx && ctx.members, m);

  // The hub's refusal of a short handle two agents share (§8.6
  // ambiguous_mention), in words with the long forms it names; null for
  // any other error.
  function ambiguousMention(err) {
    const fields = err && err.code === "invalid" && err.details && err.details.fields;
    if (!fields || !Object.values(fields).includes("ambiguous_mention")) return null;
    const named = (err.details && err.details.mentions) || {};
    // One sentence per handle; the long forms joined as the catalog's language says "or".
    const or = new Intl.ListFormat(M.i18n.language, { type: "disjunction" });
    const parts = Object.keys(named).map((handle) => M.t("mention.ambiguous", { handle: "@" + handle, count: named[handle].length,
      names: or.format(named[handle].map((n) => "@" + n)) }));
    return { message: (parts.length ? parts.join("; ") : M.t("mention.ambiguous_unnamed")) + "." };
  }

  // A member as every view names them: always a way to their view in the
  // project (the maintainer's rule: a member is always clickable), the full
  // name as tooltip. `who` is a member id or a reference carrying
  // {member_id or id, display_name, handle}. opts.text: what it says (the
  // display name by default; "handle" for @handle); opts.avatar: a picture
  // of that size before it. A member the project does not list (removed,
  // outside), or a view read from outside the project, gets plain text.
  // opts.instance: the agent instance that wrote or did it (§6.17), its id
  // or {instance, harness, model}; the agent is then named
  // <handle>#<id> (owner/handle#id where two agents share the handle),
  // the #id muted with the session's harness and model as its tooltip, so
  // two instances of one agent read apart. A human has no instances.
  // The handle and the #id are two links (the maintainer, tsk-bczgjkfpw1wg):
  // the member's page, and the same page's Sessions with that instance.
  function memberRef(ctx, who, opts) {
    const o = opts || {};
    const id = typeof who === "string" ? who : who && (who.member_id || who.id);
    const m = id && ctx.memberById ? ctx.memberById[id] : null;
    const name = (m && m.display_name) || (who && who.display_name) || (id && ctx.nameOf ? ctx.nameOf(id) : id) || "—";
    const handle = (m && handleOf(ctx, m)) || (who && who.handle);
    const inst = instanceOf(o.instance);
    const agent = !(m && m.kind === "human") && !(who && who.kind === "human");
    // Without a handle (a reference read across projects carries none) the
    // name stands before the #id: the instance is said all the same.
    const linkable = !!m && !ctx.outsider && typeof ctx.link === "function";
    const suffix = inst && agent
      ? (linkable
        ? h("a", { class: "member-instance muted", href: instanceHref(ctx, id, inst.id), title: instanceTitle(inst) }, "#" + inst.id)
        : h("span", { class: "member-instance muted", title: instanceTitle(inst) }, "#" + inst.id))
      : null;
    const label = suffix && handle ? (o.text === "handle" ? "@" : "") + handle
      : o.text === "handle" ? (handle ? "@" + handle : name) : (o.text || name);
    const pic = o.avatar && m && M.avatar ? M.avatar(m, o.avatar) : null;
    const ref = !linkable
      ? h("span", { class: "member-ref plain", title: name }, pic, label)
      : h("a", { class: "member-ref", href: ctx.link("members", id), title: name, "data-member": id }, pic, label);
    // The #id is a link of its own beside the handle's, never inside it.
    return suffix ? h("span", { class: "member-ref-instance" }, ref, suffix) : ref;
  }
  // Where an instance's #id leads: its member's page, Sessions, with it chosen.
  const instanceHref = (ctx, memberId, instanceId) => ctx.link("members", memberId, "sessions", instanceId);
  const INSTANCE = /^[2-9a-hjkmnp-z]{4,5}$/; // an instance id (§6.17)
  function instanceOf(x) {
    const src = typeof x === "string" ? { instance: x } : x;
    const iid = src && src.instance;
    return typeof iid === "string" && INSTANCE.test(iid) ? { id: iid, harness: src.harness, model: src.model } : null;
  }
  function instanceTitle(inst) {
    const said = [inst.harness, inst.model].filter((x) => typeof x === "string" && x);
    return M.t("member.instance", { id: inst.id }) + (said.length ? " · " + said.join(" · ") : "");
  }

  // A member as a chip (the designer's handover on the overview, #6484):
  // a pill linking to their Members row, the avatar round for a human and
  // rounded square for an agent, a presence dot on it, then @handle; the
  // full name, trust and role, kind and presence in its tooltip and accessible name.
  // A member the project does not list is the same chip without a link.
  const PRESENCE_WORDS = { online: "online", away: "away", offline: "offline", paused: "paused", revoked: "revoked" };
  function memberChip(ctx, who) {
    const id = typeof who === "string" ? who : who && (who.member_id || who.id);
    const m = (id && ctx.memberById && ctx.memberById[id]) || (typeof who === "object" ? who : null) || { id };
    const handle = handleOf(ctx, m) || m.handle || id;
    const presence = m.presence || "offline";
    const said = [m.display_name || handle, M.trust ? M.trust.words(m) : m.role, m.kind, PRESENCE_WORDS[presence] || presence].filter(Boolean).join(" · ");
    const face = [
      h("span", { class: "chip-avatar " + (m.kind === "agent" ? "agent" : "human") }, M.avatar ? M.avatar(m, 22) : null,
        h("span", { class: "chip-dot presence-" + presence, "aria-hidden": "true" })),
      h("span", { class: "chip-handle" }, "@" + handle),
    ];
    const linkable = ctx.memberById && ctx.memberById[id] && !ctx.outsider && typeof ctx.link === "function";
    return linkable
      ? h("a", { class: "member-chip", href: ctx.link("members", id), title: said, "aria-label": said, "data-member": id }, face)
      : h("span", { class: "member-chip plain", title: said }, face);
  }

  const isSilentAgent = (member) => !!member && member.kind === "agent"
    && ["away", "offline", "paused", "revoked"].includes(member.presence);

  function silentSince(member, warn) {
    if (!isSilentAgent(member)) return null;
    const date = member.last_seen_at && new Date(member.last_seen_at);
    const known = date && !Number.isNaN(date.getTime());
    const text = known ? M.t("member.silent_since", { time: M.fmt.time(date) })
      : M.t("member.silent_unknown");
    return h("span", { class: "member-silence " + (warn ? "flag-inline" : "muted"),
      title: known ? M.t("member.last_call", { time: formatTime(member.last_seen_at) }) : M.t("member.no_last_call") }, text);
  }

  // A dormant instance (§6.17): kept with its session, woken only by its own
  // address, so it is always said with that address.
  const dormantOf = (m) => ((m && m.instances) || []).filter((i) => !i.revoked_at && i.dormant);
  const dormantNote = (ctx, m, inst) => M.t("instance.dormant", { address: "@" + (handleOf(ctx, m) || m.handle || m.id) + "#" + inst.id });

  M.dom = { handleOf, handleIn, ambiguousMention, isSilentAgent, silentSince, dormantOf, dormantNote, memberRef, instanceHref, memberChip, h, append, clear, safeUrl, formatTime, formatAgo, NAME_RULES, mentionSpans, sniffImage, IMAGE_MAX, SEND_KEYS, sendKeysFor, showSendKeys, sendOnCtrlEnter };
})(window.Maity);
