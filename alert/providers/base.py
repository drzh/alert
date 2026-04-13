"""Provider abstraction for alert sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Mapping, Sequence

from alert.models import AlertItem, SourceConfig, StoredAlert, TargetConfig

if TYPE_CHECKING:
    from alert.infra.http import HttpClient


class AlertProvider(ABC):
    """Base class for alert providers."""

    name: str
    default_email_title: str

    @abstractmethod
    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        """Parse source content into alert items."""

    def fetch_content(self, target: TargetConfig, http_client: HttpClient) -> str:
        """Fetch provider content for one target."""

        return http_client.fetch_text(
            target.url,
            timeout_seconds=target.timeout_seconds,
        )

    def should_alert(
        self,
        history: Sequence[StoredAlert],
        item: AlertItem,
        target: TargetConfig,
    ) -> bool:
        """Decide whether a parsed item should emit a new alert."""

        return all(record.item_id != item.item_id for record in history)

    def build_subject(
        self,
        source: SourceConfig,
        alerts_by_target: Mapping[str, Sequence[AlertItem]],
    ) -> str:
        """Build the notification subject for a source execution."""

        return source.resolved_email_title(self.default_email_title)

    def after_target(
        self,
        target: TargetConfig,
        items: Sequence[AlertItem],
        pending: Sequence[AlertItem],
        content: str,
        *,
        persist: bool,
        notification_sent: bool,
    ) -> None:
        """Run provider-specific follow-up logic after target execution."""
