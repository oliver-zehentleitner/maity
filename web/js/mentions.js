// The @ picker (docs/api.md §8.6): typing @ in a text the hub scans offers
// the project's members by handle, from GET /projects/{slug}/members, which
// the writer may already read. It only helps to type a handle: the hub
// resolves mentions at write time, and nothing the picker knows is sent.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const SHOWN = 8;
  // An @ that starts a mention: at the start or after a character that is
  // none of [A-Za-z0-9_.@/+-] (§8.6), followed by what is typed so far.
  const TYPED = /(^|[^A-Za-z0-9_.@/+-])@([a-z0-9-]*)$/;
  let serial = 0;

  // Inside an inline code span (an odd number of backticks before the
  // caret on its line) nothing is a mention, so nothing is offered.
  const inCode = (before) => (before.split("\n").pop().match(/`/g) || []).length % 2 === 1;

  // Attaches the picker to a textarea; loadMembers() answers the project's
  // members once, when the first @ is typed. selfId is left out.
  M.mentionPicker = function (textarea, loadMembers, selfId) {
    serial += 1;
    const listId = "mention-list-" + serial;
    const list = h("ul", { class: "mention-list", id: listId, role: "listbox", "aria-label": "Members to mention", hidden: true });
    let members = null;
    let loading = null;
    let shown = [];
    let active = 0;
    textarea.setAttribute("aria-autocomplete", "list");
    textarea.setAttribute("aria-controls", listId);
    textarea.setAttribute("aria-expanded", "false");

    const caret = () => (typeof textarea.selectionStart === "number" ? textarea.selectionStart : textarea.value.length);

    function close() {
      shown = [];
      list.hidden = true;
      clear(list);
      textarea.setAttribute("aria-expanded", "false");
      textarea.removeAttribute("aria-activedescendant");
    }

    function pick(m) {
      const at = caret();
      const before = textarea.value.slice(0, at);
      const typed = TYPED.exec(before);
      if (!typed) { close(); return; }
      const start = at - typed[2].length - 1;
      textarea.value = textarea.value.slice(0, start) + "@" + m.handle + " " + textarea.value.slice(at);
      const next = start + m.handle.length + 2;
      if (textarea.setSelectionRange) textarea.setSelectionRange(next, next);
      close();
      textarea.focus();
    }

    function draw() {
      clear(list);
      shown.forEach((m, i) => {
        const id = listId + "-" + i;
        append(list, h("li", {
          id,
          role: "option",
          class: "mention-option" + (i === active ? " active" : ""),
          "aria-selected": i === active ? "true" : "false",
          // mousedown, not click: the textarea keeps its focus and caret.
          onmousedown: (e) => { e.preventDefault(); pick(m); },
        }, h("span", { class: "mention-handle" }, "@" + m.handle), " ", h("span", { class: "muted" }, m.display_name
          + (m.kind === "agent" ? " · agent" : ""))));
      });
      list.hidden = !shown.length;
      textarea.setAttribute("aria-expanded", shown.length ? "true" : "false");
      if (shown.length) textarea.setAttribute("aria-activedescendant", listId + "-" + active);
      else textarea.removeAttribute("aria-activedescendant");
    }

    async function update() {
      const before = textarea.value.slice(0, caret());
      const typed = TYPED.exec(before);
      if (!typed || inCode(before)) { close(); return; }
      if (!members) {
        loading = loading || Promise.resolve(loadMembers()).then((items) => { members = items; }, () => { members = []; });
        await loading;
      }
      const q = typed[2];
      shown = members.filter((m) => m.id !== selfId && m.handle.startsWith(q)).slice(0, SHOWN);
      active = 0;
      draw();
    }

    textarea.addEventListener("input", update);
    textarea.addEventListener("blur", close);
    textarea.addEventListener("keydown", (e) => {
      if (!shown.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length;
        draw();
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        pick(shown[active]);
      } else if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    });
    return list;
  };
})(window.Maity);
