// A new deploy under an open page (docs/api.md §1.1 `Maity-Web-Version`, §16.11): every API
// answer names the dashboard the hub serves, the shell names the one this page runs. When they
// differ, a band above the header offers a reload; the page never reloads by itself
// (web/context/refresh.md 9d7aee6c). "Later" hides the band for that version in this tab, a
// newer one brings it back. Reload asks first while typed text may be lost; the dashboard keeps
// none of it over a reload.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h } = M.dom;
  const ID = "new-version-banner";

  let own;              // this page's version, from the shell's meta element (undefined: not read yet)
  let shown = null;     // the newer version the band stands for
  const later = new Set(); // the versions "Later" was chosen for: two hubs side by side may answer
                           // both of two newer ones, and neither brings the band back

  function ownVersion() {
    if (own === undefined) {
      const meta = document.head && document.head.querySelector('meta[name="maity-web-version"]');
      own = (meta && meta.getAttribute("content")) || null;
    }
    return own;
  }

  // Before the reload the person asked for, a question while they may lose something
  // (web/context/refresh.md 9d7aee6c). A simple rule, not a complete one: any text field (an
  // input, a textarea, a contenteditable), in a form or not, that they typed into (a trusted
  // `input` event, never a value a script set) and that still holds text; or a chat draft that is
  // not blank (js/chat.js says so through `holds`). An extra question costs a click; a case it
  // misses (a field a redraw replaced) is still a reload the person chose.
  const TEXT = /^(|text|search|email|url|tel|number|password)$/;
  // A contenteditable host by the browser's own reading (isContentEditable), its attribute in
  // any case ("TRUE" edits as "true" does) where that reading is missing.
  const editable = (f) => !!f && (f.isContentEditable === true || (f.isContentEditable === undefined
    && f.getAttribute && f.getAttribute("contenteditable") != null
    && String(f.getAttribute("contenteditable")).toLowerCase() !== "false"));
  const textField = (f) => !!f && (f.tagName === "TEXTAREA" || editable(f)
    || (f.tagName === "INPUT" && TEXT.test(((f.getAttribute && f.getAttribute("type")) || "").toLowerCase())));
  const textOf = (f) => (f.tagName === "TEXTAREA" || f.tagName === "INPUT" ? f.value : f.textContent);
  const typedInto = new WeakSet();
  // The editable hosts typed into, kept by reference: a selector cannot name every spelling of
  // the attribute. One leaving the page is dropped at the next look.
  const typedHosts = new Set();
  document.addEventListener("input", (e) => {
    if (!e || !e.isTrusted || !textField(e.target)) return;
    typedInto.add(e.target);
    if (e.target.tagName !== "TEXTAREA" && e.target.tagName !== "INPUT") typedHosts.add(e.target);
  }, true);
  const holders = new Map();

  function unsentInput() {
    const holds = (f) => typeof textOf(f) === "string" && textOf(f).trim() !== "";
    const fields = document.body ? document.body.querySelectorAll("textarea, input") : [];
    if (Array.from(fields).some((f) => typedInto.has(f) && holds(f))) return true;
    for (const host of Array.from(typedHosts)) {
      if (!document.body || !document.body.contains(host)) { typedHosts.delete(host); continue; }
      if (holds(host)) return true;
    }
    return Array.from(holders.values()).some((fn) => { try { return !!fn(); } catch (err) { return false; } });
  }

  function reload() {
    if (unsentInput() && !window.confirm(M.t("new_version.unsent"))) return;
    M.newVersion.reloadPage();
  }

  function draw() {
    const header = document.getElementById("header");
    if (!header || !header.parentNode) return;
    const parent = header.parentNode;
    const old = Array.from(parent.childNodes).find((n) => n.id === ID);
    if (!shown || later.has(shown)) { if (old) parent.removeChild(old); return; }
    const words = M.t("new_version.text");
    // Kept as it stands while nothing it says changed: a new band would be announced again
    // (role="status") and take the focus from its buttons on every page drawn.
    if (old && old.getAttribute("data-version") === shown && old.getAttribute("data-words") === words) return;
    const band = h("div", { id: ID, class: "new-version-banner", role: "status", "data-version": shown, "data-words": words },
      h("span", {}, words),
      h("button", { type: "button", class: "new-version-reload", onclick: reload }, M.t("new_version.reload")),
      h("button", { type: "button", class: "secondary new-version-later", onclick: () => { later.add(shown); draw(); } }, M.t("new_version.later")));
    if (old) parent.replaceChild(band, old);
    else parent.insertBefore(band, header);
  }

  // Each API answer's `Maity-Web-Version` (js/api.js). Two hubs side by side during a deploy may
  // answer both values: the band stands from the first newer one until a reload or "Later".
  function seen(version) {
    const mine = ownVersion();
    if (!mine || !version || version === mine || version === shown) return;
    shown = version;
    draw();
  }

  M.newVersion = {
    seen,
    // Drawn again with every page, so the band follows a change of language.
    draw,
    // window.location.reload, here so that the smoke test can see it called.
    reloadPage: () => window.location.reload(),
    unsentInput,
    // What a page keeps outside its fields (the chats' drafts): `fn()` true while it holds some.
    holds: (name, fn) => { if (fn) holders.set(name, fn); else holders.delete(name); },
  };
})(window.Maity);
