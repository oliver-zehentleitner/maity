"""Header values and the message itself (docs/api.md §18.5).

Every header value the hub builds has every control character removed first: CR, LF,
every other C0 character, U+007F and U+2028/U+2029. A value that is not pure ASCII is
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

_CONTROL = re.compile("[\x00-\x1f\x7f  ]")


def clean(value: str) -> str:
    """The value without a control character."""
    return _CONTROL.sub("", value)


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
