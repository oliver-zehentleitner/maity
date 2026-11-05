"""Tests for tools/ktw_pin.py.

Standard library only, so CI runs them without installing anything:
    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ktw_pin

ROOT = Path(__file__).resolve().parent.parent
SHA = "1af21fcc16a52e2971083ffb96d92b0f1f008399"
SOURCE = "https://github.com/oliver-zehentleitner/keep-the-why/tree/v1.2.3/skills/keep-the-why"


class Pins(unittest.TestCase):
    def tree(self, **override: str) -> Path:
        files = {
            ".keep-the-why": "<!-- keep-the-why:config -->\n- context-schema: 1.2.3\n",
            **{name: "- context-schema: 1.2.3\n" for name in ktw_pin.SUB_CONFIGS},
            "AGENTS.md": f"`npx skills@9.9.9 add {SOURCE}`\nor read {SOURCE}.\n",
            "docs/api.md": (
                f'"install": [ "npx skills@9.9.9 add {SOURCE} -g -y",\n'
                '"git clone --depth 1 --branch v1.2.3 https://github.com/oliver-zehentleitner/keep-the-why <tmp>"\n'
            ),
            "hub/README.md": "the skill's `v1.2.3` release tree\n",
            "hub/src/maity_hub/config.py": f'KTW_SKILL_SOURCE = (\n    "{SOURCE}"\n)\n',
            "hub/src/maity_hub/ktw_skill.py": 'SKILLS_INSTALLER = "skills@9.9.9"\n"install": [f"npx {SKILLS_INSTALLER} add"]\n',
            "hub/tests/test_keep_the_why_policy.py": f'SOURCE = "{SOURCE}"\n',
            ".github/workflows/ktw-lint.yml": f"      - uses: oliver-zehentleitner/keep-the-why@{SHA} # lint-v1.2.3.1\n",
        }
        files.update(override)
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        return root

    def test_this_repository_is_consistent(self) -> None:
        self.assertEqual(ktw_pin.check(ROOT), [])

    def test_every_copy_on_the_schema_passes(self) -> None:
        self.assertEqual(ktw_pin.check(self.tree()), [])

    def test_a_moving_latest_fails(self) -> None:
        latest = SOURCE.replace("v1.2.3", "latest")
        problems = ktw_pin.check(self.tree(**{"AGENTS.md": f"`npx skills@9.9.9 add {latest}`\n"}))
        self.assertEqual(
            problems, ["AGENTS.md:1: the skill's tree is 'latest', context-schema is 1.2.3"]
        )

    def test_a_schema_bump_without_the_pins_fails_everywhere(self) -> None:
        root = self.tree(**{".keep-the-why": "- context-schema: 1.2.4\n"})
        problems = ktw_pin.check(root)
        self.assertTrue(any(p.startswith("AGENTS.md:1:") for p in problems))
        self.assertTrue(any(p.startswith("hub/src/maity_hub/config.py:2:") for p in problems))
        self.assertTrue(any("Git fallback" in p for p in problems))
        self.assertTrue(any("linter action's tag is lint-v1.2.3.1" in p for p in problems))

    def test_an_unpinned_or_other_installer_fails(self) -> None:
        root = self.tree(
            **{"AGENTS.md": f"`npx skills add {SOURCE}`\n`npx skills@9.9.8 add {SOURCE}`\n"}
        )
        self.assertEqual(
            ktw_pin.check(root),
            [
                "AGENTS.md:1: `npx skills` without a version",
                "AGENTS.md:2: `npx skills@9.9.8`, hub/src/maity_hub/ktw_skill.py pins skills@9.9.9",
            ],
        )

    def test_the_linter_action_by_tag_fails(self) -> None:
        line = "      - uses: oliver-zehentleitner/keep-the-why@lint-latest\n"
        problems = ktw_pin.check(self.tree(**{".github/workflows/ktw-lint.yml": line}))
        self.assertEqual(len(problems), 2)
        self.assertIn("not a commit SHA", problems[0])

    def test_the_short_forms_are_checked_too(self) -> None:
        root = self.tree(
            **{
                "hub/README.md": "the skill's `v1.2.2` release tree\n",
                "docs/api.md": "names as its `context-schema` (`tree/v1.2.2`), and\n"
                "the skills installer at a fixed version (`skills@9.9.8`); an\n",
            }
        )
        self.assertEqual(
            ktw_pin.check(root),
            [
                "docs/api.md:1: the skill's tree is 'v1.2.2', context-schema is 1.2.3",
                "docs/api.md:2: `skills@9.9.8`, hub/src/maity_hub/ktw_skill.py pins skills@9.9.9",
                "hub/README.md:1: the skill's tree is 'v1.2.2', context-schema is 1.2.3",
            ],
        )

    def test_a_moving_ref_in_a_short_form_fails(self) -> None:
        root = self.tree(
            **{
                "hub/README.md": "the skill's `latest` release tree\n",
                "docs/api.md": "names as its `context-schema` (`tree/latest`), and\n"
                "the skills installer at a fixed version (`skills@latest`); an\n"
                "or the installer (`skills`) itself\n",
            }
        )
        self.assertEqual(
            ktw_pin.check(root),
            [
                "docs/api.md:1: the skill's tree is 'latest', context-schema is 1.2.3",
                "docs/api.md:2: `skills@latest`, hub/src/maity_hub/ktw_skill.py pins skills@9.9.9",
                "docs/api.md:3: `skills` without a version",
                "hub/README.md:1: the skill's tree is 'latest', context-schema is 1.2.3",
            ],
        )

    def test_a_missing_package_configuration_is_named(self) -> None:
        root = self.tree()
        (root / "cli/.keep-the-why").unlink()
        self.assertEqual(
            ktw_pin.check(root), ["cli/.keep-the-why: missing (named in tools/ktw_pin.py)"]
        )

    def test_a_package_on_another_schema_fails(self) -> None:
        root = self.tree(
            **{
                "hub/.keep-the-why": "- context-schema: 1.2.3\n",
                "web/.keep-the-why": "- context-schema: 1.2.2\n",
            }
        )
        self.assertEqual(
            ktw_pin.check(root), ["web/.keep-the-why: context-schema 1.2.2, the root's is 1.2.3"]
        )

    def test_a_missing_file_is_named(self) -> None:
        root = self.tree()
        (root / "hub/README.md").unlink()
        self.assertEqual(
            ktw_pin.check(root), ["hub/README.md: missing (named in tools/ktw_pin.py)"]
        )


if __name__ == "__main__":
    unittest.main()
