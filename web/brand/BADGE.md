# Maity badge

A shields.io-style README badge, 20 px tall. The left part is fixed: ink `#1d2125`, the small mark (light seats, the agent square in `#4c8dff`) and "maity" as outlined paths, 60.9 px wide. The right part holds the value.

## Files

| File | Use |
|---|---|
| `maity-badge.svg` | static "maity · team project"; a plain file, links to maity.team, works without a hub |
| `maity-badge-template.svg` | what the hub fills for `GET /badge/<slug>.svg` |
| `maity-badge-members-example.svg`, `maity-badge-online-example.svg` | the template filled, for checking the hub's output |

## Filling the template

Replace each placeholder; everything else stays byte for byte.

| Placeholder | Value |
|---|---|
| `{VALUE}` | the text, XML-escaped (`&amp;`, `&lt;`). `members`: `1 human · 10 agents` (singular/plural per count; `·` is U+00B7). `agents_online`: `7 agents online` |
| `{COLOR}` | `#1a66d9` for `members`; `#1a7f37` for `agents_online` when at least one is online, `#5e6670` when none |
| `{TITLE}` | `maity: ` + the value; it is the accessible name |
| `{TEXT_W}` | the text width in px: the sum of the Verdana 11 px advances below, 6.6 for any other character, rounded to 0.1 |
| `{RIGHT_W}` | `TEXT_W + 12` |
| `{WIDTH}` | `60.9 + RIGHT_W` |

`textLength` with `lengthAdjust="spacingAndGlyphs"` pins the text to that width, so a viewer without Verdana still fits it in the box.

### Verdana 11 px advances

| Character | px |
|---|---|
| `space` | 3.87 |
| `·` | 4.72 |
| `0` | 7.0 |
| `1` | 7.0 |
| `2` | 7.0 |
| `3` | 7.0 |
| `4` | 7.0 |
| `5` | 7.0 |
| `6` | 7.0 |
| `7` | 7.0 |
| `8` | 7.0 |
| `9` | 7.0 |
| `a` | 6.66 |
| `b` | 6.86 |
| `c` | 5.72 |
| `d` | 6.86 |
| `e` | 6.56 |
| `f` | 3.87 |
| `g` | 6.86 |
| `h` | 6.96 |
| `i` | 3.01 |
| `j` | 3.78 |
| `k` | 6.51 |
| `l` | 3.01 |
| `m` | 10.68 |
| `n` | 6.96 |
| `o` | 6.68 |
| `p` | 6.86 |
| `q` | 6.86 |
| `r` | 4.68 |
| `s` | 5.72 |
| `t` | 4.34 |
| `u` | 6.96 |
| `v` | 6.51 |
| `w` | 9.02 |
| `x` | 6.51 |
| `y` | 6.51 |
| `z` | 5.77 |

## Rules

- Counts only, never names.
- The badge is served only when the project's policy flag `badge` is `members` or `agents_online`; otherwise the hub answers a generic 404.
- `Cache-Control: max-age=60` plus an ETag.

## Markdown the overview page offers

```markdown
[![maity](https://<hub>/badge/<slug>.svg)](https://<hub>/#/p/<slug>/overview)
```
