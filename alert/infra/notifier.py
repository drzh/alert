"""Notification backends."""

from __future__ import annotations

import os
import mimetypes
import smtplib
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from html import unescape
from pathlib import Path
from typing import TextIO

from alert.models import Attachment, SmtpConfig


class NotificationError(RuntimeError):
    """Raised when a notification cannot be sent."""


class Notifier:
    """Notification protocol."""

    def send(
        self,
        subject: str,
        body_html: str,
        attachments: tuple[Attachment, ...] = (),
    ) -> None:  # pragma: no cover - interface definition
        raise NotImplementedError


@dataclass
class ConsoleNotifier(Notifier):
    """Dry-run notifier that prints messages."""

    stream: TextIO = sys.stdout

    def send(
        self,
        subject: str,
        body_html: str,
        attachments: tuple[Attachment, ...] = (),
    ) -> None:
        print(f"Subject: {subject}", file=self.stream)
        print(body_html, file=self.stream)
        if attachments:
            names = ", ".join(attachment.filename or Path(attachment.path).name for attachment in attachments)
            print(f"Attachments: {names}", file=self.stream)


@dataclass
class SmtpNotifier(Notifier):
    """SMTP-backed notifier."""

    config: SmtpConfig

    def send(
        self,
        subject: str,
        body_html: str,
        attachments: tuple[Attachment, ...] = (),
    ) -> None:
        password = os.getenv(self.config.password_env)
        if not password:
            raise NotificationError(
                f"SMTP password environment variable is not set: {self.config.password_env}"
            )

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.config.sender
        message["To"] = ", ".join(self.config.recipients)
        message.set_content(unescape(body_html))
        message.add_alternative(body_html, subtype="html")
        for attachment in attachments:
            attachment_path = Path(attachment.path)
            if not attachment_path.is_file():
                raise NotificationError(f"Attachment does not exist: {attachment_path}")

            data = attachment_path.read_bytes()
            mimetype = attachment.mimetype or mimetypes.guess_type(attachment_path.name)[0] or "application/octet-stream"
            maintype, subtype = mimetype.split("/", 1)
            message.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename or attachment_path.name,
            )

        try:
            with smtplib.SMTP(self.config.host, self.config.port) as server:
                server.ehlo()
                if self.config.starttls:
                    server.starttls()
                    server.ehlo()
                server.login(self.config.username, password)
                server.send_message(message)
        except Exception as exc:  # pragma: no cover - depends on external SMTP server.
            raise NotificationError(str(exc)) from exc
