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

  // The code in a text as §8.6 reads it: fenced blocks (a line starting
  // with three or more backticks or tildes, to its closing fence or the
  // end) and inline spans (a run of n backticks to the next run of exactly
  // n). An unclosed run is plain text. Ranges are [start, end) in the
  // text's UTF-16 indices, as a caret counts.
  function codeRanges(text) {
    const ranges = [];
    const plain = [];
    let at = 0;
    let fence = null;
    let segment = 0;
    text.split("\n").forEach((line, i, lines) => {
      const end = at + line.length + (i < lines.length - 1 ? 1 : 0);
      if (fence) {
        const close = new RegExp("^" + (fence.ch === "`" ? "`" : "~") + "{" + fence.n + ",}\\s*$");
        if (close.test(line)) { ranges.push([fence.start, end]); fence = null; segment = end; }
      } else {
        const open = /^(`{3,}|~{3,})/.exec(line);
        if (open) {
          if (at > segment) plain.push([segment, at]);
          fence = { ch: open[1][0], n: open[1].length, start: at };
        }
      }
      at = end;
    });
    if (fence) ranges.push([fence.start, text.length]);
    else if (text.length > segment) plain.push([segment, text.length]);
    plain.forEach(([from, to]) => {
      const part = text.slice(from, to);
      const runs = [...part.matchAll(/`+/g)].map((m) => ({ i: m.index, n: m[0].length }));
      for (let k = 0; k < runs.length; k += 1) {
        const close = runs.findIndex((r, j) => j > k && r.n === runs[k].n);
        if (close < 0) continue;
        ranges.push([from + runs[k].i, from + runs[close].i + runs[close].n]);
        k = close;
      }
    });
    return ranges;
  }
  const inCode = (text, caret) => codeRanges(text).some(([a, b]) => caret > a && caret < b + 1 && caret <= b);
  M.mentionCode = codeRanges;

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
    // A textarea is a textbox: aria-autocomplete, aria-controls and
    // aria-activedescendant are its; aria-expanded is not (axe aria-allowed-attr).
    textarea.setAttribute("aria-controls", listId);

    const caret = () => (typeof textarea.selectionStart === "number" ? textarea.selectionStart : textarea.value.length);

    function close() {
      shown = [];
      list.hidden = true;
      clear(list);
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
      if (shown.length) textarea.setAttribute("aria-activedescendant", listId + "-" + active);
      else textarea.removeAttribute("aria-activedescendant");
    }

    // What is typed before the caret, if it is a mention being written.
    function typedNow() {
      const at = caret();
      const before = textarea.value.slice(0, at);
      const typed = TYPED.exec(before);
      return typed && !inCode(textarea.value, at) ? typed : null;
    }

    // Every input, blur and Escape starts a new generation: an answer that
    // comes back for an older one draws nothing.
    let generation = 0;
    async function update() {
      const mine = ++generation;
      if (!typedNow()) { close(); return; }
      if (!members) {
        // A failed read is tried again at the next @, not given up for good.
        loading = loading || Promise.resolve(loadMembers()).then((items) => { members = items; }, () => { loading = null; });
        await loading;
        if (!members) { if (mine === generation) close(); return; }
      }
      if (mine !== generation) return;
      // Read again: the text, the caret or the focus may have moved meanwhile.
      const typed = typedNow();
      const away = document.activeElement && document.activeElement !== textarea;
      if (!typed || away) { close(); return; }
      const q = typed[2];
      shown = members.filter((m) => m.id !== selfId && m.handle.startsWith(q)).slice(0, SHOWN);
      active = 0;
      draw();
    }

    textarea.addEventListener("input", update);
    textarea.addEventListener("blur", () => { generation += 1; close(); });
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
        generation += 1;
        close();
      }
    });
    return list;
  };
})(window.Maity);
