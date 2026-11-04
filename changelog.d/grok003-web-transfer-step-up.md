### Changed

- web: the smoke test pins that a project transfer whose `POST /projects/{owner}/{slug}/transfer` the hub refuses with `step_up_required` (`docs/api.md` §2.8.4, §6.25) asks for the code in the transfer form and, once it is given, sends the transfer again and shows its result. The Keep the Why entry on a project's name in `web/context/views.md` says the step-up is entered in place, no longer only said, and is `active` again.
