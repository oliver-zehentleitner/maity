// A new deploy under an open page (docs/api.md §1.1 `Maity-Web-Version`, §16.11): every API
// answer names the dashboard the hub serves, the shell names the one this page runs. When they
// differ, a band above the header offers a reload; the page never reloads by itself
// (web/context/refresh.md 9d7aee6c). "Later" hides the band for that version in this tab, a
// newer one brings it back. Over a reload, input the reader typed and has not sent (a chat's
// draft, a note, a changed setting) asks first: the dashboard keeps none of them over a reload.
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

  // What a reload would lose (web/context/refresh.md 9d7aee6c). Two sources, because no rule on
  // the DOM alone can tell a sent form from an unsent one when forms send asynchronously and
  // pages draw their fields anew:
  // - A field the reader changed: marked by a trusted `input` or `change` event (typing, pasting,
  //   autofill, a drop, a click on a checkbox, a choice in a select), never by a value a script
  //   sets; a file loaded into a field by the reader's choice is marked by its page (`changed`).
  //   Only a field whose value waits for a sending counts: a textarea, or a field of a form that
  //   is no search; a filter, a sort or a switch that saves itself at once stands outside a form,
  //   and one inside a form says so with `data-saves-itself`. It holds input while it still has
  //   some: text that is not blank, a box or choice the reader set. A form that sent clears its
  //   field, so it holds none; one whose sending failed keeps the text, so it still does.
  // - What a page keeps outside its fields (a chat's draft in another chat, a card panel drawn
  //   anew with what was typed): the page says so itself through `holds(name, fn)`.
  const NOT_TYPED = /^(button|submit|reset|image|hidden)$/;
  const CHOSEN = /^(checkbox|radio)$/;
  const kind = (f) => ((f && f.getAttribute && f.getAttribute("type")) || "").toLowerCase();
  const typable = (f) => !!f && (f.tagName === "TEXTAREA" || f.tagName === "SELECT"
    || (f.tagName === "INPUT" && !NOT_TYPED.test(kind(f))));
  const byReader = new WeakSet();
  function mark(e) { if (e && e.isTrusted && typable(e.target)) byReader.add(e.target); }
  document.addEventListener("input", mark, true);
  document.addEventListener("change", mark, true);
  const sendsLater = (f) => {
    if (f.getAttribute("data-saves-itself") != null) return false;
    if (f.tagName === "TEXTAREA") return true;
    for (let n = f.parentNode; n; n = n.parentNode) {
      if (n.tagName === "FORM") return (n.getAttribute("role") || "") !== "search";
    }
    return false;
  };
  const stillHolds = (f) => (f.tagName === "SELECT" || CHOSEN.test(kind(f)) ? true
    : typeof f.value === "string" && f.value.trim() !== "");
  const holders = new Map();

  function unsentInput() {
    const fields = document.body ? document.body.querySelectorAll("textarea, input, select") : [];
    if (Array.from(fields).some((f) => byReader.has(f) && sendsLater(f) && stillHolds(f))) return true;
    return Array.from(holders.values()).some((fn) => { try { return !!fn(); } catch (err) { return false; } });
  }

  // The browser's own "leave the page?" while an input would be lost; one prompt, whichever
  // listener asks (js/project-message.js asks for its own body as well).
  function guard(e) { if (unsentInput()) { e.preventDefault(); e.returnValue = ""; } }

  function reload() {
    window.addEventListener("beforeunload", guard);
    M.newVersion.reloadPage();
    // Kept from the guard after a reload the reader stopped: it belongs to the click alone.
    window.setTimeout(() => window.removeEventListener("beforeunload", guard), 0);
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
    // A page that keeps typed input outside its fields names it here: `fn()` true while it
    // holds some. One per name; a later one replaces it, none (null) removes it.
    holds: (name, fn) => { if (fn) holders.set(name, fn); else holders.delete(name); },
    // A form that stays as it is after its saving succeeded (a setting) says so: its fields, or
    // the one field given, hold no input until the reader changes them again.
    clean: (root) => {
      if (!root) return;
      if (typable(root)) byReader.delete(root);
      if (root.querySelectorAll) Array.from(root.querySelectorAll("textarea, input, select")).forEach((f) => byReader.delete(f));
    },
    // A value the reader brought in by a way that fires no event of theirs (a file loaded into
    // the field): input as if typed.
    changed: (f) => { if (typable(f)) byReader.add(f); },
    // For a page's `holds`: whether a map of unsaved edits (id -> {field: value}) holds any, text
    // that is not blank or a switch turned on.
    editsHeld: (edits) => Array.from(edits.values()).some((d) => d && Object.values(d)
      .some((v) => v === true || (typeof v === "string" && v.trim() !== ""))),
  };
})(window.Maity);
