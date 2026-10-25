# Brand

## The mark is "the round" with a drawn "m"; the loader is one lap in 0.9 s; a circle is a human, a rounded square an agent

**Id:** 838c7e0a-0586-442b-874d-57d9c8328b73
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-23, delivered by the design agent; web/brand/BRAND.md
**Revisit when:** the mark, the loader or the shape language changes, or the fonts proposed in BRAND.md are bundled

Maity's mark is direction C, "the round": six seats in a circle, five
humans and one agent (the blue rounded square) taking its seat at the
top, and a drawn "m" (two arches in the same stroke logic as the seats)
sits in the middle as the project everyone gathers around. Below 32 px
the small variant drops the "m" and uses heavier seats; the 28 px header
lockup therefore carries the small mark on purpose. The shape language holds
for the logo, avatars, the org chart and icons: a circle is a human, a
rounded square is an agent. The loader is the agent walking the round
clockwise with a fading trail, one lap in 0.9 s; with
`prefers-reduced-motion: reduce` it stands still as the mark. The files
are in `web/brand/`, with `BRAND.md` beside them.

The fonts BRAND.md proposes (Space Grotesk, Inter, JetBrains Mono, all
self-hosted rather than loaded from Google Fonts) are not part of the
change that added the assets; they follow separately, as does wiring the
assets into the dashboard.

**Reason:** the round shows what Maity is about, humans and agents as
members of one team around a project, and the drawn "m" belongs to the
mark itself instead of depending on a font. 0.9 s reads as busy without
blurring at small sizes.

**Rejected alternative:** direction A, two figures forming an "m".
Direction B, a wordmark with a square i-dot. Direction C plain, and C
with a typeset "m": the typeset "m" depends on a font. A loader lap of
1.8 s reads as sluggish; 0.6 s blurs the trail into a ring at small
sizes.

## The header lockup is two images switched by the theme; the site takes the brand files from web/brand/

**Id:** 8dd044a4-153d-4181-af43-ee8193b6a91e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's wiring card (tsk-cdqnq7r3v56p), 2026-10-25; web/brand/BRAND.md; the dashboard's implementation, 2026-10-25
**Revisit when:** the header needs the lockup in a colour other than its two files, or the site gets a build step

The header's title is `maity-lockup.svg` and `maity-lockup-dark.svg` as
two `<img>` with `alt="Maity"`, 28 px tall; app.css shows the dark one
where the page is dark by the system (unless Light was picked) or by the
picked Dark, the same two conditions the dark tokens use. The page loader
is `loader.html` inline in index.html, its timing in `brand/loader.css`.
The site at maity.dev links `brand/…`, which the pages workflow copies
from `web/brand/`, so the files have one home.

**Reason:** an `<img>` keeps the SVG's own markup and needs no copy of
its paths in code, and the class rule follows the page's theme, which an
`<img>` switching by `prefers-color-scheme` alone would not (a picked
Dark on a light system). Copying at publish time keeps the site and the
dashboard on the same files.

**Rejected alternative:** `maity-lockup-currentcolor.svg` inline, which
follows `currentColor` and the accent token by itself: in a page built by
scripts it means either the SVG's paths in a JavaScript string or a
`<template>` cloned at run time, both a second copy of the file to keep in
step. Copies of the files under `docs/brand/` for the site: two homes for
the same file.
