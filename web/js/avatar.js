// A member's picture. A generated identicon first: a 5×5 mirrored pattern
// and a hue, both from the member id alone, so every client draws the same
// picture for the same member. Where the member carries an avatar URL the
// page may show (§6.10), that picture replaces it once it has loaded. Built
// as SVG nodes, never from markup. Decorative: the name is always written
// next to it.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const SVG = "http://www.w3.org/2000/svg";

  function svg(tag, attrs) {
    const el = document.createElementNS(SVG, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
    return el;
  }

  // FNV-1a, 32 bits: small, and the same in every browser.
  function fnv(text) {
    let x = 0x811c9dc5;
    for (const ch of String(text)) {
      x ^= ch.codePointAt(0);
      x = Math.imul(x, 0x01000193) >>> 0;
    }
    return x >>> 0;
  }

  // The cells that are on, as [column, row], for columns 0–4 (2–4 mirror 0–2).
  function cells(id) {
    const bits = fnv(id);
    const on = [];
    for (let row = 0; row < 5; row += 1) {
      for (let col = 0; col < 3; col += 1) {
        if ((bits >>> (row * 3 + col)) & 1) {
          on.push([col, row]);
          if (col < 2) on.push([4 - col, row]);
        }
      }
    }
    // An empty pattern would read as a missing picture: one cell at least.
    return on.length ? on : [[2, 2]];
  }

  const hueOf = (id) => fnv(id + "#hue") % 360;

  function identicon(id, size) {
    const box = svg("svg", { class: "avatar-svg", viewBox: "0 0 7 7", width: size, height: size, "aria-hidden": "true", focusable: "false" });
    // The hue as a custom property; the theme sets lightness and background.
    if (box.style && box.style.setProperty) box.style.setProperty("--avatar-h", String(hueOf(id)));
    box.appendChild(svg("rect", { class: "avatar-bg", x: 0, y: 0, width: 7, height: 7, rx: 1.4 }));
    cells(id).forEach(([x, y]) => box.appendChild(svg("rect", { class: "avatar-on", x: x + 1, y: y + 1, width: 1, height: 1 })));
    return box;
  }

  // The side to ask the hub for (§6.10, Sizes): the smallest of its sizes that covers the
  // shown size on this screen (at most twice the CSS pixels). Only the hub's avatar
  // addresses take `s`; a logo or banner is loaded as it is given.
  const SIDES = [32, 64, 128, 256];
  function sized(url, px) {
    if (!/^\/api\/v1\/avatars\//.test(url) || /[?&]s=/.test(url)) return url;
    const ratio = Math.min(Math.max(Number(window.devicePixelRatio) || 1, 1), 2);
    const side = SIDES.find((s) => s >= px * ratio) || 256;
    return url + (url.includes("?") ? "&" : "?") + "s=" + side;
  }

  // Load the picture once its place is near the screen: a page with many avatars (the
  // board) never waits for the ones nobody sees. Without IntersectionObserver, at once.
  // A placeholder that is not on the page 10 s after it was drawn is let go, whether or
  // not the observer ever saw it: a view drawn again (and again) leaves none observed. A
  // view that is put on the page later than that keeps the generated picture.
  const UNPLACED_MS = 10000;
  const waiting = new Map(); // placeholder -> { start, born }
  let observer = null;
  let sweepTimer = null;
  function release(el) {
    waiting.delete(el);
    if (observer) observer.unobserve(el);
  }
  function sweep(now) {
    waiting.forEach((w, el) => { if (el.isConnected === false && now - w.born >= UNPLACED_MS) release(el); });
    if (waiting.size && sweepTimer === null) {
      sweepTimer = window.setTimeout(() => { sweepTimer = null; sweep(Date.now()); }, UNPLACED_MS);
    }
  }
  function whenSeen(el, start) {
    if (typeof window.IntersectionObserver !== "function") { start(); return; }
    if (!observer) {
      observer = new window.IntersectionObserver((entries) => entries.forEach((e) => {
        const w = waiting.get(e.target);
        if (!w || !e.isIntersecting) return;
        release(e.target);
        w.start();
      }), { rootMargin: "200px" });
    }
    const now = Date.now();
    waiting.set(el, { start, born: now });
    observer.observe(el);
    sweep(now);
  }

  // The picture for a placeholder that is still waiting for it (smoke tests only).
  const pending = new WeakMap();

  // member: { id, avatar_url? }. The generated picture is shown at once; where the member
  // carries a picture the page may load (h() allows only the hub's own images), it is loaded
  // at the size shown and takes the generated one's place once it has arrived. One that
  // does not load (a 404 once the access is gone, §6.10) leaves the generated one.
  M.avatar = function (member, size) {
    const px = size || 24;
    const shown = identicon(member && member.id ? member.id : "?", px);
    const url = member && member.avatar_url ? sized(member.avatar_url, px) : null;
    if (!url || !M.dom.isOwnImage(url)) return shown;
    const start = () => {
      let img;
      try {
        img = M.dom.h("img", { class: "avatar-img", alt: "", width: String(px), height: String(px), decoding: "async", src: url });
      } catch (refused) {
        return; // not an image the page may load: the generated one stays
      }
      pending.set(shown, img);
      img.addEventListener("load", () => {
        pending.delete(shown);
        if (shown.parentNode) shown.parentNode.replaceChild(img, shown);
      });
      img.addEventListener("error", () => pending.delete(shown));
    };
    whenSeen(shown, start);
    return shown;
  };
  M.avatar.picture = (placeholder) => pending.get(placeholder) || null;
  // Smoke tests only: how many placeholders wait, and a sweep at a given time.
  M.avatar.waiting = () => waiting.size;
  M.avatar.sweep = sweep;
  M.avatar.sized = sized;
  M.avatar.cells = cells;
  M.avatar.hueOf = hueOf;
})(window.Maity);
