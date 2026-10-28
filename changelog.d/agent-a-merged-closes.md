### Added

- docs: §6.6 "A merge closes the loop": the probe's first observation of a card's reported pull request as merged emits `task_merged` to the card's done authority; under the new policy `merged_closes: auto` the hub moves the card to `done` itself when no dependency, objection hold or missing approval keeps it.
