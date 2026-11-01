// Maity docs: copy buttons, the search and the highlighted "On this page" entry.
// The pages work without this file.
(() => {
  for (const pre of document.querySelectorAll(".content pre")) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "copy"; b.textContent = "Copy";
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(pre.querySelector("code")?.innerText ?? pre.innerText); b.textContent = "Copied"; }
      catch { b.textContent = "Select and copy"; }
      setTimeout(() => (b.textContent = "Copy"), 1600);
    });
    pre.appendChild(b);
  }

  const box = document.querySelector(".search");
  if (box) {
    box.hidden = false;
    const input = box.querySelector("input"), list = box.querySelector(".search-results");
    let index = null;
    const load = async () => { if (!index) { try { index = await (await fetch("/docs/_assets/search.json")).json(); } catch { index = []; } } return index; };
    input.addEventListener("focus", load, { once: true });
    input.addEventListener("input", async () => {
      const q = input.value.trim().toLowerCase(); list.textContent = "";
      if (q.length < 2) return;
      const words = q.split(/\s+/);
      const hits = (await load()).filter(e => words.every(w => (e.t + " " + e.p).toLowerCase().includes(w))).slice(0, 12);
      for (const e of hits) {
        const li = document.createElement("li"), a = document.createElement("a"), s = document.createElement("small");
        a.href = e.u; a.textContent = e.t; s.textContent = e.p; a.appendChild(s); li.appendChild(a); list.appendChild(li);
      }
      if (!hits.length) { const li = document.createElement("li"); li.className = "none"; li.textContent = "Nothing found."; list.appendChild(li); }
    });
    document.addEventListener("keydown", e => {
      if (e.key === "/" && document.activeElement !== input && !/input|textarea/i.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); }
    });
  }

  const links = [...document.querySelectorAll(".toc a")];
  if (links.length && "IntersectionObserver" in window) {
    const byId = new Map(links.map(a => [decodeURIComponent(a.hash.slice(1)), a]));
    const io = new IntersectionObserver(entries => {
      for (const en of entries) if (en.isIntersecting) { links.forEach(a => a.classList.remove("on")); byId.get(en.target.id)?.classList.add("on"); }
    }, { rootMargin: "-70px 0px -70% 0px" });
    for (const id of byId.keys()) { const h = document.getElementById(id); if (h) io.observe(h); }
  }
})();
