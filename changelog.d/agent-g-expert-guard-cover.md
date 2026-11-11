### Fixed

- hub: a covered member whose covered cards would not come back to it may become an expert: cards the substitute touched or that were closed since stay with the substitute, and cards reassigned or taken over since have already left it. The role guard counted every card naming the member in `cover.for` and refused with `holds_cards`, while §2.3 refuses only for cards the cover's end would give back. The guard and the cover's end now share one rule (`cover.gives_back`).
