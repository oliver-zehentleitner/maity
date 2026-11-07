### Changed

- cli: a `maity join` that fails before anything is kept (an expired or wrong
  code, a refused hub) removes the state directory and the parent
  directories it created for it, deepest first and only while empty; a
  directory that existed before is never touched (tsk-v0m0wbkm3d7j).
