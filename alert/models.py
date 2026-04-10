"""Typed domain models for the alert system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class TargetConfig:
    """Configuration for a single alert target."""

    url: str
    threshold: float | None = None
    name: str | None = None
    options: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0

    @property
    def display_name(self) -> str:
        return self.name or self.url


@dataclass(frozen=True)
class SourceConfig:
    """Configuration for a logical alert source and its targets."""

    name: str
    provider: str
    db_file: str
    email_title: str | None = None
    targets: tuple[TargetConfig, ...] = field(default_factory=tuple)
    keep_records: int = 1000
    options: Mapping[str, Any] = field(default_factory=dict)

    def resolved_email_title(self, default_title: str) -> str:
        return self.email_title or default_title


@dataclass(frozen=True)
class SmtpConfig:
    """SMTP configuration for outgoing notifications."""

    host: str
    port: int
    username: str
    password_env: str
    sender: str
    recipients: tuple[str, ...]
    starttls: bool = True


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration."""

    sources: tuple[SourceConfig, ...]
    smtp: SmtpConfig | None = None

    def get_source(self, name: str) -> SourceConfig:
        for source in self.sources:
            if source.name == name:
                return source
        raise KeyError(f"Unknown source: {name}")


@dataclass(frozen=True)
class Attachment:
    """A file attachment to include with a notification."""

    path: str
    filename: str | None = None
    mimetype: str | None = None


@dataclass(frozen=True)
class AlertItem:
    """A parsed alert candidate emitted by a provider."""

    item_id: str
    message: str
    value: str | None = None
    occurred_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    attachments: tuple[Attachment, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StoredAlert:
    """An alert item already persisted in storage."""

    source_name: str
    target_url: str
    item_id: str
    message: str
    value: str | None
    occurred_at: str | None
    metadata: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True)
class RunSummary:
    """A summary of a source execution."""

    source_name: str
    targets_checked: int
    items_seen: int
    alerts_triggered: int
    alerts_saved: int
    notification_sent: bool
    dry_run: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
