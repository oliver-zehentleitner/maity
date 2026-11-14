"""Header values and the message itself (docs/api.md §18.5).

Every header value the hub builds is one line of plain text first: each run of control and
line-break characters (Unicode Cc: C0, U+007F and C1 such as U+0085; Zl: U+2028; Zp: U+2029)
becomes one space, whatever a human typed into a name. A value that is not pure ASCII is
then encoded as RFC 2047 encoded-words, which `email.policy.SMTP` does. Addresses are
the checked single addresses of §18.4 and enter a header only as one `Address`; no
header line or recipient list is joined from strings by hand.
"""

from __future__ import annotations

import re
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import SMTP

MAX_NAME = 200

# Every character of Unicode category Cc (C0, U+007F, C1), Zl and Zp: all of them, since
# `email.policy` refuses a header value with any line break it knows, U+0085 included.
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


def clean(value: str) -> str:
    """The value on one line: each run of control and line-break characters is one space."""
    return _CONTROL.sub(" ", value)


def printable(value: object, maximum: int) -> bool:
    """A non-empty string of at most `maximum` characters with no control character."""
    return isinstance(value, str) and 0 < len(value) <= maximum and not _CONTROL.search(value)


def valid_name(value: object) -> bool:
    """A sender's display name (`from.name`, §16.2)."""
    return printable(value, MAX_NAME) and isinstance(value, str) and value.strip() == value


def _address(addr: str, name: str | None = None) -> Address:
    local, _, domain = addr.rpartition("@")
    return Address(display_name=clean(name or ""), username=local, domain=domain)


def message(
    *,
    sender: str,
    sender_name: str | None,
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
) -> EmailMessage:
    """A plain-text UTF-8 mail. `sender`, `to` and `reply_to` are checked addresses."""
    mail = EmailMessage(policy=SMTP)
    mail["From"] = _address(sender, sender_name)
    mail["To"] = _address(to)
    if reply_to is not None:
        mail["Reply-To"] = _address(reply_to)
    mail["Subject"] = clean(subject)
    mail["Auto-Submitted"] = "auto-generated"
    mail.set_content(body, charset="utf-8")
    return mail
