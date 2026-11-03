### Fixed

- hub: the whole contract's `toc` counts section numbers over every heading of the file before
  it cuts at 2000, so a number that occurs again past the cut anchors by position; a
  directory tree the forge does not answer is no longer kept, so the next read asks again
  (review of #1261, tsk-zd9es4kp51w1).
