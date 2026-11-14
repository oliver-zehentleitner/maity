### Fixed

- hub: two `task_updated` events now carry what §8.2 requires. A checklist tick (`POST …/checklist/{item_id}`) sends `fields: ["release"]` and `history: []` beside the new `release`, and the move to `done` a merge makes on its own (§6.6) sends `history: []`; neither writes a history entry (§6.15). The contract says so in §6.7 and §6.15.
