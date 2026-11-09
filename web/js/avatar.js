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
  // board) never waits for the ones nobody sees. Without IntersectionObserver or WeakRef,
  // at once. The observer watches only placeholders that are on the page. One that is not
  // (built before its view is mounted, or taken off the page) is held only weakly, so a view
  // that is thrown away keeps nothing alive. It is watched (again) once it is on the page:
  // `sweep` runs after every change of the page (MutationObserver, once per frame) and at
  // every avatar drawn.
  const starts = new WeakMap(); // placeholder -> start, until its picture is started
  const offPage = new Set(); // WeakRefs of placeholders not on the page
  const watched = new Set(); // placeholders on the page, observed
  let observer = null;
  let swept = false;
  function sweep() {
    swept = false;
    watched.forEach((el) => {
      if (el.isConnected !== false) return;
      watched.delete(el);
      observer.unobserve(el);
      offPage.add(new WeakRef(el));
    });
    offPage.forEach((ref) => {
      const el = ref.deref();
      if (!el || !starts.has(el)) { offPage.delete(ref); return; }
      if (el.isConnected === false) return;
      offPage.delete(ref);
      watched.add(el);
      observer.observe(el);
    });
  }
  function soon() {
    if (swept) return;
    swept = true;
    (window.requestAnimationFrame || ((f) => window.setTimeout(f, 16)))(sweep);
  }
  function whenSeen(el, start) {
    if (typeof window.IntersectionObserver !== "function" || typeof window.WeakRef !== "function") { start(); return; }
    if (!observer) {
      observer = new window.IntersectionObserver((entries) => entries.forEach((e) => {
        const go = starts.get(e.target);
        if (!go || !e.isIntersecting) return;
        starts.delete(e.target);
        watched.delete(e.target);
        observer.unobserve(e.target);
        go();
      }), { rootMargin: "200px" });
      if (typeof window.MutationObserver === "function" && document.body) {
        new window.MutationObserver(soon).observe(document.body, { childList: true, subtree: true });
      }
    }
    starts.set(el, start);
    offPage.add(new WeakRef(el));
    soon();
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
  // Smoke tests only: how many placeholders are watched or held off the page, and a sweep now.
  M.avatar.watched = () => watched.size;
  M.avatar.offPage = () => offPage.size;
  M.avatar.sweep = sweep;
  M.avatar.sized = sized;
  M.avatar.cells = cells;
  M.avatar.hueOf = hueOf;
})(window.Maity);
