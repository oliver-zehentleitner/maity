"""The Maity hub: the server humans and their coding agents join."""

from importlib.metadata import version

__version__ = version("maity-hub")

API_VERSION = "v1"

# The newest CLI on PyPI, named to agents so an older one warns (§5.2, §8.3). Raised after a
# CLI release, not with the version bump: main runs ahead of PyPI, and an upgrade to a
# version that isn't published yet does nothing (cli/context/version.md).
CLI_VERSION = "0.1.0a4"
