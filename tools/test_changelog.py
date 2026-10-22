"""Tests for tools/changelog.py.

Standard library only, so CI runs them without installing anything:
    python3 -m unittest discover -s tools -p 'test_*.py'
pytest collects them as well.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import changelog  # noqa: E402

HEAD = """# Changelog

Intro.

## [Unreleased]

Unreleased changes are collected in `changelog.d/` (one file per pull request) and folded in at release.
"""

OLD_RELEASE = """
## [0.1.0] - 2026-01-01

### Added

- hub: the first thing.
"""


class Repo:
    def __init__(self, root: Path, changelog_text: str = HEAD, **fragments: str) -> None:
        self.root = root
        (root / "changelog.d").mkdir()
        (root / "changelog.d" / "README.md").write_text("# not a fragment\n\nprose\n")
        (root / "CHANGELOG.md").write_text(changelog_text)
        for name, text in fragments.items():
            (root / "changelog.d" / f"{name}.md").write_text(text)

    def run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = changelog.main(list(argv), root=self.root)
        return code, out.getvalue(), err.getvalue()

    def text(self) -> str:
        return (self.root / "CHANGELOG.md").read_text()

    def fragments(self) -> list[str]:
        return sorted(p.name for p in (self.root / "changelog.d").iterdir())


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class CheckTest(Base):
    def test_valid_fragments_pass(self) -> None:
        repo = Repo(
            self.tmp,
            a="### Added\n\n- cli: one\n  continued\n\n- cli: two\n\n### Fixed\n\n- hub: three\n",
            b="### Security\n- hub: four\n",
        )
        code, out, err = repo.run("check")
        self.assertEqual(code, 0, err)
        self.assertIn("2 fragment(s)", out)

    def test_no_fragments_pass(self) -> None:
        self.assertEqual(Repo(self.tmp).run("check")[0], 0)

    def test_unknown_heading(self) -> None:
        code, _, err = Repo(self.tmp, a="### Added\n\n- x\n\n### Improved\n\n- y\n").run("check")
        self.assertEqual(code, 1)
        self.assertIn("changelog.d/a.md:5: heading '### Improved'", err)

    def test_wrong_heading_level(self) -> None:
        code, _, err = Repo(self.tmp, a="## Added\n\n- x\n").run("check")
        self.assertEqual(code, 1)
        self.assertIn("changelog.d/a.md:1:", err)

    def test_bullet_outside_heading(self) -> None:
        code, _, err = Repo(self.tmp, a="- x\n\n### Added\n\n- y\n").run("check")
        self.assertEqual(code, 1)
        self.assertIn("changelog.d/a.md:1: bullet outside", err)

    def test_prose_line(self) -> None:
        code, _, err = Repo(self.tmp, a="### Added\n\nSome prose.\n- y\n").run("check")
        self.assertEqual(code, 1)
        self.assertIn("changelog.d/a.md:3: expected", err)

    def test_heading_without_bullets(self) -> None:
        code, _, err = Repo(self.tmp, a="### Added\n\n### Fixed\n\n- y\n").run("check")
        self.assertEqual(code, 1)
        self.assertIn("changelog.d/a.md:1: '### Added' has no bullet", err)

    def test_empty_file(self) -> None:
        code, _, err = Repo(self.tmp, a="\n\n").run("check")
        self.assertEqual(code, 1)
        self.assertIn("changelog.d/a.md:1: empty fragment", err)

    def test_not_markdown(self) -> None:
        repo = Repo(self.tmp)
        (self.tmp / "changelog.d" / "a.txt").write_text("### Added\n\n- x\n")
        code, _, err = repo.run("check")
        self.assertEqual(code, 1)
        self.assertIn("changelog.d/a.txt:1:", err)

    def test_every_finding_reported(self) -> None:
        code, _, err = Repo(self.tmp, a="- x\n", b="### Nope\n").run("check")
        self.assertEqual(code, 1)
        self.assertIn("a.md:1", err)
        self.assertIn("b.md:1", err)


class ReleaseTest(Base):
    def test_folds_fragments_in_canonical_and_name_order(self) -> None:
        repo = Repo(
            self.tmp,
            HEAD + OLD_RELEASE,
            **{
                "b-second": "### Fixed\n\n- hub: b fixed\n\n### Added\n\n- hub: b added\n",
                "a-first": "### Added\n\n- cli: a added\n  wrapped\n\n### Security\n\n- hub: a sec\n",
            },
        )
        code, out, err = repo.run("release", "0.2.0", "--date", "2026-10-22")
        self.assertEqual(code, 0, err)
        self.assertEqual(
            repo.text(),
            "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n"
            "Unreleased changes are collected in `changelog.d/` (one file per pull request) "
            "and folded in at release.\n\n"
            "## [0.2.0] - 2026-10-22\n\n"
            "### Added\n\n- cli: a added\n  wrapped\n- hub: b added\n\n"
            "### Fixed\n\n- hub: b fixed\n\n"
            "### Security\n\n- hub: a sec\n\n"
            "## [0.1.0] - 2026-01-01\n\n### Added\n\n- hub: the first thing.\n",
        )
        self.assertEqual(repo.fragments(), ["README.md"])
        self.assertIn("deleted changelog.d/a-first.md", out)
        self.assertIn("4 from 2 fragment(s)", out)

    def test_keeps_entries_still_under_unreleased_first(self) -> None:
        text = HEAD + "\n### Fixed\n\n- web: old fix\n\n### Added\n\n- web: old\n" + OLD_RELEASE
        repo = Repo(self.tmp, text, z="### Added\n\n- web: new\n")
        code, _, err = repo.run("release", "0.2.0", "--date", "2026-10-22")
        self.assertEqual(code, 0, err)
        section = repo.text().split("## [0.2.0] - 2026-10-22\n\n")[1].split("## [0.1.0]")[0]
        self.assertEqual(
            section, "### Added\n\n- web: old\n- web: new\n\n### Fixed\n\n- web: old fix\n\n"
        )
        self.assertNotIn("old fix", repo.text().split("## [0.2.0]")[0])

    def test_dry_run_changes_nothing(self) -> None:
        repo = Repo(self.tmp, HEAD, a="### Added\n\n- x\n")
        code, out, _ = repo.run("release", "0.2.0", "--date", "2026-10-22", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(repo.text(), HEAD)
        self.assertEqual(repo.fragments(), ["README.md", "a.md"])
        self.assertIn("## [0.2.0] - 2026-10-22", out)
        self.assertIn("would delete changelog.d/a.md", out)

    def test_default_date_is_today(self) -> None:
        import datetime

        repo = Repo(self.tmp, HEAD, a="### Added\n\n- x\n")
        self.assertEqual(repo.run("release", "0.2.0")[0], 0)
        self.assertIn(f"## [0.2.0] - {datetime.date.today().isoformat()}", repo.text())

    def test_refuses_invalid_fragment_and_writes_nothing(self) -> None:
        repo = Repo(self.tmp, HEAD, a="### Added\n\n- x\n", b="### Nope\n\n- y\n")
        code, _, err = repo.run("release", "0.2.0", "--date", "2026-10-22")
        self.assertEqual(code, 1)
        self.assertIn("changelog.d/b.md:1", err)
        self.assertEqual(repo.text(), HEAD)
        self.assertEqual(repo.fragments(), ["README.md", "a.md", "b.md"])

    def test_refuses_existing_version(self) -> None:
        repo = Repo(self.tmp, HEAD + OLD_RELEASE, a="### Added\n\n- x\n")
        code, _, err = repo.run("release", "0.1.0", "--date", "2026-10-22")
        self.assertEqual(code, 1)
        self.assertIn("already released", err)

    def test_refuses_nothing_to_release(self) -> None:
        code, _, err = Repo(self.tmp).run("release", "0.2.0")
        self.assertEqual(code, 1)
        self.assertIn("nothing to release", err)

    def test_refuses_bad_version_and_date(self) -> None:
        repo = Repo(self.tmp, HEAD, a="### Added\n\n- x\n")
        self.assertEqual(repo.run("release", "v0.2")[0], 1)
        self.assertEqual(repo.run("release", "0.2.0", "--date", "22.10.2026")[0], 1)
        self.assertEqual(repo.run("release", "0.2.0", "--date", "2026-02-30")[0], 1)
        self.assertEqual(repo.text(), HEAD)

    def test_refuses_changelog_without_unreleased(self) -> None:
        repo = Repo(self.tmp, "# Changelog\n", a="### Added\n\n- x\n")
        code, _, err = repo.run("release", "0.2.0")
        self.assertEqual(code, 1)
        self.assertIn("[Unreleased]", err)


class RepositoryTest(unittest.TestCase):
    """The repository's own fragments are valid."""

    def test_repository_fragments(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = changelog.main(["check"])
        self.assertEqual(code, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
