// Markdown as DOM nodes, for what humans and agents write in a chat: the
// small part of CommonMark people use there — paragraphs and line breaks,
// headings, lists, quotes, fenced code (with a Copy button), inline code,
// emphasis, and links that are plain https. Every piece of text becomes a
// text node: raw HTML stays visible as text, and no markup is parsed
// (context/rendering.md). What is not understood is shown as written.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, safeUrl } = M.dom;

  // Inline: code spans first (a run of n backticks to the next run of
  // exactly n), then links, autolinks and emphasis in the text between.
  function inline(text) {
    const out = [];
    let at = 0;
    const runs = [...text.matchAll(/`+/g)];
    for (let k = 0; k < runs.length; k += 1) {
      const open = runs[k];
      const close = runs.findIndex((r, j) => j > k && r[0].length === open[0].length);
      if (close < 0) continue;
      out.push(...spans(text.slice(at, open.index)));
      const inner = text.slice(open.index + open[0].length, runs[close].index);
      out.push(h("code", null, inner.length > 2 && inner.startsWith(" ") && inner.endsWith(" ") ? inner.slice(1, -1) : inner));
      at = runs[close].index + runs[close][0].length;
      k = close;
    }
    out.push(...spans(text.slice(at)));
    return out;
  }

  // [text](https://…), a bare https://… and **strong**, *em* or _em_.
  const TOKEN = /\[([^\]\n]+)\]\((https:\/\/[^\s)]+)\)|(https:\/\/[^\s<>()]+[^\s<>().,;:!?'"])|\*\*([^*\n]+)\*\*|(?:^|(?<=[\s(]))[*_]([^*_\n]+)[*_](?=$|[\s).,;:!?])/g;
  function spans(text) {
    const out = [];
    let at = 0;
    for (const m of text.matchAll(TOKEN)) {
      if (m.index > at) out.push(text.slice(at, m.index));
      if (m[1] !== undefined) {
        const url = safeUrl(m[2]);
        out.push(url ? h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, m[1]) : m[0]);
      } else if (m[3] !== undefined) {
        const url = safeUrl(m[3]);
        out.push(url ? h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, m[3]) : m[0]);
      } else if (m[4] !== undefined) {
        out.push(h("strong", null, m[4]));
      } else {
        out.push(h("em", null, m[5]));
      }
      at = m.index + m[0].length;
    }
    if (at < text.length) out.push(text.slice(at));
    return out;
  }

  // A paragraph's lines, each break kept.
  function lines(list) {
    const out = [];
    list.forEach((l, i) => { if (i) out.push(h("br")); out.push(...inline(l)); });
    return out;
  }

  function codeBlock(code, lang) {
    const pre = h("pre", { class: "md-code", tabindex: "0", "aria-label": lang ? "Code, " + lang : "Code" }, h("code", null, code));
    const copy = h("button", {
      type: "button",
      class: "small md-copy",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(code);
          copy.textContent = "Copied";
        } catch (err) {
          copy.textContent = "Copy failed — select the text";
        }
      },
    }, "Copy");
    return h("div", { class: "md-code-box" }, lang ? h("span", { class: "md-lang" }, lang) : null, copy, pre);
  }

  // Blocks, line by line.
  M.markdown = function (source) {
    const all = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let i = 0;
    let para = [];
    const flush = () => { if (para.length) out.push(h("p", null, lines(para))); para = []; };
    while (i < all.length) {
      const line = all[i];
      const fence = /^(`{3,}|~{3,})\s*([\w+-]*)\s*$/.exec(line);
      if (fence) {
        flush();
        const close = new RegExp("^" + fence[1][0] + "{" + fence[1].length + ",}\\s*$");
        const body = [];
        i += 1;
        while (i < all.length && !close.test(all[i])) { body.push(all[i]); i += 1; }
        out.push(codeBlock(body.join("\n"), fence[2]));
        i += 1;
        continue;
      }
      const heading = /^(#{1,3})\s+(.*)$/.exec(line);
      if (heading) {
        flush();
        // Headings inside a message stay small: h4 to h6.
        out.push(h("h" + (heading[1].length + 3), { class: "md-h" }, inline(heading[2])));
        i += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        flush();
        const quoted = [];
        while (i < all.length && /^>\s?/.test(all[i])) { quoted.push(all[i].replace(/^>\s?/, "")); i += 1; }
        out.push(h("blockquote", null, M.markdown(quoted.join("\n"))));
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
          items.push(h("li", null, inline(m[3])));
          i += 1;
        }
        out.push(h(ordered ? "ol" : "ul", null, items));
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
