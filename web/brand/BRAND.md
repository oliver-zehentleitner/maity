# Maity brand

## Shape language

A circle is a human, a rounded square is an agent. Both are members of
the same team. It holds for the logo, avatars, the org chart and icons.

## Mark: "the round" (C3)

Five members sit in a circle. An agent, the blue square, takes its seat
at the top. A drawn "m" (two arches, the same stroke logic as the seats)
sits in the middle: the project everyone gathers around.

| File | Use |
|---|---|
| `maity-mark.svg`, `maity-mark-dark.svg` | 32 px and up, with the "m" |
| `maity-mark-small.svg`, `maity-mark-small-dark.svg` | below 32 px: no "m", heavier seats |
| `favicon.svg` | the small mark; switches with `prefers-color-scheme` |

- Clear space around the mark: one seat.
- Minimum size: 16 px.
- Lockup: mark + "maity" in Space Grotesk 700, lower case, letter-spacing -0.02em.

Decided by oliver, 2026-10-23, out of three directions (A: two figures
forming an "m"; B: wordmark with a square i-dot; C: the round). C was
chosen; of its three variants (plain, typeset "m", drawn "m") the drawn
"m" won, because it belongs to the mark instead of depending on a font.

## Loader

The agent walks the round clockwise and leaves a fading trail. One lap
takes 0.9 s, picked by oliver from 1.8 s, 0.9 s and 0.6 s. At 0.6 s the
trail blurs into a ring at small sizes; at 1.8 s it reads as sluggish.
With `prefers-reduced-motion: reduce` it stands still as the mark.

- `maity-loader.svg`, `maity-loader-dark.svg`: self-contained, safe in `<img>`.
- `loader.html` + `loader.css`: inline version that takes `--muted` and
  `--accent` from `web/css/app.css`, so it follows light and dark by itself.

## Colour

Kept from `web/css/app.css`, so the site, the hub and the logo are one family.

| Token | Light | Dark | Use |
|---|---|---|---|
| Ink (`--text`) | `#1D2125` | `#E6E9EC` | text, humans |
| Accent (`--accent`) | `#1A66D9` | `#4C8DFF` | agents, primary action |
| Paper (`--bg`) | `#F7F7F5` | `#111418` | ground |
| Surface | `#FFFFFF` | `#1A1F24` | cards |
| Signal (`--normal`) | `#8A5A00` | `#E3B341` | open decision |

On the dark accent, button text is `#0B0F14`, not white.

## Type

- Space Grotesk 600/700: headings and the wordmark.
- Inter 400/500/600: body.
- JetBrains Mono: code.

All three are OFL. A self-hosted hub with no telemetry should ship them
with the app instead of loading them from Google Fonts.

## Website and hub layout

Both have a light/dark switch, and every colour comes from one light
and one dark token set. Mock-ups for the landing page and the hub
(decision inbox) in both themes are on the canvas.
