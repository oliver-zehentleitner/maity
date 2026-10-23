"""One SMTP conversation per mail, with the settings in effect (docs/api.md §16.2, §16.3).

It connects only to the configured host and port. Under `starttls` the server must offer
STARTTLS: without it the send fails at stage `tls` and nothing is sent in clear, unless
the operator set the insecure `MAITY_SMTP_ALLOW_PLAINTEXT`. `AUTH` is never sent without
TLS. Certificates are always verified, against the system store or `MAITY_SMTP_CA_FILE`.

The outcome names the stage where it stopped and the server's reply, never a stack
trace; the username and the password, and their base64 forms, never appear in it.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import re
import smtplib
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from maity_hub import clock
from maity_hub.mail import headers
from maity_hub.mail.settings import Resolved, tls_refusal
from maity_hub.views import ts

log = logging.getLogger(__name__)

TIMEOUT = 20.0  # seconds for the whole conversation (§16.3)
MAX_DETAIL = 200
_REPLY = re.compile(r"^[2-5][0-9][0-9][ -]")


class _Stop(Exception):  # noqa: N818  a control-flow signal, not an error
    def __init__(self, stage: str, code: int | None = None, reply: bytes | str | None = None):
        super().__init__(stage)
        self.stage, self.code, self.reply = stage, code, reply


@dataclass(frozen=True)
class Outcome:
    ok: bool
    stage: str | None
    smtp_code: int | None
    detail: str | None
    at: datetime

    def view(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "stage": self.stage,
            "smtp_code": self.smtp_code,
            "detail": self.detail,
            "at": ts(self.at),
        }


def send(resolved: Resolved, mail: EmailMessage, *, timeout: float = TIMEOUT) -> Outcome:
    """Hand `mail` to the configured server: one sender, one recipient, both from the
    message's checked addresses. The caller checked that the settings are complete."""
    sender = resolved.sender
    assert sender is not None and resolved.value("host")
    recipient = str(mail["To"].addresses[0].addr_spec)
    secrets = _secrets(resolved)
    try:
        code, reply = _converse(
            resolved, sender.address, recipient, mail, time.monotonic() + timeout
        )
    except _Stop as stop:
        return _outcome(False, stop.stage, stop.code, stop.reply, secrets)
    return _outcome(True, None, code, reply, secrets)


def _converse(
    resolved: Resolved, sender: str, recipient: str, mail: EmailMessage, deadline: float
) -> tuple[int, bytes]:
    host, port, tls = resolved.value("host"), resolved.value("port"), resolved.value("tls")
    context = ssl.create_default_context(
        cafile=str(resolved.env.ca_file) if resolved.env.ca_file else None
    )

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise _Stop("timeout")
        return left

    if tls_refusal(resolved):
        raise _Stop("tls")  # never in clear to a host that is not loopback (§16.2)
    try:
        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise _Stop("resolve") from None
    stage = "connect"
    client: smtplib.SMTP
    try:
        # The host goes into the constructor: smtplib verifies the certificate against
        # the name it connected to.
        if tls == "implicit":
            client = smtplib.SMTP_SSL(host, port, timeout=remaining(), context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=remaining())
    except smtplib.SMTPConnectError as error:
        raise _Stop(stage, error.smtp_code, error.smtp_error) from None
    except ssl.SSLError:
        raise _Stop("tls") from None
    except TimeoutError:
        raise _Stop("timeout") from None
    except (smtplib.SMTPException, OSError):
        raise _Stop(stage) from None
    try:
        _step(client, remaining)
        code, reply = client.ehlo()
        if code != 250:
            raise _Stop(stage, code, reply)
        secure = tls == "implicit"
        if tls == "starttls":
            stage = "tls"
            if client.has_extn("starttls"):
                _step(client, remaining)
                try:
                    code, reply = client.starttls(context=context)
                except smtplib.SMTPResponseException as error:
                    raise _Stop(stage, error.smtp_code, error.smtp_error) from None
                except (ssl.SSLError, ssl.CertificateError):
                    raise _Stop(stage) from None
                secure = True
                _step(client, remaining)
                code, reply = client.ehlo()
                if code != 250:
                    raise _Stop(stage, code, reply)
            elif resolved.env.allow_plaintext:
                log.warning(
                    "mail: %s offers no STARTTLS; sending in clear because "
                    "MAITY_SMTP_ALLOW_PLAINTEXT is set (insecure)",
                    host,
                )
            else:
                log.error("mail: %s offers no STARTTLS; nothing was sent", host)
                raise _Stop(stage)
        username = resolved.value("username")
        if username:
            stage = "auth"
            if not secure or resolved.password is None:
                raise _Stop(stage)
            _step(client, remaining)
            try:
                code, reply = client.login(username, resolved.password)
            except smtplib.SMTPAuthenticationError as error:
                raise _Stop(stage, error.smtp_code, error.smtp_error) from None
            except (smtplib.SMTPException, UnicodeError):
                # Never the exception's text: an encoding error quotes the password.
                raise _Stop(stage) from None
        stage = "mail_from"
        _step(client, remaining)
        code, reply = client.mail(sender)
        if code != 250:
            raise _Stop(stage, code, reply)
        stage = "rcpt_to"
        _step(client, remaining)
        code, reply = client.rcpt(recipient)
        if code not in (250, 251):
            raise _Stop(stage, code, reply)
        stage = "data"
        _step(client, remaining)
        code, reply = client.data(mail.as_bytes())
        if code != 250:
            raise _Stop(stage, code, reply)
        with contextlib.suppress(smtplib.SMTPException, OSError):
            client.quit()  # the mail is accepted; a lost goodbye changes nothing
        return code, reply
    except TimeoutError:
        raise _Stop("timeout") from None
    except smtplib.SMTPResponseException as error:
        raise _Stop(stage, error.smtp_code, error.smtp_error) from None
    except (smtplib.SMTPException, OSError, UnicodeError):
        raise _Stop(stage) from None
    finally:
        with contextlib.suppress(OSError):
            client.close()


def _step(client: smtplib.SMTP, remaining: Any) -> None:
    """Give the next exchange only what is left of the whole conversation's time."""
    if client.sock is not None:
        client.sock.settimeout(remaining())


def _secrets(resolved: Resolved) -> list[str]:
    username, password = resolved.value("username"), resolved.password
    plain = [s for s in (username, password) if s]
    forms = list(plain)
    for value in plain:
        forms.append(base64.b64encode(value.encode()).decode())
    if username and password:
        forms.append(base64.b64encode(f"\0{username}\0{password}".encode()).decode())
    return sorted(forms, key=len, reverse=True)  # the longest first: no partial leftovers


def _outcome(
    ok: bool, stage: str | None, code: int | None, reply: bytes | str | None, secrets: list[str]
) -> Outcome:
    detail = None
    if code is not None and 200 <= code <= 599 and reply is not None:
        text = reply.decode("utf-8", "replace") if isinstance(reply, bytes) else reply
        line = f"{code} {text.splitlines()[0] if text else ''}"
        if _REPLY.match(line):
            detail = headers.clean(line[4:])
            for value in secrets:
                detail = detail.replace(value, "…")
            detail = detail[:MAX_DETAIL]
    elif code is not None and not 200 <= code <= 599:
        code = None
    return Outcome(ok, stage, code, detail, clock.now())
