// Markdown as DOM nodes, for what humans and agents write in a chat: the
// small part of CommonMark people use there — paragraphs and line breaks,
// headings, lists, quotes, fenced code (with a Copy button), inline code,
// emphasis, and links that are plain https. Every piece of text becomes a
// text node: raw HTML stays visible as text, and no markup is parsed
// (context/rendering.md). What is not understood is shown as written. Ids
// in the text outside code become links (js/ids.js) where the caller says
// which project the text belongs to.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, safeUrl } = M.dom;

  // The clipboard, and what is said after it: "Copied", or how to copy by hand.
  async function copied(text) {
    try {
      await navigator.clipboard.writeText(text);
      return "Copied";
    } catch (err) {
      return "Copy failed — select the text";
    }
  }

  // Inline code copies itself on a click, or Enter or Space (the maintainer,
  // tsk-rdx6gaqveygx); a click that ends a selection inside it copies nothing.
  // "Copied" stands beside it for two seconds, a status for a screen reader.
  function inlineCode(text) {
    const said = h("span", { class: "md-copied", role: "status" });
    const copy = async () => {
      said.textContent = await copied(text);
      window.setTimeout(() => { said.textContent = ""; }, 2000);
    };
    // Only a click that ends a selection inside this code is a selection,
    // not a copy; one elsewhere on the page never swallows a key.
    const selectedHere = () => {
      const sel = window.getSelection ? window.getSelection() : null;
      return !!sel && !sel.isCollapsed && String(sel) !== "" && typeof sel.containsNode === "function" && sel.containsNode(code, true);
    };
    const code = h("code", { class: "md-inline-copy", tabindex: "0", role: "button", title: "Click to copy", "aria-label": "Copy " + text,
      onclick: () => { if (!selectedHere()) copy(); },
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copy(); } } }, text);
    return [code, said];
  }

  // Inline: code spans first (a run of n backticks to the next run of
  // exactly n), then links, autolinks and emphasis in the text between.
  function inline(text, at) {
    const out = [];
    let from = 0;
    const runs = [...text.matchAll(/`+/g)];
    for (let k = 0; k < runs.length; k += 1) {
      const open = runs[k];
      const close = runs.findIndex((r, j) => j > k && r[0].length === open[0].length);
      if (close < 0) continue;
      out.push(...spans(text.slice(from, open.index), at));
      const inner = text.slice(open.index + open[0].length, runs[close].index);
      out.push(...inlineCode(inner.length > 2 && inner.startsWith(" ") && inner.endsWith(" ") ? inner.slice(1, -1) : inner));
      from = runs[close].index + runs[close][0].length;
      k = close;
    }
    out.push(...spans(text.slice(from), at));
    return out;
  }

  // [text](https://…), a bare https://… and **strong**, *em* or _em_.
  // A path as a link target was the dashboard's landing page's alone; the
  // hub renders that page now (§16.7), so here it stays text.
  const TOKEN = /\[([^\[\]\n]+)\]\((https:\/\/[^\s)]+)\)|(https:\/\/[^\s<>()]+[^\s<>().,;:!?'"])|\*\*([^*\n]+)\*\*|(?:^|(?<=[\s(]))[*_]([^*_\n]+)[*_](?=$|[\s).,;:!?])/g;
  function spans(text, where) {
    const out = [];
    const plain = (s) => (where ? M.ids.link(s, where) : [s]);
    let at = 0;
    for (const m of text.matchAll(TOKEN)) {
      if (m.index > at) out.push(...plain(text.slice(at, m.index)));
      if (m[1] !== undefined) {
        const url = safeUrl(m[2]);
        // A text that looks like another address says where the link goes.
        const looks = /^\s*(https?:\/\/|www\.)/i.test(m[1]) && hostOf(m[1]) !== hostOf(m[2]);
        // An https link opens apart, without an opener.
        out.push(!url ? m[0] : h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, m[1]));
        if (url && looks) out.push(h("span", { class: "md-real-href" }, " (goes to " + hostOf(m[2]) + ")"));
      } else if (m[3] !== undefined) {
        const url = safeUrl(m[3]);
        out.push(url ? h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, m[3]) : m[0]);
      } else if (m[4] !== undefined) {
        out.push(h("strong", null, plain(m[4])));
      } else {
        out.push(h("em", null, plain(m[5])));
      }
      at = m.index + m[0].length;
    }
    if (at < text.length) out.push(...plain(text.slice(at)));
    return out;
  }

  const hostOf = (u) => (/^\s*(?:https?:\/\/)?([^/?#\s]+)/i.exec(u) || [null, ""])[1].toLowerCase();

  // A paragraph's lines, each break kept.
  function lines(list, at) {
    const out = [];
    list.forEach((l, i) => { if (i) out.push(h("br")); out.push(...inline(l, at)); });
    return out;
  }

  // Characters that make code read differently from what runs (Trojan Source).
  const INVISIBLE = /[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]/;
  let blocks = 0;
  function codeBlock(code, lang) {
    blocks += 1;
    const name = "Code" + (lang ? " (" + lang + ")" : "") + ", block " + blocks;
    const pre = h("pre", { class: "md-code", tabindex: "0", role: "region", "aria-label": name }, h("code", null, code));
    const copy = h("button", {
      type: "button",
      class: "small md-copy",
      "aria-label": "Copy " + name,
      onclick: async () => {
        copy.textContent = await copied(code);
        window.setTimeout(() => { copy.textContent = "Copy"; }, 2000);
      },
    }, "Copy");
    // The language and Copy sit inside the block's corner (the designer's
    // pass part 1); a warning about invisible characters stands above it.
    return h("div", { class: "md-code-box" },
      INVISIBLE.test(code) ? h("p", { class: "flag md-invisible" }, "This code contains invisible characters (bidi or zero-width); what you copy may differ from what you see.") : null,
      h("div", { class: "md-code-frame" },
        h("div", { class: "md-code-bar" }, lang ? h("span", { class: "md-lang" }, lang) : null, copy),
        pre));
  }

  // Quotes nest at most this deep; deeper is shown as written.
  const MAX_DEPTH = 8;

  // Blocks, line by line. `at`: the project the text belongs to
  // ({slug, repository}, M.ids.where), for its ids as links; none, none.
  M.markdown = function (source, at, depth) {
    const level = depth || 0;
    const all = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let i = 0;
    let para = [];
    const flush = () => { if (para.length) out.push(h("p", null, lines(para, at))); para = []; };
    while (i < all.length) {
      const line = all[i];
      // A fence (§8.6: three or more backticks or tildes, up to three spaces
      // in); a backtick fence's info string has no backtick; its first word
      // is the language.
      const fence = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
      if (fence && !(fence[1][0] === "`" && fence[2].includes("`"))) {
        flush();
        const lang = (fence[2].trim().split(/\s+/)[0] || "").slice(0, 40);
        const close = new RegExp("^ {0,3}" + (fence[1][0] === "`" ? "`" : "~") + "{" + fence[1].length + ",}\\s*$");
        const body = [];
        i += 1;
        while (i < all.length && !close.test(all[i])) { body.push(all[i]); i += 1; }
        out.push(codeBlock(body.join("\n"), lang));
        i += 1;
        continue;
      }
      const heading = /^(#{1,3})\s+(.*)$/.exec(line);
      if (heading) {
        flush();
        // A heading inside a message is a line of strong text, not a page heading.
        out.push(h("p", { class: "md-h md-h" + heading[1].length }, h("strong", null, inline(heading[2], at))));
        i += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        flush();
        const quoted = [];
        while (i < all.length && /^>\s?/.test(all[i])) { quoted.push(all[i].replace(/^>\s?/, "")); i += 1; }
        out.push(level < MAX_DEPTH
          ? h("blockquote", null, M.markdown(quoted.join("\n"), at, level + 1))
          : h("p", { class: "md-deep" }, lines(quoted, at)));
        continue;
      }
      const item = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/.exec(line);
      if (item) {
        flush();
        const ordered = /\d/.test(item[2]);
        const items = [];
        while (i < all.length) {
          const m = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/.exec(all[i]);
          if (!m || /\d/.test(m[2]) !== ordered) break;
          items.push(h("li", null, inline(m[3], at)));
          i += 1;
        }
        // A numbered list starts where its first item does.
        const first = ordered ? parseInt(item[2], 10) : 1;
        out.push(h(ordered ? "ol" : "ul", ordered && first !== 1 ? { start: String(first) } : null, items));
        continue;
      }
      if (!line.trim()) { flush(); i += 1; continue; }
      para.push(line);
      i += 1;
    }
    flush();
    return out;
  };
})(window.Maity);
