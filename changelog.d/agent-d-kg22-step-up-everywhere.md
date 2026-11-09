### Fixed

- web: every call the hub guards with the second factor now asks for the code in place and
  repeats the call: creating and re-pairing a runner's pairing line, the instance's mail
  settings, a password change, changing or removing the mail address, approving a held address
  change, and answering a request whose go moves a project. Before, these showed only "This needs
  your second factor first." `make check` now fails on a dashboard call to such a route outside
  the question where it can read the call's path, and a hub test keeps that list equal to the
  hub's routes (tsk-6dk86ej9s0fq).
