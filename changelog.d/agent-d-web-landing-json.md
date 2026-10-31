### Added
- web: the landing editor imports and exports the page as JSON (Admin →
  Landing page → Import or export JSON): paste or choose a file with the
  hub's body or one language's page; it is loaded into the editor after a
  confirmation, checked by the hub's preview, and saved only with Save.

### Fixed
- web: saving the landing page asks for the second factor when the hub
  requires a step-up, and an empty operator line in the footer is sent
  as none instead of an empty text the hub refuses.
