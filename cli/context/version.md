# Version and build identity

## Freeze the source revision in packages; show the live revision in a checkout

**Id:** d7461421-902a-47fb-aa7a-f3967e081dc7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-rk1s9fchwstm (2026-10-31); [direct-URL metadata specification](https://packaging.python.org/en/latest/specifications/direct-url/); [setuptools build-command extensions](https://setuptools.pypa.io/en/latest/userguide/extension.html)
**See:** https://github.com/oliver-zehentleitner/maity — 227cd75c-bfc7-4cd8-9ba8-cf877cd3bf21 — as of 2026-10-31
**See:** runner.md — ea36c196-f8e6-43ae-bc47-49c8d5379a65 — as of 2026-10-31
**Revisit when:** the CLI changes build backend or installer metadata identifies local Git builds reliably

`--version` keeps the release version and adds a source revision, with
`-dirty` when the CLI worktree has uncommitted changes. Wheel and sdist
builds freeze that identity in a package JSON file; a wheel built from
an extracted sdist keeps its stamp. A source or editable checkout uses
its current Git identity. Without either a verified revision or a
valid packaged stamp, the build is explicitly `unknown`.

**Reason:** one release version covered many unreleased source builds,
so an old installation looked current. Direct-URL metadata is not
present for ordinary index installs and explicitly carries no VCS
information for local-directory installs, including editable ones.
A packaged stamp identifies installed code without Git or the original
repository. A checkout needs its live identity because its code can
change after installation. Build discovery never uses the caller's
working directory, which may belong to an unrelated repository.
Even an adjacent Git root must track the project's manifest and Maity
package before it can supply a live revision. An sdist unpacked inside another
repository retains its frozen identity instead of adopting that
repository's HEAD; an unstamped archive stays unknown.

Live Git discovery uses the existing guarded `proc.GIT`/`proc.run`
path and preserves inherited Git locations. Pins matching the source
clone are honored; redirects to another tree or alternate object/index
locations make the source identity `unknown`. Dropping the runner's
pins merely to get a revision would remove a confinement boundary.

The stamp contains only revision and dirty state, without machine
paths or build time, so repeated builds from the same source retain
the same identity. The existing release-version and tag policy remains
the basis of minimum-version checks; this does not turn each main
commit into a new release.

**Rejected alternatives:**
- A release-version bump alone: does not distinguish local source
  builds made between releases.
- Relying only on `direct_url.json`: misses the local pip/pipx install
  that exposed the problem.
- Running `git describe` in the user's working directory: can describe
  a different repository and fails when Git is unavailable.
- A new runtime versioning dependency: the existing setuptools build
  hooks and standard-library reader are enough.
- A separate direct Git subprocess: skips the central fsmonitor,
  hook and submodule protections. The Git-call-site CI guard caught
  this in the first implementation; it was replaced with the shared
  guarded path rather than adding an exception to that guard.
