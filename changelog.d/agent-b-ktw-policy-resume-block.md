### Added

- hub: `memory.provider` (`none`, `keep-the-why`, default `keep-the-why`) as the named form of `keep_the_why`, on projects and in the resume packet's `project.memory` (§6.1)
- hub: `policy.keep_the_why` (`required`, `optional`) and `policy.keep_the_why_defaults` (`adopt`, `ask`), migration 0059 (§6.1, §6.23)
- hub: the resume packet's `keep_the_why` block carries `skill`, `config` and `personal_defaults`; `MAITY_KTW_SKILL_SOURCE` points the skill's texts at a mirror (§6.23)

### Changed

- hub: a project created without `keep_the_why` or `memory` now has the provider `keep-the-why`, as the contract says (§6.1)
