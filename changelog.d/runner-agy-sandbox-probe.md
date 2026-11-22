### Changed

- cli: `maity runner check` no longer warns that agy's terminal sandbox cannot start on a host where AppArmor restricts unprivileged user namespaces but a profile named `agy` is loaded: that is a warning that the runner cannot verify it. Where the namespaces are refused and nothing lifts that, `check` reports an error, and every agy start there says in the runner's log that it runs commands unsandboxed, unless `require_sandbox = true` refuses it (tsk-xjy2d5617sar).
