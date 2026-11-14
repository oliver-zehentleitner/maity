"""A plain line of text (§2.3): what the hub shows inside its own sentences, such as a bridge's
purpose in the consent it files, must not be able to look like a further part of them. No
control character (a line break or tab included), no format character (the bidirectional
controls, zero-width characters), no line or paragraph separator. tsk-zadkerpebgd5 is to grow
this into the one rule for names and short texts."""

from __future__ import annotations

import unicodedata

# Cc control, Cf format (bidi controls and isolates, zero-width), Zl line and Zp paragraph
# separators; Cs surrogates and Co private use cannot be shown as text either.
_NOT_PLAIN = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs", "Co"})


def is_plain_line(value: str) -> bool:
    """One line of plain text: nothing in it that is not shown as a character."""
    return not any(unicodedata.category(c) in _NOT_PLAIN for c in value)
