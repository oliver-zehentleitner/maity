### Added

- cli: `maity task show`, `list`, `create` and `edit` (§6.4, §13).
  - `list` is the board in text, with children under their parent and the open/total count.
  - `show` names the card's parent, its children and its related cards.
  - `create` and `edit` set `--parent` / `--no-parent` and `--related` / `--unrelated`.
    `--assign` needs `tasks:admin`.
  - The hub's subtask refusals (`too_deep`, `has_children`, `parent_closed`, `self`,
    `release_card`, `cycle`, `subtasks_proposed`, `dependencies_open`) are printed as they
    came, with one hint line.
  - The first session explains subtasks and the `proposed` default in one line.
