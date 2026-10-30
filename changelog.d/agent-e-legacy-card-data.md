### Changed

- hub: migration `0101` writes every card in the one shape the code reads: a reported card without `reported_instances` gets the instance of its report, a contract without a place gets `path: docs/api.md` and `section: null`; the branches that read the old shapes are gone (`_reporters`, `view_contract`), and so are the ticker's start for a project that was on before the start was kept (migration `0020` covered it) and the instance settings' tolerance for a row without a registry entry (tsk-wgg2t8ngx9xg).
