"""Tests for tools/readme_sync.py.

Standard library only, so CI runs them without installing anything:
    python3 -m unittest discover -s tools -p 'test_*.py'
pytest collects them as well.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import readme_sync  # noqa: E402

ORIGIN = "<!-- translated-from: README.md@" + "a" * 40 + " -->"
EN_LINE = "**English** · [Deutsch](README.de.md)"
DE_LINE = "[English](README.md) · **Deutsch**"

SOURCE = f"""<h1><img src="logo.svg" alt="Maity"></h1>

{EN_LINE}

Intro with [a link](docs/a.md).

### Try it

```sh
# not a heading
```

## What it is

![Board](docs/img/board.png)
"""

GERMAN = f"""{ORIGIN}
<h1><img src="logo.svg" alt="Maity"></h1>

{DE_LINE}

Einleitung mit [einem Link](docs/a.md).

### Ausprobieren

```sh
# keine Überschrift
```

## Was es ist

![Board](docs/img/board.png)
"""


class Repo:
    def __init__(self, root: Path, **files: str) -> None:
        self.root = root
        (root / "web/js/i18n").mkdir(parents=True)
        (root / "web/js/i18n/languages.js").write_text(
            'window.MAITY_I18N_LANGUAGES = ["de", "en"];\n', encoding="utf-8"
        )
        for name, text in files.items():
            (root / name.replace("_", ".")).write_text(text, encoding="utf-8")

    def check(self) -> list[str]:
        return readme_sync.check(self.root)


class ReadmeSyncTest(unittest.TestCase):
    def repo(self, **files: str) -> Repo:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Repo(Path(directory.name), **files)

    def test_a_translation_in_step_passes(self) -> None:
        self.assertEqual(self.repo(README_md=SOURCE, README_de_md=GERMAN).check(), [])

    def test_the_language_line_puts_english_first_and_the_own_in_bold(self) -> None:
        line = readme_sync.language_line("de", ["de", "en", "fr"])
        self.assertEqual(line, "[English](README.md) · **Deutsch** · [Français](README.fr.md)")

    def test_a_missing_translation_is_named(self) -> None:
        findings = self.repo(README_md=SOURCE).check()
        self.assertEqual(len(findings), 1)
        self.assertIn("README.de.md:1: missing", findings[0])

    def test_a_section_added_to_the_source_fails(self) -> None:
        added = SOURCE + "\n## Licence\n\nMIT.\n"
        findings = self.repo(README_md=added, README_de_md=GERMAN).check()
        self.assertEqual(len(findings), 1)
        self.assertIn("headings differ", findings[0])

    def test_a_heading_at_another_level_fails(self) -> None:
        moved = GERMAN.replace("## Was es ist", "### Was es ist")
        findings = self.repo(README_md=SOURCE, README_de_md=moved).check()
        self.assertIn("headings differ", findings[0])

    def test_a_hash_line_in_code_is_no_heading(self) -> None:
        outline = readme_sync.outline(["```", "# comment", "```", "## Real"])
        self.assertEqual(outline, [(4, 2)])

    def test_the_origin_comment_is_required(self) -> None:
        bare = GERMAN.split("\n", 1)[1]
        findings = self.repo(README_md=SOURCE, README_de_md=bare).check()
        self.assertTrue(any("first line must be" in f for f in findings), findings)

    def test_a_short_hash_is_refused(self) -> None:
        short = GERMAN.replace("a" * 40, "a" * 8)
        findings = self.repo(README_md=SOURCE, README_de_md=short).check()
        self.assertTrue(any("first line must be" in f for f in findings), findings)

    def test_the_language_line_is_required_in_both(self) -> None:
        findings = self.repo(
            README_md=SOURCE.replace(EN_LINE, ""), README_de_md=GERMAN.replace(DE_LINE, "")
        ).check()
        self.assertEqual(len([f for f in findings if "language line" in f]), 2, findings)

    def test_a_changed_link_target_fails(self) -> None:
        changed = GERMAN.replace("docs/a.md", "docs/de/a.md")
        findings = self.repo(README_md=SOURCE, README_de_md=changed).check()
        self.assertEqual(findings, ["README.de.md:1: the links or images differ from README.md"])

    def test_a_language_without_a_name_is_named(self) -> None:
        repo = self.repo(README_md=SOURCE, README_de_md=GERMAN)
        (repo.root / "web/js/i18n/languages.js").write_text(
            'window.MAITY_I18N_LANGUAGES = ["de", "en", "xx"];\n', encoding="utf-8"
        )
        self.assertEqual(
            repo.check(), ["tools/readme_sync.py: no name for xx; add it to NAMES"]
        )


if __name__ == "__main__":
    unittest.main()
