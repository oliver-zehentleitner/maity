"""A scripted SMTP server on the loopback interface, for the mail tests: it speaks just
enough of RFC 5321 (and STARTTLS, AUTH) to drive every stage of the hub's conversation,
and records what it was told."""

from __future__ import annotations

import datetime
import ipaddress
import socket
import ssl
import threading
from dataclasses import dataclass, field
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@dataclass
class Script:
    starttls: bool = False
    tls: ssl.SSLContext | None = None  # for STARTTLS, or the whole connection
    implicit: bool = False
    greeting: str = "220 fake ESMTP"
    auth_reply: str = "235 2.7.0 accepted"
    rcpt_reply: str = "250 2.1.5 ok"
    data_reply: str = "250 2.0.0 queued as 42"
    silent_after_greeting: bool = False


@dataclass
class Record:
    commands: list[str] = field(default_factory=list)
    data: bytes = b""
    tls_used: bool = False


class FakeSmtp:
    def __init__(self, script: Script) -> None:
        self.script = script
        self.record = Record()
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.close()
        self._thread.join(timeout=5)

    def _serve(self) -> None:
        try:
            conn, _ = self._server.accept()
        except OSError:
            return
        conn.settimeout(10)
        try:
            if self.script.implicit:
                assert self.script.tls is not None
                conn = self.script.tls.wrap_socket(conn, server_side=True)
                self.record.tls_used = True
            self._talk(conn)
        except (OSError, ssl.SSLError):
            pass
        finally:
            conn.close()

    def _talk(self, conn: socket.socket) -> None:
        reader = conn.makefile("rb")
        secure = self.script.implicit

        def say(line: str) -> None:
            conn.sendall(line.encode() + b"\r\n")

        say(self.script.greeting)
        if self.script.silent_after_greeting:
            reader.readline()
            return
        while True:
            raw = reader.readline()
            if not raw:
                return
            line = raw.decode().rstrip("\r\n")
            verb = line.split(" ", 1)[0].upper()
            self.record.commands.append(verb)
            if verb in ("EHLO", "HELO"):
                lines = ["fake"]
                if self.script.starttls and not secure:
                    lines.append("STARTTLS")
                # Offered in clear too: the hub must refuse it there, not the server.
                lines.append("AUTH PLAIN LOGIN")
                for i, text in enumerate(lines):
                    say(("250 " if i == len(lines) - 1 else "250-") + text)
            elif verb == "STARTTLS":
                say("220 2.0.0 ready")
                assert self.script.tls is not None
                conn = self.script.tls.wrap_socket(conn, server_side=True)
                reader = conn.makefile("rb")
                secure = self.record.tls_used = True
            elif verb == "AUTH":
                say(self.script.auth_reply)
            elif verb == "MAIL":
                say("250 2.1.0 ok")
            elif verb == "RCPT":
                say(self.script.rcpt_reply)
            elif verb == "DATA":
                say("354 go ahead")
                chunks = []
                while (chunk := reader.readline()) not in (b".\r\n", b""):
                    chunks.append(chunk)
                self.record.data = b"".join(chunks)
                say(self.script.data_reply)
            elif verb == "QUIT":
                say("221 bye")
                return
            else:
                say("502 5.5.2 not implemented")


def certificate(directory: Path) -> tuple[Path, ssl.SSLContext]:
    """A self-signed certificate for 127.0.0.1: its file (the hub's CA file) and a
    server context that presents it."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake smtp")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file = directory / "smtp-cert.pem"
    key_file = directory / "smtp-key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    return cert_file, context
