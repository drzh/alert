"""Application runner for alerts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

from alert.infra.http import HttpClient
from alert.infra.notifier import Notifier
from alert.infra.repository import AlertRepository
from alert.models import AlertItem, Attachment, RunSummary, SourceConfig, TargetConfig
from alert.registry import get_provider

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TargetRun:
    target: TargetConfig
    content: str
    items: tuple[AlertItem, ...]
    pending: tuple[AlertItem, ...]


@dataclass
class AlertRunner:
    """Orchestrates fetching, parsing, notification, and persistence."""

    http_client: HttpClient
    notifier: Notifier

    def run_source(self, source: SourceConfig, persist: bool = True) -> RunSummary:
        provider = get_provider(source.provider)
        repository = AlertRepository(source.db_file)

        target_runs: list[_TargetRun] = []
        items_seen = 0
        errors: list[str] = []
        notification_sent = False
        saved = 0
        alerts_to_save: dict[str, list[AlertItem]] = {}

        try:
            for target in source.targets:
                try:
                    content = provider.fetch_content(target, self.http_client)
                    items = provider.parse_items(target, content)
                    history = repository.get_history(source.name, target.url)
                except Exception as exc:
                    message = f"{source.name}:{target.url} -> {exc}"
                    LOGGER.exception("Target execution failed: %s", message)
                    errors.append(message)
                    continue

                items_seen += len(items)
                pending = tuple(
                    item for item in items
                    if provider.should_alert(history=history, item=item, target=target)
                )
                target_runs.append(
                    _TargetRun(
                        target=target,
                        content=content,
                        items=tuple(items),
                        pending=pending,
                    )
                )

            alerts_to_save = {
                run.target.url: list(run.pending)
                for run in target_runs
                if run.pending
            }

            if alerts_to_save:
                try:
                    subject = provider.build_subject(source, alerts_to_save)
                    body_html = self._render_email_body(alerts_to_save, source=source)
                    attachments = _collect_attachments(alerts_to_save)
                    self.notifier.send(subject, body_html, attachments=attachments)
                    notification_sent = True
                except Exception as exc:
                    message = f"{source.name}:notification -> {exc}"
                    LOGGER.exception("Notification failed: %s", message)
                    errors.append(message)
                else:
                    if persist:
                        try:
                            for target_url, alerts in alerts_to_save.items():
                                saved += repository.save_alerts(source.name, target_url, alerts)
                                repository.prune(source.name, target_url, keep=source.keep_records)
                        except Exception as exc:
                            message = f"{source.name}:persistence -> {exc}"
                            LOGGER.exception("Persistence failed: %s", message)
                            errors.append(message)

        finally:
            for run in target_runs:
                try:
                    provider.after_target(
                        run.target,
                        run.items,
                        run.pending,
                        run.content,
                        persist=persist,
                        notification_sent=notification_sent,
                    )
                except Exception as exc:
                    message = f"{source.name}:{run.target.url}:follow_up -> {exc}"
                    LOGGER.exception(
                        "Provider follow-up failed for %s:%s",
                        source.name,
                        run.target.url,
                    )
                    errors.append(message)
            repository.close()

        return RunSummary(
            source_name=source.name,
            targets_checked=len(source.targets),
            items_seen=items_seen,
            alerts_triggered=sum(len(alerts) for alerts in alerts_to_save.values()),
            alerts_saved=saved,
            notification_sent=notification_sent,
            dry_run=not persist,
            errors=tuple(errors),
        )

    def _render_email_body(
        self,
        alerts_by_target: dict[str, list[AlertItem]],
        source: SourceConfig,
    ) -> str:
        sections: list[str] = []
        target_index = {target.url: target for target in source.targets}
        for target_url, alerts in alerts_by_target.items():
            target = target_index[target_url]
            if len(source.targets) > 1:
                sections.append(f"<h3>{escape(target.display_name)}</h3>")
            for alert in alerts:
                sections.append(alert.message)
        return "\n".join(sections)


def _collect_attachments(alerts_by_target: dict[str, list[AlertItem]]) -> tuple[Attachment, ...]:
    collected: list[Attachment] = []
    seen: set[tuple[str, str | None]] = set()
    for alerts in alerts_by_target.values():
        for alert in alerts:
            for attachment in alert.attachments:
                key = (attachment.path, attachment.filename)
                if key in seen:
                    continue
                seen.add(key)
                collected.append(attachment)
    return tuple(collected)
