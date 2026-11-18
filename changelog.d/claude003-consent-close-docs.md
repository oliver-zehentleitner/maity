### Fixed

- docs: §15.5 **Closing** no longer says that a `DELETE` of a placement whose
  consent request is open always closes it at once (tsk-90ssz6mz37tn). The
  request is withdrawn; a creation not yet approved then closes at once
  (`removed`), and an approved placement whose open request is a change of
  its spec drops the change and closes the uniform way, as the hub does. The
  withdrawn row of §15.6 **Settling** says the same.
