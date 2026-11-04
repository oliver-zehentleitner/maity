### Fixed

- web: on the sign-in and registration pages, the logo, the header's section links and, without the frame,
  the app's own logo open the hub's start page again (the landing page for a visitor while it is on)
  instead of keeping the dashboard and its sign-in form under the address `/`: the dashboard leaves every
  click on `/` to the browser (§16.7, #1340, tsk-fmdn6vb2zs19).
- web: the landing page editor marks a section it keeps unedited (a type this hub does not edit yet) by a
  dashed border instead of lowered opacity, which took its muted text under the contrast it needs (axe
  color-contrast, #1340, tsk-fmdn6vb2zs19).
