### Added

- hub: `skill.guide` in the resume packet's Keep the Why block, from
  `MAITY_KTW_SKILL_GUIDE` (default `https://keepthewhy.com/installation/`)
  (§6.23)

### Changed

- hub: the packet's skills installer line is non-interactive (`-g -y`)
  (§6.23)
- hub: an explicit `null` for `policy.keep_the_why` is refused (`unknown`)
  instead of clearing the stored value (§6.1)
- hub: an agent that sets `policy.keep_the_why` or
  `policy.keep_the_why_defaults` gets `humans_only` instead of a scope error
  (§2.3, which now lists every field of `HUMANS_ONLY_POLICY`)
