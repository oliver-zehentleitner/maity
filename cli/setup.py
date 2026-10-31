"""PEP 517 build hooks: preserve Git identity in wheels and source distributions."""

import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))
from maity.versioninfo import STAMP_FILE, stamp_for, write_stamp  # noqa: E402


class StampedBuild(build_py):
    def run(self) -> None:
        stamp = stamp_for(PROJECT)
        super().run()
        if not self.editable_mode:
            write_stamp(Path(self.build_lib) / "maity" / STAMP_FILE, stamp)


class StampedSdist(sdist):
    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        stamp = stamp_for(PROJECT)
        super().make_release_tree(base_dir, files)
        write_stamp(Path(base_dir) / "src" / "maity" / STAMP_FILE, stamp)


setup(cmdclass={"build_py": StampedBuild, "sdist": StampedSdist})
