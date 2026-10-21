"""Request bodies: strict, so that an unknown field is `invalid` (§1.1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

HANDLE_PATTERN = r"^[a-z0-9][a-z0-9-]{1,30}$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}$"


def title(**kwargs: Any) -> Any:
    """A title field: 1 to 200 characters (§1.7)."""
    return Field(min_length=1, max_length=200, **kwargs)


def markdown(**kwargs: Any) -> Any:
    """A Markdown body: at most 16 KiB characters (§1.7)."""
    return Field(max_length=16384, **kwargs)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitIdentity(Strict):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=200)
