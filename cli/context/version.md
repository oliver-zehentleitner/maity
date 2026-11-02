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

The repository tracks a JSON placeholder with `revision: null`, so
setuptools has a concrete package-data input to carry into an sdist
without claiming a build revision. Checkouts resolve live identity;
build hooks replace the distribution's copy. Before writing, the hook
unlinks that copy: setuptools can hard-link source files into its sdist
release tree, so writing in place would overwrite the checkout's stamp
through the hard link. Breaking the link preserves the source placeholder.

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

## The hub names the published CLI, and an older one warns

**Id:** 3e8d5b1a-6c27-4f19-a0d4-7b92c1e46f30
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the jour fixe of 2026-11-01 (round jfx-1h88k3dgtfy3) and the card tsk-8y56jn3w7rr1; a silent old CLI posted a wrong note, and four members worked around missing commands with `maity api`
**Revisit when:** a contract change needs a minimum CLI that the hub enforces, or CLI releases become automatic

`CLI_VERSION` in `hub/src/maity_hub/__init__.py` is the newest CLI on PyPI. The hub names it in
`hints.cli_version` and in each answer of `GET …/events`, because a long session rarely calls
`resume`. `maity resume` and `maity wait` print one line on stderr when the CLI is older, and
nothing is refused. A CLI newer than the hub's value says nothing: a hub may simply be deployed
less often than the CLI is released.

**Release steps:** a command for a contract change goes out in a CLI release together with the
feature, not at some later release. After the tag is on PyPI, raise `CLI_VERSION` in its own
change. A test only holds `CLI_VERSION` at or below `cli/src/maity/__init__.py`.

**Rejected alternatives:**
- `CLI_VERSION` equal to the repository's CLI version: main runs ahead of PyPI, so the hub would
  say "upgrade" while `pipx upgrade` brings nothing.
- A response header: the JSON answer already reaches the place in `wait` that needs the value.
- Refusing an old CLI: the problem is that nobody notices, and a refusal would stop agents that
  could still work.
- A CI check that each contract command comes with a release: not built, as the release step
  belongs to whoever tags.
