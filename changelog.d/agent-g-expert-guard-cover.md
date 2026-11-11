### Fixed

- hub: a covered member whose covered cards stay with the substitute (touched by it, closed since, or no longer with it) may become an expert; the role guard counted every card naming it in `cover.for` and refused with `holds_cards`, while §2.3 refuses only for cards the cover's end would give back. The guard and the cover's end now share one rule (`cover.gives_back`).
